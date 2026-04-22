"""Event seed layer — plan/04 §6.

An :class:`EventSeed` is a tiny ``(trigger, hint_text, weight)`` bundle.
:class:`EventSeedPool` evaluates every seed's trigger against the
current :class:`CreatureState` and session meta, then picks ONE active
seed (or none) via weighted random. The chosen seed's ``hint_text`` is
surfaced as a single :class:`EventSeedBlock` at the end of the persona
prompt (PR-X4-5 wiring), nudging the LLM toward narrative beats
without fragmenting the system prompt across many conditional blocks.

Exposed:

- :class:`EventSeed` — frozen dataclass.
- :class:`EventSeedPool` — ``pick(creature, meta, *, rng=None)`` and
  ``list_active(creature, meta)``; never raises.
- :class:`EventSeedBlock` — :class:`PromptBlock` wrapping one seed.
- :data:`DEFAULT_SEEDS` — plan §6.3's baseline seed set (8 seeds).
"""

from __future__ import annotations

from .block import EventSeedBlock
from .pool import EventSeed, EventSeedPool
from .seeds.default import (
    DEFAULT_SEEDS,
    SEED_HIGH_AFFECTION,
    SEED_HIGH_STRESS,
    SEED_INFANT_FIRST_CHIRP,
    SEED_LONG_GAP_REUNION,
    SEED_MILESTONE_JUST_HIT,
    SEED_QUIET_NIGHT,
    SEED_RAINY_DAY,
    SEED_THIRTY_DAY_MILESTONE,
)

__all__ = [
    "DEFAULT_SEEDS",
    "EventSeed",
    "EventSeedBlock",
    "EventSeedPool",
    "SEED_HIGH_AFFECTION",
    "SEED_HIGH_STRESS",
    "SEED_INFANT_FIRST_CHIRP",
    "SEED_LONG_GAP_REUNION",
    "SEED_MILESTONE_JUST_HIT",
    "SEED_QUIET_NIGHT",
    "SEED_RAINY_DAY",
    "SEED_THIRTY_DAY_MILESTONE",
]
