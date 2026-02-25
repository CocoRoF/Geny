"""
Resource Limits Configuration.

Controls API cost budgets, agent turn limits, and bash command timeouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults


@register_config
@dataclass
class LimitsConfig(BaseConfig):
    """Resource and execution limits."""

    max_budget_usd: float = 10.0
    max_turns: int = 50
    bash_default_timeout_ms: int = 30000
    bash_max_timeout_ms: int = 600000

    _ENV_MAP = {
        "max_budget_usd": "CLAUDE_MAX_BUDGET_USD",
        "max_turns": "CLAUDE_MAX_TURNS",
        "bash_default_timeout_ms": "BASH_DEFAULT_TIMEOUT_MS",
        "bash_max_timeout_ms": "BASH_MAX_TIMEOUT_MS",
    }

    @classmethod
    def get_default_instance(cls) -> "LimitsConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "limits"

    @classmethod
    def get_display_name(cls) -> str:
        return "Limits"

    @classmethod
    def get_description(cls) -> str:
        return "API cost budget, agent turn limits, and bash command timeouts."

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "limits"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "제한",
                "description": "API 비용 예산, 에이전트 턴 제한 및 Bash 명령 타임아웃.",
                "groups": {
                    "limits": "제한 설정",
                },
                "fields": {
                    "max_budget_usd": {
                        "label": "최대 예산 (USD)",
                        "description": "세션당 최대 API 비용 제한",
                    },
                    "max_turns": {
                        "label": "최대 에이전트 턴",
                        "description": "작업당 최대 에이전트 턴 수",
                    },
                    "bash_default_timeout_ms": {
                        "label": "Bash 기본 타임아웃 (ms)",
                        "description": "Bash 명령의 기본 타임아웃",
                    },
                    "bash_max_timeout_ms": {
                        "label": "Bash 최대 타임아웃 (ms)",
                        "description": "Bash 명령의 최대 허용 타임아웃",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="max_budget_usd",
                field_type=FieldType.NUMBER,
                label="Max Budget (USD)",
                description="Maximum API cost limit per session",
                default=10.0,
                min_value=0,
                max_value=1000,
                group="limits",
                apply_change=env_sync("CLAUDE_MAX_BUDGET_USD"),
            ),
            ConfigField(
                name="max_turns",
                field_type=FieldType.NUMBER,
                label="Max Agent Turns",
                description="Maximum number of agent turns per task",
                default=50,
                min_value=1,
                max_value=500,
                group="limits",
                apply_change=env_sync("CLAUDE_MAX_TURNS"),
            ),
            ConfigField(
                name="bash_default_timeout_ms",
                field_type=FieldType.NUMBER,
                label="Bash Default Timeout (ms)",
                description="Default timeout for bash commands",
                default=30000,
                min_value=1000,
                max_value=3600000,
                group="limits",
                apply_change=env_sync("BASH_DEFAULT_TIMEOUT_MS"),
            ),
            ConfigField(
                name="bash_max_timeout_ms",
                field_type=FieldType.NUMBER,
                label="Bash Max Timeout (ms)",
                description="Maximum allowed timeout for bash commands",
                default=600000,
                min_value=1000,
                max_value=7200000,
                group="limits",
                apply_change=env_sync("BASH_MAX_TIMEOUT_MS"),
            ),
        ]
