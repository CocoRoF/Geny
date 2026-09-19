"""Build :class:`geny_executor.CredentialBundle` from Geny's settings.

Phase H of the LLM backend upgrade cycle. The API credentials moved
out of ``APIConfig`` into a dedicated hidden ``LLMCredentialsConfig``
(edited only through the LLM Backends panel); ``CLIBackendClaudeCodeConfig``
is also hidden from the general list. This builder unifies both into the
single :class:`CredentialBundle` channel that
``Pipeline.from_manifest_async`` consumes.

The bundle is built fresh per session so a user toggling a backend on
or off (or rotating a key) takes effect on the next session create.

2026-09-17 — ``geny_router``. Every environment now names one provider,
and a session's **route** (the accounts it uses, in order) arrives here
as that provider's credentials. The per-provider entries below stay:
they are what a route hop built from an API-key account resolves to,
and what a legacy environment pinned to ``anthropic`` still uses.

2026-09-19 — the ``claude_code_cli`` entry is gone, and with it the
per-session MCP bridge that existed to hand Geny's tool registry to a
CLI running its own agentic loop. Nothing runs its own loop any more
(executor 2.68.0): ``geny_claude_code`` drives the same binary as a
pure token generator and its tools are dispatched by Stage 10, so a
bridge back into Geny would be a bridge to ourselves.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from geny_executor import CredentialBundle, ProviderCredentials

from service.config import get_config_manager
from service.config.sub_config.general.api_config import APIConfig
from service.config.sub_config.general.llm_credentials_config import LLMCredentialsConfig


__all__ = ["CredentialBundleBuilder"]


def _env_int(name: str) -> int:
    """Best-effort int from an env var; 0 when unset or non-numeric."""
    try:
        return int(os.environ.get(name, "0") or "0")
    except (TypeError, ValueError):
        return 0


class CredentialBundleBuilder:
    """Turn the live Geny config into a frozen :class:`CredentialBundle`.

    Usage::

        builder = CredentialBundleBuilder(route_targets=targets)
        bundle = builder.build()

    The builder reads from ``get_config_manager()`` on every ``build()``
    call so it picks up live edits.
    """

    def __init__(
        self,
        config_manager: Any | None = None,
        *,
        route_targets: Optional[list] = None,
        route_balance: bool = False,
        route_notify: Optional[Any] = None,
        session_id: Optional[str] = None,
        route_timeout_s: Optional[float] = None,
    ) -> None:
        self._cm = config_manager or get_config_manager()
        self._route_targets = list(route_targets or [])
        self._route_balance = bool(route_balance)
        self._route_notify = route_notify
        self._session_id = session_id
        self._route_timeout_s = route_timeout_s

    # ─────────────────────────────────────────────────────────── build ─

    def build(self) -> CredentialBundle:
        creds = self._cm.load_config(LLMCredentialsConfig)

        by_provider: Dict[str, ProviderCredentials] = {
            "anthropic": ProviderCredentials(
                api_key=(creds.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")),
            ),
            "openai": ProviderCredentials(
                api_key=(creds.openai_api_key or os.environ.get("OPENAI_API_KEY", "")),
            ),
            "google": ProviderCredentials(
                api_key=(creds.google_api_key or os.environ.get("GOOGLE_API_KEY", "")),
            ),
            "vllm": ProviderCredentials(
                base_url=(creds.base_url or None),
            ),
        }

        # Branded local (OpenAI-compatible) backends — executor 2.9.0
        # ProviderProfile providers. Registered only when a base_url is
        # configured (config field or env fallback) so
        # ``bundle.has(provider)`` / ``preferred_provider`` reflect real
        # availability and an unconfigured local card never shadows a
        # configured cloud backend. ``ollama_num_ctx`` rides in extras →
        # the client emits ``extra_body.options.num_ctx`` so Ollama loads
        # the model with the requested window.
        ollama_url = creds.ollama_base_url or os.environ.get("OLLAMA_BASE_URL", "")
        if ollama_url:
            ollama_extras: Dict[str, Any] = {}
            num_ctx = creds.ollama_num_ctx or _env_int("OLLAMA_NUM_CTX")
            if num_ctx and num_ctx > 0:
                ollama_extras["ollama_num_ctx"] = int(num_ctx)
            by_provider["ollama"] = ProviderCredentials(
                base_url=ollama_url, extras=ollama_extras
            )
        lmstudio_url = creds.lmstudio_base_url or os.environ.get("LMSTUDIO_BASE_URL", "")
        if lmstudio_url:
            by_provider["lmstudio"] = ProviderCredentials(base_url=lmstudio_url)
        custom_url = creds.custom_base_url or os.environ.get("CUSTOM_LLM_BASE_URL", "")
        if custom_url:
            by_provider["custom"] = ProviderCredentials(base_url=custom_url)

        # The session's route. Registered ONLY when it resolved to at least
        # one usable hop, so ``bundle.has("geny_router")`` answers the
        # question session creation actually asks — "can this session reach
        # a model?" — instead of reporting a route of nothing as configured.
        if self._route_targets:
            extras: Dict[str, Any] = {"targets": self._route_targets}
            if self._route_notify is not None:
                extras["notify"] = self._route_notify
            if self._session_id:
                extras["session_id"] = self._session_id
            if self._route_timeout_s:
                extras["timeout_s"] = float(self._route_timeout_s)
            if self._route_balance:
                # Spread turns across the healthy hops (least-recently-used)
                # instead of asking the first one until it hits its cap.
                extras["balance"] = True
            by_provider["geny_router"] = ProviderCredentials(extras=extras)

        return CredentialBundle(by_provider=by_provider)
