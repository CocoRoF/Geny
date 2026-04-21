"""AgentSessionManager idle monitor on TickEngine (cycle 20260421_8 PR-X2-5).

Pins the contract after migrating ``_idle_monitor_loop`` onto the
shared TickEngine:

1. ``start_idle_monitor`` registers an ``idle_monitor`` spec.
2. ``stop_idle_monitor`` unregisters and stops the owned engine.
3. Owned vs injected engine: owner controls start/stop.
4. ``_scan_for_idle_sessions`` still flips RUNNING → IDLE and emits
   SESSION_IDLE on the bus (no functional regression from PR-X2-2).
"""

from __future__ import annotations

import pytest

from backend.service.lifecycle import (
    LifecycleEvent,
    LifecyclePayload,
    SessionLifecycleBus,
)
from backend.service.langgraph.agent_session_manager import AgentSessionManager
from backend.service.tick import TickEngine


def _make_manager_skeleton() -> AgentSessionManager:
    """Build a manager skeleton bypassing heavy __init__.

    The spec registration / scan paths only need:
    - ``_idle_tick_engine`` / ``_owns_idle_tick_engine`` / interval / jitter
    - ``_idle_monitor_running``
    - ``_local_agents`` (for scan)
    - ``_store`` (register() called on mark_idle)
    - ``_lifecycle_bus`` (emit called on mark_idle)
    """
    mgr = object.__new__(AgentSessionManager)
    mgr._idle_tick_engine = TickEngine()
    mgr._owns_idle_tick_engine = True
    mgr._idle_monitor_interval = 60.0
    mgr._idle_monitor_jitter = 3.0
    mgr._idle_monitor_running = False
    mgr._local_agents = {}
    mgr._store = _FakeStore()
    mgr._lifecycle_bus = SessionLifecycleBus()
    return mgr


class _FakeStore:
    def __init__(self) -> None:
        self.registered: list[tuple[str, dict]] = []

    def register(self, session_id: str, info: dict) -> None:
        self.registered.append((session_id, info))


class _FakeInfo:
    def __init__(self, data: dict) -> None:
        self._data = data

    def model_dump(self, *, mode: str = "python") -> dict:
        return self._data


class _FakeAgent:
    def __init__(
        self, *, status_running: bool = True, will_flip: bool = True
    ) -> None:
        self.status = _FakeStatus(running=status_running)
        self._flip = will_flip
        self._flipped = False

    def mark_idle(self) -> bool:
        if self._flip:
            self.status = _FakeStatus(running=False)
            self._flipped = True
            return True
        return False

    def get_session_info(self) -> _FakeInfo:
        return _FakeInfo({"status": "IDLE"})


class _FakeStatus:
    def __init__(self, *, running: bool) -> None:
        self._running = running

    def __eq__(self, other: object) -> bool:
        # Tests only compare `agent.status == SessionStatus.RUNNING`.
        from backend.service.langgraph.agent_session_manager import (
            SessionStatus,
        )
        return isinstance(other, SessionStatus) and bool(self._running) == (
            other is SessionStatus.RUNNING
        )


# -- lifecycle wiring -------------------------------------------------------


@pytest.mark.asyncio
async def test_start_registers_tick_spec() -> None:
    mgr = _make_manager_skeleton()
    await mgr.start_idle_monitor()
    try:
        specs = mgr._idle_tick_engine.specs()
        assert "idle_monitor" in specs
        spec = specs["idle_monitor"]
        assert spec.interval == 60.0
        assert spec.jitter == 3.0
        assert spec.handler == mgr._scan_for_idle_sessions
        assert mgr._idle_tick_engine.is_running()
    finally:
        await mgr.stop_idle_monitor()


@pytest.mark.asyncio
async def test_stop_unregisters_spec_and_stops_owned_engine() -> None:
    mgr = _make_manager_skeleton()
    await mgr.start_idle_monitor()
    await mgr.stop_idle_monitor()
    assert "idle_monitor" not in mgr._idle_tick_engine.specs()
    assert not mgr._idle_tick_engine.is_running()
    assert not mgr._idle_monitor_running


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    mgr = _make_manager_skeleton()
    await mgr.start_idle_monitor()
    await mgr.start_idle_monitor()  # no duplicate spec, no raise
    assert len(mgr._idle_tick_engine.specs()) == 1
    await mgr.stop_idle_monitor()


@pytest.mark.asyncio
async def test_stop_without_start_is_noop() -> None:
    mgr = _make_manager_skeleton()
    await mgr.stop_idle_monitor()


@pytest.mark.asyncio
async def test_injected_engine_is_not_started_by_manager() -> None:
    mgr = _make_manager_skeleton()
    shared = TickEngine()
    mgr.set_tick_engine(shared)
    await mgr.start_idle_monitor()
    try:
        assert "idle_monitor" in shared.specs()
        assert not shared.is_running(), (
            "injected engine must be started by its owner"
        )
    finally:
        await mgr.stop_idle_monitor()
        assert "idle_monitor" not in shared.specs()


def test_set_tick_engine_after_start_raises() -> None:
    mgr = _make_manager_skeleton()
    mgr._idle_monitor_running = True  # simulate started
    with pytest.raises(RuntimeError, match="before start_idle_monitor"):
        mgr.set_tick_engine(TickEngine())


# -- scan behaviour ---------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_flips_running_agents_and_emits_bus() -> None:
    mgr = _make_manager_skeleton()
    mgr._local_agents = {
        "sid-1": _FakeAgent(status_running=True, will_flip=True),
        "sid-2": _FakeAgent(status_running=True, will_flip=True),
    }
    seen: list[LifecyclePayload] = []

    async def _handler(payload: LifecyclePayload) -> None:
        seen.append(payload)

    mgr._lifecycle_bus.subscribe(LifecycleEvent.SESSION_IDLE, _handler)

    await mgr._scan_for_idle_sessions()

    assert {p.session_id for p in seen} == {"sid-1", "sid-2"}
    assert all(p.meta["reason"] == "timeout" for p in seen)
    # Both transitions persisted to the store.
    assert len(mgr._store.registered) == 2


@pytest.mark.asyncio
async def test_scan_skips_non_running_agents() -> None:
    mgr = _make_manager_skeleton()
    mgr._local_agents = {
        "sid-stopped": _FakeAgent(status_running=False, will_flip=True),
    }
    seen: list[LifecyclePayload] = []

    async def _handler(payload: LifecyclePayload) -> None:
        seen.append(payload)

    mgr._lifecycle_bus.subscribe(LifecycleEvent.SESSION_IDLE, _handler)
    await mgr._scan_for_idle_sessions()
    assert seen == []


@pytest.mark.asyncio
async def test_scan_handles_mark_idle_returning_false() -> None:
    mgr = _make_manager_skeleton()
    mgr._local_agents = {
        "sid-running-but-vtuber": _FakeAgent(
            status_running=True, will_flip=False
        ),
    }
    seen: list[LifecyclePayload] = []

    async def _handler(payload: LifecyclePayload) -> None:
        seen.append(payload)

    mgr._lifecycle_bus.subscribe(LifecycleEvent.SESSION_IDLE, _handler)
    await mgr._scan_for_idle_sessions()
    # mark_idle returned False → no emit, no store write.
    assert seen == []
    assert mgr._store.registered == []
