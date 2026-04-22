"""Unit tests for the baseline :data:`DEFAULT_SEEDS` catalogue.

Each seed's trigger is exercised at its boundary (on vs off) — plan/04
§6.3's intent is that these fire on *specific* situations, not
ambient background. A regression that widens or narrows a trigger
(e.g. ``>`` drifting to ``>=``, case sensitivity changing) would
silently alter the pool's pick distribution.

The pool itself is tested in :mod:`test_pool`; this file focuses on
the catalogue's content.
"""

from __future__ import annotations

from backend.service.state.schema.creature_state import (
    Bond,
    CreatureState,
    Progression,
    Vitals,
)


def _creature(
    *,
    progression: Progression | None = None,
    vitals: Vitals | None = None,
    bond: Bond | None = None,
) -> CreatureState:
    kwargs: dict = {"character_id": "c1", "owner_user_id": "u1"}
    if progression is not None:
        kwargs["progression"] = progression
    if vitals is not None:
        kwargs["vitals"] = vitals
    if bond is not None:
        kwargs["bond"] = bond
    return CreatureState(**kwargs)


# ── Catalogue shape ───────────────────────────────────────────────────


def test_default_seeds_contains_eight_entries() -> None:
    from backend.service.game.events import DEFAULT_SEEDS

    assert len(DEFAULT_SEEDS) == 8


def test_default_seed_ids_are_unique() -> None:
    from backend.service.game.events import DEFAULT_SEEDS

    ids = [s.id for s in DEFAULT_SEEDS]
    assert len(set(ids)) == len(ids), f"duplicate ids: {ids}"


def test_default_seeds_all_have_nonempty_hint_text() -> None:
    from backend.service.game.events import DEFAULT_SEEDS

    for seed in DEFAULT_SEEDS:
        assert seed.hint_text.strip(), f"seed {seed.id!r} has empty hint_text"


def test_default_seed_weights_follow_salience_ordering() -> None:
    """Plan/04 §6.3 implies: transition spikes > recurring milestones >
    ambient. Encoded as 3.0 / 2.0 / 1.0-1.5."""
    from backend.service.game.events import (
        SEED_HIGH_AFFECTION,
        SEED_HIGH_STRESS,
        SEED_INFANT_FIRST_CHIRP,
        SEED_LONG_GAP_REUNION,
        SEED_MILESTONE_JUST_HIT,
        SEED_QUIET_NIGHT,
        SEED_RAINY_DAY,
        SEED_THIRTY_DAY_MILESTONE,
    )

    assert SEED_MILESTONE_JUST_HIT.weight == 3.0
    assert SEED_LONG_GAP_REUNION.weight == 2.0
    assert SEED_THIRTY_DAY_MILESTONE.weight == 2.0
    assert SEED_INFANT_FIRST_CHIRP.weight == 1.5
    assert SEED_RAINY_DAY.weight == 1.5
    assert SEED_HIGH_AFFECTION.weight == 1.0
    assert SEED_HIGH_STRESS.weight == 1.0
    assert SEED_QUIET_NIGHT.weight == 1.0


# ── Infant first chirp ────────────────────────────────────────────────


def test_infant_first_chirp_fires_at_infant_age_zero() -> None:
    from backend.service.game.events import SEED_INFANT_FIRST_CHIRP

    creature = _creature(progression=Progression(life_stage="infant", age_days=0))
    assert SEED_INFANT_FIRST_CHIRP.trigger(creature, {}) is True


def test_infant_first_chirp_does_not_fire_at_age_one() -> None:
    from backend.service.game.events import SEED_INFANT_FIRST_CHIRP

    creature = _creature(progression=Progression(life_stage="infant", age_days=1))
    assert SEED_INFANT_FIRST_CHIRP.trigger(creature, {}) is False


def test_infant_first_chirp_does_not_fire_for_child_at_age_zero() -> None:
    """Fresh ``child`` at 0d shouldn't fire — the seed is about the
    awakening moment, which lives on the infant curve."""
    from backend.service.game.events import SEED_INFANT_FIRST_CHIRP

    creature = _creature(progression=Progression(life_stage="child", age_days=0))
    assert SEED_INFANT_FIRST_CHIRP.trigger(creature, {}) is False


# ── 30-day milestone ──────────────────────────────────────────────────


def test_thirty_day_milestone_fires_at_multiples_of_30() -> None:
    from backend.service.game.events import SEED_THIRTY_DAY_MILESTONE

    for age in (30, 60, 90, 120):
        creature = _creature(progression=Progression(life_stage="child", age_days=age))
        assert SEED_THIRTY_DAY_MILESTONE.trigger(creature, {}) is True, age


def test_thirty_day_milestone_does_not_fire_at_day_zero() -> None:
    """Zero is a multiple of 30 mathematically but 'day 0' is a non-event
    — the infant_first_chirp seed owns that moment."""
    from backend.service.game.events import SEED_THIRTY_DAY_MILESTONE

    creature = _creature(progression=Progression(life_stage="infant", age_days=0))
    assert SEED_THIRTY_DAY_MILESTONE.trigger(creature, {}) is False


def test_thirty_day_milestone_does_not_fire_on_off_day() -> None:
    from backend.service.game.events import SEED_THIRTY_DAY_MILESTONE

    for age in (1, 29, 31, 59):
        creature = _creature(progression=Progression(life_stage="child", age_days=age))
        assert SEED_THIRTY_DAY_MILESTONE.trigger(creature, {}) is False, age


# ── High stress ──────────────────────────────────────────────────────


def test_high_stress_fires_at_threshold_and_above() -> None:
    from backend.service.game.events import SEED_HIGH_STRESS

    for stress in (70.0, 85.0, 100.0):
        creature = _creature(vitals=Vitals(stress=stress))
        assert SEED_HIGH_STRESS.trigger(creature, {}) is True, stress


