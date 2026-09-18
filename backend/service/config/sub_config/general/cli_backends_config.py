"""CLI-backend (Claude Code) settings — LEGACY, read once at boot.

This was the global "Claude Code backend" a pre-accounts Geny reached its
model through: one binary, one login, one toggle. Model **accounts**
replaced it (``service/llm_accounts``) — each account owns its own
``CLAUDE_CONFIG_DIR``, so any number of logins sit side by side and a
session's route picks between them.

Nothing builds credentials from this any more. It is kept for exactly one
reader: ``service/llm_accounts/adopt_legacy.py``, which on first boot
turns whatever this config describes into a real account, so an install
that upgrades with credentials but no accounts can still start a session.
Do not add new readers; add an account kind instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults


PERMISSION_MODE_OPTIONS = [
    {"value": "default", "label": "default"},
    {"value": "acceptEdits", "label": "acceptEdits"},
    {"value": "auto", "label": "auto"},
    {"value": "bypassPermissions", "label": "bypassPermissions"},
    {"value": "dontAsk", "label": "dontAsk"},
    {"value": "plan", "label": "plan"},
]


# The four auth methods the LLM Backends → Claude Code (CLI) modal lets
# the user pick from. Stored as a single source-of-truth on the config
# so the health probe + credential bundle both honour the user's
# explicit choice instead of guessing from whatever credential material
# happens to be present.
#
#   host_mount     — re-use the host's ``~/.claude/`` (mounted RW into
#                    the container). Auth method = subscription, source =
#                    OAuth credential file under HOME.
#   in_modal_login — ran ``claude auth login`` from inside the modal;
#                    OAuth credentials live in the container's
#                    ``~/.claude/.credentials.json``. Auth method =
#                    subscription, source = same file as host_mount.
#   setup_token    — pasted a long-lived ``claude setup-token`` value.
#                    The CLI binary itself reads it through its own
#                    credential persistence; we treat the auth method
#                    as subscription for UI purposes (the CLI's
#                    ``--bare`` short-circuit only applies to the
#                    ``api_key`` mode).
#   api_key        — explicit ``ANTHROPIC_API_KEY`` (per-card field or
#                    inherited from the Anthropic provider's key). The
#                    only mode where the spawned subprocess gets
#                    ``ANTHROPIC_API_KEY`` injected into its env.
AUTH_MODE_OPTIONS = [
    {"value": "host_mount", "label": "Host mount"},
    {"value": "in_modal_login", "label": "Modal login"},
    {"value": "setup_token", "label": "Setup token"},
    {"value": "api_key", "label": "API key (Console)"},
]
AUTH_MODE_VALUES = {opt["value"] for opt in AUTH_MODE_OPTIONS}


@register_config
@dataclass
class CLIBackendClaudeCodeConfig(BaseConfig):
    """Claude Code CLI backend settings.

    The fields map straight to ``ClaudeCodeCLIClient`` constructor
    kwargs via ``CredentialBundleBuilder``.
    """

    enabled: bool = False
    binary_path: str = ""                 # default: auto-detect via PATH
    workspace_root: str = ""              # session workspace; "" = use parent state cwd
    bare_mode: bool = True
    default_permission_mode: str = "default"
    max_budget_usd: float = 0.0            # 0 = no cap
    # User's explicit auth choice from the LLM Backends → Claude Code (CLI)
    # modal. Drives BOTH the health card's auth-method label AND what the
    # ``CredentialBundleBuilder`` feeds to ``ClaudeCodeCLIClient`` — when
    # the user picks ``in_modal_login`` we MUST not inject ANTHROPIC_API_KEY
    # into the subprocess env, because the CLI binary prefers env-var
    # auth over its own OAuth credential file and a stale key would 401
    # an otherwise valid session. Default ``host_mount`` mirrors the
    # original "reuse host's ~/.claude" behaviour.
    auth_mode: str = "host_mount"
    api_key: str = ""                      # only consumed when auth_mode == "api_key"
    settings_path: str = ""                # --settings file
    mcp_config_path: str = ""              # --mcp-config <path>
    allow_tools_csv: str = ""              # comma-separated --allowedTools
    disallow_tools_csv: str = ""           # comma-separated --disallowedTools
    extra_args_csv: str = ""               # extra argv flags
    # Per-CLI-call wall-clock budget. The Claude Code CLI runs a FULL agentic
    # tool-loop per invocation (sub-agent tasks routinely run many minutes), so
    # 300s was far too tight — it killed long sub-agent work mid-run with
    # "stream readline timeout". Default to 1h; tunable up to 4h.
    timeout_s: float = 3600.0

    _ENV_MAP = {
        "enabled": "CLAUDE_CODE_ENABLED",
        "binary_path": "CLAUDE_CODE_BINARY",
        "workspace_root": "CLAUDE_CODE_WORKSPACE_ROOT",
    }

    @classmethod
    def get_default_instance(cls) -> "CLIBackendClaudeCodeConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "cli_backend_claude_code"

    @classmethod
    def get_display_name(cls) -> str:
        return "Claude Code (CLI)"

    @classmethod
    def get_description(cls) -> str:
        return (
            "Settings for the Claude Code CLI backend. Drives the local "
            "``claude`` binary as a geny-executor LLM provider."
        )

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "terminal"

    @classmethod
    def is_user_visible(cls) -> bool:
        # Phase H — edited only through the LLM Backends panel's
        # ClaudeCodeAuthModal, not the auto-form list.
        return False

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "Claude Code (CLI)",
                "description": "로컬 claude CLI를 geny-executor의 LLM provider로 사용합니다.",
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enabled",
                description="Activate the Claude Code CLI provider in CredentialBundle.",
                default=False,
                group="claude_code",
                apply_change=env_sync("CLAUDE_CODE_ENABLED"),
            ),
            ConfigField(
                name="binary_path",
                field_type=FieldType.STRING,
                label="Binary Path",
                description="Path to the ``claude`` binary. Empty = auto-detect via PATH.",
                default="",
                placeholder="/usr/local/bin/claude",
                group="claude_code",
                apply_change=env_sync("CLAUDE_CODE_BINARY"),
            ),
            ConfigField(
                name="workspace_root",
                field_type=FieldType.STRING,
                label="Workspace Root",
                description="CWD passed to the spawned claude subprocess. Empty = parent.",
                default="",
                group="claude_code",
                apply_change=env_sync("CLAUDE_CODE_WORKSPACE_ROOT"),
            ),
            ConfigField(
                name="bare_mode",
                field_type=FieldType.BOOLEAN,
                label="Bare Mode",
                description="Pass --bare so hooks / auto-memory / LSP / plugin sync are disabled (recommended).",
                default=True,
                group="claude_code",
            ),
            ConfigField(
                name="default_permission_mode",
                field_type=FieldType.SELECT,
                label="Permission Mode",
                description="Forwarded as --permission-mode. 'default' omits the flag.",
                default="default",
                options=PERMISSION_MODE_OPTIONS,
                group="claude_code",
            ),
            ConfigField(
                name="max_budget_usd",
                field_type=FieldType.NUMBER,
                label="Max Budget (USD)",
                description="Per-call budget cap (0 = no cap). Forwarded as --max-budget-usd.",
                default=0.0,
                min_value=0.0,
                group="claude_code",
            ),
            ConfigField(
                name="auth_mode",
                field_type=FieldType.SELECT,
                label="Auth Mode",
                description=(
                    "Which Claude Code auth method to use. Picked from the "
                    "LLM Backends modal's four radio buttons; persisted "
                    "here so the backend honours the user's explicit "
                    "choice instead of guessing from available credentials."
                ),
                default="host_mount",
                options=AUTH_MODE_OPTIONS,
                group="claude_code",
            ),
            ConfigField(
                name="api_key",
                field_type=FieldType.PASSWORD,
                label="ANTHROPIC_API_KEY (api_key mode only)",
                description="Consumed only when auth_mode == 'api_key'. Other modes ignore this field.",
                default="",
                group="claude_code",
                secure=True,
            ),
            ConfigField(
                name="settings_path",
                field_type=FieldType.STRING,
                label="Settings file",
                description="Forwarded as --settings. Empty to skip.",
                default="",
                group="claude_code",
            ),
            ConfigField(
                name="mcp_config_path",
                field_type=FieldType.STRING,
                label="MCP config path",
                description="Forwarded as --mcp-config <path>. Empty to skip.",
                default="",
                group="claude_code",
            ),
            ConfigField(
                name="allow_tools_csv",
                field_type=FieldType.STRING,
                label="Allowed Tools (CSV)",
                description="Comma-separated. Forwarded via --allowedTools.",
                default="",
                placeholder="Read,Bash(git *),Edit",
                group="claude_code",
            ),
            ConfigField(
                name="disallow_tools_csv",
                field_type=FieldType.STRING,
                label="Disallowed Tools (CSV)",
                description="Comma-separated. Forwarded via --disallowedTools.",
                default="",
                group="claude_code",
            ),
            ConfigField(
                name="extra_args_csv",
                field_type=FieldType.STRING,
                label="Extra Args (CSV)",
                description="Escape hatch — additional argv tokens, comma-separated.",
                default="",
                group="claude_code",
            ),
            ConfigField(
                name="timeout_s",
                field_type=FieldType.NUMBER,
                label="Timeout (seconds)",
                description="Per-call wall-clock timeout covering the CLI's full "
                "agentic tool-loop (incl. sub-agent / sub-worker delegation, which "
                "can run many minutes). Default 3600s (1h); raise for very long tasks.",
                default=3600.0,
                min_value=10.0,
                max_value=14400.0,
                group="claude_code",
            ),
        ]


# ``CLIBackendCopilotConfig`` was removed in cycle 20260520. The
# ``gh copilot`` CLI advertises (and the upstream geny-executor's
# ``CopilotCLIClient`` honestly mirrors) ``supports_streaming=False``,
# ``supports_tools=False``, ``supports_mcp_passthrough=False`` — it is a
# one-shot text-in / text-out subprocess that cannot participate in
# Geny's Sub-Worker delegation or Stage-10 tool dispatch. Keeping the
# config card around encouraged operators to enable a backend that would
# immediately fail at the first tool call. Existing DB rows for
# ``cli_backend_copilot`` are harmlessly ignored.
