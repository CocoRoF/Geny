"""
Fish Speech Configuration.

Settings for the open-source Fish Speech TTS engine.
Uses an OpenAI-compatible API for fast synthesis.
Requires a locally running Fish Speech Docker container.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class FishSpeechConfig(BaseConfig):
    """Fish Speech TTS settings — open-source fast TTS"""

    enabled: bool = False
    api_url: str = "http://fish-speech:8080"
    reference_id: str = ""

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_fish_speech"

    @classmethod
    def get_display_name(cls) -> str:
        return "Fish Speech"

    @classmethod
    def get_description(cls) -> str:
        return "Open-source fast speech synthesis — OpenAI-compatible API"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_icon(cls) -> str:
        return "fish"

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enabled",
                description="Fish Speech Docker service must be running",
                group="server",
            ),
            ConfigField(
                name="api_url",
                field_type=FieldType.URL,
                label="API URL",
                description="OpenAI-compatible API server address",
                group="server",
                placeholder="http://localhost:8080",
            ),
            ConfigField(
                name="reference_id",
                field_type=FieldType.STRING,
                label="Reference Voice ID",
                description="Registered reference voice ID",
                group="voice",
            ),
        ]

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "Fish Speech",
                "description": "오픈소스 고속 음성 합성 — OpenAI 호환 API",
                "groups": {
                    "server": "서버",
                    "voice": "보이스",
                },
                "fields": {
                    "enabled": {
                        "label": "활성화",
                        "description": "Fish Speech Docker 서비스가 실행 중이어야 합니다",
                    },
                    "api_url": {
                        "label": "API URL",
                        "description": "OpenAI 호환 API 서버 주소",
                    },
                    "reference_id": {
                        "label": "Reference Voice ID",
                        "description": "등록된 레퍼런스 보이스 ID",
                    },
                },
            },
            "en": {
                "display_name": "Fish Speech",
                "description": "Open-source fast TTS — OpenAI-compatible API",
                "groups": {
                    "server": "Server",
                    "voice": "Voice",
                },
            },
        }
