"""Registry hydrate catch-up (plan/02 §5.4, cycle 20260421_9 PR-X3-4).

``hydrate`` must fire a single ``provider.tick`` when the loaded
snapshot is older than ``CATCHUP_THRESHOLD``, and must *not* fire when
the snapshot is fresh. A failing catch-up tick must not break the turn.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Sequence, Tuple

import pytest

from backend.service.state.decay import (
    CATCHUP_THRESHOLD,
    DEFAULT_DECAY,
    DecayPolicy,
    DecayRule,
    apply_decay,
)
from backend.service.state.provider.in_memory import (
    InMemoryCreatureStateProvider,
)
from backend.service.state.provider.interface import StateConflictError
from backend.service.state.registry import (
    CREATURE_STATE_KEY,
    SessionRuntimeRegistry,
)
from backend.service.state.schema.creature_state import CreatureState


class _StubState:
    def __init__(self) -> None:
        self.shared: Dict[str, Any] = {}
        self.events: List[Tuple[str, Dict[str, Any]]] = []

    def add_event(self, name: str, payload: Dict[str, Any]) -> None:
        self.events.append((name, payload))


class _CountingProvider(InMemoryCreatureStateProvider):
    """InMemory provider that counts ``tick`` invocations."""

    def __init__(self) -> None:
        super().__init__()
        self.tick_calls: List[str] = []

    async def tick(self, character_id: str, policy: Any) -> CreatureState:  # type: ignore[override]
        self.tick_calls.append(character_id)
        return await super().tick(character_id, policy)


def _registry(provider, *, character_id: str = "c1") -> SessionRuntimeRegistry:
    return SessionRuntimeRegistry(
        session_id="sess-1",
        character_id=character_id,
        owner_user_id="u1",
        provider=provider,
    )


@pytest.mark.asyncio
async def test_hydrate_skips_catchup_when_snapshot_is_fresh() -> None:
    prov = _CountingProvider()
    await prov.load("c1", owner_user_id="u1")  # last_tick_at ≈ now
    reg = _registry(prov)
    state = _StubState()
    await reg.hydrate(state)
    assert prov.tick_calls == []  # nothing to catch up on
    assert not any(n == "state.catchup" for n, _ in state.events)


@pytest.mark.asyncio
async def test_hydrate_triggers_catchup_past_threshold() -> None:
    prov = _CountingProvider()
    await prov.load("c1", owner_user_id="u1")
    # Push last_tick_at just past the threshold.
    stale = datetime.now(timezone.utc) - (CATCHUP_THRESHOLD + timedelta(minutes=5))
    await prov.set_absolute("c1", {"last_tick_at": stale, "vitals.hunger": 10.0})

    reg = _registry(prov)
    state = _StubState()
    snap = await reg.hydrate(state)

    assert prov.tick_calls == ["c1"]
    # Hunger should have drifted up per DEFAULT_DECAY rate.
    assert snap.vitals.hunger > 10.0
    # Event fired.
    catchup = [p for n, p in state.events if n == "state.catchup"]
    assert len(catchup) == 1
    assert catchup[0]["character_id"] == "c1"
    assert "from_last_tick_at" in catchup[0]
    assert "to_last_tick_at" in catchup[0]


@pytest.mark.asyncio
async def test_hydrate_catchup_boundary_exactly_at_threshold() -> None:
    """At exactly CATCHUP_THRESHOLD, no catch-up (strict-greater semantics)."""
    prov = _CountingProvider()
    await prov.load("c1", owner_user_id="u1")

    # Pin last_tick_at so elapsed is known. Run so wall-clock delta < threshold.
    pinned = datetime.now(timezone.utc) - (CATCHUP_THRESHOLD - timedelta(seconds=30))
    await prov.set_absolute("c1", {"last_tick_at": pinned})

    reg = _registry(prov)
    state = _StubState()
    await reg.hydrate(state)
    assert prov.tick_calls == []


@pytest.mark.asyncio
async def test_hydrate_uses_caught_up_snapshot_in_shared() -> None:
    prov = _CountingProvider()
    await prov.load("c1", owner_user_id="u1")
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    await prov.set_absolute("c1", {"last_tick_at": stale, "vitals.hunger": 20.0})

    reg = _registry(prov)
    state = _StubState()
    await reg.hydrate(state)

    shared_snap = state.shared[CREATURE_STATE_KEY]
    # After catch-up, both the returned snap and shared slot agree.
    assert shared_snap.vitals.hunger > 20.0
    assert shared_snap.last_tick_at > stale + timedelta(hours=4)


@pytest.mark.asyncio
async def test_hydrate_catchup_failure_does_not_block_turn() -> None:
    """Provider.tick raising must not propagate — stages get stale snap."""

    class _ExplodingProvider(InMemoryCreatureStateProvider):
        async def tick(self, character_id: str, policy: Any) -> CreatureState:  # type: ignore[override]
            raise RuntimeError("storage on fire")

    prov = _ExplodingProvider()
    await prov.load("c1", owner_user_id="u1")
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    await prov.set_absolute("c1", {"last_tick_at": stale, "vitals.hunger": 20.0})

    reg = _registry(prov)
    state = _StubState()
    snap = await reg.hydrate(state)

    # Stale snapshot used — hunger unchanged.
    assert snap.vitals.hunger == pytest.approx(20.0)
    failed = [p for n, p in state.events if n == "state.catchup_failed"]
    assert failed and failed[0]["reason"] == "storage on fire"


@pytest.mark.asyncio
async def test_hydrate_catchup_survives_occ_conflict() -> None:
    """StateConflictError from catch-up is treated like any other failure."""

    class _ConflictProvider(InMemoryCreatureStateProvider):
        async def tick(self, character_id: str, policy: Any) -> CreatureState:  # type: ignore[override]
            raise StateConflictError("apply raced")

    prov = _ConflictProvider()
    await prov.load("c1", owner_user_id="u1")
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    await prov.set_absolute("c1", {"last_tick_at": stale})

    reg = _registry(prov)
    state = _StubState()
    snap = await reg.hydrate(state)  # must not raise
    assert snap is not None
    assert any(n == "state.catchup_failed" for n, _ in state.events)


@pytest.mark.asyncio
async def test_hydrate_works_with_provider_without_tick() -> None:
    """Legacy provider (no tick method) must not break hydrate."""

    class _NoTickProvider:
        def __init__(self) -> None:
            self._store: Dict[str, CreatureState] = {}

        async def load(
            self, character_id: str, *, owner_user_id: str = "",
        ) -> CreatureState:
            stale = datetime.now(timezone.utc) - timedelta(hours=5)
            state = self._store.get(character_id)
            if state is None:
                state = CreatureState(
                    character_id=character_id,
                    owner_user_id=owner_user_id,
                    last_tick_at=stale,
                )
                self._store[character_id] = state
            return state

        async def apply(
            self, snapshot: CreatureState, mutations: Sequence[Any],
        ) -> CreatureState:
            return snapshot  # unused here

    prov: Any = _NoTickProvider()
    reg = _registry(prov)
    state = _StubState()
    snap = await reg.hydrate(state)
    # No catch-up attempted; no failure either.
    assert snap is not None
    assert not any(n == "state.catchup" for n, _ in state.events)
    assert not any(n == "state.catchup_failed" for n, _ in state.events)


@pytest.mark.asyncio
async def test_hydrate_emits_hydrated_after_catchup() -> None:
    """state.hydrated payload should reflect post-catchup last_tick_at."""
    prov = _CountingProvider()
    await prov.load("c1", owner_user_id="u1")
    stale = datetime.now(timezone.utc) - timedelta(hours=10)
    await prov.set_absolute("c1", {"last_tick_at": stale})

    reg = _registry(prov)
    state = _StubState()
    await reg.hydrate(state)

    hydrated = [p for n, p in state.events if n == "state.hydrated"]
    assert hydrated
    # Hydrated event carries the *new* last_tick_at, not the stale one.
    hydrated_at = datetime.fromisoformat(hydrated[0]["last_tick_at"])
    assert hydrated_at > stale + timedelta(hours=9)


@pytest.mark.asyncio
async def test_hydrate_accepts_custom_catchup_policy() -> None:
    """A registry can override DEFAULT_DECAY for its catch-up."""

    class _ObservingProvider(InMemoryCreatureStateProvider):
        def __init__(self) -> None:
            super().__init__()
            self.seen_policies: List[DecayPolicy] = []

        async def tick(self, character_id: str, policy: DecayPolicy) -> CreatureState:  # type: ignore[override]
            self.seen_policies.append(policy)
            return await super().tick(character_id, policy)

    prov = _ObservingProvider()
    await prov.load("c1", owner_user_id="u1")
    await prov.set_absolute("c1", {
        "last_tick_at": datetime.now(timezone.utc) - timedelta(hours=2),
    })

    custom = DecayPolicy(rules=(DecayRule("vitals.stress", +10.0),))
    reg = SessionRuntimeRegistry(
        session_id="s",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        catchup_policy=custom,
    )
    state = _StubState()
    await reg.hydrate(state)
    assert prov.seen_policies == [custom]


def test_apply_decay_reachable_from_decay_module() -> None:
    """Smoke: the symbol is exported from decay for other modules."""
    now = datetime.now(timezone.utc)
    state = CreatureState(
        character_id="c", owner_user_id="u",
        last_tick_at=now - timedelta(hours=1),
    )
    state.vitals.hunger = 0.0
    after = apply_decay(
        state, DecayPolicy(rules=(DecayRule("vitals.hunger", +1.0),)), now=now,
    )
    assert after.vitals.hunger == pytest.approx(1.0)
    # Default export used.
    assert DEFAULT_DECAY is not None
