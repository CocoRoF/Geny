"""Plan/Phase03 §3.1 — mood natural drift via DecayRule.regress_to.

These tests pin three properties of the mood-regression branch:

1. Basic emotions (joy/sadness/anger/fear/excitement) drift toward 0.
2. ``calm`` drifts toward 0.5 — both upward from 0 and downward from 1.
3. Drift never overshoots its target (10h of pull on a 0.1 gap settles
   at the target, not past it).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from service.state.decay import DEFAULT_DECAY, DecayPolicy, DecayRule, apply_decay
from service.state.schema.creature_state import CreatureState
from service.state.schema.mood import MoodVector


_NOW = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)


def _mk(mood: MoodVector | None = None) -> CreatureState:
    s = CreatureState(
        character_id="c1",
        owner_user_id="u1",
        last_tick_at=_NOW,
    )
    if mood is not None:
        s.mood = mood
    return s


# ── basic emotions decay toward 0 ──────────────────────────────────


def test_joy_drifts_toward_zero_at_minus_015_per_hour() -> None:
    s = _mk(MoodVector(joy=1.0, calm=0.5))
    out = apply_decay(s, DEFAULT_DECAY, now=_NOW + timedelta(hours=1))
    # 1.0 - 0.15 = 0.85
    assert out.mood.joy == pytest.approx(0.85, abs=1e-6)


def test_anger_drifts_fastest() -> None:
    s = _mk(MoodVector(anger=1.0, calm=0.5))
    out = apply_decay(s, DEFAULT_DECAY, now=_NOW + timedelta(hours=1))
    # rate 0.20/hr → 0.80
    assert out.mood.anger == pytest.approx(0.80, abs=1e-6)


def test_sadness_drifts_slowest() -> None:
    s = _mk(MoodVector(sadness=1.0, calm=0.5))
    out = apply_decay(s, DEFAULT_DECAY, now=_NOW + timedelta(hours=1))
    # rate 0.10/hr → 0.90
    assert out.mood.sadness == pytest.approx(0.90, abs=1e-6)


def test_drift_does_not_overshoot_target() -> None:
    """A 10h pull on a 0.05 gap settles exactly at 0.0, not negative."""
    s = _mk(MoodVector(joy=0.05, calm=0.5))
    out = apply_decay(s, DEFAULT_DECAY, now=_NOW + timedelta(hours=10))
    assert out.mood.joy == pytest.approx(0.0, abs=1e-9)


def test_drift_holds_at_zero_when_already_neutral() -> None:
    s = _mk(MoodVector(joy=0.0, calm=0.5))
    out = apply_decay(s, DEFAULT_DECAY, now=_NOW + timedelta(hours=24))
    assert out.mood.joy == pytest.approx(0.0)


# ── calm drifts to the 0.5 midpoint from both sides ───────────────


def test_calm_drifts_up_from_zero_toward_half() -> None:
    s = _mk(MoodVector(calm=0.0))
    out = apply_decay(s, DEFAULT_DECAY, now=_NOW + timedelta(hours=1))
    # rate 0.05/hr toward 0.5 → 0.05
    assert out.mood.calm == pytest.approx(0.05, abs=1e-6)


def test_calm_drifts_down_from_one_toward_half() -> None:
    s = _mk(MoodVector(calm=1.0))
    out = apply_decay(s, DEFAULT_DECAY, now=_NOW + timedelta(hours=1))
    # 1.0 → 0.95 (pull toward 0.5)
    assert out.mood.calm == pytest.approx(0.95, abs=1e-6)


def test_calm_settles_exactly_at_half_after_long_idle() -> None:
    s = _mk(MoodVector(calm=0.0))
    out = apply_decay(s, DEFAULT_DECAY, now=_NOW + timedelta(hours=100))
    # 100h * 0.05 = 5.0 worth of pull; gap is 0.5 → lands exactly at 0.5
    assert out.mood.calm == pytest.approx(0.5, abs=1e-9)


# ── DecayRule.regress_to contract ─────────────────────────────────


def test_regress_to_ignores_rate_sign() -> None:
    """Plan §3.1 — only |rate| matters in regression mode; sign is unused."""
    s = _mk(MoodVector(joy=0.6, calm=0.5))
    # Same magnitude, opposite sign — should yield identical drift.
    pol_a = DecayPolicy(rules=(
        DecayRule("mood.joy", rate_per_hour=-0.20,
                  clamp_min=0.0, clamp_max=1.0, regress_to=0.0),
    ))
    pol_b = DecayPolicy(rules=(
        DecayRule("mood.joy", rate_per_hour=+0.20,
                  clamp_min=0.0, clamp_max=1.0, regress_to=0.0),
    ))
    out_a = apply_decay(s, pol_a, now=_NOW + timedelta(hours=1))
    out_b = apply_decay(s, pol_b, now=_NOW + timedelta(hours=1))
    assert out_a.mood.joy == out_b.mood.joy


def test_default_decay_includes_six_mood_axes_with_regress_to() -> None:
    by_path = {r.path: r for r in DEFAULT_DECAY.rules}
    for axis in ("joy", "sadness", "anger", "fear", "excitement"):
        rule = by_path[f"mood.{axis}"]
        assert rule.regress_to == 0.0
        assert rule.clamp_min == 0.0
        assert rule.clamp_max == 1.0
    calm = by_path["mood.calm"]
    assert calm.regress_to == 0.5
