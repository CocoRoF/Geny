"""CreatureState schema dataclasses (PR-X3-1, cycle 20260421_9)."""

from __future__ import annotations

from .creature_state import (
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
from .mood import MoodVector
from .mutation import Mutation, MutationBuffer, MutationOp

__all__ = [
    "CHARACTER_ROLE_OTHER",
    "CHARACTER_ROLE_VTUBER",
    "CHARACTER_ROLE_WORKER",
    "KNOWN_CHARACTER_ROLES",
    "SCHEMA_VERSION",
    "Bond",
    "CreatureState",
    "MoodVector",
    "Mutation",
    "MutationBuffer",
    "MutationOp",
    "Progression",
    "Vitals",
]
