"""Bus emission integration — manager + agent wiring produces events.

These tests intentionally bypass the heavy ``AgentSessionManager`` /
``AgentSession`` construction paths (which need env service, sessions.json,
etc.). We drive the bus directly through the manager property and through
``AgentSession``'s revive emission helpers — the wiring under test is:

1. ``manager.lifecycle_bus`` is a live ``SessionLifecycleBus``.
2. ``AgentSession`` with a ``lifecycle_bus`` kwarg calls it from
   ``_emit_revived`` / ``_schedule_revived_emit``.
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from backend.service.lifecycle import (
    LifecycleEvent,
    LifecyclePayload,
    SessionLifecycleBus,
)


def _make_recorder() -> tuple[list[LifecyclePayload], "_AsyncHandler"]:
    """Return (bucket, handler) — handler is a real coroutine function.

    A coroutine *function* is required (callable class with ``__call__``
    is rejected by the bus) so that ``asyncio.iscoroutinefunction``
    accepts it. See ``SessionLifecycleBus._ensure_async``.
    """
    events: List[LifecyclePayload] = []

    async def handler(payload: LifecyclePayload) -> None:
        events.append(payload)

    return events, handler


_AsyncHandler = object  # type alias placeholder for readability only


@pytest.mark.asyncio
async def test_manager_lifecycle_bus_is_wired() -> None:
    """Smoke-test: manager exposes a live bus via its property.

    We cannot construct a real ``AgentSessionManager`` in unit tests
    (env service, sessions.json, executor deps). Instead construct a
    minimal subclass that skips ``__init__`` and only sets the bus —
    this mirrors the property access path exactly.
    """
    from backend.service.langgraph.agent_session_manager import (
        AgentSessionManager,
    )

    mgr = object.__new__(AgentSessionManager)
    mgr._lifecycle_bus = SessionLifecycleBus()

    events, handler = _make_recorder()
    mgr.lifecycle_bus.subscribe(LifecycleEvent.SESSION_CREATED, handler)
    await mgr.lifecycle_bus.emit(
        LifecycleEvent.SESSION_CREATED,
        "sid",
        role="worker",
        is_vtuber=False,
    )

    assert len(events) == 1
    p = events[0]
    assert p.event is LifecycleEvent.SESSION_CREATED
    assert p.session_id == "sid"
    assert p.meta == {"role": "worker", "is_vtuber": False}


@pytest.mark.asyncio
async def test_agent_session_emit_revived_fires_with_bus() -> None:
    """``AgentSession._emit_revived`` pushes SESSION_REVIVED through the bus."""
    from backend.service.langgraph.agent_session import AgentSession
    from service.langgraph.session_freshness import SessionFreshness

    bus = SessionLifecycleBus()
    events, handler = _make_recorder()
    bus.subscribe(LifecycleEvent.SESSION_REVIVED, handler)

    # Build a session skeleton that has just enough shape for the helper.
    agent = object.__new__(AgentSession)
    agent._session_id = "sid-revive"
    agent._lifecycle_bus = bus
    agent._freshness = SessionFreshness()
    agent._freshness.record_revival()

    await agent._emit_revived(kind="pipeline_rebuild")

    assert len(events) == 1
    p = events[0]
    assert p.event is LifecycleEvent.SESSION_REVIVED
    assert p.session_id == "sid-revive"
    assert p.meta["kind"] == "pipeline_rebuild"
    assert p.meta["revive_count"] == 1


@pytest.mark.asyncio
async def test_agent_session_emit_revived_without_bus_is_noop() -> None:
    """No bus attached → helper short-circuits silently."""
    from backend.service.langgraph.agent_session import AgentSession
    from service.langgraph.session_freshness import SessionFreshness

    agent = object.__new__(AgentSession)
    agent._session_id = "sid-no-bus"
    agent._lifecycle_bus = None
    agent._freshness = SessionFreshness()

    await agent._emit_revived(kind="pipeline_rebuild")  # must not raise


@pytest.mark.asyncio
async def test_schedule_revived_emit_runs_in_background() -> None:
    """The sync variant schedules a task that fires on the next loop tick."""
    from backend.service.langgraph.agent_session import AgentSession
    from service.langgraph.session_freshness import SessionFreshness

    bus = SessionLifecycleBus()
    events, handler = _make_recorder()
    bus.subscribe(LifecycleEvent.SESSION_REVIVED, handler)

    agent = object.__new__(AgentSession)
    agent._session_id = "sid-sched"
    agent._lifecycle_bus = bus
    agent._freshness = SessionFreshness()

    # Call the sync method from async context.
    agent._schedule_revived_emit(kind="auto_revive")
    # Yield once so the scheduled task gets to run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(events) == 1
    assert events[0].meta["kind"] == "auto_revive"


def test_schedule_revived_emit_outside_loop_is_noop() -> None:
    """Called with no running loop → skipped silently."""
    from backend.service.langgraph.agent_session import AgentSession
    from service.langgraph.session_freshness import SessionFreshness

    bus = SessionLifecycleBus()
    agent = object.__new__(AgentSession)
    agent._session_id = "sid-no-loop"
    agent._lifecycle_bus = bus
    agent._freshness = SessionFreshness()

    # No running loop — method must not raise.
    agent._schedule_revived_emit(kind="auto_revive")
