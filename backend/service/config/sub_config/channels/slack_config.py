"""
Slack Bot Configuration.

Enables Claude Control integration with Slack workspaces.
Allows users to interact with Claude sessions via Slack messages.
"""

from dataclasses import dataclass, field
from typing import List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class SlackConfig(BaseConfig):
    """
    Slack Bot Configuration.

    Enables Claude Control integration with Slack workspaces.
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
        return "Configure Slack bot integration for Claude Control. Allows users to interact with Claude sessions through Slack messages and slash commands."

    @classmethod
    def get_category(cls) -> str:
        return "channels"

    @classmethod
    def get_icon(cls) -> str:
        return "slack"

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
