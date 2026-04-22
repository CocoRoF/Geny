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

    # ── Persistent residency policy (Phase 1d) ───────────────────────
    # We are the sole GPU tenant: pre-allocate everything we'll need at
    # startup and never release it. Runtime should observe *zero* new
    # large allocations. See dev_docs/20260422_OmniVoice_Perf/.
    gpu_memory_fraction: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "If > 0, cap this process at this fraction of total VRAM via "
            "torch.cuda.set_per_process_memory_fraction(). 0 disables the cap. "
            "Recommended: 0.7 on hosts that share the GPU with a desktop, "
            "0.9 on dedicated hosts. GTX 1070 (8GB) → ~5.5GB at 0.7."
        ),
    )
    cudnn_benchmark: bool = Field(
        default=True,
        description=(
            "Enable cudnn.benchmark — algorithm selection cache for fixed "
            "input shapes. Safe for OmniVoice because _generate_iterative "
            "keeps shapes constant within a generation."
        ),
    )

    # ── Warmup (Phase 1a + 1d-4) ────────────────────────────────────
    warmup_enabled: bool = Field(
        default=True,
        description="Run multi-shape warmup syntheses inside lifespan.",
    )
    warmup_voice_profile: str = Field(
        default="",
        description=(
            "Container-relative profile name (e.g. 'paimon_ko'). Empty = use "
            "auto mode (no voice clone). Warmup falls back to auto on lookup miss."
        ),
    )
    warmup_buckets_seconds: tuple[float, float, float] = Field(
        default=(1.5, 4.0, 9.0),
        description=(
            "Target audio durations for short / medium / long warmup buckets. "
            "These exercise the cuDNN algorithm cache for the bucket sizes "
            "that real traffic will hit."
        ),
    )

    # ── Output buffer pool (Phase 1d-3) ─────────────────────────────
    pinned_pool_slots: int = Field(
        default=4,
        ge=0,
        le=64,
        description=(
            "Number of pre-allocated pinned host buffers used for D2H "
            "copies of synthesised PCM. 0 disables the pool."
        ),
    )
    max_audio_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=600.0,
        description=(
            "Upper bound on a single synthesised utterance. Drives sizing "
            "of the pinned pool and (in PR-2) the GenerationWorkspace."
        ),
    )

    # ── Forward-looking guards (defaults intentionally conservative) ─
    use_compile: Literal["auto", "always", "never"] = Field(
        default="auto",
        description=(
            "torch.compile policy. 'auto' enables on cap >= (7,0). On Pascal "
            "(sm_61) this is a no-op regardless. Reserved for Phase 3."
        ),
    )
    ref_cache_size: int = Field(
        default=0,
        ge=0,
        le=64,
        description=(
            "Voice-reference embedding LRU cache size. Reserved for Phase 2b; "
            "0 disables (current behaviour)."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
