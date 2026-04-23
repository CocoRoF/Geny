"""Plan/Phase03 §3.3 — saturation factor on mood-axis deltas.

When the *current* mood value is high, additional positive deltas
on the same axis are scaled down (and eventually fully suppressed).
This stops a positive-feedback loop where a saturated joy axis
keeps absorbing more ``[joy]`` tags forever.

Negative deltas (regress toward neutral) are NOT saturated by this
mechanism — bringing joy down should always be easy.
"""

from __future__ import annotations

import pytest
from geny_executor.core.state import PipelineState

from service.emit.affect_tag_emitter import (
    AffectTagEmitter,
    MOOD_ALPHA,
    _saturation_factor,
)
from service.state import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    MutationBuffer,
)
from service.state.schema.creature_state import CreatureState
from service.state.schema.mood import MoodVector


# ── pure factor curve ────────────────────────────────────────────


def test_saturation_below_half_is_unity() -> None:
    assert _saturation_factor(0.0) == 1.0
    assert _saturation_factor(0.49) == 1.0


def test_saturation_at_half_is_unity_boundary() -> None:
    # At exactly 0.5 the function falls through to the linear branch
    # but evaluates to 1.0; this makes the curve continuous.
    assert _saturation_factor(0.5) == pytest.approx(1.0)


def test_saturation_at_eight_tenths_is_half() -> None:
    assert _saturation_factor(0.8) == pytest.approx(0.5)


def test_saturation_at_one_is_zero() -> None:
    assert _saturation_factor(1.0) == 0.0
    assert _saturation_factor(1.5) == 0.0  # above cap → still suppressed


def test_saturation_curve_is_monotonic_decreasing() -> None:
    last = 1.01
    for step in range(0, 11):
        v = step / 10.0
        cur = _saturation_factor(v)
        assert cur <= last + 1e-9
        last = cur


# ── integrated emitter behavior ──────────────────────────────────


def _state_with_snap(text: str, mood: MoodVector) -> tuple[PipelineState, MutationBuffer]:
    state = PipelineState()
    state.final_text = text
    buf = MutationBuffer()
    state.shared[MUTATION_BUFFER_KEY] = buf
    snap = CreatureState(character_id="c1", owner_user_id="u1", mood=mood)
    state.shared[CREATURE_STATE_KEY] = snap
    return state, buf


def _by_path(buf, path):
    return [m for m in buf.items if m.path == path]


@pytest.mark.asyncio
async def test_high_joy_state_attenuates_new_joy_delta() -> None:
    """Snapshot has joy=0.95 → sat≈0.125 → new mood.joy delta is ~1/8."""
    state, buf = _state_with_snap("[joy:1]", MoodVector(joy=0.95))
    await AffectTagEmitter().emit(state)
    joys = _by_path(buf, "mood.joy")
    assert len(joys) == 1
    expected = 1.0 * MOOD_ALPHA * _saturation_factor(0.95)
    assert joys[0].value == pytest.approx(expected, abs=1e-6)


@pytest.mark.asyncio
async def test_saturated_joy_axis_drops_to_zero_and_is_skipped() -> None:
    """At joy=1.0 the factor is 0 → no mood.joy mutation is appended."""
    state, buf = _state_with_snap("[joy:1]", MoodVector(joy=1.0))
    await AffectTagEmitter().emit(state)
    assert _by_path(buf, "mood.joy") == []


@pytest.mark.asyncio
async def test_saturation_only_attenuates_mood_not_bond() -> None:
    """bond.* paths are not subject to the saturation factor."""
    state, buf = _state_with_snap("[joy:1]", MoodVector(joy=1.0))
    await AffectTagEmitter().emit(state)
    # mood.joy fully suppressed; bond.affection still applies (full strength).
    aff = _by_path(buf, "bond.affection")
    assert len(aff) == 1
    assert aff[0].value == pytest.approx(0.5)
