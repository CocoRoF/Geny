"""ThinkingTriggerService on TickEngine (cycle 20260421_8 PR-X2-4).

Pins the contract after migrating the service's old ``_loop`` into a
TickEngine spec:

1. ``start()`` registers a ``thinking_trigger`` spec on the engine.
2. ``scan_all`` respects per-session adaptive backoff (handler-internal
   skip — spec cadence stays fixed at 30s).
3. ``stop()`` unregisters the spec and clears state.
4. An externally-injected ``TickEngine`` is honoured (shared-engine path
   for PR-X2-5/X2-6) and not started/stopped by the service.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from service.tick import TickEngine
from service.vtuber.thinking_trigger import ThinkingTriggerService


@pytest.mark.asyncio
async def test_start_registers_tick_spec() -> None:
    engine = TickEngine()
    svc = ThinkingTriggerService(engine=engine)
    await svc.start()
    try:
        specs = engine.specs()
        assert "thinking_trigger" in specs
        spec = specs["thinking_trigger"]
        assert spec.interval == 30.0
        assert spec.jitter == 2.0
        assert spec.handler == svc.scan_all
    finally:
        await svc.stop()


@pytest.mark.asyncio
async def test_stop_unregisters_spec_and_clears_state() -> None:
    engine = TickEngine()
    svc = ThinkingTriggerService(engine=engine)
    await svc.start()
    svc.record_activity("sid-A")
    svc.disable("sid-B")
    assert svc._activity
    assert svc._disabled_sessions

    await svc.stop()
    assert "thinking_trigger" not in engine.specs()
    assert svc._activity == {}
    assert svc._disabled_sessions == set()
    assert svc._consecutive_triggers == {}


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    engine = TickEngine()
    svc = ThinkingTriggerService(engine=engine)
    await svc.start()
    await svc.start()  # second start must be a no-op, no duplicate registration
    assert len(engine.specs()) == 1
    await svc.stop()


@pytest.mark.asyncio
async def test_stop_without_start_is_noop() -> None:
    svc = ThinkingTriggerService()
    await svc.stop()  # must not raise


@pytest.mark.asyncio
async def test_injected_engine_is_not_auto_started_by_service() -> None:
    engine = TickEngine()
    svc = ThinkingTriggerService(engine=engine)
    await svc.start()
    assert not engine.is_running(), (
        "injected engine must be started by its owner, not the service"
    )
    await svc.stop()


@pytest.mark.asyncio
async def test_owned_engine_is_started_and_stopped() -> None:
    svc = ThinkingTriggerService()
    await svc.start()
    assert svc._engine.is_running()
    await svc.stop()
    assert not svc._engine.is_running()


@pytest.mark.asyncio
async def test_scan_all_skips_sessions_within_threshold() -> None:
    import time

    svc = ThinkingTriggerService(idle_threshold=120.0)
    svc._fire_trigger = AsyncMock()  # type: ignore[assignment]
    # Just-now activity → below threshold → must not fire.
    svc._activity["sid-fresh"] = time.time()
    await svc.scan_all()
    svc._fire_trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_all_fires_for_sessions_over_threshold() -> None:
    import time

    svc = ThinkingTriggerService(idle_threshold=10.0)
    fire = AsyncMock()
    svc._fire_trigger = fire  # type: ignore[assignment]
    # Activity 60s ago → over threshold (10s) → must fire.
    svc._activity["sid-idle"] = time.time() - 60
    await svc.scan_all()
    fire.assert_awaited_once_with("sid-idle")


@pytest.mark.asyncio
async def test_scan_all_skips_disabled_sessions() -> None:
    import time

    svc = ThinkingTriggerService(idle_threshold=10.0)
    fire = AsyncMock()
    svc._fire_trigger = fire  # type: ignore[assignment]
    svc._activity["sid-off"] = time.time() - 60
    svc.disable("sid-off")
    await svc.scan_all()
    fire.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_all_respects_adaptive_backoff() -> None:
    """Once consecutive_triggers climbs, threshold grows — the same
    idle duration that fires at count=0 should skip at count=20.
    """
    import time

    svc = ThinkingTriggerService(
        idle_threshold=120.0, max_idle_threshold=3600.0
    )
    fire = AsyncMock()
    svc._fire_trigger = fire  # type: ignore[assignment]

    svc._activity["sid"] = time.time() - 500.0  # 500s idle
    svc._consecutive_triggers["sid"] = 20  # max-scale threshold

    # At count=20 the adaptive threshold is at/near the 3600s ceiling,
    # so 500s idle must NOT fire.
    await svc.scan_all()
    fire.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_all_resets_activity_after_fire() -> None:
    """After firing, the session's last-activity must be bumped to ``now``
    so the next tick doesn't immediately re-fire.
    """
    import time

    svc = ThinkingTriggerService(idle_threshold=10.0)
    svc._fire_trigger = AsyncMock()  # type: ignore[assignment]
    before = time.time() - 60
    svc._activity["sid"] = before

    await svc.scan_all()

    assert svc._activity["sid"] > before
