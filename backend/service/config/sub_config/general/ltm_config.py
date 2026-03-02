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
                "display_name": "장기 기억 (Vector DB)",
                "description": (
                    "FAISS 벡터 데이터베이스 기반의 의미론적 장기 기억 검색 설정. "
                    "임베딩 제공자, 청킹, 검색 파라미터를 구성합니다."
                ),
                "groups": {
                    "toggle": "활성화",
                    "embedding": "임베딩 설정",
                    "chunking": "청킹 설정",
                    "retrieval": "검색 설정",
                },
                "fields": {
                    "enabled": {
                        "label": "장기 기억 벡터 검색 활성화",
                        "description": "FAISS 벡터 DB 기반 의미론적 검색을 활성화합니다",
                    },
                    "embedding_provider": {
                        "label": "임베딩 제공자",
                        "description": "텍스트를 벡터로 변환할 API 제공자",
                    },
                    "embedding_model": {
                        "label": "임베딩 모델",
                        "description": "선택한 제공자에 맞는 임베딩 모델",
                    },
                    "embedding_api_key": {
                        "label": "임베딩 API 키",
                        "description": "선택한 임베딩 제공자의 API 키",
                        "placeholder": "sk-… / AIza… / pa-…",
                    },
                    "chunk_size": {
                        "label": "청크 크기",
                        "description": "메모리 텍스트를 분할하는 단위 (문자 수)",
                    },
                    "chunk_overlap": {
                        "label": "청크 오버랩",
                        "description": "인접 청크 간 겹치는 문자 수",
                    },
                    "top_k": {
                        "label": "검색 결과 수 (Top-K)",
                        "description": "벡터 검색 시 반환할 최대 결과 수",
                    },
                    "score_threshold": {
                        "label": "유사도 임계값",
                        "description": "이 값 미만의 결과는 제외 (0 = 필터 없음)",
                    },
                    "max_inject_chars": {
                        "label": "최대 주입 문자 수",
                        "description": "컨텍스트에 주입할 벡터 검색 결과의 최대 문자 수",
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
        ]
