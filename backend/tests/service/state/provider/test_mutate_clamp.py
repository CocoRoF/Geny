"""Plan/Phase03 §3.4 — path-aware clamps in apply_mutations.

``mood.*`` is an EMA distribution and must stay in [0, 1].
``vitals.*`` stays in [0, 100].
``bond.*`` is floored at 0 (no upper cap by design).
"""

from __future__ import annotations

import pytest

from service.state.provider.mutate import apply_mutations
from service.state.schema.creature_state import CreatureState
from service.state.schema.mutation import Mutation


def _mk() -> CreatureState:
    return CreatureState(character_id="c1", owner_user_id="u1")


def _mut(op: str, path: str, value, source: str = "test") -> Mutation:
    return Mutation(op=op, path=path, value=value, source=source)


# ── mood ────────────────────────────────────────────────────────


def test_mood_add_clamps_high_to_one() -> None:
    s = _mk()
    s.mood.joy = 0.9
    out = apply_mutations(s, [_mut("add", "mood.joy", +0.5)])
    assert out.mood.joy == pytest.approx(1.0)


def test_mood_add_clamps_low_to_zero() -> None:
    s = _mk()
    s.mood.joy = 0.1
    out = apply_mutations(s, [_mut("add", "mood.joy", -0.5)])
    assert out.mood.joy == pytest.approx(0.0)


def test_mood_set_above_one_is_clamped() -> None:
    s = _mk()
    out = apply_mutations(s, [_mut("set", "mood.joy", 1.7)])
    assert out.mood.joy == pytest.approx(1.0)


def test_mood_set_below_zero_is_clamped() -> None:
    s = _mk()
    out = apply_mutations(s, [_mut("set", "mood.joy", -0.4)])
    assert out.mood.joy == pytest.approx(0.0)


# ── vitals ──────────────────────────────────────────────────────


def test_vitals_add_clamps_high_to_one_hundred() -> None:
    s = _mk()
    s.vitals.hunger = 95.0
    out = apply_mutations(s, [_mut("add", "vitals.hunger", +20.0)])
    assert out.vitals.hunger == pytest.approx(100.0)


def test_vitals_add_clamps_low_to_zero() -> None:
    s = _mk()
    s.vitals.hunger = 5.0
    out = apply_mutations(s, [_mut("add", "vitals.hunger", -20.0)])
    assert out.vitals.hunger == pytest.approx(0.0)


def test_vitals_set_above_hundred_is_clamped() -> None:
    s = _mk()
    out = apply_mutations(s, [_mut("set", "vitals.hunger", 200.0)])
    assert out.vitals.hunger == pytest.approx(100.0)


# ── bond ────────────────────────────────────────────────────────


def test_bond_add_floors_at_zero_and_no_upper_cap() -> None:
    s = _mk()
    s.bond.affection = 1.0
    out = apply_mutations(s, [_mut("add", "bond.affection", -5.0)])
    assert out.bond.affection == pytest.approx(0.0)
    out2 = apply_mutations(s, [_mut("add", "bond.affection", +500.0)])
    # No upper clamp on bond.* — stays at 501.0.
    assert out2.bond.affection == pytest.approx(501.0)


def test_bond_set_negative_is_floored() -> None:
    s = _mk()
    out = apply_mutations(s, [_mut("set", "bond.affection", -3.5)])
    assert out.bond.affection == pytest.approx(0.0)
