"""``ManifestSelector`` + :data:`DEFAULT_TREE` — cycle 20260421_10 PR-X4-1.

Pins the contract from ``plan/04 §7``:

- Baseline tree fires ``infant → child → teen → adult`` at the
  documented gates — and *only* at those gates.
- The selector never raises: unknown tree id, unknown life_stage,
  predicate errors, missing character attrs all degrade to "stay on
  current manifest".
- Naming is decoupled — default ``{stage}_{archetype}`` pattern, with
  the archetype-less fallback that strips the suffix.
- First matching edge wins (rules below shadow rules above in a
  custom tree).

These tests use plain dataclasses for the character double since the
:class:`CharacterLike` protocol is structural; the actual DB model
(extended in PR-X4-5) will satisfy the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pytest

from backend.service.progression import (
    DEFAULT_TREE,
    DEFAULT_TREE_ID,
    ManifestSelector,
    Transition,
    default_manifest_naming,
)
from backend.service.state.schema.creature_state import (
    Bond,
    CreatureState,
    Progression,
)


# ── helpers ─────────────────────────────────────────────────────────


@dataclass
class _FakeChar:
    """Minimal :class:`CharacterLike` stand-in for tests."""

    species: str = "catgirl"
    growth_tree_id: str = DEFAULT_TREE_ID
    personality_archetype: str = "cheerful"


def _creature(
    *,
    life_stage: str = "infant",
    manifest_id: str = "base",
    age_days: int = 0,
    milestones: List[str] | None = None,
    familiarity: float = 0.0,
    affection: float = 0.0,
) -> CreatureState:
    return CreatureState(
        character_id="c1",
        owner_user_id="u1",
        bond=Bond(affection=affection, familiarity=familiarity),
        progression=Progression(
            life_stage=life_stage,
            age_days=age_days,
            manifest_id=manifest_id,
            milestones=list(milestones or []),
        ),
    )


def _default_selector() -> ManifestSelector:
    return ManifestSelector({DEFAULT_TREE_ID: DEFAULT_TREE})


# ── default_manifest_naming — pure ──────────────────────────────────


def test_default_naming_joins_stage_and_archetype() -> None:
    char = _FakeChar(personality_archetype="curious")
    assert default_manifest_naming("child", char) == "child_curious"


def test_default_naming_falls_back_to_stage_when_archetype_missing() -> None:
    # Structural — CharacterLike says the field exists, but the value
    # may be empty in legacy rows. The selector must still work.
    char = _FakeChar(personality_archetype="")
    assert default_manifest_naming("infant", char) == "infant"


def test_default_naming_strips_archetype_whitespace() -> None:
    char = _FakeChar(personality_archetype="  introvert  ")
    assert default_manifest_naming("teen", char) == "teen_introvert"


# ── ManifestSelector.select — happy paths ──────────────────────────


@pytest.mark.asyncio
async def test_select_returns_current_manifest_when_no_edge_applies() -> None:
    sel = _default_selector()
    # Fresh infant, no age / bond progress.
    creature = _creature(life_stage="infant", manifest_id="infant_cheerful")
    assert (
        await sel.select(creature, _FakeChar()) == "infant_cheerful"
    )


@pytest.mark.asyncio
async def test_select_fires_infant_to_child_at_documented_gates() -> None:
    sel = _default_selector()
    creature = _creature(
        life_stage="infant",
        manifest_id="infant_cheerful",
        age_days=3,
        familiarity=20.0,
    )
    assert await sel.select(creature, _FakeChar()) == "child_cheerful"


@pytest.mark.asyncio
async def test_select_does_not_fire_below_age_gate() -> None:
    sel = _default_selector()
    # Bond cleared, age not yet.
    creature = _creature(
        life_stage="infant", manifest_id="infant_cheerful",
        age_days=2, familiarity=50.0,
    )
    assert await sel.select(creature, _FakeChar()) == "infant_cheerful"


@pytest.mark.asyncio
async def test_select_does_not_fire_below_bond_gate() -> None:
    sel = _default_selector()
    # Age cleared, bond not yet.
    creature = _creature(
        life_stage="infant", manifest_id="infant_cheerful",
        age_days=30, familiarity=19.9,
    )
    assert await sel.select(creature, _FakeChar()) == "infant_cheerful"


@pytest.mark.asyncio
async def test_select_fires_child_to_teen() -> None:
    sel = _default_selector()
    char = _FakeChar(personality_archetype="curious")
    creature = _creature(
        life_stage="child", manifest_id="child_curious",
        age_days=14, affection=40.0,
    )
    assert await sel.select(creature, char) == "teen_curious"


@pytest.mark.asyncio
async def test_select_fires_teen_to_adult_only_with_milestone() -> None:
    sel = _default_selector()
    char = _FakeChar(personality_archetype="introvert")
    # Timer cleared but milestone absent → no fire.
    no_milestone = _creature(
        life_stage="teen", manifest_id="teen_introvert", age_days=40,
    )
    assert await sel.select(no_milestone, char) == "teen_introvert"

    # With milestone → fires.
    with_milestone = _creature(
        life_stage="teen",
        manifest_id="teen_introvert",
        age_days=40,
        milestones=["first_conflict_resolved"],
    )
    assert await sel.select(with_milestone, char) == "adult_introvert"


@pytest.mark.asyncio
async def test_select_adult_stage_has_no_outgoing_edge() -> None:
    """Plan §7.6: single monotonic progression, no adult→X in default."""
    sel = _default_selector()
    creature = _creature(
        life_stage="adult", manifest_id="adult_artisan", age_days=400,
        affection=100.0, familiarity=100.0,
    )
    assert (
        await sel.select(creature, _FakeChar(personality_archetype="artisan"))
        == "adult_artisan"
    )


# ── ManifestSelector.select — robustness (never raises) ─────────────


@pytest.mark.asyncio
async def test_select_unknown_tree_falls_back_to_default_tree() -> None:
    sel = _default_selector()
    char = _FakeChar(growth_tree_id="never_registered")
    creature = _creature(
        life_stage="infant", manifest_id="base",
        age_days=3, familiarity=30.0,
    )
    # The default tree still applies, so the transition fires.
    assert await sel.select(creature, char) == "child_cheerful"


@pytest.mark.asyncio
async def test_select_with_no_fallback_and_unknown_tree_stays_put() -> None:
    sel = ManifestSelector(
        {DEFAULT_TREE_ID: DEFAULT_TREE}, default_tree_id=None,
    )
    char = _FakeChar(growth_tree_id="never_registered")
    creature = _creature(
        life_stage="infant", manifest_id="stuck_infant",
        age_days=99, familiarity=99.0,
    )
    assert await sel.select(creature, char) == "stuck_infant"


@pytest.mark.asyncio
async def test_select_unknown_life_stage_stays_on_current_manifest() -> None:
    sel = _default_selector()
    creature = _creature(
        life_stage="larva",  # not in the default tree
        manifest_id="larva_weird",
        age_days=999,
        affection=999.0,
    )
    assert await sel.select(creature, _FakeChar()) == "larva_weird"


@pytest.mark.asyncio
async def test_select_predicate_exception_is_swallowed() -> None:
    """A bad tree must not bring down a turn."""

    def boom(_: CreatureState) -> bool:
        raise RuntimeError("predicate blew up")

    bad_tree = (Transition("infant", "child", boom),)
    sel = ManifestSelector({DEFAULT_TREE_ID: bad_tree})
    creature = _creature(
        life_stage="infant", manifest_id="infant_cheerful",
    )
    assert (
        await sel.select(creature, _FakeChar()) == "infant_cheerful"
    )


@pytest.mark.asyncio
async def test_select_naming_exception_is_swallowed() -> None:
    def bad_naming(_: str, __) -> str:
        raise RuntimeError("naming blew up")

    sel = ManifestSelector(
        {DEFAULT_TREE_ID: DEFAULT_TREE}, naming=bad_naming,
    )
    creature = _creature(
        life_stage="infant", manifest_id="infant_cheerful",
        age_days=3, familiarity=30.0,
    )
    # Would have transitioned, but naming failed — caller stays put.
    assert (
        await sel.select(creature, _FakeChar()) == "infant_cheerful"
    )


@pytest.mark.asyncio
async def test_select_handles_missing_character_attrs_gracefully() -> None:
    @dataclass
    class _Partial:
        # No personality_archetype at all.
        species: str = "catgirl"
        growth_tree_id: str = DEFAULT_TREE_ID

    sel = _default_selector()
    creature = _creature(
        life_stage="infant", manifest_id="infant",
        age_days=3, familiarity=30.0,
    )
    # Default naming treats missing archetype as empty → "child".
    assert await sel.select(creature, _Partial()) == "child"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_select_empty_manifest_id_falls_back_to_base() -> None:
    """A half-initialized progression (manifest_id='') shouldn't leak
    empty string to callers — plan/04 §7.6 names ``base`` the floor."""
    sel = _default_selector()
    creature = _creature(life_stage="unknown", manifest_id="")
    assert await sel.select(creature, _FakeChar()) == "base"


# ── Tree semantics ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_matching_edge_wins() -> None:
    """If two edges share a from_stage, the first one declared wins —
    designers put their override earliest."""

    custom = (
        Transition("infant", "child", lambda s: True),  # always
        Transition("infant", "teen", lambda s: True),   # shadowed
    )
    sel = ManifestSelector({DEFAULT_TREE_ID: custom})
    creature = _creature(life_stage="infant", manifest_id="infant_base")
    assert await sel.select(creature, _FakeChar()) == "child_cheerful"


@pytest.mark.asyncio
async def test_trees_are_snapshotted_at_construction() -> None:
    """A designer mutating their tree dict after handing it in should
    not change selector behaviour mid-session."""
    trees: dict = {DEFAULT_TREE_ID: list(DEFAULT_TREE)}
    sel = ManifestSelector(trees)
    # Mutate after construction.
    trees[DEFAULT_TREE_ID].append(
        Transition("adult", "larva", lambda s: True),
    )
    creature = _creature(life_stage="adult", manifest_id="adult_artisan")
    # The frozen snapshot doesn't include the added edge.
    assert (
        await sel.select(creature, _FakeChar(personality_archetype="artisan"))
        == "adult_artisan"
    )


def test_trees_property_returns_read_only_like_view() -> None:
    sel = _default_selector()
    view = sel.trees
    # Mutating the returned dict must not affect the selector's copy.
    view.pop(DEFAULT_TREE_ID, None)  # type: ignore[attr-defined]
    assert DEFAULT_TREE_ID in sel.trees
