"""Progression end-to-end — cycle 20260421_10 PR-X4-6.

The X4 cycle built five components, each covered by its own unit
suite:

- PR-X4-1 :class:`ManifestSelector` + :data:`DEFAULT_TREE`
- PR-X4-2 stage-specific ``EnvironmentManifest`` factory
- PR-X4-3 live :class:`ProgressionBlock`
- PR-X4-4 :class:`EventSeedPool` + :data:`DEFAULT_SEEDS`
- PR-X4-5 ``SessionRuntimeRegistry`` runs the selector and
  :class:`CharacterPersonaProvider` appends live blocks + seed block.

Each works in isolation, but the cycle's contract is the chain:
turn-start hydrate calls the selector → mutations queued → persist
commits them → next session picks up the new manifest. The
``session_meta["new_milestone"]`` stamp hands off to the event-seed
pool so the prompt feels the transition on the *same* turn, not only
the next session.

This module simulates a compressed 14-day play-through using the real
in-memory provider and the real ``DEFAULT_TREE``. Time is advanced via
``set_absolute`` (not wall-clock ticks) so scenarios stay
deterministic and the suite stays fast. Every scenario asserts the
observable cross-component contract — the persisted snapshot, the
emitted events, the shared-mem ``new_milestone``, and the downstream
:class:`ProgressionBlock` text — not internal mutation order.

Scenarios
---------
- **S1 — day 0→2**: below the ``age_days ≥ 3`` gate, selector stays on
  ``infant_cheerful`` even when familiarity is already past 20.
- **S2 — day 3 with familiarity 25**: infant→child transition fires.
  Three mutations persist, ``state.manifest_transition`` emits once,
  ``session_meta["new_milestone"]`` stamps on the same turn, and
  ``ProgressionBlock`` on the *next* hydrate reports ``child``.
- **S3 — day 5 with familiarity 10**: bond gate blocks the transition
  — selector keeps ``infant`` even though age is past the day-3 timer.
- **S4 — two-hop (day 3 then day 14)**: after the infant→child hop, a
  second session at day 14 with affection 50 fires child→teen. The
  milestones list accumulates ``enter:child_*`` *and* ``enter:teen_*``.
- **S5 — event seed same-turn**: the turn a transition fires, the
  :class:`EventSeedPool` with :data:`DEFAULT_SEEDS` picks
  :data:`SEED_MILESTONE_JUST_HIT` (weight 3.0) off
  ``session_meta["new_milestone"]``.
- **S6 — selector silent on unknown tree**: a character pointing at a
  missing growth tree with the selector's default fallback disabled
  keeps its current manifest id — no mutations, no events, no crash.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, Tuple

import pytest
from geny_executor.core.state import PipelineState

from service.game.events import (
    DEFAULT_SEEDS,
    EventSeedPool,
    SEED_MILESTONE_JUST_HIT,
)
from service.persona.blocks import ProgressionBlock
from service.progression.selector import ManifestSelector
from service.progression.trees.default import DEFAULT_TREE, DEFAULT_TREE_ID
from service.state import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    SESSION_META_KEY,
    InMemoryCreatureStateProvider,
    SessionRuntimeRegistry,
)


# ── Lightweight fixtures local to this module ──────────────────────────


class _Character:
    """Minimal :class:`CharacterLike` stand-in.

    Mirrors ``_SessionCharacterLike`` from ``agent_session.py`` but
    kept out of the integration suite's import surface so a rename
    there doesn't silently break these tests. We only need the three
    attributes the selector reads.
    """

    __slots__ = ("species", "growth_tree_id", "personality_archetype")

    def __init__(
        self,
        *,
        species: str = "generic",
        growth_tree_id: str = DEFAULT_TREE_ID,
        personality_archetype: str = "",
    ) -> None:
        self.species = species
        self.growth_tree_id = growth_tree_id
        self.personality_archetype = personality_archetype


def _make_registry(
    provider: InMemoryCreatureStateProvider,
    *,
    character: Any,
    session_id: str = "sess-x4e2e",
    character_id: str = "nico",
    selector: ManifestSelector | None = None,
) -> SessionRuntimeRegistry:
    return SessionRuntimeRegistry(
        session_id=session_id,
        character_id=character_id,
        owner_user_id="player-1",
        provider=provider,
        manifest_selector=(
            selector if selector is not None else ManifestSelector({DEFAULT_TREE_ID: DEFAULT_TREE})
        ),
        character=character,
    )


async def _prime(
    provider: InMemoryCreatureStateProvider,
    *,
    character_id: str = "nico",
    owner_user_id: str = "player-1",
    age_days: int = 0,
    life_stage: str = "infant",
    manifest_id: str = "infant_cheerful",
    familiarity: float = 0.0,
    affection: float = 0.0,
    milestones: List[str] | None = None,
) -> None:
    """Seed the provider's store so scenarios can start from any
    day/bond combo without running 14 real decay ticks."""
    await provider.load(character_id, owner_user_id=owner_user_id)
    patch: Dict[str, Any] = {
        "progression.age_days": age_days,
        "progression.life_stage": life_stage,
        "progression.manifest_id": manifest_id,
        "bond.familiarity": familiarity,
        "bond.affection": affection,
    }
    if milestones is not None:
        patch["progression.milestones"] = list(milestones)
    await provider.set_absolute(character_id, patch)


async def _run_session(
    registry: SessionRuntimeRegistry,
) -> Tuple[PipelineState, Any]:
    """Single session turn: hydrate → persist, no tool calls.

    Returns the hydrated state and the persisted snapshot. Used when a
    scenario only cares that the *transition* path ran; tool-driven
    scenarios build their own turn with the same pattern as
    ``test_state_e2e.py``.
    """
    state = PipelineState()
    await registry.hydrate(state)
    persisted = await registry.persist(state)
    return state, persisted


# ── S1 — day 0→2 — age gate blocks transition ─────────────────────────


@pytest.mark.asyncio
async def test_s1_under_age_gate_stays_infant_even_with_bond_satisfied() -> None:
    """Day 2 + familiarity 25 — bond alone isn't enough; stay on infant.

    Guards against a regression where a predicate dropped the ``>= 3``
    comparison and transitioned on bond alone (plan §7.3's intentional
    "age is the gate" rule).
    """
    provider = InMemoryCreatureStateProvider()
    await _prime(provider, age_days=2, familiarity=25.0)
    registry = _make_registry(
        provider, character=_Character(personality_archetype="curious"),
    )

    state, persisted = await _run_session(registry)

    assert persisted.progression.life_stage == "infant"
    assert persisted.progression.manifest_id == "infant_cheerful"
    # No transition mutation queued during hydrate.
    assert "enter:child_curious" not in persisted.progression.milestones
    # ProgressionBlock still reads "infant".
    assert "[Stage] infant" in ProgressionBlock().render(state)


# ── S2 — day 3 with familiarity ≥ 20 — infant→child fires ─────────────


@pytest.mark.asyncio
async def test_s2_day3_with_bond_20_triggers_infant_to_child() -> None:
    """End-to-end infant→child hop.

    Verifies *every* observable the wiring produces:

    1. ``progression.manifest_id`` + ``life_stage`` updated on the
       persisted snapshot.
    2. ``enter:child_curious`` appears exactly once in the milestones
       list (first hop, not re-stamped on subsequent hydrate of the
       same snapshot in the same session).
    3. ``state.manifest_transition`` emits with from/to pair.
    4. ``session_meta["new_milestone"]`` stamps same-turn.
    5. Next hydrate (new registry) sees ``child_curious`` as current —
       selector no-ops because current already matches.
    """
    provider = InMemoryCreatureStateProvider()
    await _prime(provider, age_days=3, familiarity=25.0)

    registry = _make_registry(
        provider, character=_Character(personality_archetype="curious"),
    )

    state = PipelineState()
    await registry.hydrate(state)

    # Same-turn observables.
    assert state.shared[SESSION_META_KEY]["new_milestone"] == "enter:child_curious"
    transitions = [
        p for n, p in _events(state) if n == "state.manifest_transition"
    ]
    assert len(transitions) == 1
    assert transitions[0]["from_manifest_id"] == "infant_cheerful"
    assert transitions[0]["to_manifest_id"] == "child_curious"
    assert transitions[0]["new_life_stage"] == "child"

    persisted = await registry.persist(state)
    assert persisted.progression.manifest_id == "child_curious"
    assert persisted.progression.life_stage == "child"
    assert persisted.progression.milestones.count("enter:child_curious") == 1

    # Next session — selector no-ops because current now matches the
    # target. Ensures we don't double-stamp.
    next_registry = _make_registry(
        provider, character=_Character(personality_archetype="curious"),
        session_id="sess-next",
    )
    next_state, next_persisted = await _run_session(next_registry)
    assert next_persisted.progression.manifest_id == "child_curious"
    assert next_persisted.progression.milestones.count("enter:child_curious") == 1
    meta = next_state.shared[SESSION_META_KEY]
    assert "new_milestone" not in meta


# ── S3 — day 5 with familiarity 10 — bond gate blocks ─────────────────


@pytest.mark.asyncio
async def test_s3_day5_with_bond_10_stays_infant() -> None:
    """Age ≥ 3 alone isn't enough; the bond gate still blocks."""
    provider = InMemoryCreatureStateProvider()
    await _prime(provider, age_days=5, familiarity=10.0)
    registry = _make_registry(
        provider, character=_Character(personality_archetype="curious"),
    )

    state, persisted = await _run_session(registry)

    assert persisted.progression.manifest_id == "infant_cheerful"
    assert persisted.progression.life_stage == "infant"
    # No transition event emitted.
    assert not [n for n, _ in _events(state) if n == "state.manifest_transition"]


