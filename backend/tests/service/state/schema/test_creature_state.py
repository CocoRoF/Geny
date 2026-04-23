"""CreatureState schema contract (cycle 20260421_9 PR-X3-1).

Covers dataclass defaults, independence of default containers across
instances, timestamps, and ``SCHEMA_VERSION`` constant.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime, timezone

from service.state.schema.creature_state import (
    CHARACTER_ROLE_OTHER,
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
    KNOWN_CHARACTER_ROLES,
    SCHEMA_VERSION,
    Bond,
    CreatureState,
    Progression,
    Vitals,
)
from service.state.schema.mood import MoodVector


def test_schema_version_is_two() -> None:
    # Bumped from 1 → 2 in Plan/Phase04 (character_role addition).
    assert SCHEMA_VERSION == 2


def test_vitals_defaults() -> None:
    v = Vitals()
    assert v.hunger == 50.0
    assert v.energy == 80.0
    assert v.stress == 20.0
    assert v.cleanliness == 80.0


def test_bond_defaults_all_zero() -> None:
    b = Bond()
    assert b.affection == 0.0
    assert b.trust == 0.0
    assert b.familiarity == 0.0
    assert b.dependency == 0.0


def test_progression_defaults() -> None:
    p = Progression()
    assert p.age_days == 0
    assert p.life_stage == "infant"
    assert p.xp == 0
    assert p.milestones == []
    assert p.manifest_id == "base"


def test_creature_state_requires_identity() -> None:
    # dataclass enforces character_id / owner_user_id presence via
    # positional args — constructing without them should raise.
    try:
        CreatureState()  # type: ignore[call-arg]
    except TypeError:
        return
    raise AssertionError("CreatureState should require identity fields")


def test_creature_state_minimal_construction() -> None:
    s = CreatureState(character_id="c1", owner_user_id="u1")
    assert s.character_id == "c1"
    assert s.owner_user_id == "u1"
    assert isinstance(s.vitals, Vitals)
    assert isinstance(s.bond, Bond)
    assert isinstance(s.mood, MoodVector)
    assert isinstance(s.progression, Progression)
    assert s.recent_events == []
    assert s.last_interaction_at is None
    assert s.schema_version == SCHEMA_VERSION


def test_defaults_are_independent_across_instances() -> None:
    """field(default_factory=...) must produce fresh containers per instance."""
    a = CreatureState(character_id="a", owner_user_id="u")
    b = CreatureState(character_id="b", owner_user_id="u")
    a.vitals.hunger = 99.0
    a.bond.affection = 5.0
    a.progression.milestones.append("first_meet")
    a.recent_events.append("hello")

    assert b.vitals.hunger == 50.0
    assert b.bond.affection == 0.0
    assert b.progression.milestones == []
    assert b.recent_events == []


def test_last_tick_at_is_utc_aware_and_recent() -> None:
    before = datetime.now(timezone.utc)
    s = CreatureState(character_id="c", owner_user_id="u")
    after = datetime.now(timezone.utc)
    assert s.last_tick_at.tzinfo is not None
    assert s.last_tick_at.utcoffset() == (datetime.now(timezone.utc).utcoffset())
    assert before <= s.last_tick_at <= after


def test_all_schema_types_are_dataclasses() -> None:
    for t in (Vitals, Bond, Progression, CreatureState, MoodVector):
        assert is_dataclass(t)


def test_character_role_default_is_vtuber() -> None:
    """Plan/Phase04: default role is VTuber for backward compat."""
    s = CreatureState(character_id="c", owner_user_id="u")
    assert s.character_role == CHARACTER_ROLE_VTUBER


def test_character_role_constants_distinct() -> None:
    assert CHARACTER_ROLE_VTUBER == "vtuber"
    assert CHARACTER_ROLE_WORKER == "worker"
    assert CHARACTER_ROLE_OTHER == "other"
    assert len({CHARACTER_ROLE_VTUBER, CHARACTER_ROLE_WORKER, CHARACTER_ROLE_OTHER}) == 3


def test_known_character_roles_complete() -> None:
    assert set(KNOWN_CHARACTER_ROLES) == {
        CHARACTER_ROLE_VTUBER,
        CHARACTER_ROLE_WORKER,
        CHARACTER_ROLE_OTHER,
    }


def test_character_role_explicit_assignment() -> None:
    worker = CreatureState(
        character_id="w1",
        owner_user_id="u",
        character_role=CHARACTER_ROLE_WORKER,
    )
    assert worker.character_role == CHARACTER_ROLE_WORKER
