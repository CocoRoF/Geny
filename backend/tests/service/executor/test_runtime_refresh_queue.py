"""E.1 (cycle 20260426_1) — between-turn runtime refresh tests.

Verifies the queue + drain semantics of
``AgentSession.queue_runtime_refresh`` /
``AgentSession._apply_pending_runtime_refresh``. Direct method tests
against a fake Pipeline avoid spinning the full ``initialize`` path.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# AgentSession transitively imports pydantic via service.sessions.models.
pytest.importorskip("pydantic")

from service.executor.agent_session import AgentSession  # noqa: E402


def _bare_session(*, initialized: bool = True, with_pipeline: bool = True) -> AgentSession:
    """Construct a minimal AgentSession without going through __init__,
    populating only the attrs the queue/drain helpers read."""
    s = AgentSession.__new__(AgentSession)
    s._session_id = "sx"
    s._initialized = initialized
    s._pipeline = (
        SimpleNamespace(
            _set_tool_stage_permission_matrix=MagicMock(),
            _set_tool_stage_hook_runner=MagicMock(),
        )
        if with_pipeline
        else None
    )
    s._pending_runtime_refresh = None
    return s


def test_queue_rejects_unknown_scope() -> None:
    s = _bare_session()
    assert s.queue_runtime_refresh("not-a-scope") is False
    assert s._pending_runtime_refresh is None


def test_queue_rejects_uninitialized_session() -> None:
    s = _bare_session(initialized=False)
    assert s.queue_runtime_refresh("permissions") is False


def test_queue_rejects_session_without_pipeline() -> None:
    s = _bare_session(with_pipeline=False)
    assert s.queue_runtime_refresh("permissions") is False


def test_queue_accepts_valid_scope() -> None:
    s = _bare_session()
    assert s.queue_runtime_refresh("permissions") is True
    assert s._pending_runtime_refresh == "permissions"


def test_apply_no_op_when_queue_empty() -> None:
    s = _bare_session()
    # Should not raise even when nothing's queued.
    s._apply_pending_runtime_refresh()
    s._pipeline._set_tool_stage_permission_matrix.assert_not_called()
    s._pipeline._set_tool_stage_hook_runner.assert_not_called()


def test_apply_clears_flag_even_on_failure(monkeypatch) -> None:
    """A failed reload must NOT leave the queue stuck — the flag is
    one-shot and clears before the install call."""
    s = _bare_session()
    s.queue_runtime_refresh("permissions")

    # Stub install_permission_rules to raise.
    import service.permission.install as perm_install

    def boom():
        raise RuntimeError("permission install failed")

    monkeypatch.setattr(perm_install, "install_permission_rules", boom)

    s._apply_pending_runtime_refresh()
    # Flag is cleared regardless of failure.
    assert s._pending_runtime_refresh is None


def test_apply_calls_permissions_setter(monkeypatch) -> None:
    """Happy path — install returns rules+mode; the executor's stage
    setter is called with them."""
    s = _bare_session()
    s.queue_runtime_refresh("permissions")

    import service.permission.install as perm_install

    fake_rules = ["rule1", "rule2"]
    fake_mode = "enforce"
    monkeypatch.setattr(
        perm_install,
        "install_permission_rules",
        lambda: (fake_rules, fake_mode),
    )

    s._apply_pending_runtime_refresh()

    s._pipeline._set_tool_stage_permission_matrix.assert_called_once_with(
        permission_rules=fake_rules,
        permission_mode=fake_mode,
    )
    s._pipeline._set_tool_stage_hook_runner.assert_not_called()


def test_apply_with_scope_all_calls_both_setters(monkeypatch) -> None:
    s = _bare_session()
    s.queue_runtime_refresh("all")

    import service.permission.install as perm_install
    import service.hooks.install as hook_install

    monkeypatch.setattr(
        perm_install, "install_permission_rules", lambda: ([], "advisory"),
    )
    monkeypatch.setattr(
        hook_install, "install_hook_runner", lambda: object(),
    )

    s._apply_pending_runtime_refresh()
    s._pipeline._set_tool_stage_permission_matrix.assert_called_once()
    s._pipeline._set_tool_stage_hook_runner.assert_called_once()


def test_apply_skips_hook_when_install_returns_none(monkeypatch) -> None:
    """install_hook_runner returns ``None`` when the env gate is closed
    or no hooks are configured — refresh must skip the setter quietly."""
    s = _bare_session()
    s.queue_runtime_refresh("hooks")

    import service.hooks.install as hook_install

    monkeypatch.setattr(hook_install, "install_hook_runner", lambda: None)

    s._apply_pending_runtime_refresh()
    s._pipeline._set_tool_stage_hook_runner.assert_not_called()
