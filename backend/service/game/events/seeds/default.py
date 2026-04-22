"""Baseline event seeds — plan/04 §6.3.

Eight seeds covering the three trigger surfaces the plan mentions:

- **Creature state**: infant first chirp, 30-day milestone, high stress,
  high affection — evaluated from :class:`CreatureState` directly.
- **Session meta**: rainy day, quiet night, long-gap reunion — evaluated
  from ``session_meta`` keys the caller supplies (``weather``,
  ``local_hour``, ``hours_since_last_session``). Missing keys are
  *absence signals*, not errors — the trigger just returns ``False``.
- **Transition flag**: milestone just hit — fires when the PR-X4-5
  integration stamps ``session_meta["new_milestone"]`` with a freshly
  appended milestone id.

Triggers are pure, sync, and defensive — every attribute access uses
``getattr`` / ``meta.get`` so malformed state or an early-boot session
returns ``False`` instead of raising. :class:`EventSeedPool` swallows
exceptions anyway, but triggers that never raise keep the debug log
clean.

Weights encode relative salience. A just-hit milestone beats a
monthly anniversary beats ambient signals — ``3.0`` / ``2.0`` /
``1.0-1.5`` — so rare narrative peaks surface when they coincide with
ambient triggers.
"""

from __future__ import annotations

from typing import Any, Mapping

from backend.service.state.schema.creature_state import CreatureState

from ..pool import EventSeed


# ── Trigger helpers ───────────────────────────────────────────────────


def _int_or_zero(value: Any) -> int:
    """``int(value)`` with a zero fallback for ``None`` / garbage."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ── Creature-state triggers ───────────────────────────────────────────


def _infant_first_chirp_trigger(
    creature: CreatureState, meta: Mapping[str, Any],
) -> bool:
    progression = getattr(creature, "progression", None)
    if progression is None:
        return False
    life_stage = getattr(progression, "life_stage", "") or ""
    age_days = _int_or_zero(getattr(progression, "age_days", 0))
    return life_stage == "infant" and age_days == 0


SEED_INFANT_FIRST_CHIRP = EventSeed(
    id="infant_first_chirp",
    trigger=_infant_first_chirp_trigger,
    hint_text=(
        "This is the creature's very first day awake — a tiny chirp, "
        "fumble, or wide-eyed question is in character."
    ),
    weight=1.5,
)


def _thirty_day_milestone_trigger(
    creature: CreatureState, meta: Mapping[str, Any],
) -> bool:
    progression = getattr(creature, "progression", None)
    if progression is None:
        return False
    age_days = _int_or_zero(getattr(progression, "age_days", 0))
    return age_days > 0 and age_days % 30 == 0


SEED_THIRTY_DAY_MILESTONE = EventSeed(
    id="thirty_day_milestone",
    trigger=_thirty_day_milestone_trigger,
    hint_text=(
        "Today marks a 30-day milestone since awakening — the creature "
        "can mention it if it flows naturally."
    ),
    weight=2.0,
)


def _high_stress_trigger(
    creature: CreatureState, meta: Mapping[str, Any],
) -> bool:
    vitals = getattr(creature, "vitals", None)
    if vitals is None:
        return False
    return _float_or_zero(getattr(vitals, "stress", 0.0)) >= 70.0


SEED_HIGH_STRESS = EventSeed(
    id="high_stress",
    trigger=_high_stress_trigger,
    hint_text=(
        "The creature's stress is near its peak — replies may trail "
        "off, snap short, or quietly ask for space."
    ),
    weight=1.0,
)


def _high_affection_trigger(
    creature: CreatureState, meta: Mapping[str, Any],
) -> bool:
    bond = getattr(creature, "bond", None)
    if bond is None:
        return False
    return _float_or_zero(getattr(bond, "affection", 0.0)) >= 10.0


SEED_HIGH_AFFECTION = EventSeed(
    id="high_affection",
    trigger=_high_affection_trigger,
    hint_text=(
        "The bond with the owner is deep — warmth, familiarity, and "
        "small nicknames can colour any reply."
    ),
    weight=1.0,
)


# ── Session-meta triggers ─────────────────────────────────────────────


def _rainy_day_trigger(
    creature: CreatureState, meta: Mapping[str, Any],
) -> bool:
    weather = str(meta.get("weather", "")).strip().lower()
    return weather == "rain"


SEED_RAINY_DAY = EventSeed(
    id="rainy_day",
    trigger=_rainy_day_trigger,
    hint_text=(
        "It's raining outside — the creature may notice the sound or "
        "comment on the weather if it fits the moment."
    ),
    weight=1.5,
)


_QUIET_NIGHT_HOURS = frozenset({22, 23, 0, 1, 2, 3, 4})


def _quiet_night_trigger(
    creature: CreatureState, meta: Mapping[str, Any],
) -> bool:
    raw = meta.get("local_hour", None)
    if raw is None:
        return False
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        return False
    return hour in _QUIET_NIGHT_HOURS


SEED_QUIET_NIGHT = EventSeed(
    id="quiet_night",
    trigger=_quiet_night_trigger,
    hint_text=(
        "It's late at night — the creature's voice can be softer, "
        "sleepier, more reflective."
    ),
    weight=1.0,
)


_LONG_GAP_HOURS = 7 * 24  # ≥ one week since the last session.


def _long_gap_reunion_trigger(
    creature: CreatureState, meta: Mapping[str, Any],
) -> bool:
    raw = meta.get("hours_since_last_session", None)
    if raw is None:
        return False
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        return False
    return hours >= _LONG_GAP_HOURS


SEED_LONG_GAP_REUNION = EventSeed(
    id="long_gap_reunion",
    trigger=_long_gap_reunion_trigger,
    hint_text=(
        "A long time has passed since the last session (about a week "
        "or more) — greet the reunion with warmth or mild relief."
    ),
    weight=2.0,
)


# ── Transition-flag trigger ───────────────────────────────────────────


def _milestone_just_hit_trigger(
    creature: CreatureState, meta: Mapping[str, Any],
) -> bool:
    new_milestone = meta.get("new_milestone", "")
    return isinstance(new_milestone, str) and bool(new_milestone.strip())


SEED_MILESTONE_JUST_HIT = EventSeed(
    id="milestone_just_hit",
    trigger=_milestone_just_hit_trigger,
    hint_text=(
        "A new life milestone was just reached — a moment of quiet "
        "pride or gentle celebration is fitting."
    ),
    weight=3.0,
)


DEFAULT_SEEDS: tuple[EventSeed, ...] = (
    SEED_INFANT_FIRST_CHIRP,
    SEED_THIRTY_DAY_MILESTONE,
    SEED_MILESTONE_JUST_HIT,
    SEED_LONG_GAP_REUNION,
    SEED_RAINY_DAY,
    SEED_HIGH_AFFECTION,
    SEED_HIGH_STRESS,
    SEED_QUIET_NIGHT,
)


__all__ = [
    "DEFAULT_SEEDS",
    "SEED_HIGH_AFFECTION",
    "SEED_HIGH_STRESS",
    "SEED_INFANT_FIRST_CHIRP",
    "SEED_LONG_GAP_REUNION",
    "SEED_MILESTONE_JUST_HIT",
    "SEED_QUIET_NIGHT",
    "SEED_RAINY_DAY",
    "SEED_THIRTY_DAY_MILESTONE",
]
