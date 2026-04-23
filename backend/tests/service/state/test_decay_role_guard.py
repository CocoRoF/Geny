"""Plan/Phase04 — apply_decay must skip non-VTuber characters.

The pure decay function is the single chokepoint that both the
periodic decay service AND the registry catch-up share. Pinning the
guard here means *both* code paths inherit the VTuber-only contract
without duplication.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from service.state.decay import DEFAULT_DECAY, DecayPolicy, DecayRule, apply_decay
from service.state.schema.creature_state import (
    CHARACTER_ROLE_OTHER,
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
    CreatureState,
)


def _state(role: str, *, hunger: float = 50.0) -> CreatureState:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    s = CreatureState(
        character_id="c1",
        owner_user_id="u1",
        character_role=role,
        last_tick_at=now,
    )
    s.vitals.hunger = hunger
    s.vitals.energy = 80.0
    s.vitals.cleanliness = 80.0
    s.vitals.stress = 20.0
    s.bond.familiarity = 10.0
    return s


def test_apply_decay_no_drift_for_worker() -> None:
    s = _state(CHARACTER_ROLE_WORKER)
    later = s.last_tick_at + timedelta(hours=10)
    after = apply_decay(s, DEFAULT_DECAY, now=later)
    # Vitals untouched.
    assert after.vitals.hunger == pytest.approx(50.0)
    assert after.vitals.energy == pytest.approx(80.0)
    assert after.vitals.cleanliness == pytest.approx(80.0)
    assert after.vitals.stress == pytest.approx(20.0)
    assert after.bond.familiarity == pytest.approx(10.0)


def test_apply_decay_still_bumps_clock_for_worker() -> None:
    """Skip rules but advance last_tick_at — next call computes elapsed
    from here, not from a stale boundary."""
    s = _state(CHARACTER_ROLE_WORKER)
    later = s.last_tick_at + timedelta(hours=3)
    after = apply_decay(s, DEFAULT_DECAY, now=later)
    assert after.last_tick_at == later


def test_apply_decay_no_drift_for_other() -> None:
    s = _state(CHARACTER_ROLE_OTHER)
    later = s.last_tick_at + timedelta(hours=24)
    after = apply_decay(s, DEFAULT_DECAY, now=later)
    assert after.vitals.hunger == pytest.approx(50.0)


def test_apply_decay_no_drift_for_unknown_role() -> None:
    """Defense in depth: unknown role => skip."""
    s = _state("researcher")
    later = s.last_tick_at + timedelta(hours=10)
    after = apply_decay(s, DEFAULT_DECAY, now=later)
    assert after.vitals.hunger == pytest.approx(50.0)


def test_apply_decay_drifts_for_vtuber() -> None:
    s = _state(CHARACTER_ROLE_VTUBER, hunger=50.0)
    later = s.last_tick_at + timedelta(hours=2)
    after = apply_decay(
        s, DecayPolicy(rules=(DecayRule("vitals.hunger", +2.5),)), now=later,
    )
    # 2h * +2.5 = +5
    assert after.vitals.hunger == pytest.approx(55.0)


def test_apply_decay_preserves_row_version_for_worker() -> None:
    s = _state(CHARACTER_ROLE_WORKER)
    setattr(s, "_row_version", 9)
    later = s.last_tick_at + timedelta(hours=1)
    after = apply_decay(s, DEFAULT_DECAY, now=later)
    assert getattr(after, "_row_version") == 9


def test_apply_decay_does_not_mutate_input_for_worker() -> None:
    s = _state(CHARACTER_ROLE_WORKER, hunger=33.0)
    original_tick = s.last_tick_at
    later = s.last_tick_at + timedelta(hours=5)
    apply_decay(s, DEFAULT_DECAY, now=later)
    assert s.vitals.hunger == pytest.approx(33.0)
    assert s.last_tick_at == original_tick
