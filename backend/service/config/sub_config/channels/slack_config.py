"""
Slack Bot Configuration.

Enables Geny Agent integration with Slack workspaces.
Allows users to interact with Claude sessions via Slack messages.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class SlackConfig(BaseConfig):
    """
    Slack Bot Configuration.

    Enables Geny Agent integration with Slack workspaces.
    Allows users to interact with Claude sessions via Slack messages.
    """

    # Connection settings
    enabled: bool = False
    bot_token: str = ""  # xoxb-...
    app_token: str = ""  # xapp-... for Socket Mode
    signing_secret: str = ""

    # Workspace settings
    workspace_id: str = ""

    # Channel settings
    allowed_channel_ids: List[str] = field(default_factory=list)
    default_channel_id: str = ""

    # Permissions
    admin_user_ids: List[str] = field(default_factory=list)
    allowed_user_ids: List[str] = field(default_factory=list)

    # Behavior settings
    respond_to_mentions: bool = True
    respond_to_dms: bool = True
    respond_in_thread: bool = True  # Reply in threads
    use_blocks: bool = True  # Use Slack Block Kit for rich formatting
    max_message_length: int = 4000

    # Session settings
    session_timeout_minutes: int = 30
    max_sessions_per_user: int = 3
    default_prompt: str = ""

    # Slash commands
    enable_slash_commands: bool = True
    slash_command_name: str = "/claude"

    @classmethod
    def get_config_name(cls) -> str:
        return "slack"

    @classmethod
    def get_display_name(cls) -> str:
        return "Slack"

    @classmethod
    def get_description(cls) -> str:
        return "Configure Slack bot integration for Geny Agent. Allows users to interact with Claude sessions through Slack messages and slash commands."

    @classmethod
    def get_category(cls) -> str:
        return "channels"

    @classmethod
    def get_icon(cls) -> str:
        return "slack"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "Slack",
                "description": "Slack 봇 연동 설정. 사용자가 Slack 메시지 및 슬래시 명령을 통해 Claude 세션과 대화할 수 있습니다.",
                "groups": {
                    "connection": "연결 설정",
                    "workspace": "워크스페이스",
                    "permissions": "권한",
                    "behavior": "동작 설정",
                    "session": "세션 설정",
                    "commands": "슬래시 명령",
                },
                "fields": {
                    "enabled": {
                        "label": "Slack 연동 활성화",
                        "description": "Slack 봇 연동 활성화 또는 비활성화",
                    },
                    "bot_token": {
                        "label": "봇 토큰 (xoxb-)",
                        "description": "xoxb-로 시작하는 Slack 봇 토큰",
                    },
                    "app_token": {
                        "label": "앱 토큰 (xapp-)",
                        "description": "Socket Mode용 Slack 앱 레벨 토큰 (xapp-으로 시작)",
                    },
                    "signing_secret": {
                        "label": "서명 시크릿",
                        "description": "요청 검증을 위한 Slack 앱 서명 시크릿",
                    },
                    "workspace_id": {
                        "label": "워크스페이스 ID",
                        "description": "Slack 워크스페이스 ID (선택)",
                    },
                    "allowed_channel_ids": {
                        "label": "허용된 채널 ID",
                        "description": "쉼표로 구분된 채널 ID 목록. 비워두면 모든 채널 허용.",
                    },
                    "default_channel_id": {
                        "label": "기본 채널 ID",
                        "description": "봇 응답용 기본 채널",
                    },
                    "admin_user_ids": {
                        "label": "관리자 사용자 ID",
                        "description": "쉼표로 구분된 관리자 권한 사용자 ID 목록",
                    },
                    "allowed_user_ids": {
                        "label": "허용된 사용자 ID",
                        "description": "쉼표로 구분된 봇 사용 허용 사용자 ID 목록. 비워두면 모든 사용자 허용.",
                    },
                    "respond_to_mentions": {
                        "label": "멘션에 응답",
                        "description": "봇이 멘션되었을 때 응답",
                    },
                    "respond_to_dms": {
                        "label": "DM에 응답",
                        "description": "사용자가 DM으로 대화 허용",
                    },
                    "respond_in_thread": {
                        "label": "스레드에서 응답",
                        "description": "스레드에서 메시지에 응답",
                    },
                    "use_blocks": {
                        "label": "Block Kit 사용",
                        "description": "풍부한 메시지 포맷을 위한 Slack Block Kit 사용",
                    },
                    "max_message_length": {
                        "label": "최대 메시지 길이",
                        "description": "메시지당 최대 글자 수 (Slack 제한: 4000)",
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
                        "description": "Slack에서 시작된 세션의 기본 시스템 프롬프트",
                    },
                    "enable_slash_commands": {
                        "label": "슬래시 명령 활성화",
                        "description": "슬래시 명령 지원 활성화",
                    },
                    "slash_command_name": {
                        "label": "슬래시 명령 이름",
                        "description": "슬래시 명령의 이름 (예: /claude)",
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
                label="Enable Slack Integration",
                description="Enable or disable Slack bot integration",
                default=False,
                group="connection"
            ),
            ConfigField(
                name="bot_token",
                field_type=FieldType.PASSWORD,
                label="Bot Token (xoxb-)",
                description="Slack bot token starting with xoxb-",
                required=True,
                placeholder="xoxb-...",
                group="connection",
                secure=True
            ),
            ConfigField(
                name="app_token",
                field_type=FieldType.PASSWORD,
                label="App Token (xapp-)",
                description="Slack app-level token for Socket Mode (starts with xapp-)",
                placeholder="xapp-...",
                group="connection",
                secure=True
            ),
            ConfigField(
                name="signing_secret",
                field_type=FieldType.PASSWORD,
                label="Signing Secret",
                description="Slack app signing secret for request verification",
                placeholder="Enter signing secret",
                group="connection",
                secure=True
            ),

            # Workspace group
            ConfigField(
                name="workspace_id",
                field_type=FieldType.STRING,
                label="Workspace ID",
                description="Slack workspace ID (optional)",
                placeholder="T01234567",
                group="workspace"
            ),
            ConfigField(
                name="allowed_channel_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed Channel IDs",
                description="Comma-separated list of channel IDs. Leave empty for all channels.",
                placeholder="C01234567, C98765432",
                group="workspace"
            ),
            ConfigField(
                name="default_channel_id",
                field_type=FieldType.STRING,
                label="Default Channel ID",
                description="Default channel for bot responses",
                placeholder="C01234567",
                group="workspace"
            ),

            # Permissions group
            ConfigField(
                name="admin_user_ids",
                field_type=FieldType.TEXTAREA,
                label="Admin User IDs",
                description="Comma-separated list of user IDs with admin privileges",
                placeholder="U01234567",
                group="permissions"
            ),
            ConfigField(
                name="allowed_user_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed User IDs",
                description="Comma-separated list of user IDs allowed to use the bot. Leave empty for all users.",
                placeholder="U01234567, U98765432",
                group="permissions"
            ),

            # Behavior group
            ConfigField(
                name="respond_to_mentions",
                field_type=FieldType.BOOLEAN,
                label="Respond to Mentions",
                description="Respond when the bot is mentioned",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="respond_to_dms",
                field_type=FieldType.BOOLEAN,
                label="Respond to Direct Messages",
                description="Allow users to interact via DMs",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="respond_in_thread",
                field_type=FieldType.BOOLEAN,
                label="Reply in Threads",
                description="Reply to messages in threads",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="use_blocks",
                field_type=FieldType.BOOLEAN,
                label="Use Block Kit",
                description="Use Slack Block Kit for rich message formatting",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="max_message_length",
                field_type=FieldType.NUMBER,
                label="Max Message Length",
                description="Maximum characters per message (Slack limit: 4000)",
                default=4000,
                min_value=100,
                max_value=4000,
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
                description="Default system prompt for Slack-initiated sessions",
                placeholder="You are a helpful assistant...",
                group="session"
            ),

            # Slash commands group
            ConfigField(
                name="enable_slash_commands",
                field_type=FieldType.BOOLEAN,
                label="Enable Slash Commands",
                description="Enable slash command support",
                default=True,
                group="commands"
            ),
            ConfigField(
                name="slash_command_name",
                field_type=FieldType.STRING,
                label="Slash Command Name",
                description="Name of the slash command (e.g., /claude)",
                default="/claude",
                placeholder="/claude",
                group="commands"
            ),
        ]
