"""
Discord Bot Configuration.

Enables Claude Control integration with Discord servers.
Allows users to interact with Claude sessions via Discord messages.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class DiscordConfig(BaseConfig):
    """
    Discord Bot Configuration.

    Enables Claude Control integration with Discord servers.
    Allows users to interact with Claude sessions via Discord messages.
    """

    # Connection settings
    enabled: bool = False
    bot_token: str = ""
    application_id: str = ""

    # Server/Guild settings
    guild_ids: List[str] = field(default_factory=list)  # Specific guilds, empty = all

    # Channel settings
    allowed_channel_ids: List[str] = field(default_factory=list)  # Empty = all channels
    command_prefix: str = "!"

    # Permissions
    admin_role_ids: List[str] = field(default_factory=list)
    allowed_user_ids: List[str] = field(default_factory=list)  # Empty = all users

    # Behavior settings
    respond_to_mentions: bool = True
    respond_to_dms: bool = False
    auto_thread: bool = True  # Create threads for conversations
    max_message_length: int = 2000

    # Session settings
    session_timeout_minutes: int = 30  # Auto-close inactive sessions
    max_sessions_per_user: int = 3
    default_prompt: str = ""  # Default system prompt for Discord sessions

    @classmethod
    def get_config_name(cls) -> str:
        return "discord"

    @classmethod
    def get_display_name(cls) -> str:
        return "Discord"

    @classmethod
    def get_description(cls) -> str:
        return "Configure Discord bot integration for Claude Control. Allows users to interact with Claude sessions through Discord messages."

    @classmethod
    def get_category(cls) -> str:
        return "channels"

    @classmethod
    def get_icon(cls) -> str:
        return "discord"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "Discord",
                "description": "Discord 봇 연동 설정. 사용자가 Discord 메시지를 통해 Claude 세션과 대화할 수 있습니다.",
                "groups": {
                    "connection": "연결 설정",
                    "server": "서버 설정",
                    "permissions": "권한",
                    "behavior": "동작 설정",
                    "session": "세션 설정",
                },
                "fields": {
                    "enabled": {
                        "label": "Discord 연동 활성화",
                        "description": "Discord 봇 연동 활성화 또는 비활성화",
                    },
                    "bot_token": {
                        "label": "봇 토큰",
                        "description": "Discord Developer Portal의 Discord 봇 토큰",
                    },
                    "application_id": {
                        "label": "애플리케이션 ID",
                        "description": "Developer Portal의 Discord 애플리케이션 ID",
                    },
                    "guild_ids": {
                        "label": "길드 ID (선택)",
                        "description": "쉼표로 구분된 길드/서버 ID 목록. 비워두면 모든 길드 허용.",
                    },
                    "allowed_channel_ids": {
                        "label": "허용된 채널 ID (선택)",
                        "description": "쉼표로 구분된 봇이 응답하는 채널 ID 목록. 비워두면 모든 채널 허용.",
                    },
                    "command_prefix": {
                        "label": "명령 접두사",
                        "description": "봇 명령 접두사 (예: !claude, /ask)",
                    },
                    "admin_role_ids": {
                        "label": "관리자 역할 ID",
                        "description": "쉼표로 구분된 관리자 권한 역할 ID 목록",
                    },
                    "allowed_user_ids": {
                        "label": "허용된 사용자 ID (선택)",
                        "description": "쉼표로 구분된 봇 사용 허용 사용자 ID 목록. 비워두면 모든 사용자 허용.",
                    },
                    "respond_to_mentions": {
                        "label": "멘션에 응답",
                        "description": "메시지에서 봇이 멘션되었을 때 응답",
                    },
                    "respond_to_dms": {
                        "label": "DM에 응답",
                        "description": "사용자가 DM으로 대화 허용",
                    },
                    "auto_thread": {
                        "label": "자동 스레드 생성",
                        "description": "대화를 위한 스레드 자동 생성",
                    },
                    "max_message_length": {
                        "label": "최대 메시지 길이",
                        "description": "메시지당 최대 글자 수 (Discord 제한: 2000)",
                    },
                    "session_timeout_minutes": {
                        "label": "세션 타임아웃 (분)",
                        "description": "비활성 세션을 지정 시간 후 자동 종료",
                    },
                    "max_sessions_per_user": {
                        "label": "사용자당 최대 세션 수",
                        "description": "사용자당 최대 동시 세션 수",
                    },
                    "default_prompt": {
                        "label": "기본 시스템 프롬프트",
                        "description": "Discord에서 시작된 세션의 기본 시스템 프롬프트",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            # Connection group
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enable Discord Integration",
                description="Enable or disable Discord bot integration",
                default=False,
                group="connection"
            ),
            ConfigField(
                name="bot_token",
                field_type=FieldType.PASSWORD,
                label="Bot Token",
                description="Discord bot token from Discord Developer Portal",
                required=True,
                placeholder="Enter your Discord bot token",
                group="connection",
                secure=True
            ),
            ConfigField(
                name="application_id",
                field_type=FieldType.STRING,
                label="Application ID",
                description="Discord application ID from Developer Portal",
                placeholder="123456789012345678",
                group="connection"
            ),

            # Server group
            ConfigField(
                name="guild_ids",
                field_type=FieldType.TEXTAREA,
                label="Guild IDs (Optional)",
                description="Comma-separated list of guild/server IDs. Leave empty for all guilds.",
                placeholder="123456789012345678, 987654321098765432",
                group="server"
            ),
            ConfigField(
                name="allowed_channel_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed Channel IDs (Optional)",
                description="Comma-separated list of channel IDs where bot responds. Leave empty for all channels.",
                placeholder="123456789012345678, 987654321098765432",
                group="server"
            ),
            ConfigField(
                name="command_prefix",
                field_type=FieldType.STRING,
                label="Command Prefix",
                description="Prefix for bot commands (e.g., !claude, /ask)",
                default="!",
                placeholder="!",
                group="server"
            ),

            # Permissions group
            ConfigField(
                name="admin_role_ids",
                field_type=FieldType.TEXTAREA,
                label="Admin Role IDs",
                description="Comma-separated list of role IDs with admin privileges",
                placeholder="123456789012345678",
                group="permissions"
            ),
            ConfigField(
                name="allowed_user_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed User IDs (Optional)",
                description="Comma-separated list of user IDs allowed to use the bot. Leave empty for all users.",
                placeholder="123456789012345678, 987654321098765432",
                group="permissions"
            ),

            # Behavior group
            ConfigField(
                name="respond_to_mentions",
                field_type=FieldType.BOOLEAN,
                label="Respond to Mentions",
                description="Respond when the bot is mentioned in a message",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="respond_to_dms",
                field_type=FieldType.BOOLEAN,
                label="Respond to Direct Messages",
                description="Allow users to interact via DMs",
                default=False,
                group="behavior"
            ),
            ConfigField(
                name="auto_thread",
                field_type=FieldType.BOOLEAN,
                label="Auto Create Threads",
                description="Automatically create threads for conversations",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="max_message_length",
                field_type=FieldType.NUMBER,
                label="Max Message Length",
                description="Maximum characters per message (Discord limit: 2000)",
                default=2000,
                min_value=100,
                max_value=2000,
                group="behavior"
            ),

            # Session group
            ConfigField(
                name="session_timeout_minutes",
                field_type=FieldType.NUMBER,
                label="Session Timeout (minutes)",
                description="Auto-close inactive sessions after this many minutes",
                default=30,
                min_value=5,
                max_value=1440,
                group="session"
            ),
            ConfigField(
                name="max_sessions_per_user",
                field_type=FieldType.NUMBER,
                label="Max Sessions Per User",
                description="Maximum concurrent sessions per user",
                default=3,
                min_value=1,
                max_value=10,
                group="session"
            ),
            ConfigField(
                name="default_prompt",
                field_type=FieldType.TEXTAREA,
                label="Default System Prompt",
                description="Default system prompt for Discord-initiated sessions",
                placeholder="You are a helpful assistant...",
                group="session"
            ),
        ]