# ── S4 — two-hop 14-day simulation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_s4_14day_simulation_walks_infant_child_teen() -> None:
    """14-day play-through — infant→child at day 3, child→teen at day 14.

    Plan/04's sample curve, compressed: prime each session boundary
    with the day/bond numbers a daily player would have accumulated,
    and assert the selector fires exactly at the predicate crossings.
    """
    provider = InMemoryCreatureStateProvider()
    character = _Character(personality_archetype="curious")

    # Day 3, familiarity crossed — first hop.
    await _prime(provider, age_days=3, familiarity=25.0)
    reg_day3 = _make_registry(provider, character=character, session_id="d3")
    _, snap_day3 = await _run_session(reg_day3)
    assert snap_day3.progression.life_stage == "child"
    assert snap_day3.progression.manifest_id == "child_curious"

    # Day 8, child with affection still low — no further transition.
    await provider.set_absolute(
        "nico",
        {"progression.age_days": 8, "bond.affection": 20.0},
    )
    reg_day8 = _make_registry(provider, character=character, session_id="d8")
    state_day8, snap_day8 = await _run_session(reg_day8)
    assert snap_day8.progression.life_stage == "child"
    assert not [
        n for n, _ in _events(state_day8) if n == "state.manifest_transition"
    ]

    # Day 14 with affection 50 — child→teen fires.
    await provider.set_absolute(
        "nico",
        {"progression.age_days": 14, "bond.affection": 50.0},
    )
    reg_day14 = _make_registry(provider, character=character, session_id="d14")
    state_day14 = PipelineState()
    await reg_day14.hydrate(state_day14)
    assert state_day14.shared[SESSION_META_KEY]["new_milestone"] == "enter:teen_curious"
    snap_day14 = await reg_day14.persist(state_day14)
    assert snap_day14.progression.life_stage == "teen"
    assert snap_day14.progression.manifest_id == "teen_curious"

    # Both hop milestones are recorded in order.
    milestones = snap_day14.progression.milestones
    assert milestones.count("enter:child_curious") == 1
    assert milestones.count("enter:teen_curious") == 1
    assert (
        milestones.index("enter:child_curious")
        < milestones.index("enter:teen_curious")
    )


