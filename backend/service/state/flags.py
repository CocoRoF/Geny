"""Role / turn-kind discriminator helpers (Plan/Phase04).

A handful of subsystems need to ask "is this a VTuber?" or "what kind
of turn is this?" without taking a hard dependency on ``CreatureState``
internals. Centralising the predicates here means the role string
literal lives in exactly one place — :mod:`schema.creature_state` —
and every call site uses the same definition of "VTuber".

These helpers are intentionally tolerant:

- ``is_vtuber_state(None)`` returns ``False`` rather than raising, so
  classic-mode pipelines (no creature state at all) skip cleanly.
- Unknown role strings fall through as non-VTuber (defense in depth —
  a typo or a future role rolls forward as "skip the side-effects"
  rather than as "treat as VTuber and corrupt state").

Turn-kind support exists here in skeleton form for Phase 02 (affection
policy). The constants are defined now so call sites that need to
read ``session_meta["turn_kind"]`` have a stable vocabulary; the
classifier stage that *writes* the value lands in Phase 02.
"""

from __future__ import annotations

from typing import Any, Optional

from .schema.creature_state import (
    CHARACTER_ROLE_OTHER,
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
    CreatureState,
)

# ---------------------------------------------------------------------------
# Turn-kind vocabulary (Phase 02 — affection policy)
# ---------------------------------------------------------------------------
# Persisted into ``state.shared['session_meta']['turn_kind']`` by the
# Phase02 turn classifier stage. Read by AffectTagEmitter and by the
# loneliness-drift stage. Defined here (not in Phase02 module) so flag
# helpers can be imported without pulling the classifier in.

TURN_KIND_USER = "user"          # User-initiated dialogue / command.
TURN_KIND_TRIGGER = "trigger"    # Autonomous (ThinkingTriggerService) wake.
TURN_KIND_TOOL = "tool"          # System-driven tool follow-up.
TURN_KIND_SYSTEM = "system"      # Internal / housekeeping turn.

KNOWN_TURN_KINDS = (
    TURN_KIND_USER,
    TURN_KIND_TRIGGER,
    TURN_KIND_TOOL,
    TURN_KIND_SYSTEM,
)


# ---------------------------------------------------------------------------
# Role predicates
# ---------------------------------------------------------------------------

def is_vtuber_state(state: Optional[CreatureState]) -> bool:
    """Return ``True`` iff *state* exists and is tagged VTuber.

    Tolerant of ``None`` so callers running in classic mode (no
    creature state hydrated) collapse to a clean "no — skip the
    side-effect" branch.
    """
    if state is None:
        return False
    return getattr(state, "character_role", CHARACTER_ROLE_VTUBER) == CHARACTER_ROLE_VTUBER


def is_vtuber_role(role: Optional[str]) -> bool:
    """Pure string check — useful when only the role string is in scope.

    Mirrors :func:`is_vtuber_state` for callers that read role from
    ``session_meta`` without having the full ``CreatureState`` handy
    (e.g. game tools that only see the contextvars).
    """
    return role == CHARACTER_ROLE_VTUBER


def role_of(state: Optional[CreatureState]) -> str:
    """Return the role string, defaulting to VTuber.

    The default matches the dataclass default — a hydrated state with
    no explicit role *is* a VTuber by construction (the field landed
    in v2; the migration backfilled v1 rows as VTuber).
    """
    if state is None:
        return CHARACTER_ROLE_VTUBER
    return getattr(state, "character_role", CHARACTER_ROLE_VTUBER) or CHARACTER_ROLE_VTUBER


# ---------------------------------------------------------------------------
# Turn-kind helpers
# ---------------------------------------------------------------------------

def get_turn_kind(session_meta: Any) -> str:
    """Read ``turn_kind`` from a session_meta dict, defaulting to USER.

    USER is the safe default because:

    * Pre-Phase02 session_meta dicts have no ``turn_kind`` key — those
      turns *are* user-initiated (the only path that historically
      hydrated state was the user calling execute_command).
    * If the classifier ever fails to set the key, treating the turn
      as USER is the conservative choice — it preserves bond
      mutations rather than silently swallowing them.
    """
    if not isinstance(session_meta, dict):
        return TURN_KIND_USER
    kind = session_meta.get("turn_kind")
    if isinstance(kind, str) and kind in KNOWN_TURN_KINDS:
        return kind
    return TURN_KIND_USER


def is_user_turn(session_meta: Any) -> bool:
    """Convenience wrapper — Phase02 affection policy gating."""
    return get_turn_kind(session_meta) == TURN_KIND_USER


__all__ = [
    "CHARACTER_ROLE_OTHER",
    "CHARACTER_ROLE_VTUBER",
    "CHARACTER_ROLE_WORKER",
    "KNOWN_TURN_KINDS",
    "TURN_KIND_SYSTEM",
    "TURN_KIND_TOOL",
    "TURN_KIND_TRIGGER",
    "TURN_KIND_USER",
    "get_turn_kind",
    "is_user_turn",
    "is_vtuber_role",
    "is_vtuber_state",
    "role_of",
]
