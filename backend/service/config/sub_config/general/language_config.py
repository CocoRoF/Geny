"""
Language Configuration.

Controls the UI display language and the language used for
system prompts / Claude responses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults

LANGUAGE_OPTIONS = [
    {"value": "en", "label": "English"},
    {"value": "ko", "label": "한국어 (Korean)"},
]


@register_config
@dataclass
class LanguageConfig(BaseConfig):
    """Language settings for UI and prompts."""

    language: str = "en"

    _ENV_MAP = {
        "language": "GENY_LANGUAGE",
    }

    @classmethod
    def get_default_instance(cls) -> "LanguageConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "language"

    @classmethod
    def get_display_name(cls) -> str:
        return "Language"

    @classmethod
    def get_description(cls) -> str:
        return "UI display language."

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "language"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "언어",
                "description": "UI 표시 언어 설정.",
                "groups": {
                    "language": "언어 설정",
                },
                "fields": {
                    "language": {
                        "label": "UI 언어",
                        "description": "사용자 인터페이스에 사용할 언어",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="language",
                field_type=FieldType.SELECT,
                label="UI Language",
                description="Language used for the user interface",
                default="en",
                options=LANGUAGE_OPTIONS,
                group="language",
                apply_change=env_sync("GENY_LANGUAGE"),
            ),
        ]

    # ── Public helpers for services ──

    @staticmethod
    def get_language() -> str:
        """Get current UI language (fast env-var lookup)."""
        return os.environ.get("GENY_LANGUAGE", "en")
