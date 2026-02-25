"""
Microsoft Teams Bot Configuration.

Enables Claude Control integration with Microsoft Teams.
Allows users to interact with Claude sessions via Teams messages.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class TeamsConfig(BaseConfig):
    """
    Microsoft Teams Bot Configuration.

    Enables Claude Control integration with Microsoft Teams.
    Allows users to interact with Claude sessions via Teams messages.
    """

    # Connection settings
    enabled: bool = False
    app_id: str = ""  # Microsoft App ID
    app_password: str = ""  # Microsoft App Password
    tenant_id: str = ""  # Azure AD tenant ID (optional, for single-tenant)

    # Bot Framework settings
    bot_endpoint: str = ""  # Messaging endpoint URL

    # Channel settings
    allowed_team_ids: List[str] = field(default_factory=list)
    allowed_channel_ids: List[str] = field(default_factory=list)

    # Permissions
    admin_user_ids: List[str] = field(default_factory=list)  # Azure AD Object IDs
    allowed_user_ids: List[str] = field(default_factory=list)

    # Behavior settings
    respond_to_mentions: bool = True
    respond_to_direct_messages: bool = True
    respond_in_threads: bool = True
    use_adaptive_cards: bool = True  # Use Adaptive Cards for rich formatting
    max_message_length: int = 28000  # Teams limit

    # Session settings
    session_timeout_minutes: int = 30
    max_sessions_per_user: int = 3
    default_prompt: str = ""

    # Graph API settings (optional, for advanced features)
    enable_graph_api: bool = False
    graph_client_secret: str = ""

    @classmethod
    def get_config_name(cls) -> str:
        return "teams"

    @classmethod
    def get_display_name(cls) -> str:
        return "Microsoft Teams"

    @classmethod
    def get_description(cls) -> str:
        return "Configure Microsoft Teams bot integration for Claude Control. Allows users to interact with Claude sessions through Teams messages."

    @classmethod
    def get_category(cls) -> str:
        return "channels"

    @classmethod
    def get_icon(cls) -> str:
        return "teams"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "Microsoft Teams",
                "description": "Microsoft Teams 봇 연동 설정. 사용자가 Teams 메시지를 통해 Claude 세션과 대화할 수 있습니다.",
                "groups": {
                    "connection": "연결 설정",
                    "teams": "팀 설정",
                    "permissions": "권한",
                    "behavior": "동작 설정",
                    "session": "세션 설정",
                    "graph": "Graph API",
                },
                "fields": {
                    "enabled": {
                        "label": "Teams 연동 활성화",
                        "description": "Microsoft Teams 봇 연동 활성화 또는 비활성화",
                    },
                    "app_id": {
                        "label": "Microsoft 앱 ID",
                        "description": "Azure Portal의 애플리케이션 (클라이언트) ID",
                    },
                    "app_password": {
                        "label": "앱 비밀번호",
                        "description": "Azure Portal의 클라이언트 시크릿",
                    },
                    "tenant_id": {
                        "label": "테넌트 ID (선택)",
                        "description": "단일 테넌트 앱용 Azure AD 테넌트 ID. 멀티 테넌트는 비워두세요.",
                    },
                    "bot_endpoint": {
                        "label": "봇 엔드포인트 URL",
                        "description": "봇의 메시징 엔드포인트 URL",
                    },
                    "allowed_team_ids": {
                        "label": "허용된 팀 ID",
                        "description": "쉼표로 구분된 팀 ID 목록. 비워두면 모든 팀 허용.",
                    },
                    "allowed_channel_ids": {
                        "label": "허용된 채널 ID",
                        "description": "쉼표로 구분된 채널 ID 목록. 비워두면 모든 채널 허용.",
                    },
                    "admin_user_ids": {
                        "label": "관리자 사용자 ID (Azure AD 개체 ID)",
                        "description": "쉼표로 구분된 관리자 권한 Azure AD 개체 ID 목록",
                    },
                    "allowed_user_ids": {
                        "label": "허용된 사용자 ID",
                        "description": "쉼표로 구분된 봇 사용 허용 사용자 ID 목록. 비워두면 모든 사용자 허용.",
                    },
                    "respond_to_mentions": {
                        "label": "멘션에 응답",
                        "description": "봇이 멘션되었을 때 응답",
                    },
                    "respond_to_direct_messages": {
                        "label": "DM에 응답",
                        "description": "사용자가 1:1 채팅으로 대화 허용",
                    },
                    "respond_in_threads": {
                        "label": "스레드에서 응답",
                        "description": "스레드/대화에서 메시지에 응답",
                    },
                    "use_adaptive_cards": {
                        "label": "Adaptive Cards 사용",
                        "description": "풍부한 메시지 포맷을 위한 Adaptive Cards 사용",
                    },
                    "max_message_length": {
                        "label": "최대 메시지 길이",
                        "description": "메시지당 최대 글자 수",
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
                        "description": "Teams에서 시작된 세션의 기본 시스템 프롬프트",
                    },
                    "enable_graph_api": {
                        "label": "Microsoft Graph API 활성화",
                        "description": "고급 기능(사용자 정보, 파일 등)을 위한 Graph API 활성화",
                    },
                    "graph_client_secret": {
                        "label": "Graph API 클라이언트 시크릿",
                        "description": "Graph API 접근을 위한 추가 클라이언트 시크릿 (다른 경우)",
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
                label="Enable Teams Integration",
                description="Enable or disable Microsoft Teams bot integration",
                default=False,
                group="connection"
            ),
            ConfigField(
                name="app_id",
                field_type=FieldType.STRING,
                label="Microsoft App ID",
                description="Application (client) ID from Azure Portal",
                required=True,
                placeholder="00000000-0000-0000-0000-000000000000",
                group="connection"
            ),
            ConfigField(
                name="app_password",
                field_type=FieldType.PASSWORD,
                label="App Password",
                description="Client secret from Azure Portal",
                required=True,
                placeholder="Enter app password/secret",
                group="connection",
                secure=True
            ),
            ConfigField(
                name="tenant_id",
                field_type=FieldType.STRING,
                label="Tenant ID (Optional)",
                description="Azure AD Tenant ID for single-tenant apps. Leave empty for multi-tenant.",
                placeholder="00000000-0000-0000-0000-000000000000",
                group="connection"
            ),
            ConfigField(
                name="bot_endpoint",
                field_type=FieldType.URL,
                label="Bot Endpoint URL",
                description="The messaging endpoint URL for your bot",
                placeholder="https://your-bot.azurewebsites.net/api/messages",
                group="connection"
            ),

            # Team settings group
            ConfigField(
                name="allowed_team_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed Team IDs",
                description="Comma-separated list of Team IDs. Leave empty for all teams.",
                placeholder="19:abc123...",
                group="teams"
            ),
            ConfigField(
                name="allowed_channel_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed Channel IDs",
                description="Comma-separated list of channel IDs. Leave empty for all channels.",
                placeholder="19:abc123...",
                group="teams"
            ),

            # Permissions group
            ConfigField(
                name="admin_user_ids",
                field_type=FieldType.TEXTAREA,
                label="Admin User IDs (Azure AD Object IDs)",
                description="Comma-separated list of Azure AD Object IDs with admin privileges",
                placeholder="00000000-0000-0000-0000-000000000000",
                group="permissions"
            ),
            ConfigField(
                name="allowed_user_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed User IDs",
                description="Comma-separated list of user IDs allowed to use the bot. Leave empty for all.",
                placeholder="00000000-0000-0000-0000-000000000000",
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
                name="respond_to_direct_messages",
                field_type=FieldType.BOOLEAN,
                label="Respond to Direct Messages",
                description="Allow users to interact via 1:1 chat",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="respond_in_threads",
                field_type=FieldType.BOOLEAN,
                label="Reply in Threads",
                description="Reply to messages in threads/conversations",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="use_adaptive_cards",
                field_type=FieldType.BOOLEAN,
                label="Use Adaptive Cards",
                description="Use Adaptive Cards for rich message formatting",
                default=True,
                group="behavior"
            ),
            ConfigField(
                name="max_message_length",
                field_type=FieldType.NUMBER,
                label="Max Message Length",
                description="Maximum characters per message",
                default=28000,
                min_value=100,
                max_value=28000,
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
                description="Default system prompt for Teams-initiated sessions",
                placeholder="You are a helpful assistant...",
                group="session"
            ),

            # Graph API group
            ConfigField(
                name="enable_graph_api",
                field_type=FieldType.BOOLEAN,
                label="Enable Microsoft Graph API",
                description="Enable Graph API for advanced features (user info, files, etc.)",
                default=False,
                group="graph"
            ),
            ConfigField(
                name="graph_client_secret",
                field_type=FieldType.PASSWORD,
                label="Graph API Client Secret",
                description="Additional client secret for Graph API access (if different)",
                placeholder="Enter Graph API secret",
                group="graph",
                secure=True
            ),
        ]
