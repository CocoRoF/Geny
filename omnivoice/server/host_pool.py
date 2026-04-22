"""Pre-allocated pinned-host PCM buffer pool (Phase 1d-3).

Why
---
``audio_gpu.cpu().numpy()`` on the synthesis path performs:

  (a) a host malloc the size of the audio,
  (b) an implicit ``cudaStreamSynchronize``,
  (c) the D2H copy itself,
  (d) numpy wrapping under the GIL.

Doing this on every request adds latency and jitter. By pre-allocating a
small fixed pool of ``pin_memory=True`` int16 buffers at startup we skip
(a) and (d) entirely, can use ``non_blocking=True`` for (c), and pair the
copy with a dedicated D2H CUDA stream so the *next* generation's compute
can begin overlapping (relevant once Phase 4 streaming is wired in).

Design
------
* Tensors are int16, mono, sized for the longest utterance the service
  promises to handle (``Settings.max_audio_seconds * sample_rate``).
* The pool is an :class:`asyncio.Queue`; ``acquire`` awaits a free slot
  and ``release`` returns it. There is no fallback path that allocates
  on the fly — the pool sizing is a hard cap mirroring
  ``Settings.pinned_pool_slots``.
* On hosts without CUDA the pool degrades to plain (un-pinned) tensors.
  This keeps the same call-site contract on dev workstations and CPU
  CI runners.

This module is intentionally torch-only: it has no FastAPI / pydantic
imports and is safe to import in unit tests that stub the rest of the
runtime.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PinnedPCMPoolStats:
    slots_total: int
    slots_free: int
    sample_capacity: int
    sample_rate: int
    pinned: bool


class PinnedPCMPool:
    """Bounded async pool of int16 PCM buffers.

    Use via :meth:`borrow` for an automatic-release context manager, or
    the lower-level :meth:`acquire` / :meth:`release` pair.
    """

    def __init__(
        self,
        *,
        slots: int,
        max_seconds: float,
        sample_rate: int,
        pin_memory: Optional[bool] = None,
    ) -> None:
        if slots < 0:
            raise ValueError(f"slots must be >= 0, got {slots}")
        if max_seconds <= 0:
            raise ValueError(f"max_seconds must be > 0, got {max_seconds}")
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be > 0, got {sample_rate}")

        self._slots = slots
        self._sample_capacity = int(round(max_seconds * sample_rate))
        self._sample_rate = sample_rate
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max(slots, 1))
        self._pinned = bool(pin_memory) if pin_memory is not None else False
        self._allocated = False

    # ── lifecycle ────────────────────────────────────────────────────
    def allocate(self) -> None:
        """Allocate the underlying tensors. Idempotent.

        Safe to call before any event loop exists (we only touch the
        :class:`asyncio.Queue` synchronously here).
        """
        if self._allocated or self._slots == 0:
            self._allocated = True
            return

        try:
            import torch  # local import keeps tests free of torch
        except ImportError:  # pragma: no cover - torch is required in container
            raise RuntimeError("PinnedPCMPool requires torch")

        pin = self._pinned and torch.cuda.is_available()
        if self._pinned and not torch.cuda.is_available():
            logger.info(
                "PinnedPCMPool: CUDA unavailable, falling back to non-pinned host buffers"
            )
        self._pinned = pin

        for _ in range(self._slots):
            buf = torch.empty(self._sample_capacity, dtype=torch.int16, pin_memory=pin)
            self._queue.put_nowait(buf)
        self._allocated = True
        logger.info(
            "PinnedPCMPool ready: slots=%d capacity=%d samples (%.1fs @ %dHz) pinned=%s",
            self._slots,
            self._sample_capacity,
            self._sample_capacity / self._sample_rate,
            self._sample_rate,
            self._pinned,
        )

    def close(self) -> None:
        """Drop references to all buffers. Pinned memory is freed by GC."""
        # Drain the queue
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._allocated = False

    # ── access ───────────────────────────────────────────────────────
    async def acquire(self, n_samples: int):
        """Wait for a free buffer and return its first ``n_samples`` view.

        The returned tensor is a *view* into the pooled buffer; the caller
        must release the *underlying* buffer (the one returned by the
        view's ``data_ptr``) via :meth:`release`. Use :meth:`borrow` for
        an automatic-release context manager to avoid bookkeeping bugs.
        """
        if self._slots == 0:
            raise RuntimeError("PinnedPCMPool was configured with slots=0")
        if n_samples <= 0:
            raise ValueError(f"n_samples must be > 0, got {n_samples}")
        if n_samples > self._sample_capacity:
            raise ValueError(
                f"requested {n_samples} samples but pool capacity is "
                f"{self._sample_capacity} ({self._sample_capacity / self._sample_rate:.1f}s)"
            )
        if not self._allocated:
            raise RuntimeError("PinnedPCMPool.allocate() has not been called")

        buf = await self._queue.get()
        return buf  # caller slices [:n_samples] themselves; we keep the full ref

    def release(self, buf) -> None:
        """Return a previously-acquired buffer to the pool."""
        if self._slots == 0:
            return
        try:
            self._queue.put_nowait(buf)
        except asyncio.QueueFull:  # pragma: no cover - bookkeeping bug
            logger.error("PinnedPCMPool.release: queue full, dropping buffer")

    @contextlib.asynccontextmanager
    async def borrow(self, n_samples: int) -> AsyncIterator:
        """Async context manager that acquires and auto-releases a buffer."""
        buf = await self.acquire(n_samples)
        try:
            yield buf
        finally:
            self.release(buf)

    # ── introspection ────────────────────────────────────────────────
    def stats(self) -> PinnedPCMPoolStats:
        return PinnedPCMPoolStats(
            slots_total=self._slots,
            slots_free=self._queue.qsize() if self._allocated else 0,
            sample_capacity=self._sample_capacity,
            sample_rate=self._sample_rate,
            pinned=self._pinned,
        )

    @property
    def sample_capacity(self) -> int:
        return self._sample_capacity

    @property
    def sample_rate(self) -> int:
        return self._sample_rate
