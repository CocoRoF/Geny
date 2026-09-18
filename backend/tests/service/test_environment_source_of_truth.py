"""Coverage for the "Environment manifest = single source of truth" refactor.

This replaces ``test_default_provider_override.py`` from the prior
heuristics era. The old override layer (PR #861) and several bypass
paths have been removed; what's tested here is that the canonical flow
holds end-to-end.

Invariants:

1. ``AgentSessionManager._extract_primary_provider`` returns whatever
   the env manifest's ``stage6.config['provider']`` says — no global
   override layer in front of it.
2. ``CredentialBundle.preferred_provider()`` (geny-executor 2.2.0 —
   replaces the deleted ``backend_resolver`` module) reads the user's
   configured backend and returns it, ``None`` when nothing is
   configured (call sites keep the anthropic last-resort).
3. Every seed environment names ``geny_router`` — a seed does not pick
   a backend; the session's account route does.

The ``claude_code_cli`` invariants that used to head this list are gone
with the provider (executor 2.68.0). The legacy CLI backend config is
still read, but only by ``service/llm_accounts/adopt_legacy.py``, which
has its own tests.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict
from unittest.mock import patch

import pytest

from service.config.sub_config.general.llm_credentials_config import (
    LLMCredentialsConfig,
)
from service.environment.service import EnvironmentService
from service.executor.credentials import CredentialBundleBuilder


def _preferred(cm) -> str | None:
    """Bundle-derived provider choice, isolated from ambient env keys."""
    scrub = {k: "" for k in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
    )}
    with patch.dict(os.environ, scrub):
        return CredentialBundleBuilder(config_manager=cm).build().preferred_provider()


def _minimal_env_manifest_dict(provider: str = "anthropic") -> Dict[str, Any]:
    return {
        "metadata": {
            "id": "test-env",
            "name": "Test env",
            "description": "",
            "tags": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "pipeline": {"name": "test", "max_iterations": 1},
        "stages": [
            {
                "order": 6,
                "name": "api",
                "active": True,
                "artifact": "default",
                "strategies": {"retry": "exponential_backoff", "router": "passthrough"},
                "strategy_configs": {},
                "config": {"provider": provider},
                "tool_binding": None,
                "model_override": None,
                "chain_order": {},
            }
        ],
        "tools": {"built_in": [], "external": [], "mcp_servers": []},
    }


class _StubConfigManager:
    def __init__(
        self,
        *,
                anthropic_api_key: str = "",
        openai_api_key: str = "",
        google_api_key: str = "",
        base_url: str = "",
    ) -> None:
        self._llm = LLMCredentialsConfig(
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key,
            google_api_key=google_api_key,
            base_url=base_url,
        )
    def load_config(self, cls):
        if cls is LLMCredentialsConfig:
            return self._llm
        raise ValueError(f"unexpected config requested: {cls}")


def test_extract_primary_provider_reads_manifest_only(tmp_path):
    """No global override layer in front of the manifest. The validator
    sees exactly what Pipeline.from_manifest_async will wire."""
    from service.executor.agent_session_manager import AgentSessionManager

    svc = EnvironmentService(storage_path=str(tmp_path / "envs"))
    (svc.storage_path / "test-env.json").write_text(
        json.dumps({
            "id": "test-env",
            "name": "Test",
            "manifest": _minimal_env_manifest_dict(provider="geny_codex"),
        })
    )

    mgr = AgentSessionManager.__new__(AgentSessionManager)
    mgr._environment_service = svc
    assert mgr._extract_primary_provider("test-env") == "geny_codex"


# ─────────────────────────────── preferred_provider (ex backend_resolver) ─


def test_resolver_picks_anthropic_when_only_anthropic_key():
    cm = _StubConfigManager(anthropic_api_key="sk-ant-x")
    assert _preferred(cm) == "anthropic"


def test_resolver_picks_openai_when_only_openai_key():
    cm = _StubConfigManager(openai_api_key="sk-proj-x")
    assert _preferred(cm) == "openai"


def test_resolver_returns_none_when_nothing_configured():
    """The library never silently defaults — ``None`` forces call sites
    to own the fallback (templates keep Geny's anthropic last-resort)."""
    cm = _StubConfigManager()
    assert _preferred(cm) is None


# ─────────────────────────────── build_manifest provider plumbing ─


def test_build_manifest_threads_provider():
    """The library factory stamps the provider into Stage 6 directly —
    same single-source contract the old build_default_manifest had."""
    from geny_executor import build_manifest

    m = build_manifest("default", provider="geny_router").to_dict()
    s6 = next(s for s in m["stages"] if s["name"] == "api")
    assert s6["config"]["provider"] == "geny_router"


def test_every_seed_names_the_router():
    """A seed no longer picks a backend. Which model answers is the
    session's account route, so changing model never costs the user the
    tool roster, persona and permission policy they built here."""
    from service.environment.templates import (
        create_vscode_env,
        create_vtuber_env,
        create_worker_env,
    )

    for factory in (create_worker_env, create_vtuber_env, create_vscode_env):
        m = factory().to_dict()
        s6 = next(s for s in m["stages"] if s["name"] == "api")
        assert s6["config"]["provider"] == "geny_router", factory.__name__
