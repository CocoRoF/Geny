"""Runtime configuration loaded from environment variables.

All knobs that a Geny operator may want to tune at deploy time are
collected here. Defaults are chosen to match the docker-compose service
contract documented in ``Geny/dev_docs/20260422_OmniVoice/index.md``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Geny-OmniVoice server settings.

    Environment variables use the ``OMNIVOICE_`` prefix and match the
    docker-compose ``environment:`` block exactly.
    """

    model_config = SettingsConfigDict(
        env_prefix="OMNIVOICE_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Model loading ────────────────────────────────────────────────
    model: str = Field(
        default="k2-fsa/OmniVoice",
        description="HuggingFace repo id or absolute path to the OmniVoice checkpoint.",
    )
    device: str = Field(
        default="cuda:0",
        description="Torch device map. Use 'cpu' or 'mps' for non-CUDA hosts.",
    )
    dtype: Literal["float16", "bfloat16", "float32"] = Field(
        default="float16",
        description="Inference dtype for the language-model backbone.",
    )

    # ── Server ───────────────────────────────────────────────────────
    host: str = Field(default="0.0.0.0", description="Bind address.")
    port: int = Field(default=9881, description="Bind port.")
    log_level: str = Field(default="info", description="uvicorn log level.")

    # ── Voice / data layout ──────────────────────────────────────────
    voices_dir: str = Field(
        default="/voices",
        description="Container path to the directory holding voice profiles.",
    )

    # ── Whisper auto-ASR for missing ref_text ────────────────────────
    auto_asr: bool = Field(
        default=False,
        description="Load Whisper at startup so reference text can be auto-transcribed.",
    )
    asr_model: str = Field(
        default="openai/whisper-large-v3-turbo",
        description="Whisper model id; only used when auto_asr is true.",
    )

    # ── Concurrency ──────────────────────────────────────────────────
    max_concurrency: int = Field(
        default=1,
        ge=1,
        description=(
            "Maximum concurrent in-flight synthesis calls. Single-GPU hosts "
            "should keep this at 1 to avoid CUDA OOM."
        ),
    )

    # ── Generation defaults ──────────────────────────────────────────
    default_num_step: int = Field(default=32, ge=1, le=128)
    default_guidance_scale: float = Field(default=2.0, ge=0.0, le=10.0)
    default_sample_rate: int = Field(default=24000)

    # ── HuggingFace cache ────────────────────────────────────────────
    hf_cache: str = Field(
        default="/models/hf-cache",
        description="HuggingFace cache directory; mirrored to HF_HOME at startup.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
