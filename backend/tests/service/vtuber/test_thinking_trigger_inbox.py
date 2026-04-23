"""Inbox-priority gating in ThinkingTriggerService (Plan / Phase06).

Background
----------

When the linked Sub-Worker finishes a task and reports back via
``_notify_linked_vtuber``, the message is delivered directly to the
VTuber if it is idle, and queued into the per-session inbox if the
VTuber is busy. The inbox drain path normally pulls these queued
messages back into a fresh ``execute_command`` turn, but the
thinking-trigger service used to fire a synthetic ``[THINKING_TRIGGER]``
prompt on top of an unread queue, causing the VTuber to narrate
"still waiting" while a real result was sitting unprocessed.

These tests pin the new contract:

* ``scan_all`` checks ``inbox.unread_count`` *before* the idle threshold
  comparison. If unread > 0, it kicks ``_drain_inbox`` instead of
  ``_fire_trigger``.
* ``_fire_trigger`` re-checks unread count at the last moment to handle
  the race where a Sub-Worker result lands between scan and fire.
* The helpers ``_safe_inbox_unread_count`` and ``_kick_inbox_drain``
  swallow inbox/drain failures so a misbehaving subsystem cannot block
  the trigger loop.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from service.vtuber.thinking_trigger import ThinkingTriggerService


# ---------------------------------------------------------------------------
# scan_all — inbox priority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_all_prefers_drain_over_fire_when_inbox_has_unread(
    monkeypatch,
) -> None:
    svc = ThinkingTriggerService(idle_threshold=10.0)
    fire = AsyncMock()
    drain = AsyncMock()
    svc._fire_trigger = fire  # type: ignore[assignment]
    svc._kick_inbox_drain = drain  # type: ignore[assignment]
    monkeypatch.setattr(
        svc, "_safe_inbox_unread_count", lambda _sid: 3
    )

    # Idle long enough that without the inbox guard we would fire.
    svc._activity["sid-busy-inbox"] = time.time() - 60

    await svc.scan_all()

    fire.assert_not_awaited()
    drain.assert_awaited_once_with("sid-busy-inbox")


@pytest.mark.asyncio
async def test_scan_all_fires_trigger_when_inbox_empty(monkeypatch) -> None:
    svc = ThinkingTriggerService(idle_threshold=10.0)
    fire = AsyncMock()
    drain = AsyncMock()
    svc._fire_trigger = fire  # type: ignore[assignment]
    svc._kick_inbox_drain = drain  # type: ignore[assignment]
    monkeypatch.setattr(
        svc, "_safe_inbox_unread_count", lambda _sid: 0
    )

    svc._activity["sid-idle"] = time.time() - 60

    await svc.scan_all()

    drain.assert_not_awaited()
    fire.assert_awaited_once_with("sid-idle")


@pytest.mark.asyncio
async def test_scan_all_drain_path_resets_activity(monkeypatch) -> None:
    """After dispatching a drain we still bump activity so the next
    tick doesn't pile up duplicate drains for the same session.
    """
    svc = ThinkingTriggerService(idle_threshold=10.0)
    svc._fire_trigger = AsyncMock()  # type: ignore[assignment]
    svc._kick_inbox_drain = AsyncMock()  # type: ignore[assignment]
    monkeypatch.setattr(
        svc, "_safe_inbox_unread_count", lambda _sid: 1
    )

    before = time.time() - 60
    svc._activity["sid"] = before

    await svc.scan_all()

    assert svc._activity["sid"] > before


@pytest.mark.asyncio
async def test_scan_all_inbox_guard_runs_even_below_idle_threshold(
    monkeypatch,
) -> None:
    """A queued Sub-Worker result must be drained promptly even if the
    session is technically below the idle threshold — otherwise a
    chatty user keeps the threshold permanently un-tripped while the
    inbox grows.
    """
    svc = ThinkingTriggerService(idle_threshold=120.0)
    fire = AsyncMock()
    drain = AsyncMock()
    svc._fire_trigger = fire  # type: ignore[assignment]
    svc._kick_inbox_drain = drain  # type: ignore[assignment]
    monkeypatch.setattr(
        svc, "_safe_inbox_unread_count", lambda _sid: 2
    )

    # Recent activity (well below threshold).
    svc._activity["sid-fresh"] = time.time() - 5

    await svc.scan_all()

    fire.assert_not_awaited()
    drain.assert_awaited_once_with("sid-fresh")


# ---------------------------------------------------------------------------
# _fire_trigger — last-mile guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_trigger_defers_to_drain_when_inbox_filled_late(
    monkeypatch,
) -> None:
    """The race we're guarding against: ``scan_all`` saw 0 unread, but
    by the time ``_fire_trigger`` runs, a Sub-Worker has just delivered
    a [SUB_WORKER_RESULT] into the inbox. The trigger must defer to
    drain instead of firing a synthetic idle prompt that contradicts
    the queued result.
    """
    svc = ThinkingTriggerService()

    drain = AsyncMock()
    monkeypatch.setattr(
        svc, "_safe_inbox_unread_count", lambda _sid: 1
    )
    monkeypatch.setattr(svc, "_kick_inbox_drain", drain)

    # Make execute_command explode if the trigger ever fires — the
    # whole point of the guard is that we DON'T reach it.
    async def _explode(*_a, **_kw):
        raise AssertionError("trigger fired despite unread inbox")

    import service.execution.agent_executor as exec_mod

    monkeypatch.setattr(exec_mod, "execute_command", _explode)

    await svc._fire_trigger("sid")

    drain.assert_awaited_once_with("sid")


# ---------------------------------------------------------------------------
# Helper resilience
# ---------------------------------------------------------------------------


def test_safe_inbox_unread_count_returns_zero_on_failure(monkeypatch) -> None:
    """Any inbox subsystem failure must not propagate — the trigger
    loop has to stay live even if the inbox file is corrupt or the
    module import explodes.
    """
    def _broken_get_inbox_manager():
        raise RuntimeError("inbox storage offline")

    monkeypatch.setattr(
        "service.chat.inbox.get_inbox_manager",
        _broken_get_inbox_manager,
        raising=False,
    )

    assert ThinkingTriggerService._safe_inbox_unread_count("sid") == 0


@pytest.mark.asyncio
async def test_kick_inbox_drain_swallows_errors(monkeypatch) -> None:
    async def _broken_drain(_sid):
        raise RuntimeError("drain crashed")

    import service.execution.agent_executor as exec_mod

    monkeypatch.setattr(exec_mod, "_drain_inbox", _broken_drain)

    # Must not raise.
    await ThinkingTriggerService._kick_inbox_drain("sid")
