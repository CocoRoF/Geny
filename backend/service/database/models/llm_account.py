"""LLM account — one way this server can reach a model.

A Claude Code login, a second Claude Code login, a ChatGPT (Codex) login, an
Anthropic key, a local Ollama: each is one row. There is no limit per kind —
three Claude subscriptions are three rows, each owning its own
``CLAUDE_CONFIG_DIR`` so logging into one never logs the others out.

Nothing secret lives here. Keys, setup tokens and Codex OAuth tokens go to
:mod:`service.llm_accounts.secrets` (a 0600 file outside the database), and
the row only records that a secret exists.
"""
from typing import Dict, List

from service.database.models.base_model import BaseModel


class LLMAccountModel(BaseModel):
    """One model account (non-secret configuration only)."""

    def __init__(
        self,
        account_id: str = "",
        kind: str = "",
        label: str = "",
        enabled: bool = True,
        base_url: str = "",
        # Claude Code only: how the CLI authenticates, and whether the CLI
        # merely generates tokens (the harness runs the tools) or runs its
        # own agent loop.
        claude_auth_method: str = "login",
        # Legacy: used to select the CLI-owns-the-loop mode. Read by
        # nothing since 2026-09-19 (a provider is a model, not an agent);
        # the column stays so existing rows load unchanged.
        claude_mode: str = "token",
        effort: str = "",
        # JSON blobs — identity (email / plan / org) as last observed, the
        # models discovered from the provider, and the last check's verdict.
        identity_json: str = "",
        models_json: str = "",
        status_json: str = "",
        # What THIS endpoint serves, when the kind's default is only a
        # guess: one OpenAI-compatible address is a laptop's llama.cpp and
        # the next is a gateway in front of GPT-5. Merged over the kind's
        # declaration when the hop is built.
        capabilities_json: str = "",
        # How much context this endpoint's models hold:
        # ``{"declared": <int>, "discovered": {"<model>": <int>}}``.
        # Two sources, named, because they have a precedence: the operator
        # knows what sits behind a private address, and the endpoint knows
        # what it was launched with. Neither is a guess, which is the point —
        # the pipeline sizes compaction from this number.
        context_window_json: str = "",
        has_secret: bool = False,
        sort_order: int = 0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.account_id = account_id
        self.kind = kind
        self.label = label
        self.enabled = enabled
        self.base_url = base_url
        self.claude_auth_method = claude_auth_method
        self.claude_mode = claude_mode
        self.effort = effort
        self.identity_json = identity_json
        self.models_json = models_json
        self.status_json = status_json
        self.capabilities_json = capabilities_json
        self.context_window_json = context_window_json
        self.has_secret = has_secret
        self.sort_order = sort_order

    def get_table_name(self) -> str:
        return "llm_accounts"

    def get_schema(self) -> Dict[str, str]:
        return {
            "account_id": "VARCHAR(64) NOT NULL",
            "kind": "VARCHAR(40) NOT NULL",
            "label": "VARCHAR(200) DEFAULT ''",
            "enabled": "BOOLEAN DEFAULT TRUE",
            "base_url": "VARCHAR(500) DEFAULT ''",
            "claude_auth_method": "VARCHAR(20) DEFAULT 'login'",
            "claude_mode": "VARCHAR(20) DEFAULT 'token'",
            "effort": "VARCHAR(20) DEFAULT ''",
            "identity_json": "TEXT",
            "models_json": "TEXT",
            "status_json": "TEXT",
            "capabilities_json": "TEXT",
            "context_window_json": "TEXT",
            "has_secret": "BOOLEAN DEFAULT FALSE",
            "sort_order": "INTEGER DEFAULT 0",
        }

    def get_indexes(self) -> List[tuple]:
        return [("idx_llm_accounts_account_id", "account_id")]
