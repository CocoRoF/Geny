"""
GPT-SoVITS Configuration.

Settings for the open-source GPT-SoVITS voice cloning engine.
Supports emotion-based reference audio selection for natural expression.
Requires a locally running GPT-SoVITS Docker container.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class GPTSoVITSConfig(BaseConfig):
    """GPT-SoVITS TTS settings — open-source voice cloning"""

    enabled: bool = False
    api_url: str = "http://gpt-sovits:9880"
    ref_audio_dir: str = "/app/static/voices/paimon_ko"
    container_ref_dir: str = "/workspace/GPT-SoVITS/references/paimon_ko"
    prompt_text: str = "우와아 이건 세상에서 제일 맛있는 요리야 이히힛 역시 네가 최고야"
    prompt_lang: str = "ko"
    top_k: int = 5
    top_p: float = 1.0
    temperature: float = 1.0
    speed: float = 1.0

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_gpt_sovits"

    @classmethod
    def get_display_name(cls) -> str:
        return "GPT-SoVITS"

    @classmethod
    def get_description(cls) -> str:
        return "Open-source voice cloning — natural emotion via per-emotion reference audio"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_icon(cls) -> str:
        return "lab"

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enabled",
                description="GPT-SoVITS Docker service must be running",
                group="server",
            ),
            ConfigField(
                name="api_url",
                field_type=FieldType.URL,
                label="API URL",
                description="GPT-SoVITS API v2 server address (Docker: http://gpt-sovits:9880)",
                group="server",
                placeholder="http://gpt-sovits:9880",
            ),
            ConfigField(
                name="ref_audio_dir",
                field_type=FieldType.STRING,
                label="Reference Audio Path (Backend)",
                description="Backend container path to per-emotion reference files",
                group="voice",
                placeholder="/app/static/voices/paimon_ko",
            ),
            ConfigField(
                name="container_ref_dir",
                field_type=FieldType.STRING,
                label="Reference Audio Path (GPT-SoVITS Container)",
                description="GPT-SoVITS container path — must match Docker volume mount (/workspace/GPT-SoVITS/references/...)",
                group="voice",
                placeholder="/workspace/GPT-SoVITS/references/paimon_ko",
            ),
            ConfigField(
                name="prompt_text",
                field_type=FieldType.STRING,
                label="Prompt Text",
                description="Transcription text for the reference audio",
                group="voice",
            ),
            ConfigField(
                name="prompt_lang",
                field_type=FieldType.SELECT,
                label="Prompt Language",
                group="voice",
                options=[
                    {"value": "ko", "label": "한국어"},
                    {"value": "ja", "label": "日本語"},
                    {"value": "en", "label": "English"},
                    {"value": "zh", "label": "中文"},
                ],
            ),
            ConfigField(
                name="top_k",
                field_type=FieldType.NUMBER,
                label="Top-K",
                group="generation",
                min_value=1,
                max_value=50,
            ),
            ConfigField(
                name="top_p",
                field_type=FieldType.NUMBER,
                label="Top-P",
                group="generation",
                min_value=0.0,
                max_value=1.0,
            ),
            ConfigField(
                name="temperature",
                field_type=FieldType.NUMBER,
                label="Temperature",
                group="generation",
                min_value=0.1,
                max_value=2.0,
            ),
            ConfigField(
                name="speed",
                field_type=FieldType.NUMBER,
                label="Speech Speed",
                group="generation",
                min_value=0.5,
                max_value=2.0,
            ),
        ]

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "GPT-SoVITS",
                "description": "오픈소스 음성 복제 — 감정별 레퍼런스 오디오로 자연스러운 감정 표현",
                "groups": {
                    "server": "서버",
                    "voice": "보이스",
                    "generation": "생성 파라미터",
                },
                "fields": {
                    "enabled": {
                        "label": "활성화",
                        "description": "GPT-SoVITS Docker 서비스가 실행 중이어야 합니다",
                    },
                    "api_url": {
                        "label": "API URL",
                        "description": "GPT-SoVITS API v2 서버 주소",
                    },
                    "ref_audio_dir": {
                        "label": "레퍼런스 오디오 경로 (Backend)",
                        "description": "Backend 컨테이너 기준 감정별 레퍼런스 파일 디렉토리",
                    },
                    "container_ref_dir": {
                        "label": "레퍼런스 오디오 경로 (GPT-SoVITS 컨테이너)",
                        "description": "GPT-SoVITS 컨테이너 내부 경로 — Docker 볼륨 마운트와 일치해야 합니다",
                    },
                    "prompt_text": {
                        "label": "프롬프트 텍스트",
                        "description": "레퍼런스 오디오에 해당하는 발화 텍스트",
                    },
                    "prompt_lang": {
                        "label": "프롬프트 언어",
                    },
                    "speed": {
                        "label": "발화 속도",
                    },
                },
            },
            "en": {
                "display_name": "GPT-SoVITS",
                "description": "Open-source voice cloning — emotion references",
                "groups": {
                    "server": "Server",
                    "voice": "Voice",
                    "generation": "Generation Parameters",
                },
            },
        }
