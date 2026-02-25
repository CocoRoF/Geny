"""
Telemetry Configuration.

Controls auto-updater, error reporting, and usage telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults


@register_config
@dataclass
class TelemetryConfig(BaseConfig):
    """Telemetry and update settings."""

    disable_autoupdater: bool = True
    disable_error_reporting: bool = True
    disable_telemetry: bool = True

    _ENV_MAP = {
        "disable_autoupdater": "DISABLE_AUTOUPDATER",
        "disable_error_reporting": "DISABLE_ERROR_REPORTING",
        "disable_telemetry": "DISABLE_TELEMETRY",
    }

    @classmethod
    def get_default_instance(cls) -> "TelemetryConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "telemetry"

    @classmethod
    def get_display_name(cls) -> str:
        return "Telemetry"

    @classmethod
    def get_description(cls) -> str:
        return "Control auto-updates, error reporting, and usage telemetry."

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "telemetry"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "텔레메트리",
                "description": "자동 업데이트, 오류 보고 및 사용 텔레메트리 제어.",
                "groups": {
                    "telemetry": "텔레메트리 설정",
                },
                "fields": {
                    "disable_autoupdater": {
                        "label": "자동 업데이트 비활성화",
                        "description": "자동 업데이트 방지",
                    },
                    "disable_error_reporting": {
                        "label": "오류 보고 비활성화",
                        "description": "오류 보고 전송 중지",
                    },
                    "disable_telemetry": {
                        "label": "텔레메트리 비활성화",
                        "description": "사용 텔레메트리 전송 중지",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="disable_autoupdater",
                field_type=FieldType.BOOLEAN,
                label="Disable Auto-Updater",
                description="Prevent automatic updates",
                default=True,
                group="telemetry",
                apply_change=env_sync("DISABLE_AUTOUPDATER"),
            ),
            ConfigField(
                name="disable_error_reporting",
                field_type=FieldType.BOOLEAN,
                label="Disable Error Reporting",
                description="Stop sending error reports",
                default=True,
                group="telemetry",
                apply_change=env_sync("DISABLE_ERROR_REPORTING"),
            ),
            ConfigField(
                name="disable_telemetry",
                field_type=FieldType.BOOLEAN,
                label="Disable Telemetry",
                description="Stop sending usage telemetry",
                default=True,
                group="telemetry",
                apply_change=env_sync("DISABLE_TELEMETRY"),
            ),
        ]
