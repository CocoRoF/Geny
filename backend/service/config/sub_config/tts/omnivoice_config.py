"""
OmniVoice Configuration.

Settings for the in-cluster ``geny-omnivoice`` service (see
``Geny/omnivoice/``). OmniVoice is a 600+ language zero-shot TTS model
with three modes:

- ``clone``  — voice cloning using a reference audio (compatible with
  the ``static/voices/<profile>/ref_*.wav`` layout we already use for
  GPT-SoVITS).
- ``design`` — generate a voice from a natural-language ``instruct``
  string (``"female, low pitch, british accent"``).
- ``auto``   — let the model pick a random voice.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class OmniVoiceConfig(BaseConfig):
    """OmniVoice TTS settings — Geny's vendored multilingual TTS."""

    # ── Server ──────────────────────────────────────────────────────
    enabled: bool = False
    api_url: str = "http://omnivoice:9881"
    timeout_seconds: float = 60.0

    # ── Mode + voice ────────────────────────────────────────────────
    mode: str = "clone"  # clone | design | auto
    voice_profile: str = "paimon_ko"
    instruct: str = ""  # used when mode == "design"
    language: str = ""  # empty string = auto-detect

    # ── Generation parameters ───────────────────────────────────────
    num_step: int = 32
    guidance_scale: float = 2.0
    speed: float = 1.0
    duration_seconds: float = 0.0  # 0 → use speed
    denoise: bool = True

    # ── Output ──────────────────────────────────────────────────────
    audio_format: str = "wav"  # wav | mp3 | ogg | pcm

    # ── Whisper auto-ASR (server-side) ──────────────────────────────
    auto_asr: bool = False

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_omnivoice"

    @classmethod
    def get_display_name(cls) -> str:
        return "OmniVoice"

    @classmethod
    def get_description(cls) -> str:
        return "600+ language zero-shot TTS — voice cloning + voice design"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_icon(cls) -> str:
        return "mic"

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        profile_options = cls._get_profile_options()

        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enabled",
                description="geny-omnivoice service must be running",
                group="server",
            ),
            ConfigField(
                name="api_url",
                field_type=FieldType.URL,
                label="API URL",
                description="OmniVoice service URL (Docker: http://omnivoice:9881)",
                group="server",
                placeholder="http://omnivoice:9881",
            ),
            ConfigField(
                name="timeout_seconds",
                field_type=FieldType.NUMBER,
                label="HTTP Timeout (s)",
                group="server",
                min_value=5.0,
                max_value=300.0,
            ),
            ConfigField(
                name="mode",
                field_type=FieldType.SELECT,
                label="Generation Mode",
                description="clone = use voice profile; design = use instruct; auto = random voice",
                group="voice",
                options=[
                    {"value": "clone", "label": "Clone (use voice profile)"},
                    {"value": "design", "label": "Design (use instruct text)"},
                    {"value": "auto", "label": "Auto (random voice)"},
                ],
            ),
            ConfigField(
                name="voice_profile",
                field_type=FieldType.SELECT,
                label="Voice Profile",
                description="Used in clone mode — manage at /tts-voice",
                group="voice",
                options=profile_options,
            ),
            ConfigField(
                name="instruct",
                field_type=FieldType.STRING,
                label="Voice Design Instruct",
                description='e.g. "female, low pitch, british accent"',
                group="voice",
                placeholder="female, low pitch, british accent",
            ),
            ConfigField(
                name="language",
                field_type=FieldType.STRING,
                label="Language Override",
                description="Leave empty for auto-detect. Examples: ko, en, ja, zh.",
                group="voice",
                placeholder="",
            ),
            ConfigField(
                name="auto_asr",
                field_type=FieldType.BOOLEAN,
                label="Auto-transcribe ref_text",
                description="When the profile lacks prompt_text, ask the server to use Whisper",
                group="voice",
            ),
            ConfigField(
                name="num_step",
                field_type=FieldType.NUMBER,
                label="Diffusion Steps",
                group="generation",
                min_value=1,
                max_value=128,
            ),
            ConfigField(
                name="guidance_scale",
                field_type=FieldType.NUMBER,
                label="Guidance Scale (CFG)",
                group="generation",
                min_value=0.0,
                max_value=10.0,
            ),
            ConfigField(
                name="speed",
                field_type=FieldType.NUMBER,
                label="Speech Speed",
                group="generation",
                min_value=0.5,
                max_value=2.0,
            ),
            ConfigField(
                name="duration_seconds",
                field_type=FieldType.NUMBER,
                label="Fixed Duration (s)",
                description="0 = use speed factor; >0 = override speed and pin output length",
                group="generation",
                min_value=0.0,
                max_value=120.0,
            ),
            ConfigField(
                name="denoise",
                field_type=FieldType.BOOLEAN,
                label="Denoise",
                group="generation",
            ),
            ConfigField(
                name="audio_format",
                field_type=FieldType.SELECT,
                label="Audio Format",
                group="output",
                options=[
                    {"value": "wav", "label": "WAV"},
                    {"value": "mp3", "label": "MP3"},
                    {"value": "ogg", "label": "OGG/Vorbis"},
                    {"value": "pcm", "label": "PCM (raw int16)"},
                ],
            ),
        ]

    @classmethod
    def _get_profile_options(cls) -> List[Dict[str, str]]:
        """Reuse the same scan logic as GPT-SoVITS for parity."""
        import json as _json
        from pathlib import Path as _Path

        voices_dir = (
            _Path(__file__).parent.parent.parent.parent.parent / "static" / "voices"
        )
        options: List[Dict[str, str]] = []
        if voices_dir.exists():
            for d in sorted(voices_dir.iterdir()):
                if not d.is_dir():
                    continue
                label = d.name
                pj = d / "profile.json"
                if pj.exists():
                    try:
                        data = _json.loads(pj.read_text(encoding="utf-8"))
                        if data.get("display_name"):
                            label = f"{data['display_name']} ({d.name})"
                    except Exception:
                        pass
                options.append({"value": d.name, "label": label})
        return options or [{"value": "", "label": "(no profiles)"}]

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "OmniVoice",
                "description": "600+ 언어 zero-shot TTS — 보이스 클로닝 + 보이스 디자인",
                "groups": {
                    "server": "서버",
                    "voice": "보이스",
                    "generation": "생성 파라미터",
                    "output": "출력",
                },
                "fields": {
                    "enabled": {
                        "label": "활성화",
                        "description": "geny-omnivoice 서비스가 실행 중이어야 합니다",
                    },
                    "api_url": {
                        "label": "API URL",
                        "description": "OmniVoice 서버 주소 (Docker: http://omnivoice:9881)",
                    },
                    "mode": {
                        "label": "생성 모드",
                        "description": "clone = 보이스 프로필 / design = instruct / auto = 임의 보이스",
                    },
                    "voice_profile": {
                        "label": "보이스 프로필",
                        "description": "clone 모드에서 사용 — /tts-voice 페이지에서 관리",
                    },
                    "instruct": {
                        "label": "Voice Design 지시문",
                        "description": '예: "female, low pitch, british accent"',
                    },
                    "language": {
                        "label": "언어 강제",
                        "description": "비워두면 자동 감지. 예: ko, en, ja, zh",
                    },
                },
            },
            "en": {
                "display_name": "OmniVoice",
                "description": "600+ language zero-shot TTS — cloning + design",
                "groups": {
                    "server": "Server",
                    "voice": "Voice",
                    "generation": "Generation Parameters",
                    "output": "Output",
                },
            },
        }
