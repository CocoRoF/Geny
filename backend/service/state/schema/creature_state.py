"""``CreatureState`` + substructures — the durable per-character game state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .mood import MoodVector

# Plan/Phase04 §2.1 — bumped from 1 → 2 with the addition of
# ``character_role``. Existing v1 rows deserialize via the field
# default below ("vtuber"), so the bump is informational rather than
# destructive — the migration script (provider/migrations/v1_to_v2)
# upgrades on first read so the persisted ``schema_version`` matches.
SCHEMA_VERSION = 2

# Role discriminator for "VTuber-only" gating (Plan/Phase04). Worker /
# Researcher / Planner agents reuse the same pipeline plumbing but must
# NOT trigger creature-state side-effects (decay, affect tag mutations,
# loneliness drift). Existing rows default to VTUBER for backward
# compatibility — non-VTuber characters are explicitly tagged at
# creation time by the agent-session bootstrap.
CHARACTER_ROLE_VTUBER = "vtuber"
CHARACTER_ROLE_WORKER = "worker"
CHARACTER_ROLE_OTHER = "other"

# Frozen tuple of accepted role values — used by the flags helpers and
# by the migration script to validate persisted blobs without importing
# the constants individually.
KNOWN_CHARACTER_ROLES = (
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
    CHARACTER_ROLE_OTHER,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Vitals:
    """Physical upkeep stats — decay over time, restored by interactions."""

    hunger: float = 50.0       # 0=sated, 100=starving
    energy: float = 80.0       # 0=exhausted, 100=peak
    stress: float = 20.0       # 0=calm, 100=extreme stress
    cleanliness: float = 80.0  # 0=filthy, 100=spotless


@dataclass
class Bond:
    """Relationship stats — accumulate long term; do not decay."""

    affection: float = 0.0
    trust: float = 0.0
    familiarity: float = 0.0
    dependency: float = 0.0


@dataclass
class Progression:
    """Long-term growth state."""

    age_days: int = 0
    life_stage: str = "infant"    # infant / child / teen / adult
    xp: int = 0
    milestones: List[str] = field(default_factory=list)
    manifest_id: str = "base"


@dataclass
class CreatureState:
    # Identity
    character_id: str
    owner_user_id: str

    # Role discriminator (Plan/Phase04). Defaults to VTuber for backward
    # compat — every existing row in the wild was created before the
    # field existed, and they're all VTubers by construction (only the
    # VTuber pipeline wires the state provider). Worker / planner
    # creatures (if ever introduced) must be tagged explicitly at
    # creation time so the role guards in apply_decay /
    # AffectTagEmitter / game tools skip them cleanly.
    character_role: str = CHARACTER_ROLE_VTUBER

    # Mutable game state
    vitals: Vitals = field(default_factory=Vitals)
    bond: Bond = field(default_factory=Bond)
    mood: MoodVector = field(default_factory=MoodVector)
    progression: Progression = field(default_factory=Progression)

    # Timestamps / event stream
    last_tick_at: datetime = field(default_factory=_utcnow)
    last_interaction_at: Optional[datetime] = None
    recent_events: List[str] = field(default_factory=list)

    # Schema version for migrations
    schema_version: int = SCHEMA_VERSION