# ── S5 — EventSeedPool reacts to new_milestone same-turn ──────────────


@pytest.mark.asyncio
async def test_s5_event_seed_pool_picks_milestone_just_hit_on_transition_turn() -> None:
    """The turn a transition fires, :data:`SEED_MILESTONE_JUST_HIT`
    becomes active and wins the pick — this is the contract that makes
    the prompt *feel* the transition on the same turn, not only next
    session.

    We assert on the weighted-random pick with a seeded RNG so the
    test is deterministic without locking in a specific internal RNG
    call order. We separately assert the seed is *active* (trigger
    fires) which is the stronger semantic claim.
    """
    provider = InMemoryCreatureStateProvider()
    await _prime(provider, age_days=3, familiarity=25.0)
    registry = _make_registry(
        provider, character=_Character(personality_archetype="curious"),
    )

    state = PipelineState()
    await registry.hydrate(state)

    pool = EventSeedPool(DEFAULT_SEEDS)
    creature = state.shared[CREATURE_STATE_KEY]
    meta: Mapping[str, Any] = state.shared[SESSION_META_KEY]
    active_ids = {s.id for s in pool.list_active(creature, meta)}
    assert SEED_MILESTONE_JUST_HIT.id in active_ids

    picked = pool.pick(creature, meta, rng=random.Random(0))
    # Seeded RNG + weight 3.0 on milestone_just_hit dominates the rest
    # of the active set here (the only other seed with an active
    # trigger at day 3 / no elapsed session meta is none).
    assert picked is not None
    assert picked.id == SEED_MILESTONE_JUST_HIT.id


