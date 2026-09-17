"""Carry a pre-account install into the account world, once.

Before accounts existed, a Geny server reached its model through one global
credential per provider: an ``LLMCredentialsConfig`` key, or the Claude Code
CLI backend toggle. Environments named that provider directly.

Environments now name ``geny_router``, and the router resolves the session's
route — which means an install that upgrades with credentials but no accounts
can no longer start a session at all. It says "add a model account", to a user
who already added one, years ago, in the place the product told them to.

So on boot: make the accounts the legacy credentials describe, once, and
leave the legacy config alone (document embedding still reads it).

"Once" is a MARKER, not "the table is empty". The first version used the
empty table, and the first production run proved why that is not the same
thing: adoption created one account, failed on the second, and the empty-table
gate then blocked the retry forever — a server permanently half-migrated,
with no way to finish short of hand-editing the database. With a marker, a
partial adoption is retried on the next boot and only a COMPLETE one is
recorded as done.

The Claude Code mapping is the subtle one. ``in_modal_login`` and
``host_mount`` both mean "the login sitting in this machine's own ~/.claude",
which is the ``system`` auth method — NOT ``login``, which would point the CLI
at a fresh, empty, per-account directory and report the account as signed out.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["adopt_legacy_credentials", "plan_legacy_accounts"]


def plan_legacy_accounts(creds: Any, claude_cli: Any) -> List[Dict[str, Any]]:
    """The accounts a legacy configuration describes, in route order.

    Pure, so the mapping can be tested without a database — and the ORDER
    matters: it becomes the default route, so whatever the install was
    actually using has to come first.
    """
    plan: List[Dict[str, Any]] = []

    def text(value: Any) -> str:
        return str(value or "").strip()

    # The subscription backend first when it is on: it is the one the user
    # logged into deliberately, and on a working install it is what has been
    # answering.
    if getattr(claude_cli, "enabled", False):
        mode = text(getattr(claude_cli, "auth_mode", "")) or "host_mount"
        key = text(getattr(claude_cli, "api_key", ""))
        if mode == "setup_token" and key:
            claude = {"authMethod": "token", "mode": "token"}
            secret: Optional[str] = key
        elif mode == "api_key" and key:
            claude = {"authMethod": "api_key", "mode": "token"}
            secret = key
        else:
            # host_mount / in_modal_login / anything unknown: the CLI's own
            # login on this machine.
            claude = {"authMethod": "system", "mode": "token"}
            secret = None
        plan.append({
            "kind": "claude_code",
            "label": "Claude Code",
            "claude": claude,
            **({"secret": secret} if secret else {}),
        })

    for field, kind, label in (
        ("anthropic_api_key", "anthropic", "Anthropic"),
        ("openai_api_key", "openai", "OpenAI"),
        ("google_api_key", "google", "Gemini"),
    ):
        key = text(getattr(creds, field, ""))
        if key:
            plan.append({"kind": kind, "label": label, "secret": key})

    for field, kind, label in (
        ("ollama_base_url", "ollama", "Ollama"),
        ("lmstudio_base_url", "openai_compatible", "LM Studio"),
        ("custom_base_url", "openai_compatible", "Custom"),
        ("base_url", "vllm", "vLLM"),
    ):
        url = text(getattr(creds, field, ""))
        if url:
            plan.append({"kind": kind, "label": label, "baseUrl": url})

    return plan


def _marker_path() -> "Path":
    from service.llm_accounts.service import accounts_root

    return accounts_root() / ".legacy-adopted"


def adopt_legacy_credentials(service: Any = None, config_manager: Any = None) -> int:
    """Create the accounts the legacy config describes. Returns how many.

    Returns 0 once the migration has been recorded as complete, which is every
    boot after it succeeds. Never raises: a failure here must not stop the
    server, it only leaves the user to add an account by hand.
    """
    try:
        from service.config import get_config_manager
        from service.config.sub_config.general.cli_backends_config import (
            CLIBackendClaudeCodeConfig,
        )
        from service.config.sub_config.general.llm_credentials_config import (
            LLMCredentialsConfig,
        )
        from service.llm_accounts import get_account_service

        marker = _marker_path()
        if marker.exists():
            return 0

        account_service = service or get_account_service()
        cm = config_manager or get_config_manager()
        plan = plan_legacy_accounts(
            cm.load_config(LLMCredentialsConfig),
            cm.load_config(CLIBackendClaudeCodeConfig),
        )
        if not plan:
            _record(marker)
            return 0

        # An account of a kind that already exists is the user's, not ours —
        # this is also what makes a retry after a partial adoption safe.
        have = {a.get("kind") for a in account_service.list_accounts()}
        created = 0
        failed: List[str] = []
        for entry in plan:
            kind = str(entry.get("kind"))
            if kind in have:
                continue
            try:
                account_service.create_account(entry)
                created += 1
            except Exception as exc:  # noqa: BLE001 — one bad entry is not the rest
                failed.append(kind)
                logger.error("legacy adoption: could not create the %s account (%s)", kind, exc)

        if failed:
            # No marker: the next boot retries what is still missing. Leaving
            # a half-migrated server with no way to finish is worse than
            # trying again.
            logger.error(
                "legacy adoption incomplete — %s still missing; will retry on next start",
                ", ".join(failed),
            )
        else:
            _record(marker)
        if created:
            logger.info("legacy credentials adopted as %d model account(s)", created)
        return created
    except Exception as exc:  # noqa: BLE001 — never block boot
        logger.warning("legacy credential adoption skipped: %s", exc, exc_info=True)
        return 0


def _record(marker: "Path") -> None:
    """Remember that this install has been migrated.

    Without it the only available signal is "are there accounts", and that
    answers a different question: a user who deletes every account would be
    handed the legacy ones back on the next restart.
    """
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("adopted\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("legacy adoption: could not record the marker (%s)", exc)
