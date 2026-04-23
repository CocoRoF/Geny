"""Role / turn-kind helper contracts (Plan/Phase04).

The flags module is the single source of truth for "is this a VTuber?"
and "what kind of turn is this?" predicates. These tests pin the
tolerance behaviors (None inputs, unknown role strings, missing keys)
that the apply_decay guard / AffectTagEmitter / game tools all rely on.
"""

from __future__ import annotations

from service.state.flags import (
    KNOWN_TURN_KINDS,
    TURN_KIND_SYSTEM,
    TURN_KIND_TOOL,
    TURN_KIND_TRIGGER,
    TURN_KIND_USER,
    get_turn_kind,
    is_user_turn,
    is_vtuber_role,
    is_vtuber_state,
    role_of,
)
from service.state.schema.creature_state import (
    CHARACTER_ROLE_OTHER,
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
    CreatureState,
)


# ---------------------------------------------------------------------------
# is_vtuber_state
# ---------------------------------------------------------------------------

def test_is_vtuber_state_true_for_default_creature() -> None:
    s = CreatureState(character_id="c", owner_user_id="u")
    assert is_vtuber_state(s) is True


def test_is_vtuber_state_false_for_worker() -> None:
    s = CreatureState(
        character_id="w",
        owner_user_id="u",
        character_role=CHARACTER_ROLE_WORKER,
    )
    assert is_vtuber_state(s) is False


def test_is_vtuber_state_false_for_other() -> None:
    s = CreatureState(
        character_id="o",
        owner_user_id="u",
        character_role=CHARACTER_ROLE_OTHER,
    )
    assert is_vtuber_state(s) is False


def test_is_vtuber_state_none_returns_false() -> None:
    """Tolerant of None — classic-mode pipelines collapse cleanly."""
    assert is_vtuber_state(None) is False


def test_is_vtuber_state_unknown_role_treated_as_non_vtuber() -> None:
    """Defense in depth — typos / future roles default to 'skip'."""
    s = CreatureState(
        character_id="x",
        owner_user_id="u",
        character_role="researcher",
    )
    assert is_vtuber_state(s) is False


# ---------------------------------------------------------------------------
# is_vtuber_role / role_of
# ---------------------------------------------------------------------------

def test_is_vtuber_role_string_check() -> None:
    assert is_vtuber_role(CHARACTER_ROLE_VTUBER) is True
    assert is_vtuber_role(CHARACTER_ROLE_WORKER) is False
    assert is_vtuber_role(None) is False
    assert is_vtuber_role("") is False
    assert is_vtuber_role("vtuber") is True


def test_role_of_defaults_to_vtuber_when_none() -> None:
    assert role_of(None) == CHARACTER_ROLE_VTUBER


def test_role_of_returns_explicit_role() -> None:
    s = CreatureState(
        character_id="w",
        owner_user_id="u",
        character_role=CHARACTER_ROLE_WORKER,
    )
    assert role_of(s) == CHARACTER_ROLE_WORKER


def test_role_of_empty_string_falls_back_to_vtuber() -> None:
    """Falsy role strings collapse to the VTuber default."""
    s = CreatureState(character_id="c", owner_user_id="u", character_role="")
    assert role_of(s) == CHARACTER_ROLE_VTUBER


# ---------------------------------------------------------------------------
# Turn-kind helpers
# ---------------------------------------------------------------------------

def test_known_turn_kinds_is_complete() -> None:
    assert set(KNOWN_TURN_KINDS) == {
        TURN_KIND_USER,
        TURN_KIND_TRIGGER,
        TURN_KIND_TOOL,
        TURN_KIND_SYSTEM,
    }


def test_get_turn_kind_default_user() -> None:
    """Pre-Phase02 session_meta dicts have no turn_kind — default USER."""
    assert get_turn_kind({}) == TURN_KIND_USER
    assert get_turn_kind({"foo": "bar"}) == TURN_KIND_USER


def test_get_turn_kind_known_value_passes_through() -> None:
    assert get_turn_kind({"turn_kind": TURN_KIND_TRIGGER}) == TURN_KIND_TRIGGER
    assert get_turn_kind({"turn_kind": TURN_KIND_TOOL}) == TURN_KIND_TOOL
    assert get_turn_kind({"turn_kind": TURN_KIND_SYSTEM}) == TURN_KIND_SYSTEM


def test_get_turn_kind_unknown_value_falls_back_to_user() -> None:
    assert get_turn_kind({"turn_kind": "garbage"}) == TURN_KIND_USER
    assert get_turn_kind({"turn_kind": 42}) == TURN_KIND_USER


def test_get_turn_kind_non_dict_returns_user() -> None:
    assert get_turn_kind(None) == TURN_KIND_USER
    assert get_turn_kind("not a dict") == TURN_KIND_USER


def test_is_user_turn_wraps_get_turn_kind() -> None:
    assert is_user_turn({}) is True
    assert is_user_turn({"turn_kind": TURN_KIND_USER}) is True
    assert is_user_turn({"turn_kind": TURN_KIND_TRIGGER}) is False
    assert is_user_turn(None) is True
