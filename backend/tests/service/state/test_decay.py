"""Decay math / policy contract (cycle 20260421_9 PR-X3-4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from service.state.decay import (
    CATCHUP_THRESHOLD,
    DEFAULT_DECAY,
    DecayPolicy,
    DecayRule,
    apply_decay,
)
from service.state.schema.creature_state import CreatureState


def _fresh_state(now: datetime) -> CreatureState:
    # Fix vitals to known values so drift math is trivially verifiable.
    state = CreatureState(character_id="c1", owner_user_id="u1")
    state.vitals.hunger = 50.0
    state.vitals.energy = 80.0
    state.vitals.cleanliness = 80.0
    state.vitals.stress = 20.0
    state.bond.familiarity = 10.0
    state.bond.affection = 5.0
    state.last_tick_at = now
    return state


def test_decay_rule_rejects_empty_path() -> None:
    with pytest.raises(ValueError):
        DecayRule(path="", rate_per_hour=1.0)


def test_decay_rule_rejects_inverted_clamp() -> None:
    with pytest.raises(ValueError):
        DecayRule(path="vitals.hunger", rate_per_hour=1.0, clamp_min=50, clamp_max=10)


def test_decay_policy_rejects_duplicate_paths() -> None:
    with pytest.raises(ValueError):
        DecayPolicy(rules=(
            DecayRule("vitals.hunger", +1.0),
            DecayRule("vitals.hunger", +2.0),
        ))


def test_default_decay_shape() -> None:
    paths = {r.path for r in DEFAULT_DECAY.rules}
    # Plan §5.2 — vitals & familiarity baseline.
    # Plan/Phase03 §3.1 — mood axes added with regress_to mode.
    assert paths == {
        "vitals.hunger",
        "vitals.energy",
        "vitals.cleanliness",
        "vitals.stress",
        "bond.familiarity",
        "mood.joy",
        "mood.sadness",
        "mood.anger",
        "mood.fear",
        "mood.excitement",
        "mood.calm",
    }
    # Affection / trust / dependency deliberately excluded.
    assert "bond.affection" not in paths
    assert "bond.trust" not in paths
    assert "bond.dependency" not in paths


def test_default_catchup_threshold_is_30_minutes() -> None:
    assert CATCHUP_THRESHOLD == timedelta(minutes=30)


def test_apply_decay_linear_over_one_hour() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    policy = DecayPolicy(rules=(DecayRule("vitals.hunger", +2.5),))
    after = apply_decay(state, policy, now=now + timedelta(hours=1))
    assert after.vitals.hunger == pytest.approx(52.5)
    # Original untouched.
    assert state.vitals.hunger == pytest.approx(50.0)


def test_apply_decay_fractional_elapsed() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    policy = DecayPolicy(rules=(DecayRule("vitals.energy", -1.5),))
    # 30 minutes = 0.5h → -0.75
    after = apply_decay(state, policy, now=now + timedelta(minutes=30))
    assert after.vitals.energy == pytest.approx(79.25)


def test_apply_decay_clamps_to_max() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    state.vitals.hunger = 95.0
    policy = DecayPolicy(rules=(DecayRule("vitals.hunger", +10.0),))
    # 1h * +10 = 105 → clamped to 100.
    after = apply_decay(state, policy, now=now + timedelta(hours=1))
    assert after.vitals.hunger == pytest.approx(100.0)


def test_apply_decay_clamps_to_min() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    state.vitals.energy = 5.0
    policy = DecayPolicy(rules=(DecayRule("vitals.energy", -10.0),))
    after = apply_decay(state, policy, now=now + timedelta(hours=1))
    assert after.vitals.energy == pytest.approx(0.0)


def test_apply_decay_custom_clamp_bounds() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    state.bond.familiarity = 5.0
    policy = DecayPolicy(rules=(
        DecayRule("bond.familiarity", -10.0, clamp_min=2.0, clamp_max=100.0),
    ))
    after = apply_decay(state, policy, now=now + timedelta(hours=1))
    # Would land at -5, clamped up to 2.0.
    assert after.bond.familiarity == pytest.approx(2.0)


def test_apply_decay_bumps_last_tick_at() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    later = now + timedelta(hours=2)
    after = apply_decay(state, DEFAULT_DECAY, now=later)
    assert after.last_tick_at == later
    # Source not mutated.
    assert state.last_tick_at == now


def test_apply_decay_zero_elapsed_still_bumps_clock() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    state.vitals.hunger = 33.0
    after = apply_decay(state, DEFAULT_DECAY, now=now)
    assert after.last_tick_at == now
    assert after.vitals.hunger == pytest.approx(33.0)  # no drift


def test_apply_decay_negative_elapsed_is_noop() -> None:
    """Clock skew: caller passes ``now`` earlier than last_tick_at.

    Drift should be zero, but ``last_tick_at`` still moves (to the
    caller-supplied ``now``) to avoid silently rolling the clock
    forward based on stale state.
    """
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    earlier = now - timedelta(hours=1)
    after = apply_decay(state, DEFAULT_DECAY, now=earlier)
    assert after.last_tick_at == earlier
    # No reverse-decay.
    assert after.vitals.hunger == pytest.approx(state.vitals.hunger)
    assert after.vitals.energy == pytest.approx(state.vitals.energy)


def test_apply_decay_preserves_bond_affection_trust_dependency() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    state.bond.trust = 42.0
    state.bond.dependency = 7.0
    after = apply_decay(state, DEFAULT_DECAY, now=now + timedelta(hours=50))
    assert after.bond.affection == pytest.approx(state.bond.affection)
    assert after.bond.trust == pytest.approx(42.0)
    assert after.bond.dependency == pytest.approx(7.0)


def test_apply_decay_default_now_uses_utc_now() -> None:
    """When ``now`` is omitted, apply_decay samples current UTC."""
    # Place last_tick well in the past so we see some drift regardless.
    past = datetime.now(timezone.utc) - timedelta(hours=10)
    state = CreatureState(
        character_id="c1", owner_user_id="u1", last_tick_at=past,
    )
    state.vitals.hunger = 0.0
    after = apply_decay(
        state, DecayPolicy(rules=(DecayRule("vitals.hunger", +1.0),)),
    )
    # Should be ~10 over 10h at 1/h — allow a small window for test jitter.
    assert after.vitals.hunger == pytest.approx(10.0, abs=0.5)


def test_apply_decay_rejects_non_numeric_path() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    policy = DecayPolicy(rules=(DecayRule("progression.life_stage", +1.0),))
    with pytest.raises(TypeError):
        apply_decay(state, policy, now=now + timedelta(hours=1))


def test_apply_decay_rejects_unknown_path() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    policy = DecayPolicy(rules=(DecayRule("vitals.does_not_exist", -1.0),))
    with pytest.raises(KeyError):
        apply_decay(state, policy, now=now + timedelta(hours=1))


def test_apply_decay_preserves_row_version_attribute() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    setattr(state, "_row_version", 7)
    after = apply_decay(state, DEFAULT_DECAY, now=now + timedelta(hours=1))
    assert getattr(after, "_row_version") == 7


def test_apply_decay_without_row_version_does_not_add_one() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    after = apply_decay(state, DEFAULT_DECAY, now=now + timedelta(hours=1))
    assert not hasattr(after, "_row_version")


def test_apply_decay_empty_policy_only_bumps_clock() -> None:
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    state = _fresh_state(now)
    after = apply_decay(state, DecayPolicy(rules=()), now=now + timedelta(hours=5))
    assert after.last_tick_at == now + timedelta(hours=5)
    assert after.vitals.hunger == pytest.approx(state.vitals.hunger)
