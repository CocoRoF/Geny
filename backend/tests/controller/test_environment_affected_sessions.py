"""D.3 (cycle 20260426_1) — _affected_sessions_summary helper tests.

Verifies that the controller-side helper correctly counts and names
*active* sessions bound to a given env_id. The endpoint integration
(extending PUT/PATCH responses) is a one-line addition per endpoint;
we exercise the helper directly to keep these tests free of FastAPI
TestClient and the lifespan-installed environment service.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# session.store imports SQLAlchemy on some backends; pydantic always.
pytest.importorskip("pydantic")

import controller.environment_controller as env_ctrl  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_session_store(monkeypatch):
    """Replace ``service.sessions.store.get_session_store`` with a
    MagicMock returning a controllable ``list_active`` value."""
    fake_store = MagicMock()
    fake_records = [
        {"session_id": "s1", "session_name": "alpha", "env_id": "env-A"},
        {"session_id": "s2", "session_name": "beta", "env_id": "env-A"},
        {"session_id": "s3", "session_name": "gamma", "env_id": "env-B"},
        {"session_id": "s4", "session_name": None, "env_id": "env-A"},
    ]
    fake_store.list_active.return_value = fake_records

    import service.sessions.store as store_mod

    monkeypatch.setattr(store_mod, "get_session_store", lambda: fake_store)
    yield fake_store


def test_helper_counts_only_matching_env_id() -> None:
    summary = env_ctrl._affected_sessions_summary("env-A")
    assert summary.count == 3
    assert set(summary.session_ids) == {"s1", "s2", "s4"}


def test_helper_uses_session_id_when_name_is_missing() -> None:
    summary = env_ctrl._affected_sessions_summary("env-A")
    # session s4 has no name — the helper falls back to its id.
    assert "s4" in summary.session_names
    assert "alpha" in summary.session_names


def test_helper_returns_zero_for_unknown_env() -> None:
    summary = env_ctrl._affected_sessions_summary("env-not-here")
    assert summary.count == 0
    assert summary.session_ids == []
    assert summary.session_names == []


def test_helper_returns_zero_when_store_unavailable(monkeypatch) -> None:
    """When the session store module raises on import / lookup, the
    helper returns an empty summary instead of propagating — so the
    save endpoint's response stays well-formed even in test contexts
    that didn't install the lifespan store."""
    import service.sessions.store as store_mod

    def _boom():
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(store_mod, "get_session_store", _boom)
    summary = env_ctrl._affected_sessions_summary("env-A")
    assert summary.count == 0
