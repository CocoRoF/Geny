"""Tamagotchi / creature-state feature configuration.

Gates the runtime activation of the creature-state provider + decay
service at app startup. When disabled the system runs in **classic
mode** — no ``CreatureState`` persistence, no mood/bond/vitals
mutations, the session-info UI hides the creature panel, and the
affect-tag emitter becomes a pure display-stripper.

Replaces the earlier ad-hoc ``GENY_GAME_FEATURES`` env var with a
first-class config entry so operators can toggle via the Settings UI
rather than editing ``.env``. Cycle 20260422_5 (X7-follow-up).

Defaults intentionally enable the system — the X3..X7 infrastructure
is production-ready and the default behavior should be "VTuber
sessions have mood/bond working". Turn off only when operating a
headless worker deployment that has no VTuber persona and wants to
save a SQLite file + the 15-minute decay tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults


@register_config
@dataclass
class GameConfig(BaseConfig):
    """Runtime toggle for the Tamagotchi gameification subsystem."""

    enabled: bool = True
    state_db_path: str = ""
    vtuber_only: bool = True

    # Legacy env-var shims — only used by ``get_default_instance`` so
    # an existing deploy with ``GENY_GAME_FEATURES=1`` in .env keeps
    # working on first boot until the operator edits the config via
    # the Settings UI. After the first save the config value wins.
    _ENV_MAP = {
        "enabled": "GENY_GAME_FEATURES",
        "state_db_path": "GENY_STATE_DB",
    }

    @classmethod
    def get_default_instance(cls) -> "GameConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        # Empty string = "not set" for state_db_path so the lifespan
        # can fall back to the canonical backend/data path.
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "game"

    @classmethod
    def get_display_name(cls) -> str:
        return "Tamagotchi"

    @classmethod
    def get_description(cls) -> str:
        return (
            "Control the creature-state subsystem: mood, bond, vitals, "
            "and the VTuber status UI. Requires restart to take effect."
        )

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "game"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "다마고치",
                "description": "VTuber 의 기분 / 유대 / 바이탈 등 다마고치 상태 시스템을 제어합니다. 재시작 후 적용됩니다.",
                "groups": {
                    "game": "다마고치 설정",
                },
                "fields": {
                    "enabled": {
                        "label": "활성화",
                        "description": "다마고치 상태 시스템을 켭니다. 끄면 모든 세션이 클래식 모드 (상태 없음) 로 동작합니다.",
                    },
                    "state_db_path": {
                        "label": "상태 DB 경로",
                        "description": "크리처 상태를 저장하는 SQLite 파일 경로. 비워두면 기본 경로 (backend/data/geny_state.sqlite3).",
                    },
                    "vtuber_only": {
                        "label": "VTuber 세션만 적용",
                        "description": "켜두면 VTuber 역할 세션에만 상태가 붙습니다 (일반 Worker 세션은 classic 유지).",
                    },
                },
            },
            "en": {
                "display_name": "Tamagotchi",
                "description": "Control the creature-state subsystem: mood, bond, vitals, and the VTuber status UI. Requires restart.",
                "groups": {
                    "game": "Tamagotchi Settings",
                },
                "fields": {
                    "enabled": {
                        "label": "Enabled",
                        "description": "Activate the Tamagotchi state system. When off all sessions run classic (no state).",
                    },
                    "state_db_path": {
                        "label": "State DB path",
                        "description": "SQLite file path for creature persistence. Leave empty to use backend/data/geny_state.sqlite3.",
                    },
                    "vtuber_only": {
                        "label": "VTuber sessions only",
                        "description": "When on, only VTuber-role sessions receive creature state (plain Worker stays classic).",
                    },
                },
            },
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enabled",
                description="Activate the Tamagotchi state system. Requires restart.",
                default=True,
                group="game",
                apply_change=env_sync("GENY_GAME_FEATURES"),
            ),
            ConfigField(
                name="state_db_path",
                field_type=FieldType.STRING,
                label="State DB path",
                description="SQLite file path. Empty = use default (backend/data/geny_state.sqlite3).",
                default="",
                group="game",
                apply_change=env_sync("GENY_STATE_DB"),
            ),
            ConfigField(
                name="vtuber_only",
                field_type=FieldType.BOOLEAN,
                label="VTuber sessions only",
                description="Only VTuber-role sessions receive creature state.",
                default=True,
                group="game",
            ),
        ]
