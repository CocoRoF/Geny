"""
Timezone Configuration.

Controls the timezone used across all GenY services:
- Think triggers (time-of-day prompts)
- Memory timestamps (LTM, STM writes)
- Prompt datetime section
- Shared-folder timestamps

The timezone value is an IANA identifier (e.g. "Asia/Seoul").
It is synced to the ``GENY_TIMEZONE`` environment variable so that
every module can read it cheaply via ``os.environ``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults

# Common timezone choices — value is IANA, label is user-friendly.
TIMEZONE_OPTIONS = [
    {"value": "Asia/Seoul", "label": "Asia/Seoul (KST, UTC+9)"},
    {"value": "Asia/Tokyo", "label": "Asia/Tokyo (JST, UTC+9)"},
    {"value": "Asia/Shanghai", "label": "Asia/Shanghai (CST, UTC+8)"},
    {"value": "Asia/Kolkata", "label": "Asia/Kolkata (IST, UTC+5:30)"},
    {"value": "Europe/London", "label": "Europe/London (GMT/BST)"},
    {"value": "Europe/Berlin", "label": "Europe/Berlin (CET/CEST)"},
    {"value": "Europe/Paris", "label": "Europe/Paris (CET/CEST)"},
    {"value": "America/New_York", "label": "America/New_York (EST/EDT)"},
    {"value": "America/Chicago", "label": "America/Chicago (CST/CDT)"},
    {"value": "America/Denver", "label": "America/Denver (MST/MDT)"},
    {"value": "America/Los_Angeles", "label": "America/Los_Angeles (PST/PDT)"},
    {"value": "Pacific/Auckland", "label": "Pacific/Auckland (NZST/NZDT)"},
    {"value": "Australia/Sydney", "label": "Australia/Sydney (AEST/AEDT)"},
    {"value": "UTC", "label": "UTC"},
]


@register_config
@dataclass
class TimezoneConfig(BaseConfig):
    """Timezone settings for all GenY time operations."""

    timezone: str = "Asia/Seoul"

    _ENV_MAP = {
        "timezone": "GENY_TIMEZONE",
    }

    @classmethod
    def get_default_instance(cls) -> "TimezoneConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "timezone"

    @classmethod
    def get_display_name(cls) -> str:
        return "Timezone"

    @classmethod
    def get_description(cls) -> str:
        return "Timezone used for all time operations across GenY."

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "clock"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "시간대",
                "description": "GenY 전체에서 사용하는 시간대 설정입니다.",
                "groups": {
                    "timezone": "시간대 설정",
                },
                "fields": {
                    "timezone": {
                        "label": "시간대",
                        "description": "VTuber 사고 트리거, 메모리 타임스탬프, 프롬프트 등 모든 시간 관련 기능에 적용됩니다.",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="timezone",
                field_type=FieldType.SELECT,
                label="Timezone",
                description="IANA timezone identifier used for all GenY time operations (think triggers, memory timestamps, prompts).",
                default="Asia/Seoul",
                options=TIMEZONE_OPTIONS,
                group="timezone",
                apply_change=env_sync("GENY_TIMEZONE"),
            ),
        ]

    # ── Public helpers for services ──

    @staticmethod
    def get_timezone() -> str:
        """Get current timezone IANA name (fast env-var lookup)."""
        return os.environ.get("GENY_TIMEZONE", "Asia/Seoul")
