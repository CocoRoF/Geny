"""Audio encoding helpers — turn OmniVoice's raw float32 ndarray into
container-formatted bytes that the HTTP layer can stream back to clients.
"""

from __future__ import annotations

import io
import logging
from typing import Literal

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

AudioFormat = Literal["wav", "mp3", "ogg", "pcm"]


def _to_int16(audio: np.ndarray) -> np.ndarray:
    """Float32 in [-1, 1] → int16 PCM."""
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def encode(audio: np.ndarray, sample_rate: int, fmt: AudioFormat) -> bytes:
    """Encode a 1-D mono ndarray into ``fmt``.

    Raises ``ValueError`` if the requested format is not supported by the
    runtime environment (e.g. mp3 without ffmpeg/libmp3lame).
    """
    if audio.ndim != 1:
        audio = audio.reshape(-1)

    if fmt == "wav":
        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, subtype="PCM_16", format="WAV")
        return buf.getvalue()

    if fmt == "ogg":
        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, format="OGG", subtype="VORBIS")
        return buf.getvalue()

    if fmt == "pcm":
        return _to_int16(audio).tobytes()

    if fmt == "mp3":
        try:
            from pydub import AudioSegment
        except ImportError as exc:  # pragma: no cover - env guard
            raise ValueError("mp3 encoding requires pydub + ffmpeg") from exc

        pcm = _to_int16(audio).tobytes()
        seg = AudioSegment(
            data=pcm,
            sample_width=2,
            frame_rate=sample_rate,
            channels=1,
        )
        buf = io.BytesIO()
        seg.export(buf, format="mp3")
        return buf.getvalue()

    raise ValueError(f"Unsupported audio format: {fmt}")


def media_type_for(fmt: AudioFormat) -> str:
    return {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "pcm": "application/octet-stream",
    }[fmt]
