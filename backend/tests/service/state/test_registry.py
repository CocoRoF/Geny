"""``SessionRuntimeRegistry`` contract (cycle 20260421_9 PR-X3-3).

Tests use a small ``_StubState`` that matches the pieces of
``PipelineState`` the registry touches: ``.shared`` dict + optional
``.add_event``. This keeps these tests fast and avoids dragging
executor internals into the schema suite.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from backend.service.state.hydrator import hydrate_state, persist_state
from backend.service.state.provider.in_memory import (
    InMemoryCreatureStateProvider,
)
from backend.service.state.provider.interface import StateConflictError
from backend.service.state.registry import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    SESSION_META_KEY,
    SessionRuntimeRegistry,
)
from backend.service.state.schema.creature_state import CreatureState
from backend.service.state.schema.mutation import Mutation, MutationBuffer


class _StubState:
    def __init__(self, *, with_events: bool = True) -> None:
        self.shared: Dict[str, Any] = {}
        self._events: List[Tuple[str, Dict[str, Any]]] = []
        self._with_events = with_events

    def add_event(self, name: str, payload: Dict[str, Any]) -> None:
        if not self._with_events:
            raise RuntimeError("event sink deliberately broken")
        self._events.append((name, payload))

    @property
    def events(self) -> List[Tuple[str, Dict[str, Any]]]:
        return self._events


def _mk_registry(
    provider=None,
    *,
    session_id: str = "sess-1",
    character_id: str = "c1",
    owner_user_id: str = "u1",
) -> Tuple[SessionRuntimeRegistry, InMemoryCreatureStateProvider]:
    prov = provider or InMemoryCreatureStateProvider()
    reg = SessionRuntimeRegistry(
        session_id=session_id,
        character_id=character_id,
        owner_user_id=owner_user_id,
        provider=prov,
    )
    return reg, prov


@pytest.mark.asyncio
async def test_hydrate_installs_keys_on_shared() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    snap = await reg.hydrate(state)

    assert isinstance(snap, CreatureState)
    assert state.shared[CREATURE_STATE_KEY] is snap
    assert isinstance(state.shared[MUTATION_BUFFER_KEY], MutationBuffer)
    assert len(state.shared[MUTATION_BUFFER_KEY]) == 0
    meta = state.shared[SESSION_META_KEY]
    assert meta["session_id"] == "sess-1"
    assert meta["character_id"] == "c1"
    assert meta["owner_user_id"] == "u1"


@pytest.mark.asyncio
async def test_hydrate_emits_hydrated_event() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    await reg.hydrate(state)
    names = [n for n, _ in state.events]
    assert "state.hydrated" in names
    payload = dict(state.events[0][1])
    assert payload["character_id"] == "c1"
    assert payload["session_id"] == "sess-1"
    assert "last_tick_at" in payload


@pytest.mark.asyncio
async def test_hydrate_propagates_snapshot_as_provider_result() -> None:
    reg, prov = _mk_registry()
    direct = await prov.load("c1", owner_user_id="u1")
    state = _StubState()
    snap = await reg.hydrate(state)
    assert snap.character_id == direct.character_id
    assert snap.owner_user_id == direct.owner_user_id


@pytest.mark.asyncio
async def test_persist_without_hydrate_raises_runtime_error() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    with pytest.raises(RuntimeError):
        await reg.persist(state)


@pytest.mark.asyncio
async def test_persist_requires_mutation_buffer_key() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    await reg.hydrate(state)
    # Corrupt the buffer slot.
    state.shared[MUTATION_BUFFER_KEY] = "not-a-buffer"
    with pytest.raises(RuntimeError):
        await reg.persist(state)


@pytest.mark.asyncio
async def test_persist_applies_mutations_from_buffer() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    await reg.hydrate(state)
    buf: MutationBuffer = state.shared[MUTATION_BUFFER_KEY]
    buf.append(op="add", path="vitals.hunger", value=-10.0, source="test")
    buf.append(op="append", path="recent_events", value="fed", source="test")

    new_state = await reg.persist(state)
    assert new_state.vitals.hunger == pytest.approx(40.0)
    assert new_state.recent_events == ["fed"]
    # Shared key replaced with the persisted state.
    assert state.shared[CREATURE_STATE_KEY] is new_state


@pytest.mark.asyncio
async def test_persist_emits_persisted_event_with_mutation_count() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    await reg.hydrate(state)
    buf: MutationBuffer = state.shared[MUTATION_BUFFER_KEY]
    buf.append(op="add", path="vitals.hunger", value=-1.0, source="test")
    buf.append(op="add", path="bond.affection", value=+2.0, source="test")
    await reg.persist(state)

    persisted = [p for n, p in state.events if n == "state.persisted"]
    assert persisted, "expected state.persisted event"
    assert persisted[0]["mutations"] == 2
    assert persisted[0]["character_id"] == "c1"


@pytest.mark.asyncio
async def test_persist_empty_buffer_is_noop_but_still_emits_event() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    snap = await reg.hydrate(state)
    out = await reg.persist(state)
    # In-memory provider's empty-mutation fast path returns the same snapshot
    # instance, so out is identity-equal to snap.
    assert out is snap
    persisted = [p for n, p in state.events if n == "state.persisted"]
    assert persisted and persisted[0]["mutations"] == 0


@pytest.mark.asyncio
async def test_persist_emits_conflict_and_reraises(monkeypatch) -> None:
    reg, prov = _mk_registry()
    state = _StubState()
    await reg.hydrate(state)
    buf: MutationBuffer = state.shared[MUTATION_BUFFER_KEY]
    buf.append(op="add", path="vitals.hunger", value=-1.0, source="t")

    async def boom(*a, **kw):
        raise StateConflictError("simulated")

    monkeypatch.setattr(prov, "apply", boom)
    with pytest.raises(StateConflictError):
        await reg.persist(state)
    conflict = [p for n, p in state.events if n == "state.conflict"]
    assert conflict and conflict[0]["character_id"] == "c1"
    assert conflict[0]["mutations"] == 1


@pytest.mark.asyncio
async def test_hydrate_persist_works_without_add_event() -> None:
    """State objects without ``add_event`` must not break the registry."""

    class _NoEventState:
        def __init__(self) -> None:
            self.shared: Dict[str, Any] = {}

    reg, _ = _mk_registry()
    st: Any = _NoEventState()
    snap = await reg.hydrate(st)
    assert snap is not None
    st.shared[MUTATION_BUFFER_KEY].append(
        op="add", path="vitals.hunger", value=-2.0, source="t",
    )
    new = await reg.persist(st)
    assert new.vitals.hunger == pytest.approx(48.0)


@pytest.mark.asyncio
async def test_event_sink_errors_are_swallowed() -> None:
    """If add_event raises, hydrate/persist still succeed."""
    reg, _ = _mk_registry()
    state = _StubState(with_events=False)
    # hydrate should not raise even though add_event blows up internally.
    snap = await reg.hydrate(state)
    assert isinstance(snap, CreatureState)
    state.shared[MUTATION_BUFFER_KEY].append(
        op="add", path="bond.affection", value=+1.0, source="t",
    )
    out = await reg.persist(state)
    assert out.bond.affection == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_registry_snapshot_tracks_latest_after_persist() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    await reg.hydrate(state)
    state.shared[MUTATION_BUFFER_KEY].append(
        op="add", path="vitals.hunger", value=-5.0, source="t",
    )
    new = await reg.persist(state)
    assert reg.snapshot is new  # updated to persisted state


@pytest.mark.asyncio
async def test_hydrator_free_functions_dispatch_to_registry() -> None:
    reg, _ = _mk_registry()
    state = _StubState()
    snap = await hydrate_state(state, reg)
    assert isinstance(snap, CreatureState)
    state.shared[MUTATION_BUFFER_KEY].append(
        op="add", path="vitals.hunger", value=-3.0, source="t",
    )
    out = await persist_state(state, reg)
    assert out.vitals.hunger == pytest.approx(47.0)


@pytest.mark.asyncio
async def test_state_without_shared_raises_attribute_error() -> None:
    class _Broken:
        pass

    reg, _ = _mk_registry()
    with pytest.raises(AttributeError):
        await reg.hydrate(_Broken())  # type: ignore[arg-type]


# ── Manifest selector integration (PR-X4-5) ───────────────────────────────


class _CharStub:
    """Minimal :class:`CharacterLike` for the selector."""

    def __init__(
        self,
        *,
        species: str = "generic",
        growth_tree_id: str = "default",
        personality_archetype: str = "",
    ) -> None:
        self.species = species
        self.growth_tree_id = growth_tree_id
        self.personality_archetype = personality_archetype


class _StubSelector:
    """Async ``select`` returning a preset id. Optionally raises."""

    def __init__(self, new_id: str, *, raises: Exception | None = None) -> None:
        self._new_id = new_id
        self._raises = raises

    async def select(self, creature, character) -> str:
        if self._raises is not None:
            raise self._raises
        return self._new_id


async def _prime_snapshot(
    prov: InMemoryCreatureStateProvider,
    *,
    character_id: str = "c1",
    owner_user_id: str = "u1",
    manifest_id: str = "infant_cheerful",
    life_stage: str = "infant",
    age_days: int = 3,
    familiarity: float = 25.0,
) -> None:
    """Load the base snapshot and apply enough mutations to satisfy the
    infant→child predicate (age≥3 and familiarity≥20)."""
    from backend.service.state.schema.mutation import MutationBuffer as _MB

    base = await prov.load(character_id, owner_user_id=owner_user_id)
    buf = _MB()
    buf.append(op="set", path="progression.manifest_id", value=manifest_id, source="fixture")
    buf.append(op="set", path="progression.life_stage", value=life_stage, source="fixture")
    buf.append(op="set", path="progression.age_days", value=age_days, source="fixture")
    buf.append(op="set", path="bond.familiarity", value=familiarity, source="fixture")
    await prov.apply(base, buf.items)


@pytest.mark.asyncio
async def test_no_selector_keeps_manifest_id_unchanged() -> None:
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    reg, _ = _mk_registry(provider=prov)
    state = _StubState()

    snap = await reg.hydrate(state)
    assert snap.progression.manifest_id == "infant_cheerful"
    # No mutations were appended — buffer is empty.
    assert len(state.shared[MUTATION_BUFFER_KEY]) == 0


@pytest.mark.asyncio
async def test_selector_transition_appends_three_mutations() -> None:
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    selector = _StubSelector("child_curious")
    reg = SessionRuntimeRegistry(
        session_id="s1",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        manifest_selector=selector,
        character=_CharStub(personality_archetype="curious"),
    )
    state = _StubState()
    await reg.hydrate(state)

    buf: MutationBuffer = state.shared[MUTATION_BUFFER_KEY]
    assert len(buf) == 3
    ops = [(m.op, m.path, m.value, m.source) for m in buf.items]
    assert ops[0] == ("set", "progression.manifest_id", "child_curious", "selector:transition")
    assert ops[1] == ("set", "progression.life_stage", "child", "selector:transition")
    assert ops[2] == ("append", "progression.milestones", "enter:child_curious", "selector:transition")


@pytest.mark.asyncio
async def test_selector_transition_stamps_new_milestone_on_session_meta() -> None:
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    reg = SessionRuntimeRegistry(
        session_id="s1",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        manifest_selector=_StubSelector("child_curious"),
        character=_CharStub(personality_archetype="curious"),
    )
    state = _StubState()
    await reg.hydrate(state)

    meta = state.shared[SESSION_META_KEY]
    assert meta["new_milestone"] == "enter:child_curious"


@pytest.mark.asyncio
async def test_selector_transition_emits_manifest_transition_event() -> None:
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    reg = SessionRuntimeRegistry(
        session_id="s1",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        manifest_selector=_StubSelector("teen_introvert"),
        character=_CharStub(personality_archetype="introvert"),
    )
    state = _StubState()
    await reg.hydrate(state)

    transitions = [p for n, p in state.events if n == "state.manifest_transition"]
    assert len(transitions) == 1
    t = transitions[0]
    assert t["from_manifest_id"] == "infant_cheerful"
    assert t["to_manifest_id"] == "teen_introvert"
    assert t["new_life_stage"] == "teen"


@pytest.mark.asyncio
async def test_selector_same_id_is_noop() -> None:
    """Selector returning the current id must not queue mutations."""
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    reg = SessionRuntimeRegistry(
        session_id="s1",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        manifest_selector=_StubSelector("infant_cheerful"),
        character=_CharStub(personality_archetype="cheerful"),
    )
    state = _StubState()
    await reg.hydrate(state)

    assert len(state.shared[MUTATION_BUFFER_KEY]) == 0
    meta = state.shared[SESSION_META_KEY]
    assert "new_milestone" not in meta
    assert not [n for n, _ in state.events if n == "state.manifest_transition"]


@pytest.mark.asyncio
async def test_selector_exception_leaves_state_alone() -> None:
    """A selector that raises must not crash hydrate or queue mutations."""
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    reg = SessionRuntimeRegistry(
        session_id="s1",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        manifest_selector=_StubSelector("ignored", raises=RuntimeError("boom")),
        character=_CharStub(),
    )
    state = _StubState()
    snap = await reg.hydrate(state)

    assert snap.progression.manifest_id == "infant_cheerful"
    assert len(state.shared[MUTATION_BUFFER_KEY]) == 0


@pytest.mark.asyncio
async def test_selector_unknown_stage_skips_life_stage_mutation() -> None:
    """An id the parser can't map to a known stage updates manifest_id +
    milestones but leaves life_stage alone — avoids writing a bogus
    stage keyword like ``"legacy"``."""
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    reg = SessionRuntimeRegistry(
        session_id="s1",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        manifest_selector=_StubSelector("legacy_custom"),
        character=_CharStub(),
    )
    state = _StubState()
    await reg.hydrate(state)

    buf: MutationBuffer = state.shared[MUTATION_BUFFER_KEY]
    paths = [m.path for m in buf.items]
    assert "progression.manifest_id" in paths
    assert "progression.life_stage" not in paths
    assert "progression.milestones" in paths


@pytest.mark.asyncio
async def test_selector_requires_both_selector_and_character() -> None:
    """Missing character → selector isn't consulted (and doesn't raise)."""
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    reg = SessionRuntimeRegistry(
        session_id="s1",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        manifest_selector=_StubSelector("child_curious"),
        character=None,
    )
    state = _StubState()
    await reg.hydrate(state)

    assert len(state.shared[MUTATION_BUFFER_KEY]) == 0


@pytest.mark.asyncio
async def test_selector_empty_new_id_is_noop() -> None:
    """Selector returning ``""`` is a "no opinion" — don't queue
    mutations."""
    prov = InMemoryCreatureStateProvider()
    await _prime_snapshot(prov, manifest_id="infant_cheerful")
    reg = SessionRuntimeRegistry(
        session_id="s1",
        character_id="c1",
        owner_user_id="u1",
        provider=prov,
        manifest_selector=_StubSelector(""),
        character=_CharStub(),
    )
    state = _StubState()
    await reg.hydrate(state)
    assert len(state.shared[MUTATION_BUFFER_KEY]) == 0


# ── PR-X5F-3: session_runtime attribute exposure ────────────────────


@pytest.mark.asyncio
async def test_hydrate_exposes_registry_on_session_runtime_attr() -> None:
    """``state.session_runtime`` holds the registry after hydrate.

    Pins the typed-attribute path introduced by geny-executor 0.30.0's
    ``PipelineState.session_runtime`` slot. Stages / plugins can reach
    the registry (and its ``snapshot`` / ``session_id`` /
    ``character_id`` attrs) without going through ``state.shared``.
    """
    reg, _ = _mk_registry()
    state = _StubState()
    await reg.hydrate(state)
    assert state.session_runtime is reg
    # Typed attrs reachable via the new surface
    assert state.session_runtime.session_id == "sess-1"
    assert state.session_runtime.character_id == "c1"
    assert state.session_runtime.snapshot is state.shared[CREATURE_STATE_KEY]


@pytest.mark.asyncio
async def test_hydrate_shared_dict_still_authoritative() -> None:
    """Adding the session_runtime attribute must not remove or alter
    any existing ``state.shared`` key — shared-dict consumers remain
    byte-identical."""
    reg, _ = _mk_registry()
    state = _StubState()
    snap = await reg.hydrate(state)
    # Every existing key remains exactly as before
    assert state.shared[CREATURE_STATE_KEY] is snap
    assert isinstance(state.shared[MUTATION_BUFFER_KEY], MutationBuffer)
    assert state.shared[SESSION_META_KEY]["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_hydrate_tolerates_state_that_rejects_attribute_writes() -> None:
    """A state stub using ``__slots__`` without ``session_runtime`` must
    not crash hydrate — the shared-dict path stays authoritative."""

    class _SlottedState:
        __slots__ = ("shared",)

        def __init__(self) -> None:
            self.shared: Dict[str, Any] = {}

    reg, _ = _mk_registry()
    st: Any = _SlottedState()
    snap = await reg.hydrate(st)
    assert snap is not None
    assert st.shared[CREATURE_STATE_KEY] is snap
    # No session_runtime attribute (and no raise); shared-dict path intact
    assert not hasattr(st, "session_runtime")
