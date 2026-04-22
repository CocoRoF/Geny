"""
TTS General Configuration.

Global TTS settings: provider selection, emotion mapping,
audio format, and cache configuration.

This is the "General" card in the TTS sidebar category.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class TTSGeneralConfig(BaseConfig):
    """TTS global settings — Provider selection, emotion, audio, cache"""

    # ─── Basic ───
    enabled: bool = True
    provider: str = "gpt_sovits"
    auto_speak: bool = True
    default_language: str = "ko"

    # ─── Emotion speed mapping ───
    emotion_speed_joy: float = 1.1
    emotion_speed_anger: float = 1.2
    emotion_speed_sadness: float = 0.9
    emotion_speed_fear: float = 1.3
    emotion_speed_surprise: float = 1.2

    # ─── Emotion pitch mapping ───
    emotion_pitch_joy: str = "+50Hz"
    emotion_pitch_anger: str = "+20Hz"
    emotion_pitch_sadness: str = "-50Hz"
    emotion_pitch_fear: str = "+80Hz"
    emotion_pitch_surprise: str = "+100Hz"

    # ─── Audio ───
    audio_format: str = "mp3"
    sample_rate: int = 24000

    # ─── Cache ───
    cache_enabled: bool = True
    cache_max_size_mb: int = 500
    cache_ttl_hours: int = 24

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_general"

    @classmethod
    def get_display_name(cls) -> str:
        return "General (TTS Settings)"

    @classmethod
    def get_description(cls) -> str:
        return "Provider selection, language, emotion mapping, audio format, cache"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_icon(cls) -> str:
        return "settings"

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            # ─── Basic group ───
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enable TTS",
                description="Turn on/off VTuber voice synthesis globally",
                group="basic",
            ),
            ConfigField(
                name="provider",
                field_type=FieldType.SELECT,
                label="TTS Provider",
                description="Select which TTS engine to use. Provider-specific settings are in each card.",
                group="basic",
                options=[
                    {"value": "edge_tts", "label": "Edge TTS (Free)"},
                    {"value": "openai", "label": "OpenAI TTS"},
                    {"value": "elevenlabs", "label": "ElevenLabs"},
                    {"value": "gpt_sovits", "label": "GPT-SoVITS (Open Source)"},
                    {"value": "omnivoice", "label": "OmniVoice (Open Source · 600+ langs)"},
                    {"value": "azure", "label": "Azure Speech"},
                    {"value": "google", "label": "Google Cloud TTS"},
                    {"value": "clova", "label": "NAVER CLOVA Voice"},
                ],
            ),
            ConfigField(
                name="auto_speak",
                field_type=FieldType.BOOLEAN,
                label="Auto Speak",
                description="Automatically play voice when VTuber responds",
                group="basic",
            ),
            ConfigField(
                name="default_language",
                field_type=FieldType.SELECT,
                label="Default Language",
                group="basic",
                options=[
                    {"value": "ko", "label": "한국어"},
                    {"value": "ja", "label": "日本語"},
                    {"value": "en", "label": "English"},
                ],
            ),

            # ─── Emotion mapping group ───
            ConfigField(
                name="emotion_speed_joy",
                field_type=FieldType.NUMBER,
                label="Joy — Speed",
                group="emotion_mapping",
                min_value=0.5,
                max_value=2.0,
            ),
            ConfigField(
                name="emotion_speed_anger",
                field_type=FieldType.NUMBER,
                label="Anger — Speed",
                group="emotion_mapping",
                min_value=0.5,
                max_value=2.0,
            ),
            ConfigField(
                name="emotion_speed_sadness",
                field_type=FieldType.NUMBER,
                label="Sadness — Speed",
                group="emotion_mapping",
                min_value=0.5,
                max_value=2.0,
            ),
            ConfigField(
                name="emotion_speed_fear",
                field_type=FieldType.NUMBER,
                label="Fear — Speed",
                group="emotion_mapping",
                min_value=0.5,
                max_value=2.0,
            ),
            ConfigField(
                name="emotion_speed_surprise",
                field_type=FieldType.NUMBER,
                label="Surprise — Speed",
                group="emotion_mapping",
                min_value=0.5,
                max_value=2.0,
            ),
            ConfigField(
                name="emotion_pitch_joy",
                field_type=FieldType.STRING,
                label="Joy — Pitch",
                group="emotion_mapping",
                placeholder="+5%",
            ),
            ConfigField(
                name="emotion_pitch_anger",
                field_type=FieldType.STRING,
                label="Anger — Pitch",
                group="emotion_mapping",
                placeholder="+2%",
            ),
            ConfigField(
                name="emotion_pitch_sadness",
                field_type=FieldType.STRING,
                label="Sadness — Pitch",
                group="emotion_mapping",
                placeholder="-5%",
            ),
            ConfigField(
                name="emotion_pitch_fear",
                field_type=FieldType.STRING,
                label="Fear — Pitch",
                group="emotion_mapping",
                placeholder="+8%",
            ),
            ConfigField(
                name="emotion_pitch_surprise",
                field_type=FieldType.STRING,
                label="Surprise — Pitch",
                group="emotion_mapping",
                placeholder="+10%",
            ),

            # ─── Audio group ───
            ConfigField(
                name="audio_format",
                field_type=FieldType.SELECT,
                label="Audio Format",
                group="audio",
                options=[
                    {"value": "mp3", "label": "MP3 (Recommended)"},
                    {"value": "wav", "label": "WAV (Lossless)"},
                    {"value": "ogg", "label": "OGG"},
                ],
            ),
            ConfigField(
                name="sample_rate",
                field_type=FieldType.SELECT,
                label="Sample Rate",
                group="audio",
                options=[
                    {"value": 24000, "label": "24kHz (Default)"},
                    {"value": 44100, "label": "44.1kHz"},
                    {"value": 48000, "label": "48kHz"},
                ],
            ),

            # ─── Cache group ───
            ConfigField(
                name="cache_enabled",
                field_type=FieldType.BOOLEAN,
                label="Audio Cache",
                description="Cache TTS results for same text + emotion combination",
                group="cache",
            ),
            ConfigField(
                name="cache_max_size_mb",
                field_type=FieldType.NUMBER,
                label="Max Cache Size (MB)",
                group="cache",
                min_value=100,
                max_value=5000,
            ),
            ConfigField(
                name="cache_ttl_hours",
                field_type=FieldType.NUMBER,
                label="Cache TTL (hours)",
                group="cache",
                min_value=1,
                max_value=168,
            ),
        ]

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "General (TTS 공통 설정)",
                "description": "Provider 선택, 언어, 감정 매핑, 오디오 포맷, 캐시",
                "groups": {
                    "basic": "기본",
                    "emotion_mapping": "감정 매핑",
                    "audio": "오디오",
                    "cache": "캐시",
                },
                "fields": {
                    "enabled": {
                        "label": "TTS 활성화",
                        "description": "VTuber 음성 합성 기능 전체 ON/OFF",
                    },
                    "provider": {
                        "label": "TTS Provider",
                        "description": "사용할 TTS 엔진을 선택하세요. 각 Provider의 세부 설정은 개별 카드에서 합니다.",
                    },
                    "auto_speak": {
                        "label": "자동 음성 재생",
                        "description": "VTuber 응답 시 자동으로 음성을 재생합니다",
                    },
                    "default_language": {
                        "label": "기본 언어",
                    },
                    "emotion_speed_joy": {
                        "label": "기쁨 — 속도 배율",
                    },
                    "emotion_speed_anger": {
                        "label": "분노 — 속도 배율",
                    },
                    "emotion_speed_sadness": {
                        "label": "슬픔 — 속도 배율",
                    },
                    "emotion_speed_fear": {
                        "label": "공포 — 속도 배율",
                    },
                    "emotion_speed_surprise": {
                        "label": "놀람 — 속도 배율",
                    },
                    "emotion_pitch_joy": {
                        "label": "기쁨 — 피치",
                    },
                    "emotion_pitch_anger": {
                        "label": "분노 — 피치",
                    },
                    "emotion_pitch_sadness": {
                        "label": "슬픔 — 피치",
                    },
                    "emotion_pitch_fear": {
                        "label": "공포 — 피치",
                    },
                    "emotion_pitch_surprise": {
                        "label": "놀람 — 피치",
                    },
                    "audio_format": {
                        "label": "오디오 포맷",
                    },
                    "sample_rate": {
                        "label": "샘플레이트",
                    },
                    "cache_enabled": {
                        "label": "오디오 캐시",
                        "description": "동일 텍스트+감정의 TTS 결과를 캐시합니다",
                    },
                    "cache_max_size_mb": {
                        "label": "최대 캐시 크기 (MB)",
                    },
                    "cache_ttl_hours": {
                        "label": "캐시 유효 시간 (시간)",
                    },
                },
            },
            "en": {
                "display_name": "General (TTS Settings)",
                "description": "Provider selection, language, emotion mapping, audio format, cache",
                "groups": {
                    "basic": "Basic",
                    "emotion_mapping": "Emotion Mapping",
                    "audio": "Audio",
                    "cache": "Cache",
                },
            },
        }
