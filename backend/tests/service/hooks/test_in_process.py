"""Geny in-process hook handler tests (PR-B.1.3)."""

from __future__ import annotations

import pytest

pytest.importorskip("geny_executor")

from service.hooks.in_process import (  # noqa: E402
    HIGH_RISK_TOOLS,
    install_in_process_handlers,
    log_high_risk_tool_call,
    log_permission_denied,
    observe_post_tool_use,
    recent_tool_events,
)


class _Payload:
    def __init__(self, *, tool_name, session_id="s1", details=None):
        self.tool_name = tool_name
        self.session_id = session_id
        self.details = details or {}


# ── log_permission_denied ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_permission_denied_logs_when_denied(caplog):
    caplog.set_level("WARNING")
    p = _Payload(
        tool_name="Bash",
        details={"permission_decision": "deny", "permission_reason": "no rule"},
    )
    await log_permission_denied(p)
    assert any("permission_denied" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_permission_denied_silent_when_not_denied(caplog):
    caplog.set_level("WARNING")
    await log_permission_denied(_Payload(tool_name="Read", details={"permission_decision": "allow"}))
    assert not any("permission_denied" in r.message for r in caplog.records)


# ── log_high_risk_tool_call ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_high_risk_logged(caplog):
    caplog.set_level("INFO")
    await log_high_risk_tool_call(_Payload(tool_name="Bash"))
    assert any("high_risk_tool_call" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_low_risk_silent(caplog):
    caplog.set_level("INFO")
    await log_high_risk_tool_call(_Payload(tool_name="Read"))
    assert not any("high_risk_tool_call" in r.message for r in caplog.records)


def test_high_risk_set_includes_canonical_destructive():
    for name in ("Bash", "Edit", "Write", "NotebookEdit", "MultiEdit"):
        assert name in HIGH_RISK_TOOLS


# ── observe_post_tool_use ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_tool_use_appends_to_ring():
    initial = len(recent_tool_events())
    await observe_post_tool_use(_Payload(tool_name="Read", session_id="ringtest"))
    rows = recent_tool_events()
    assert len(rows) > initial
    assert rows[0]["post_tool"] == "Read"


@pytest.mark.asyncio
async def test_recent_tool_events_limit():
    for i in range(5):
        await observe_post_tool_use(_Payload(tool_name=f"T{i}", session_id="lim"))
    rows = recent_tool_events(limit=3)
    assert len(rows) == 3


# ── install_in_process_handlers ──────────────────────────────────────


class _FakeRunner:
    def __init__(self):
        self.registered = []

    def register_in_process(self, event, handler):
        self.registered.append((event, handler))


def test_install_registers_three():
    runner = _FakeRunner()
    count = install_in_process_handlers(runner)
    assert count == 3
    assert len(runner.registered) == 3


def test_install_with_none_returns_zero(caplog):
    caplog.set_level("WARNING")
    assert install_in_process_handlers(None) == 0
    assert any("in_process_hooks_skipped" in r.message for r in caplog.records)


def test_install_with_old_runner_returns_zero():
    class _OldRunner:
        pass
    assert install_in_process_handlers(_OldRunner()) == 0
