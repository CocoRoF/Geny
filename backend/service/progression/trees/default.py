"""Baseline growth tree — ``infant → child → teen → adult``.

Implements the sample curve in ``plan/04 §7.3``. Numbers here are
**tuning knobs**, not contracts: the transition predicates are kept
obvious (threshold comparisons, no composition, no external lookups)
so a designer can edit them without reading selector internals.

Pacing rationale
----------------

- ``infant → child`` at 3 days + familiarity ≥ 20. A player who
  actually interacts daily crosses familiarity 20 in well under a
  week (``talk`` is ``+0.3/call``, so ≈67 calls); the gate is the
  age-days timer, not the bond number.
- ``child → teen`` at 14 days + affection ≥ 40. Two weeks is the
  point where "casual visitor" separates from "regular" in plan §1;
  affection 40 is "deep bond" territory without demanding the
  highest band.
- ``teen → adult`` at 40 days + milestone ``first_conflict_resolved``.
  Narrative gate on purpose — adulthood shouldn't be unlocked by
  grinding timers alone. X4-4 introduces the seed that plants this
  milestone; until then the transition simply doesn't fire.
"""

from __future__ import annotations

from typing import Tuple

from backend.service.state.schema.creature_state import CreatureState

from ..selector import Transition

DEFAULT_TREE_ID: str = "default"

_FIRST_CONFLICT_MILESTONE: str = "first_conflict_resolved"


def _has_milestone(creature: CreatureState, milestone: str) -> bool:
    milestones = getattr(creature.progression, "milestones", ()) or ()
    return milestone in milestones


DEFAULT_TREE: Tuple[Transition, ...] = (
    Transition(
        from_stage="infant",
        to_stage="child",
        predicate=lambda s: (
            s.progression.age_days >= 3 and s.bond.familiarity >= 20.0
        ),
    ),
    Transition(
        from_stage="child",
        to_stage="teen",
        predicate=lambda s: (
            s.progression.age_days >= 14 and s.bond.affection >= 40.0
        ),
    ),
    Transition(
        from_stage="teen",
        to_stage="adult",
        predicate=lambda s: (
            s.progression.age_days >= 40
            and _has_milestone(s, _FIRST_CONFLICT_MILESTONE)
        ),
    ),
)


__all__ = ["DEFAULT_TREE", "DEFAULT_TREE_ID"]
