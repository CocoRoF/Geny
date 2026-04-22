"""Process-wide OmniVoice model holder.

The model is heavy (multi-GB on GPU), loaded once at FastAPI startup
inside the ``lifespan`` context, and then accessed through this module
by request handlers.

Design highlights
-----------------

* **Phase tracking.** The engine moves through a small state machine —
  ``loading → warming → ok`` (or ``error``). The ``/health`` and
  ``/diag/phase`` routes expose the current phase so the backend
  adapter can distinguish "still warming up" from "broken".
* **Persistent residency.** ``configure_runtime()`` is called *before*
  ``load()`` so the CUDA allocator configuration (``expandable_segments``,
  per-process memory fraction, ``cudnn.benchmark``) is in place when
  weights are first materialised. Auxiliary CUDA streams (H2D / D2H)
  and a pinned host PCM pool are allocated at load time and held for
  the whole process lifetime — runtime should never trigger new large
  allocations.
* **Pascal safety.** ``resolve_dtype()`` downgrades ``bfloat16`` to
  ``float16`` on sm < 8.0 (Pascal/Volta) so the GTX 1070 deployment
  cannot accidentally pick a dtype that has no hardware support.
* **GPU serialisation.** A single ``asyncio.Semaphore`` gates all
  in-flight syntheses to ``Settings.max_concurrency``; synthesis itself
  runs in a worker thread so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import torch

from omnivoice_core import OmniVoice, OmniVoiceGenerationConfig

from server.host_pool import PinnedPCMPool
from server.settings import Settings

logger = logging.getLogger(__name__)


_DTYPE_MAP = {
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
    "float32": torch.float32,
}


# ── Phase state machine ──────────────────────────────────────────────
# Module-level so `/diag/phase` and `/health` can read it before the
# EngineState exists (during the very first moments of `load`).
_PHASES = ("loading", "warming", "compiling", "ok", "error")
_phase: str = "loading"


def get_phase() -> str:
    return _phase


def set_phase(p: str) -> None:
    global _phase
    if p not in _PHASES:
        raise ValueError(f"unknown phase {p!r}; expected one of {_PHASES}")
    if p != _phase:
        logger.info("engine phase: %s -> %s", _phase, p)
    _phase = p


@dataclass
class EngineState:
    settings: Settings
    model: OmniVoice
    semaphore: asyncio.Semaphore
    streams: dict[str, Optional[Any]] = field(default_factory=dict)
    pinned_pool: Optional[PinnedPCMPool] = None

    @property
    def sampling_rate(self) -> int:
        return int(self.model.sampling_rate)

    @property
    def has_asr(self) -> bool:
        return getattr(self.model, "_asr_pipe", None) is not None


_state: Optional[EngineState] = None


def get_state() -> EngineState:
    if _state is None:
        raise RuntimeError("OmniVoice engine has not been initialised yet.")
    return _state


def is_loaded() -> bool:
    return _state is not None


# ── Capability helpers ───────────────────────────────────────────────


def _is_cuda_device(device: str) -> bool:
    return device.startswith("cuda") and torch.cuda.is_available()


def _device_capability(device: str) -> Optional[tuple[int, int]]:
    if not _is_cuda_device(device):
        return None
    try:
        idx = int(device.split(":")[1]) if ":" in device else torch.cuda.current_device()
        return tuple(torch.cuda.get_device_capability(idx))  # type: ignore[return-value]
    except Exception:
        return None


def resolve_dtype(setting: str, device: str) -> torch.dtype:
    """Map dtype string → torch.dtype, downgrading ``bfloat16`` on Pascal/Volta.

    bf16 has no hardware tensor-core support below sm_80 (Ampere). On
    sm_61 (GTX 1070) emulated bf16 silently falls back to a slow path,
    so we hard-downgrade to fp16 — the deployment-supported dtype on
    Pascal — and log loudly.
    """
    if setting not in _DTYPE_MAP:
        raise ValueError(f"unsupported dtype: {setting!r}")
    cap = _device_capability(device)
    if setting == "bfloat16" and cap is not None and cap < (8, 0):
        logger.warning(
            "bfloat16 requested but device capability is sm_%d%d (< 8.0); "
            "downgrading to float16. Set OMNIVOICE_DTYPE=float16 explicitly to silence this.",
            cap[0], cap[1],
        )
        return torch.float16
    return _DTYPE_MAP[setting]


# ── Runtime configuration (called BEFORE load) ───────────────────────


def configure_runtime(settings: Settings) -> None:
    """Side-effecting setup that must happen before the first CUDA alloc.

    * Sets ``PYTORCH_CUDA_ALLOC_CONF`` to ``expandable_segments:True,max_split_size_mb=128``
      if the operator hasn't pinned a value already. ``expandable_segments``
      is the key knob for vLLM-style stable residency: the allocator can
      grow a single arena instead of splintering into many fixed blocks.
    * Caps this process's VRAM usage via ``set_per_process_memory_fraction``
      when ``gpu_memory_fraction > 0``. Honours the operator's chosen ratio.
    * Enables ``cudnn.benchmark`` so cuDNN can cache the fastest algorithm
      per (op, input shape, dtype) tuple. Safe because OmniVoice's
      iterative loop keeps shapes constant inside a single generation.

    Idempotent: calling twice has no extra effect.
    """
    os.environ.setdefault("HF_HOME", settings.hf_cache)
    os.environ.setdefault("TRANSFORMERS_CACHE", settings.hf_cache)

    # NOTE: ``expandable_segments:True`` is mutually exclusive with
    # ``max_split_size_mb`` in PyTorch's caching allocator — setting
    # both raises ``RuntimeError: Unrecognized CachingAllocator option``
    # at the first CUDA init. expandable_segments alone gives us the
    # vLLM-style growing arena we want for persistent residency.
    if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        logger.info("set PYTORCH_CUDA_ALLOC_CONF=%s",
                    os.environ["PYTORCH_CUDA_ALLOC_CONF"])
    else:
        # Operator-supplied values may still contain the bad combo (e.g.
        # carried over from an older Dockerfile). Strip max_split_size_mb
        # if expandable_segments is also enabled so we degrade gracefully
        # instead of crash-looping.
        cur = os.environ["PYTORCH_CUDA_ALLOC_CONF"]
        if "expandable_segments:True" in cur and "max_split_size_mb" in cur:
            sanitized = ",".join(
                p for p in cur.split(",") if not p.strip().startswith("max_split_size_mb")
            )
            os.environ["PYTORCH_CUDA_ALLOC_CONF"] = sanitized
            logger.warning(
                "PYTORCH_CUDA_ALLOC_CONF had incompatible max_split_size_mb "
                "with expandable_segments:True; sanitized to %r", sanitized,
            )
        else:
            logger.info("respecting operator-set PYTORCH_CUDA_ALLOC_CONF=%s", cur)

    if not _is_cuda_device(settings.device):
        logger.info("CUDA not available or device=%s; skipping CUDA runtime tweaks.",
                    settings.device)
        return

    if settings.cudnn_benchmark:
        torch.backends.cudnn.benchmark = True
        logger.info("torch.backends.cudnn.benchmark=True (algorithm cache enabled)")

    if settings.gpu_memory_fraction > 0:
        try:
            idx = int(settings.device.split(":")[1]) if ":" in settings.device else 0
            torch.cuda.set_per_process_memory_fraction(
                float(settings.gpu_memory_fraction), idx
            )
            logger.info(
                "torch.cuda.set_per_process_memory_fraction(%.3f, device=%d)",
                settings.gpu_memory_fraction, idx,
            )
        except Exception:
            logger.exception("Failed to set per-process memory fraction; continuing.")


def _make_streams(device: str) -> dict[str, Optional[Any]]:
    """Allocate H2D / D2H copy streams alongside the default compute stream.

    Two dedicated streams let us overlap ref-audio uploads and PCM
    downloads with kernel execution in later phases (workspace + ref
    cache). Allocated once at load and held for the process lifetime.
    """
    if not _is_cuda_device(device):
        return {"compute": None, "h2d": None, "d2h": None}
    return {
        "compute": torch.cuda.current_stream(),
        "h2d": torch.cuda.Stream(),
        "d2h": torch.cuda.Stream(),
    }


# ── Load / unload ────────────────────────────────────────────────────


def load(settings: Settings) -> EngineState:
    """Blocking model load. Called from the FastAPI lifespan."""
    global _state
    set_phase("loading")

    dtype = resolve_dtype(settings.dtype, settings.device)
    logger.info(
        "Loading OmniVoice model=%s device=%s dtype=%s",
        settings.model, settings.device, dtype,
    )
    model = OmniVoice.from_pretrained(
        settings.model,
        device_map=settings.device,
        dtype=dtype,
        load_asr=settings.auto_asr,
        asr_model_name=settings.asr_model,
    )
    logger.info("OmniVoice loaded; sampling_rate=%s", model.sampling_rate)

    streams = _make_streams(settings.device)

    pinned_pool: Optional[PinnedPCMPool] = None
    if settings.pinned_pool_slots > 0:
        pinned_pool = PinnedPCMPool(
            slots=settings.pinned_pool_slots,
            max_seconds=settings.max_audio_seconds,
            sample_rate=settings.default_sample_rate,
            # Only pin when we actually have a CUDA device; otherwise the
            # pool degrades to plain torch.empty so unit tests pass.
            pin_memory=_is_cuda_device(settings.device),
        )
        try:
            pinned_pool.allocate()
            stats = pinned_pool.stats()
            logger.info(
                "PinnedPCMPool allocated: slots=%d capacity=%d samples (≈ %.1fs @ %dHz, pinned=%s)",
                stats.slots_total, stats.sample_capacity,
                stats.sample_capacity / max(stats.sample_rate, 1),
                stats.sample_rate, stats.pinned,
            )
        except Exception:
            logger.exception("PinnedPCMPool allocation failed; running without pool.")
            pinned_pool = None

    _state = EngineState(
        settings=settings,
        model=model,
        semaphore=asyncio.Semaphore(settings.max_concurrency),
        streams=streams,
        pinned_pool=pinned_pool,
    )
    return _state


def unload() -> None:
    global _state
    if _state is None:
        set_phase("loading")
        return
    state = _state
    try:
        if state.pinned_pool is not None:
            state.pinned_pool.close()
    except Exception:
        logger.exception("Error closing PinnedPCMPool")
    try:
        del state.model
    finally:
        _state = None
        set_phase("loading")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# ── Generation ───────────────────────────────────────────────────────


def _build_gen_config(req_num_step: int, req_guidance: float, denoise: bool,
                     preprocess_prompt: bool, postprocess_output: bool
                     ) -> OmniVoiceGenerationConfig:
    return OmniVoiceGenerationConfig(
        num_step=req_num_step,
        guidance_scale=req_guidance,
        denoise=denoise,
        preprocess_prompt=preprocess_prompt,
        postprocess_output=postprocess_output,
    )


def _generate_sync(
    state: EngineState,
    *,
    text: str,
    mode: str,
    ref_audio_path: Optional[str],
    ref_text: Optional[str],
    instruct: Optional[str],
    language: Optional[str],
    speed: float,
    duration: Optional[float],
    num_step: int,
    guidance_scale: float,
    denoise: bool,
    preprocess_prompt: bool,
    postprocess_output: bool,
    seed: Optional[int] = None,
) -> np.ndarray:
    """Blocking synthesis. Runs inside an executor thread."""
    if seed is not None:
        # Deterministic mode: seed every RNG OmniVoice can pull from
        # right before generation. Required by the output-equivalence
        # regression gate; without this the MaskGIT sampler picks a
        # different duration / token sequence on every call.
        import random as _py_random
        _py_random.seed(int(seed))
        np.random.seed(int(seed) & 0xFFFFFFFF)
        try:
            import torch as _torch
            _torch.manual_seed(int(seed))
            if _torch.cuda.is_available():
                _torch.cuda.manual_seed_all(int(seed))
        except Exception:  # pragma: no cover - torch missing on dev box
            pass
    gen_config = _build_gen_config(
        num_step, guidance_scale, denoise, preprocess_prompt, postprocess_output,
    )
    kwargs: dict[str, Any] = {
        "text": text.strip(),
        "language": language or None,
        "generation_config": gen_config,
    }

    if duration is not None and duration > 0:
        kwargs["duration"] = float(duration)
    elif speed != 1.0:
        kwargs["speed"] = float(speed)

    if mode == "clone":
        if not ref_audio_path:
            raise ValueError("clone mode requires ref_audio_path")
        kwargs["voice_clone_prompt"] = state.model.create_voice_clone_prompt(
            ref_audio=ref_audio_path,
            ref_text=ref_text,
        )

    if mode == "design":
        if not instruct:
            raise ValueError("design mode requires instruct")
        kwargs["instruct"] = instruct.strip()
    elif instruct:
        kwargs["instruct"] = instruct.strip()

    audios = state.model.generate(**kwargs)
    if not audios:
        raise RuntimeError("OmniVoice returned an empty audio batch.")
    return audios[0]


def _transcribe(state: EngineState, audio_path: str) -> Optional[str]:
    if not state.has_asr:
        return None
    try:
        return state.model.transcribe(audio_path)
    except Exception:  # pragma: no cover - optional path
        logger.exception("Whisper transcription failed for %s", audio_path)
        return None


async def synthesize(
    *,
    text: str,
    mode: str,
    ref_audio_path: Optional[str],
    ref_text: Optional[str],
    instruct: Optional[str],
    language: Optional[str],
    speed: float,
    duration: Optional[float],
    num_step: int,
    guidance_scale: float,
    denoise: bool,
    preprocess_prompt: bool,
    postprocess_output: bool,
    seed: Optional[int] = None,
) -> tuple[np.ndarray, int]:
    """Public async entry point. Returns (audio_ndarray, sampling_rate)."""
    state = get_state()
    async with state.semaphore:
        loop = asyncio.get_running_loop()
        audio = await loop.run_in_executor(
            None,
            lambda: _generate_sync(
                state,
                text=text,
                mode=mode,
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                instruct=instruct,
                language=language,
                speed=speed,
                duration=duration,
                num_step=num_step,
                guidance_scale=guidance_scale,
                denoise=denoise,
                preprocess_prompt=preprocess_prompt,
                postprocess_output=postprocess_output,
                seed=seed,
            ),
        )
    return audio, state.sampling_rate


# ── Warmup (Phase 1a + 1d-4) ─────────────────────────────────────────


async def warmup() -> None:
    """Run one synthesis per length bucket to prime cuDNN and CUDA caches.

    Each bucket uses the same ``num_step`` / ``guidance_scale`` as
    production traffic, plus an explicit ``duration`` matching the
    bucket. cuDNN's algorithm cache is keyed by (op, shape, dtype) — by
    touching three representative shapes we cover the common short /
    medium / long cases without paying the first-request penalty in
    production.

    The warmup text is scaled to the bucket duration (~3 chars/sec) so
    OmniVoice has real content to synthesise; otherwise the post-process
    stage can hit a zero-size waveform reduction on long-duration
    requests built from a one-line probe.

    Failures are logged and swallowed: a warmup miss must not bring
    down the whole service. The phase machine is restored to ``ok`` on
    return regardless of per-bucket failures.
    """
    state = get_state()
    settings = state.settings
    set_phase("warming")
    base_sentence = (
        "This is a warmup probe utterance for the omnivoice service. "
    )
    try:
        for bucket in settings.warmup_buckets_seconds:
            bucket_s = float(bucket)
            # Roughly 3 chars per second of speech; round up so we never
            # under-feed the model for the requested duration.
            target_chars = max(32, int(bucket_s * 18))
            repeats = max(1, target_chars // len(base_sentence) + 1)
            warmup_text = (base_sentence * repeats)[:target_chars].strip()
            try:
                logger.info(
                    "warmup: synthesising %.1fs probe (%d chars)",
                    bucket_s, len(warmup_text),
                )
                await synthesize(
                    text=warmup_text,
                    mode="auto",
                    ref_audio_path=None,
                    ref_text=None,
                    instruct=None,
                    language=None,
                    speed=1.0,
                    duration=bucket_s,
                    num_step=settings.default_num_step,
                    guidance_scale=settings.default_guidance_scale,
                    denoise=True,
                    preprocess_prompt=True,
                    postprocess_output=True,
                )
            except Exception:
                logger.exception("warmup bucket %.1fs failed; continuing", bucket_s)
    finally:
        set_phase("ok")
