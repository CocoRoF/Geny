"""Process-wide OmniVoice model holder.

The model is heavy (multi-GB on GPU), loaded once at FastAPI startup
inside the ``lifespan`` context, and then accessed through this module
by request handlers.

A single ``asyncio.Semaphore`` serialises GPU access to ``Settings.max_concurrency``
in-flight requests. Synthesis itself runs in a worker thread so that the
event loop remains responsive while CUDA blocks.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import torch

from omnivoice_core import OmniVoice, OmniVoiceGenerationConfig

from server.settings import Settings

logger = logging.getLogger(__name__)


_DTYPE_MAP = {
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
    "float32": torch.float32,
}


@dataclass
class EngineState:
    settings: Settings
    model: OmniVoice
    semaphore: asyncio.Semaphore

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


def load(settings: Settings) -> EngineState:
    """Blocking model load. Called from the FastAPI lifespan."""
    global _state

    # Honour the configured HF cache before the first import touches it.
    os.environ.setdefault("HF_HOME", settings.hf_cache)
    os.environ.setdefault("TRANSFORMERS_CACHE", settings.hf_cache)

    dtype = _DTYPE_MAP[settings.dtype]
    logger.info(
        "Loading OmniVoice model=%s device=%s dtype=%s",
        settings.model,
        settings.device,
        settings.dtype,
    )
    model = OmniVoice.from_pretrained(
        settings.model,
        device_map=settings.device,
        dtype=dtype,
        load_asr=settings.auto_asr,
        asr_model_name=settings.asr_model,
    )
    logger.info("OmniVoice loaded; sampling_rate=%s", model.sampling_rate)

    _state = EngineState(
        settings=settings,
        model=model,
        semaphore=asyncio.Semaphore(settings.max_concurrency),
    )
    return _state


def unload() -> None:
    global _state
    if _state is None:
        return
    try:
        del _state.model
    finally:
        _state = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


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
) -> np.ndarray:
    """Blocking synthesis. Runs inside an executor thread."""
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
        # OmniVoice.create_voice_clone_prompt accepts ref_text=None and will
        # transcribe via Whisper when load_asr=True was passed at startup.
        kwargs["voice_clone_prompt"] = state.model.create_voice_clone_prompt(
            ref_audio=ref_audio_path,
            ref_text=ref_text,
        )

    if mode == "design":
        if not instruct:
            raise ValueError("design mode requires instruct")
        kwargs["instruct"] = instruct.strip()
    elif instruct:
        # auto / clone modes still allow an optional instruct hint.
        kwargs["instruct"] = instruct.strip()

    audios = state.model.generate(**kwargs)
    if not audios:
        raise RuntimeError("OmniVoice returned an empty audio batch.")
    return audios[0]


def _transcribe(state: EngineState, audio_path: str) -> Optional[str]:
    """Best-effort use of OmniVoice's built-in Whisper pipe.

    Kept as a helper for tests; production code path simply lets
    ``create_voice_clone_prompt`` perform transcription internally.
    """
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
            ),
        )
    return audio, state.sampling_rate
