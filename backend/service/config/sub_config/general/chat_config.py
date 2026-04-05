"""
Chat System Configuration.

Controls SSE polling intervals, heartbeat timings, broadcast cleanup delay,
and other chat/execution behaviour parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults


@register_config
@dataclass
class ChatConfig(BaseConfig):
    """Chat system timing and behaviour settings."""

    sse_poll_interval_ms: int = 150
    sse_heartbeat_interval_s: int = 5
    messenger_heartbeat_interval_s: int = 15
    broadcast_cleanup_delay_s: int = 60
    holder_grace_period_s: int = 300
    message_retention_days: int = 0  # 0 = keep forever

    _ENV_MAP = {
        "sse_poll_interval_ms": "CHAT_SSE_POLL_INTERVAL_MS",
        "sse_heartbeat_interval_s": "CHAT_SSE_HEARTBEAT_INTERVAL_S",
        "messenger_heartbeat_interval_s": "CHAT_MESSENGER_HEARTBEAT_INTERVAL_S",
        "broadcast_cleanup_delay_s": "CHAT_BROADCAST_CLEANUP_DELAY_S",
        "holder_grace_period_s": "CHAT_HOLDER_GRACE_PERIOD_S",
        "message_retention_days": "CHAT_MESSAGE_RETENTION_DAYS",
    }

    @classmethod
    def get_default_instance(cls) -> "ChatConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "chat"

    @classmethod
    def get_display_name(cls) -> str:
        return "Chat"

    @classmethod
    def get_description(cls) -> str:
        return "SSE polling intervals, heartbeat timings, and broadcast cleanup settings."

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "chat"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "Chat",
                "description": "SSE 폴링 간격, 하트비트 타이밍, 브로드캐스트 정리 설정.",
                "groups": {
                    "timing": "Timing Settings",
                },
                "fields": {
                    "sse_poll_interval_ms": {
                        "label": "SSE Poll Interval (ms)",
                        "description": "SSE 이벤트 스트림 폴링 간격 (밀리초)",
                    },
                    "sse_heartbeat_interval_s": {
                        "label": "SSE Heartbeat Interval (s)",
                        "description": "SSE 하트비트 전송 간격 (초)",
                    },
                    "messenger_heartbeat_interval_s": {
                        "label": "Messenger Heartbeat Interval (s)",
                        "description": "메신저 SSE 하트비트 전송 간격 (초)",
                    },
                    "broadcast_cleanup_delay_s": {
                        "label": "Broadcast Cleanup Delay (s)",
                        "description": "브로드캐스트 상태 정리 대기 시간 (초)",
                    },
                    "holder_grace_period_s": {
                        "label": "Holder Grace Period (s)",
                        "description": "백그라운드 실행 종료 유예 시간 (초)",
                    },
                    "message_retention_days": {
                        "label": "Message Retention (days)",
                        "description": "메시지 보존 기간 (일). 0 = 영구 보존",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="sse_poll_interval_ms",
                field_type=FieldType.NUMBER,
                label="SSE Poll Interval (ms)",
                description="SSE event stream poll interval in milliseconds",
                default=150,
                min_value=50,
                max_value=5000,
                group="timing",
                apply_change=env_sync("CHAT_SSE_POLL_INTERVAL_MS"),
            ),
            ConfigField(
                name="sse_heartbeat_interval_s",
                field_type=FieldType.NUMBER,
                label="SSE Heartbeat Interval (s)",
                description="Heartbeat interval for command SSE streams",
                default=5,
                min_value=1,
                max_value=60,
                group="timing",
                apply_change=env_sync("CHAT_SSE_HEARTBEAT_INTERVAL_S"),
            ),
            ConfigField(
                name="messenger_heartbeat_interval_s",
                field_type=FieldType.NUMBER,
                label="Messenger Heartbeat Interval (s)",
                description="Heartbeat interval for messenger SSE streams",
                default=15,
                min_value=1,
                max_value=120,
                group="timing",
                apply_change=env_sync("CHAT_MESSENGER_HEARTBEAT_INTERVAL_S"),
            ),
            ConfigField(
                name="broadcast_cleanup_delay_s",
                field_type=FieldType.NUMBER,
                label="Broadcast Cleanup Delay (s)",
                description="Delay before cleaning up broadcast state after completion",
                default=60,
                min_value=10,
                max_value=600,
                group="timing",
                apply_change=env_sync("CHAT_BROADCAST_CLEANUP_DELAY_S"),
            ),
            ConfigField(
                name="holder_grace_period_s",
                field_type=FieldType.NUMBER,
                label="Holder Grace Period (s)",
                description="Grace period before cleaning up background execution holders",
                default=300,
                min_value=30,
                max_value=3600,
                group="timing",
                apply_change=env_sync("CHAT_HOLDER_GRACE_PERIOD_S"),
            ),
            ConfigField(
                name="message_retention_days",
                field_type=FieldType.NUMBER,
                label="Message Retention (days)",
                description="Auto-delete messages older than this many days. 0 = keep forever.",
                default=0,
                min_value=0,
                max_value=3650,
                group="retention",
                apply_change=env_sync("CHAT_MESSAGE_RETENTION_DAYS"),
            ),
        ]
