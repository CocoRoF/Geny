"""
Long-Term Memory (Vector DB) Configuration.

Controls FAISS-backed vector retrieval for long-term memory:
- Enable / disable vector search
- Embedding provider & model selection
- Chunking parameters (size, overlap)
- Retrieval parameters (top-k, score threshold)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults


# ── Embedding provider options ────────────────────────────────────────

EMBEDDING_PROVIDER_OPTIONS = [
    {"value": "openai", "label": "OpenAI"},
    {"value": "google", "label": "Google (Gemini)"},
    {"value": "anthropic", "label": "Anthropic (Voyage)"},
]

OPENAI_MODEL_OPTIONS = [
    {"value": "text-embedding-3-small", "label": "text-embedding-3-small (1536d, cheap)", "group": "openai"},
    {"value": "text-embedding-3-large", "label": "text-embedding-3-large (3072d, best)", "group": "openai"},
    {"value": "text-embedding-ada-002", "label": "text-embedding-ada-002 (1536d, legacy)", "group": "openai"},
]

GOOGLE_MODEL_OPTIONS = [
    {"value": "text-embedding-004", "label": "text-embedding-004 (768d)", "group": "google"},
    {"value": "embedding-001", "label": "embedding-001 (768d, legacy)", "group": "google"},
]

ANTHROPIC_MODEL_OPTIONS = [
    {"value": "voyage-3-large", "label": "voyage-3-large (1024d, best)", "group": "anthropic"},
    {"value": "voyage-3", "label": "voyage-3 (1024d)", "group": "anthropic"},
    {"value": "voyage-3-lite", "label": "voyage-3-lite (512d, fast)", "group": "anthropic"},
    {"value": "voyage-code-3", "label": "voyage-code-3 (1024d, code-optimized)", "group": "anthropic"},
]

ALL_MODEL_OPTIONS = OPENAI_MODEL_OPTIONS + GOOGLE_MODEL_OPTIONS + ANTHROPIC_MODEL_OPTIONS


@register_config
@dataclass
class LTMConfig(BaseConfig):
    """Long-Term Memory vector search settings."""

    # ── Toggle ──
    enabled: bool = False

    # ── Embedding provider ──
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str = ""

    # ── Chunking ──
    chunk_size: int = 1024
    chunk_overlap: int = 256

    # ── Retrieval ──
    top_k: int = 6
    score_threshold: float = 0.35
    max_inject_chars: int = 10000

    # ── Curated Knowledge ──
    curated_knowledge_enabled: bool = False
    curated_vector_enabled: bool = False
    curated_inject_budget: int = 5000
    curated_max_results: int = 5

    # ── Auto-Curation Pipeline ──
    auto_curation_enabled: bool = False
    auto_curation_use_llm: bool = True
    auto_curation_quality_threshold: float = 0.6

    # ── Auto-Curation Scheduling ──
    auto_curation_schedule_enabled: bool = False
    auto_curation_interval_hours: int = 24
    auto_curation_max_notes_per_run: int = 20
    auto_curation_last_run: str = ""

    # ── User Opsidian Read Access ──
    user_opsidian_index_enabled: bool = False
    user_opsidian_raw_read_enabled: bool = False

    # ── Env mapping (for optional .env fallback) ──
    _ENV_MAP = {
        "embedding_api_key": "LTM_EMBEDDING_API_KEY",
    }

    # ──────────────────────────────────────────────────────────────────
    # BaseConfig interface
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def get_default_instance(cls) -> "LTMConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def is_enabled(cls) -> bool:
        """Quick check: is long-term memory enabled in the current config?

        Loads the persisted LTMConfig via the global config manager
        and returns ``config.enabled``.  Returns ``False`` on any
        error (config system unavailable, first run, etc.).
        """
        try:
            from service.config import get_config_manager

            mgr = get_config_manager()
            config = mgr.load_config(cls)
            return config is not None and config.enabled
        except Exception:
            return False

    @classmethod
    def get_config_name(cls) -> str:
        return "ltm"

    @classmethod
    def get_display_name(cls) -> str:
        return "Long-Term Memory"

    @classmethod
    def get_description(cls) -> str:
        return (
            "FAISS vector database settings for semantic long-term memory "
            "retrieval. Configure embedding provider, chunking, and search "
            "parameters."
        )

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "brain"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "Long-Term Memory (Vector DB)",
                "description": (
                    "Semantic long-term memory retrieval settings based on the FAISS vector database. "
                    "Configure embedding provider, chunking, and search parameters."
                ),
                "groups": {
                    "toggle": "Enable",
                    "embedding": "Embedding Settings",
                    "chunking": "Chunking Settings",
                    "retrieval": "Retrieval Settings",
                    "curated": "Curated Knowledge",
                    "auto_curation": "Auto-Curation Pipeline",
                    "auto_curation_schedule": "Curation Schedule",
                    "user_opsidian": "User Opsidian Access",
                },
                "fields": {
                    "enabled": {
                        "label": "Enable Long-Term Memory Vector Search",
                        "description": "Enable FAISS vector DB-based semantic search",
                    },
                    "embedding_provider": {
                        "label": "Embedding Provider",
                        "description": "API provider for converting text to vectors",
                    },
                    "embedding_model": {
                        "label": "Embedding Model",
                        "description": "Embedding model for the selected provider",
                    },
                    "embedding_api_key": {
                        "label": "Embedding API Key",
                        "description": "API key for the selected embedding provider",
                        "placeholder": "sk-… / AIza… / pa-…",
                    },
                    "chunk_size": {
                        "label": "Chunk Size",
                        "description": "Unit size (in characters) for splitting memory text",
                    },
                    "chunk_overlap": {
                        "label": "Chunk Overlap",
                        "description": "Number of overlapping characters between adjacent chunks",
                    },
                    "top_k": {
                        "label": "Top-K Results",
                        "description": "Maximum number of results to return per vector search",
                    },
                    "score_threshold": {
                        "label": "Similarity Threshold",
                        "description": "Results below this value are excluded (0 = no filter)",
                    },
                    "max_inject_chars": {
                        "label": "Max Inject Characters",
                        "description": "Maximum number of characters from vector search results to inject into context",
                    },
                    "curated_knowledge_enabled": {
                        "label": "Enable Curated Knowledge",
                        "description": "Enable the curated knowledge layer between User Opsidian and agent memory",
                    },
                    "curated_vector_enabled": {
                        "label": "Curated Vector Search",
                        "description": "Enable FAISS vector search within curated knowledge",
                    },
                    "curated_inject_budget": {
                        "label": "Curated Inject Budget",
                        "description": "Character budget for curated knowledge injected into context",
                    },
                    "curated_max_results": {
                        "label": "Curated Max Results",
                        "description": "Maximum number of curated knowledge notes to inject",
                    },
                    "auto_curation_enabled": {
                        "label": "Enable Auto-Curation",
                        "description": "Automatically curate high-quality notes from User Opsidian",
                    },
                    "auto_curation_use_llm": {
                        "label": "LLM-Assisted Curation",
                        "description": "Use LLM to evaluate and transform notes during curation",
                    },
                    "auto_curation_quality_threshold": {
                        "label": "Quality Threshold",
                        "description": "Minimum quality score (0-1) for auto-curation acceptance",
                    },
                    "auto_curation_schedule_enabled": {
                        "label": "Enable Scheduled Curation",
                        "description": "Run curation automatically on a periodic schedule",
                    },
                    "auto_curation_interval_hours": {
                        "label": "Curation Interval (hours)",
                        "description": "How often to run automatic curation (in hours)",
                    },
                    "auto_curation_max_notes_per_run": {
                        "label": "Max Notes Per Run",
                        "description": "Maximum number of notes to curate per scheduled run",
                    },
                    "auto_curation_last_run": {
                        "label": "Last Run",
                        "description": "Timestamp of the last automatic curation run",
                    },
                    "user_opsidian_index_enabled": {
                        "label": "Opsidian Index Access",
                        "description": "Allow agent to browse User Opsidian note index",
                    },
                    "user_opsidian_raw_read_enabled": {
                        "label": "Opsidian Raw Read",
                        "description": "Allow agent to read individual User Opsidian notes",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            # ── Toggle ──
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enable Vector Search",
                description="Enable FAISS-based semantic search for long-term memory",
                default=False,
                group="toggle",
            ),

            # ── Embedding ──
            ConfigField(
                name="embedding_provider",
                field_type=FieldType.SELECT,
                label="Embedding Provider",
                description="API provider for converting text to vectors",
                default="openai",
                options=EMBEDDING_PROVIDER_OPTIONS,
                group="embedding",
            ),
            ConfigField(
                name="embedding_model",
                field_type=FieldType.SELECT,
                label="Embedding Model",
                description="Model for the selected provider",
                default="text-embedding-3-small",
                options=ALL_MODEL_OPTIONS,
                group="embedding",
                depends_on="embedding_provider",
            ),
            ConfigField(
                name="embedding_api_key",
                field_type=FieldType.PASSWORD,
                label="Embedding API Key",
                description="API key for the selected embedding provider",
                required=False,
                placeholder="sk-… / AIza… / pa-…",
                group="embedding",
                secure=True,
                apply_change=env_sync("LTM_EMBEDDING_API_KEY"),
            ),

            # ── Chunking ──
            ConfigField(
                name="chunk_size",
                field_type=FieldType.NUMBER,
                label="Chunk Size (chars)",
                description="Character count per memory text chunk",
                default=1024,
                min_value=128,
                max_value=4096,
                group="chunking",
            ),
            ConfigField(
                name="chunk_overlap",
                field_type=FieldType.NUMBER,
                label="Chunk Overlap (chars)",
                description="Overlapping characters between adjacent chunks",
                default=256,
                min_value=0,
                max_value=512,
                group="chunking",
            ),

            # ── Retrieval ──
            ConfigField(
                name="top_k",
                field_type=FieldType.NUMBER,
                label="Top-K Results",
                description="Maximum number of results returned per vector search",
                default=6,
                min_value=1,
                max_value=30,
                group="retrieval",
            ),
            ConfigField(
                name="score_threshold",
                field_type=FieldType.NUMBER,
                label="Score Threshold",
                description="Filter out results below this cosine similarity (0 = no filter)",
                default=0.35,
                min_value=0.0,
                max_value=1.0,
                group="retrieval",
            ),
            ConfigField(
                name="max_inject_chars",
                field_type=FieldType.NUMBER,
                label="Max Inject Characters",
                description="Character budget for vector search results injected into context",
                default=10000,
                min_value=500,
                max_value=30000,
                group="retrieval",
            ),

            # ── Curated Knowledge ──
            ConfigField(
                name="curated_knowledge_enabled",
                field_type=FieldType.BOOLEAN,
                label="Enable Curated Knowledge",
                description="Enable the curated knowledge layer between User Opsidian and agent memory",
                default=False,
                group="curated",
            ),
            ConfigField(
                name="curated_vector_enabled",
                field_type=FieldType.BOOLEAN,
                label="Curated Vector Search",
                description="Enable FAISS vector search within curated knowledge",
                default=False,
                group="curated",
            ),
            ConfigField(
                name="curated_inject_budget",
                field_type=FieldType.NUMBER,
                label="Curated Inject Budget (chars)",
                description="Character budget for curated knowledge in context",
                default=5000,
                min_value=500,
                max_value=20000,
                group="curated",
            ),
            ConfigField(
                name="curated_max_results",
                field_type=FieldType.NUMBER,
                label="Curated Max Results",
                description="Maximum curated notes to inject per turn",
                default=5,
                min_value=1,
                max_value=20,
                group="curated",
            ),

            # ── Auto-Curation Pipeline ──
            ConfigField(
                name="auto_curation_enabled",
                field_type=FieldType.BOOLEAN,
                label="Enable Auto-Curation",
                description="Automatically curate from User Opsidian",
                default=False,
                group="auto_curation",
            ),
            ConfigField(
                name="auto_curation_use_llm",
                field_type=FieldType.BOOLEAN,
                label="LLM-Assisted Curation",
                description="Use LLM for quality evaluation during curation",
                default=True,
                group="auto_curation",
            ),
            ConfigField(
                name="auto_curation_quality_threshold",
                field_type=FieldType.NUMBER,
                label="Quality Threshold",
                description="Minimum quality score (0.0-1.0) for acceptance",
                default=0.6,
                min_value=0.0,
                max_value=1.0,
                group="auto_curation",
            ),

            # ── Auto-Curation Scheduling ──
            ConfigField(
                name="auto_curation_schedule_enabled",
                field_type=FieldType.BOOLEAN,
                label="Enable Scheduled Curation",
                description="Run curation automatically on a periodic schedule",
                default=False,
                group="auto_curation_schedule",
            ),
            ConfigField(
                name="auto_curation_interval_hours",
                field_type=FieldType.NUMBER,
                label="Interval (hours)",
                description="How often to run auto-curation",
                default=24,
                min_value=1,
                max_value=168,
                group="auto_curation_schedule",
            ),
            ConfigField(
                name="auto_curation_max_notes_per_run",
                field_type=FieldType.NUMBER,
                label="Max Notes Per Run",
                description="Cap on notes curated per scheduled run",
                default=20,
                min_value=1,
                max_value=100,
                group="auto_curation_schedule",
            ),
            ConfigField(
                name="auto_curation_last_run",
                field_type=FieldType.TEXT,
                label="Last Run",
                description="Timestamp of the last automatic curation run (read-only)",
                default="",
                group="auto_curation_schedule",
            ),

            # ── User Opsidian Access ──
            ConfigField(
                name="user_opsidian_index_enabled",
                field_type=FieldType.BOOLEAN,
                label="Opsidian Index Access",
                description="Let agents browse User Opsidian note index",
                default=False,
                group="user_opsidian",
            ),
            ConfigField(
                name="user_opsidian_raw_read_enabled",
                field_type=FieldType.BOOLEAN,
                label="Opsidian Raw Read",
                description="Let agents read individual User Opsidian notes",
                default=False,
                group="user_opsidian",
            ),
        ]
