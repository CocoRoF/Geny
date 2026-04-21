"""Generic periodic tick engine.

Design (see plan/02 §1–§4):
- One ``asyncio.Task`` per ``TickSpec`` — a slow handler on one spec
  never delays others.
- Handler exceptions are logged via ``logger.exception`` and swallowed;
  the loop continues at the next interval.
- No drift correction: each iteration is ``await handler()`` → ``await
  sleep(interval ± jitter)``. Overruns push subsequent ticks back; there
  is never more than one in-flight handler per spec.
- ``register`` after ``start`` is allowed — the new spec gets its own
  task immediately.
- ``unregister`` during run cancels the spec's task. An in-flight
  handler is allowed to finish only if it does not itself await inside
  a ``CancelledError``-safe region; normally the cancel surfaces at
  the next ``await``.
- ``_on_tick_complete(name, duration_ms)`` is a no-op hook; real
  metric wiring lands in PR-X2-4/5.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Mapping

logger = logging.getLogger(__name__)

TickHandler = Callable[[], Awaitable[None]]

_MIN_INTERVAL = 0.1
_DEFAULT_STOP_TIMEOUT = 5.0


@dataclass(frozen=True)
class TickSpec:
    name: str
    interval: float
    handler: TickHandler
    jitter: float = 0.0
    run_on_start: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("TickSpec.name must be non-empty")
        if self.interval < _MIN_INTERVAL:
            raise ValueError(
                f"TickSpec.interval must be >= {_MIN_INTERVAL}s, "
                f"got {self.interval}"
            )
        if self.jitter < 0:
            raise ValueError("TickSpec.jitter must be >= 0")
        if self.jitter >= self.interval:
            raise ValueError(
                "TickSpec.jitter must be strictly less than interval "
                f"(interval={self.interval}, jitter={self.jitter})"
            )
        if not asyncio.iscoroutinefunction(self.handler):
            raise TypeError(
                f"TickSpec.handler must be an async function; got {self.handler!r}"
            )


class TickEngine:
    def __init__(self) -> None:
        self._specs: Dict[str, TickSpec] = {}
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._running = False

    def register(self, spec: TickSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"TickSpec named {spec.name!r} is already registered")
        self._specs[spec.name] = spec
        if self._running:
            self._tasks[spec.name] = asyncio.create_task(
                self._run_spec(spec), name=f"tick:{spec.name}"
            )

    def unregister(self, name: str) -> None:
        spec = self._specs.pop(name, None)
        if spec is None:
            return
        task = self._tasks.pop(name, None)
        if task is not None and not task.done():
            task.cancel()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for spec in self._specs.values():
            self._tasks[spec.name] = asyncio.create_task(
                self._run_spec(spec), name=f"tick:{spec.name}"
            )

    async def stop(self, *, timeout: float = _DEFAULT_STOP_TIMEOUT) -> None:
        if not self._running:
            return
        self._running = False
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if not tasks:
            return
        await asyncio.wait(tasks, timeout=timeout)

    def is_running(self) -> bool:
        return self._running

    def specs(self) -> Mapping[str, TickSpec]:
        return dict(self._specs)

    async def _run_spec(self, spec: TickSpec) -> None:
        try:
            if spec.run_on_start:
                await self._tick_once(spec)
            while True:
                delay = spec.interval
                if spec.jitter > 0:
                    delay += random.uniform(-spec.jitter, spec.jitter)
                    if delay < 0:
                        delay = 0.0
                await asyncio.sleep(delay)
                await self._tick_once(spec)
        except asyncio.CancelledError:
            raise

    async def _tick_once(self, spec: TickSpec) -> None:
        start = time.monotonic()
        try:
            await spec.handler()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("tick handler raised: name=%s", spec.name)
        finally:
            duration_ms = (time.monotonic() - start) * 1000.0
            self._on_tick_complete(spec.name, duration_ms)

    def _on_tick_complete(self, name: str, duration_ms: float) -> None:
        """Metric hook — real implementation lands in PR-X2-4/5."""
        return None
