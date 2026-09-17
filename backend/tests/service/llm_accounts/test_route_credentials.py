"""The session's route, as the pipeline receives it.

One provider name reaches Stage 6 — ``geny_router`` — and the route rides in
its credentials. Two things must hold or the failure is quiet:

* A route that resolved to nothing must NOT register the provider. Session
  creation asks ``bundle.has("geny_router")`` to answer "can this session
  reach a model?", and an empty route registered as configured turns a
  clear "add an account" into a mid-turn error.
* ``notify`` has to reach the client. It is how a rotated Codex token gets
  persisted — and that token is single-use.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from service.executor.credentials import CredentialBundleBuilder


class _Config:
    """A config manager that returns defaults for every config."""

    def load_config(self, cls: Any) -> Any:
        return cls()


def _builder(**kwargs: Any) -> CredentialBundleBuilder:
    return CredentialBundleBuilder(_Config(), **kwargs)


_TARGET = {
    "accountId": "a1", "label": "Claude", "kind": "claude_code",
    "engineProvider": "geny_claude_code", "model": "sonnet", "options": {},
}


def test_a_resolved_route_registers_the_router() -> None:
    bundle = _builder(route_targets=[_TARGET], session_id="s1").build()
    assert bundle.has("geny_router")
    extras = bundle.get("geny_router").extras
    assert extras["targets"] == [_TARGET]
    assert extras["session_id"] == "s1"


def test_an_empty_route_registers_nothing() -> None:
    """So session creation can say "add a model account" instead of letting
    the turn fail at the wire."""
    assert not _builder(route_targets=[]).build().has("geny_router")


def test_the_notify_hook_reaches_the_client() -> None:
    seen: List[Dict[str, Any]] = []
    bundle = _builder(route_targets=[_TARGET], route_notify=seen.append).build()
    bundle.get("geny_router").extras["notify"]({"kind": "route"})
    assert seen == [{"kind": "route"}]


def test_the_route_reaches_the_router_client_verbatim() -> None:
    """``_creds_to_client_kwargs`` forwards extras for routed providers — if
    it ever stopped, the router would be constructed with no route at all."""
    from geny_executor.core.pipeline import _creds_to_client_kwargs

    creds = _builder(route_targets=[_TARGET], session_id="s1").build().get("geny_router")
    kwargs = _creds_to_client_kwargs("geny_router", creds)
    assert kwargs["targets"] == [_TARGET]
    assert kwargs["session_id"] == "s1"


def test_a_turn_timeout_becomes_the_route_timeout() -> None:
    creds = _builder(route_targets=[_TARGET], route_timeout_s=1800).build().get("geny_router")
    assert creds.extras["timeout_s"] == 1800.0


def test_vendor_credentials_still_load_beside_the_route() -> None:
    """A route hop built from an API-key account resolves through the same
    per-provider entries, so they cannot simply go away."""
    bundle = _builder(route_targets=[_TARGET]).build()
    assert bundle.get("anthropic") is not None
    assert bundle.get("openai") is not None
