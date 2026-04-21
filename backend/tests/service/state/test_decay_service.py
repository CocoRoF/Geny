"""``CreatureStateDecayService`` lifecycle + error isolation (PR-X3-4)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, List

import pytest

from backend.service.state.decay import DecayPolicy, DecayRule
from backend.service.state.decay_service import (
    DEFAULT_DECAY_INTERVAL_SECONDS,
    CreatureStateDecayService,
)
from backend.service.state.provider.in_memory import (
    InMemoryCreatureStateProvider,
)
from backend.service.state.provider.interface import StateConflictError
from backend.service.tick import TickEngine


@pytest.mark.asyncio
async def test_spec_defaults_match_plan() -> None:
    prov = InMemoryCreatureStateProvider()
    svc = CreatureStateDecayService(prov)
    assert svc.spec_name == "state_decay"
    assert not svc.is_running
    assert DEFAULT_DECAY_INTERVAL_SECONDS == 15 * 60


@pytest.mark.asyncio
async def test_start_registers_spec_on_owned_engine() -> None:
    prov = InMemoryCreatureStateProvider()
    svc = CreatureStateDecayService(prov, interval_seconds=1.0, jitter_seconds=0.0)
    await svc.start()
    try:
        assert svc.is_running
        assert "state_decay" in svc._tick_engine.specs()
        assert svc._tick_engine.is_running()
    finally:
        await svc.stop()
    assert not svc.is_running


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_unregisters_spec() -> None:
    prov = InMemoryCreatureStateProvider()
    svc = CreatureStateDecayService(prov, interval_seconds=1.0, jitter_seconds=0.0)
    await svc.start()
    await svc.stop()
    await svc.stop()  # second call is a no-op
    assert "state_decay" not in svc._tick_engine.specs()
    assert not svc._tick_engine.is_running()


@pytest.mark.asyncio
async def test_set_tick_engine_injects_external_and_does_not_start_it() -> None:
    prov = InMemoryCreatureStateProvider()
    external = TickEngine()
    svc = CreatureStateDecayService(prov, interval_seconds=1.0, jitter_seconds=0.0)
    svc.set_tick_engine(external)
    assert svc._tick_engine is external

    await svc.start()
    try:
        # svc didn't own the engine → it stayed NOT running.
        assert not external.is_running()
        assert "state_decay" in external.specs()
    finally:
        await svc.stop()

    # stop() should unregister but not touch the external engine's state.
    assert "state_decay" not in external.specs()
    assert not external.is_running()


@pytest.mark.asyncio
async def test_set_tick_engine_after_start_raises() -> None:
    prov = InMemoryCreatureStateProvider()
    svc = CreatureStateDecayService(prov, interval_seconds=1.0, jitter_seconds=0.0)
    await svc.start()
    try:
        with pytest.raises(RuntimeError):
            svc.set_tick_engine(TickEngine())
    finally:
        await svc.stop()


@pytest.mark.asyncio
async def test_double_start_is_noop() -> None:
    prov = InMemoryCreatureStateProvider()
    svc = CreatureStateDecayService(prov, interval_seconds=1.0, jitter_seconds=0.0)
    await svc.start()
    try:
        await svc.start()  # must not raise "already registered"
    finally:
        await svc.stop()


@pytest.mark.asyncio
async def test_handler_ticks_every_known_character() -> None:
    prov = InMemoryCreatureStateProvider()
    await prov.load("a", owner_user_id="u")
    await prov.load("b", owner_user_id="u")
    # Push last_tick_at back so decay has something to compute.
    past = datetime.now(timezone.utc) - timedelta(hours=4)
    await prov.set_absolute("a", {"last_tick_at": past, "vitals.hunger": 10.0})
    await prov.set_absolute("b", {"last_tick_at": past, "vitals.hunger": 20.0})

    svc = CreatureStateDecayService(
        prov,
        policy=DecayPolicy(rules=(DecayRule("vitals.hunger", +1.0),)),
    )
    # Hand-invoke the handler without starting the engine — the scheduling
    # itself is already covered by TickEngine's own tests.
    await svc._tick_handler()

    a_after = await prov.load("a", owner_user_id="u")
    b_after = await prov.load("b", owner_user_id="u")
    assert a_after.vitals.hunger == pytest.approx(14.0, abs=0.5)
    assert b_after.vitals.hunger == pytest.approx(24.0, abs=0.5)


@pytest.mark.asyncio
async def test_handler_isolates_per_character_failures() -> None:
    """A failing tick on one character must not skip others."""

    class _SelectivelyBrokenProvider(InMemoryCreatureStateProvider):
        async def tick(self, character_id: str, policy: Any) -> Any:  # type: ignore[override]
            if character_id == "bad":
                raise RuntimeError("simulated tick failure")
            return await super().tick(character_id, policy)

    prov = _SelectivelyBrokenProvider()
    await prov.load("good", owner_user_id="u")
    await prov.load("bad", owner_user_id="u")
    await prov.set_absolute("good", {
        "last_tick_at": datetime.now(timezone.utc) - timedelta(hours=2),
        "vitals.hunger": 10.0,
    })

    svc = CreatureStateDecayService(
        prov,
        policy=DecayPolicy(rules=(DecayRule("vitals.hunger", +1.0),)),
    )
    await svc._tick_handler()  # must complete without raising

    good = await prov.load("good", owner_user_id="u")
    assert good.vitals.hunger > 10.0


@pytest.mark.asyncio
async def test_handler_swallows_occ_conflict(caplog: pytest.LogCaptureFixture) -> None:
    """StateConflictError from a racing apply is downgraded to debug."""

    class _AlwaysConflictProvider(InMemoryCreatureStateProvider):
        async def tick(self, character_id: str, policy: Any) -> Any:  # type: ignore[override]
            raise StateConflictError("raced")

    prov = _AlwaysConflictProvider()
    await prov.load("x", owner_user_id="u")
    svc = CreatureStateDecayService(prov)
    await svc._tick_handler()  # must not raise


@pytest.mark.asyncio
async def test_handler_swallows_list_characters_failure() -> None:
    """If enumeration itself fails, the tick is a no-op — don't blow up."""

    class _BrokenList(InMemoryCreatureStateProvider):
        async def list_characters(self) -> List[str]:  # type: ignore[override]
            raise RuntimeError("no list today")

    svc = CreatureStateDecayService(_BrokenList())
    await svc._tick_handler()  # must not raise


@pytest.mark.asyncio
async def test_run_on_start_drives_one_tick_via_engine() -> None:
    """End-to-end: register via start(), let the engine fire once, verify drift."""
    prov = InMemoryCreatureStateProvider()
    await prov.load("c", owner_user_id="u")
    await prov.set_absolute("c", {
        "last_tick_at": datetime.now(timezone.utc) - timedelta(hours=2),
        "vitals.hunger": 20.0,
    })

    # Ultra-tight interval so the engine actually ticks within our wait.
    svc = CreatureStateDecayService(
        prov,
        interval_seconds=0.1,
        jitter_seconds=0.0,
        policy=DecayPolicy(rules=(DecayRule("vitals.hunger", +1.0),)),
    )
    await svc.start()
    try:
        # First tick fires ~0.1s after register; wait a bit longer.
        await asyncio.sleep(0.3)
    finally:
        await svc.stop()

    after = await prov.load("c", owner_user_id="u")
    assert after.vitals.hunger > 20.0