def test_high_stress_does_not_fire_below_threshold() -> None:
    from backend.service.game.events import SEED_HIGH_STRESS

    creature = _creature(vitals=Vitals(stress=69.99))
    assert SEED_HIGH_STRESS.trigger(creature, {}) is False


# ── High affection ───────────────────────────────────────────────────


def test_high_affection_fires_at_threshold_and_above() -> None:
    from backend.service.game.events import SEED_HIGH_AFFECTION

    for affection in (10.0, 20.0, 50.0):
        creature = _creature(bond=Bond(affection=affection))
        assert SEED_HIGH_AFFECTION.trigger(creature, {}) is True, affection


def test_high_affection_does_not_fire_below_threshold() -> None:
    from backend.service.game.events import SEED_HIGH_AFFECTION

    creature = _creature(bond=Bond(affection=9.5))
    assert SEED_HIGH_AFFECTION.trigger(creature, {}) is False


# ── Rainy day ────────────────────────────────────────────────────────


def test_rainy_day_fires_on_case_insensitive_rain() -> None:
    from backend.service.game.events import SEED_RAINY_DAY

    for meta in ({"weather": "rain"}, {"weather": "RAIN"}, {"weather": "Rain"}):
        assert SEED_RAINY_DAY.trigger(_creature(), meta) is True, meta


def test_rainy_day_trims_whitespace_before_comparing() -> None:
    from backend.service.game.events import SEED_RAINY_DAY

    assert SEED_RAINY_DAY.trigger(_creature(), {"weather": "  rain  "}) is True


def test_rainy_day_does_not_fire_for_other_weather() -> None:
    from backend.service.game.events import SEED_RAINY_DAY

    for weather in ("sunny", "snow", "", None):
        meta = {"weather": weather} if weather is not None else {}
        assert SEED_RAINY_DAY.trigger(_creature(), meta) is False, meta


# ── Quiet night ──────────────────────────────────────────────────────


def test_quiet_night_fires_between_22_and_04() -> None:
    from backend.service.game.events import SEED_QUIET_NIGHT

    for hour in (22, 23, 0, 1, 2, 3, 4):
        assert SEED_QUIET_NIGHT.trigger(_creature(), {"local_hour": hour}) is True, hour


def test_quiet_night_does_not_fire_during_day() -> None:
    from backend.service.game.events import SEED_QUIET_NIGHT

    for hour in (5, 8, 12, 17, 21):
        assert SEED_QUIET_NIGHT.trigger(_creature(), {"local_hour": hour}) is False, hour


def test_quiet_night_tolerates_missing_or_garbage_meta() -> None:
    from backend.service.game.events import SEED_QUIET_NIGHT

    assert SEED_QUIET_NIGHT.trigger(_creature(), {}) is False
    assert SEED_QUIET_NIGHT.trigger(_creature(), {"local_hour": None}) is False
    assert SEED_QUIET_NIGHT.trigger(_creature(), {"local_hour": "late"}) is False


# ── Long-gap reunion ─────────────────────────────────────────────────


def test_long_gap_reunion_fires_after_week() -> None:
    from backend.service.game.events import SEED_LONG_GAP_REUNION

    for hours in (168, 169, 720):
        assert SEED_LONG_GAP_REUNION.trigger(
            _creature(), {"hours_since_last_session": hours}
        ) is True, hours


def test_long_gap_reunion_does_not_fire_inside_week() -> None:
    from backend.service.game.events import SEED_LONG_GAP_REUNION

    for hours in (0, 1, 23, 167.9):
        assert SEED_LONG_GAP_REUNION.trigger(
            _creature(), {"hours_since_last_session": hours}
        ) is False, hours


def test_long_gap_reunion_missing_meta_is_silent() -> None:
    from backend.service.game.events import SEED_LONG_GAP_REUNION

    assert SEED_LONG_GAP_REUNION.trigger(_creature(), {}) is False


# ── Milestone just hit ───────────────────────────────────────────────


def test_milestone_just_hit_fires_on_nonempty_string_flag() -> None:
    from backend.service.game.events import SEED_MILESTONE_JUST_HIT

    assert SEED_MILESTONE_JUST_HIT.trigger(
        _creature(), {"new_milestone": "enter:teen_introvert"}
    ) is True


def test_milestone_just_hit_does_not_fire_on_empty_or_missing() -> None:
    from backend.service.game.events import SEED_MILESTONE_JUST_HIT

    for meta in ({}, {"new_milestone": ""}, {"new_milestone": "   "}, {"new_milestone": None}):
        assert SEED_MILESTONE_JUST_HIT.trigger(_creature(), meta) is False, meta


# ── Defensive fall-through (progression=None etc.) ────────────────────


def test_creature_state_triggers_tolerate_missing_sub_fields() -> None:
    """Programmatic corruption — ``progression`` / ``vitals`` / ``bond``
    nulled out on the creature — must not raise. Every trigger should
    return ``False`` in that case so the pool stays clean."""
    from backend.service.game.events import (
        SEED_HIGH_AFFECTION,
        SEED_HIGH_STRESS,
        SEED_INFANT_FIRST_CHIRP,
        SEED_THIRTY_DAY_MILESTONE,
    )

    creature = _creature()
    creature.progression = None  # type: ignore[assignment]
    creature.vitals = None  # type: ignore[assignment]
    creature.bond = None  # type: ignore[assignment]

    for seed in (
        SEED_INFANT_FIRST_CHIRP,
        SEED_THIRTY_DAY_MILESTONE,
        SEED_HIGH_STRESS,
        SEED_HIGH_AFFECTION,
    ):
        assert seed.trigger(creature, {}) is False, seed.id
