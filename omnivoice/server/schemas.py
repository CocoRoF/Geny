"""Pydantic request / response schemas for the OmniVoice HTTP API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


GenerationMode = Literal["clone", "design", "auto"]
AudioFormat = Literal["wav", "mp3", "ogg", "pcm"]


class TTSRequest(BaseModel):
    """Single-shot TTS synthesis request."""

    text: str = Field(..., min_length=1, description="Text to synthesise.")
    mode: GenerationMode = Field(
        default="auto",
        description=(
            "clone = use ref_audio_path; design = use instruct; auto = let "
            "OmniVoice pick a random voice."
        ),
    )

    # Voice cloning
    ref_audio_path: Optional[str] = Field(
        default=None,
        description="Absolute path inside the container to the reference audio file.",
    )
    ref_text: Optional[str] = Field(
        default=None,
        description=(
            "Transcript of the reference audio. If omitted and the server "
            "was started with OMNIVOICE_AUTO_ASR=true, Whisper will fill it in."
        ),
    )

    # Voice design
    instruct: Optional[str] = Field(
        default=None,
        description="Speaker attribute string (e.g. 'female, low pitch, british accent').",
    )

    # Common controls
    language: Optional[str] = Field(
        default=None,
        description="Language code or name. Omit to auto-detect.",
    )
    speed: float = Field(default=1.0, gt=0.0, le=4.0)
    duration: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Fixed output duration in seconds; overrides speed when set.",
    )
    num_step: int = Field(default=32, ge=1, le=128)
    guidance_scale: float = Field(default=2.0, ge=0.0, le=10.0)
    denoise: bool = True
    preprocess_prompt: bool = True
    postprocess_output: bool = True

    # Wire format
    audio_format: AudioFormat = Field(
        default="wav",
        description="Container format for the response body.",
    )
    sample_rate: int = Field(default=24000)


EnginePhase = Literal["loading", "warming", "compiling", "ok", "error"]


class HealthResponse(BaseModel):
    """Service health.

    ``status`` is preserved for backward compatibility with older clients
    (it collapses ``warming``/``compiling`` to ``loading``). New clients
    should consume ``phase`` directly: it distinguishes "still bringing
    weights up" from "warming the algorithm cache" from "ready to serve".
    """

    status: Literal["ok", "loading", "error"]
    phase: EnginePhase = "loading"
    model: str
    device: str
    dtype: str
    sampling_rate: int
    auto_asr: bool
    max_concurrency: int


class VoiceRefAudio(BaseModel):
    emotion: str
    file: str  # absolute container path to the wav
    prompt_text: Optional[str] = None
    prompt_lang: Optional[str] = None


class VoiceProfile(BaseModel):
    id: str  # directory name
    name: str
    language: Optional[str] = None
    is_template: bool = False
    ref_audios: list[VoiceRefAudio] = Field(default_factory=list)


class VoicesResponse(BaseModel):
    voices: list[VoiceProfile]


class LanguagesResponse(BaseModel):
    languages: list[str]


class ServiceInfoResponse(BaseModel):
    service: Literal["geny-omnivoice"]
    version: str
    model: str
    device: str
    dtype: str