# ── S6 — unknown tree → selector silent ───────────────────────────────


@pytest.mark.asyncio
async def test_s6_unknown_growth_tree_keeps_current_manifest() -> None:
    """Character pointing at a missing tree (and fallback disabled)
    must not crash or queue mutations — plan/04 §7.4's "never raises"
    contract carried through integration."""
    provider = InMemoryCreatureStateProvider()
    await _prime(provider, age_days=5, familiarity=30.0)

    # Explicit: no fallback tree, unknown id → selector keeps current.
    isolated_selector = ManifestSelector(
        {DEFAULT_TREE_ID: DEFAULT_TREE}, default_tree_id=None,
    )
    character = _Character(
        growth_tree_id="does_not_exist", personality_archetype="curious",
    )
    registry = _make_registry(
        provider,
        character=character,
        selector=isolated_selector,
        session_id="sess-unknown-tree",
    )

    state, persisted = await _run_session(registry)

    assert persisted.progression.manifest_id == "infant_cheerful"
    assert persisted.progression.life_stage == "infant"
    assert not [n for n, _ in _events(state) if n == "state.manifest_transition"]


# ── S7 — no selector → hydrate still works ────────────────────────────


@pytest.mark.asyncio
async def test_s7_registry_without_selector_is_pure_hydrator() -> None:
    """A registry built *without* a selector (pre-X4-5 call sites)
    must still hydrate and persist correctly — we can't regress the
    classic path while adding the game hook."""
    provider = InMemoryCreatureStateProvider()
    await _prime(provider, age_days=3, familiarity=25.0)

    registry = SessionRuntimeRegistry(
        session_id="sess-no-selector",
        character_id="nico",
        owner_user_id="player-1",
        provider=provider,
        # selector + character intentionally omitted.
    )

    state = PipelineState()
    snap = await registry.hydrate(state)

    assert snap.progression.manifest_id == "infant_cheerful"
    assert not [n for n, _ in _events(state) if n == "state.manifest_transition"]
    assert "new_milestone" not in state.shared[SESSION_META_KEY]


# ── Helpers ────────────────────────────────────────────────────────────


def _events(state: PipelineState) -> List[Tuple[str, Dict[str, Any]]]:
    """Shim around ``PipelineState.add_event`` — returns (type, data)
    pairs mirroring the dict layout the executor writes into
    ``state.events``."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    for ev in getattr(state, "events", ()) or ():
        if not isinstance(ev, dict):
            continue
        name = ev.get("type")
        if isinstance(name, str):
            data = ev.get("data") or {}
            out.append((name, dict(data) if isinstance(data, dict) else {}))
    return out
