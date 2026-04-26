"""
Permissions Configuration (PR-D.3.4).

Surfaces the executor's PermissionMode + Geny's runner enforcement
mode in the standard SettingsTab. Two knobs:

- ``runner_mode`` — Geny's outer "advisory|enforce" gate (does the
  PermissionRunner block deny rules or only log them).
- ``executor_mode`` — claude-code-style mode (default / plan / auto /
  bypass / acceptEdits / dontAsk) passed through to
  ``Pipeline.attach_runtime(permission_mode=…)``. Honored by every
  callsite of ``evaluate_permission`` once executor 1.2.0 (PR-B.5.1)
  is the active pin.

Both fields apply via env-sync so legacy callsites that still read
``GENY_PERMISSION_MODE`` / ``GENY_PERMISSION_EXEC_MODE`` directly
pick up the new value on the next session build.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import (
    BaseConfig,
    ConfigField,
    FieldType,
    register_config,
)
from service.config.sub_config.general.env_utils import (
    env_sync,
    read_env_defaults,
)


_RUNNER_OPTIONS = [
    {"value": "advisory", "label": "Advisory (log only)"},
    {"value": "enforce", "label": "Enforce (block on deny)"},
]


_EXECUTOR_OPTIONS = [
    {"value": "default", "label": "Default — rules decide"},
    {"value": "plan", "label": "Plan — read-only stance"},
    {"value": "auto", "label": "Auto — allow incl. destructive"},
    {"value": "bypass", "label": "Bypass — DEV ONLY (skip every check)"},
    {"value": "acceptEdits", "label": "Accept Edits — auto-allow Write/Edit"},
    {"value": "dontAsk", "label": "Don't Ask — every ASK becomes ALLOW"},
]


@register_config
@dataclass
class PermissionsConfig(BaseConfig):
    """Permission runner + executor mode."""

    runner_mode: str = "advisory"
    executor_mode: str = "default"

    _ENV_MAP = {
        "runner_mode": "GENY_PERMISSION_MODE",
        "executor_mode": "GENY_PERMISSION_EXEC_MODE",
    }

    @classmethod
    def get_default_instance(cls) -> "PermissionsConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "permissions"

    @classmethod
    def get_display_name(cls) -> str:
        return "Permissions"

    @classmethod
    def get_description(cls) -> str:
        return (
            "Permission runner mode (advisory vs enforce) and the "
            "executor-side PermissionMode (default / plan / auto / "
            "bypass / acceptEdits / dontAsk)."
        )

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "lock"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "권한",
                "description": (
                    "권한 러너 모드 (advisory / enforce) + 실행기 측 "
                    "PermissionMode (default / plan / auto / bypass / "
                    "acceptEdits / dontAsk)."
                ),
                "groups": {
                    "permissions": "권한 설정",
                },
                "fields": {
                    "runner_mode": {
                        "label": "러너 모드",
                        "description": (
                            "advisory 는 deny 규칙을 로그만 남깁니다. "
                            "enforce 는 실제로 차단합니다."
                        ),
                    },
                    "executor_mode": {
                        "label": "실행기 모드",
                        "description": (
                            "claude-code 의 PermissionMode. plan 은 "
                            "destructive 호출을 ASK 로 강제, "
                            "acceptEdits 는 Write/Edit 의 ASK 를 "
                            "자동 허용, dontAsk 는 모든 ASK 를 자동 "
                            "허용 (DENY 는 그대로)."
                        ),
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="runner_mode",
                field_type=FieldType.SELECT,
                label="Runner mode",
                description=(
                    "advisory logs deny rules; enforce blocks them."
                ),
                default="advisory",
                options=_RUNNER_OPTIONS,
                group="permissions",
                apply_change=env_sync("GENY_PERMISSION_MODE"),
            ),
            ConfigField(
                name="executor_mode",
                field_type=FieldType.SELECT,
                label="Executor mode",
                description=(
                    "claude-code-style PermissionMode. Mostly leave at "
                    "'default' unless you know which override applies."
                ),
                default="default",
                options=_EXECUTOR_OPTIONS,
                group="permissions",
                apply_change=env_sync("GENY_PERMISSION_EXEC_MODE"),
            ),
        ]
