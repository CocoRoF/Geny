"""Plan/Phase04 — v1 blob (no character_role) deserializes as VTuber.

Existing rows in the wild were written before the field landed; the
loader must transparently fill in the VTuber default so the migration
is a no-op for read paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from service.state.provider.serialize import dumps, from_dict, loads
from service.state.schema.creature_state import (
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
    CreatureState,
)


def test_v1_blob_without_role_defaults_to_vtuber() -> None:
    """A blob written before character_role existed must load as VTuber."""
    legacy_blob = json.dumps({
        "character_id": "c1",
        "owner_user_id": "u1",
        "vitals": {},
        "bond": {},
        "mood": {},
        "progression": {},
        "last_tick_at": datetime(2026, 4, 1, tzinfo=timezone.utc).isoformat(),
        "last_interaction_at": None,
        "recent_events": [],
        "schema_version": 1,
    })
    state = loads(legacy_blob)
    assert state.character_role == CHARACTER_ROLE_VTUBER
    assert state.character_id == "c1"


def test_blob_with_explicit_role_roundtrips() -> None:
    s = CreatureState(
        character_id="w1",
        owner_user_id="u1",
        character_role=CHARACTER_ROLE_WORKER,
    )
    roundtripped = loads(dumps(s))
    assert roundtripped.character_role == CHARACTER_ROLE_WORKER


def test_from_dict_missing_role_falls_back_to_vtuber() -> None:
    raw = {
        "character_id": "c",
        "owner_user_id": "u",
        "last_tick_at": datetime.now(timezone.utc).isoformat(),
    }
    state = from_dict(raw)
    assert state.character_role == CHARACTER_ROLE_VTUBER


def test_from_dict_empty_role_falls_back_to_vtuber() -> None:
    raw = {
        "character_id": "c",
        "owner_user_id": "u",
        "character_role": "",
        "last_tick_at": datetime.now(timezone.utc).isoformat(),
    }
    state = from_dict(raw)
    assert state.character_role == CHARACTER_ROLE_VTUBER
