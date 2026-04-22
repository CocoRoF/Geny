"""Affect summary extraction — PR-X6F-1.

Pins that ``summarize_affect_mutations`` produces the 6-dim vector in
the canonical tag order, that null/empty/irrelevant inputs return
``(None, None)``, and that the intensity scales so a single full-strength
tag reaches exactly 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from service.affect.summary import (
    AFFECT_VECTOR_TAGS,
    summarize_affect_mutations,
)


@dataclass
class _M:
    """Minimal mutation stand-in (duck-types the real Mutation dataclass)."""

    op: str
    path: str
    value: Any
    source: str = "test"
    note: Optional[str] = None


def test_tag_order_is_canonical() -> None:
    """Pin the exact tag order — retrieval depends on cross-turn consistency."""
    assert AFFECT_VECTOR_TAGS == (
        "joy",
        "sadness",
        "anger",
        "fear",
        "calm",
        "excitement",
    )


def test_none_input_returns_none_none() -> None:
    assert summarize_affect_mutations(None) == (None, None)


def test_empty_iterable_returns_none_none() -> None:
    assert summarize_affect_mutations([]) == (None, None)
    assert summarize_affect_mutations(()) == (None, None)


def test_only_non_mood_mutations_returns_none_none() -> None:
    """bond.* / vitals.* contributions are ignored by the affect summary."""
    entries = [
        _M(op="add", path="bond.affection", value=0.5),
        _M(op="add", path="vitals.hunger", value=-0.1),
        _M(op="set", path="mood.joy", value=0.5),  # wrong op
    ]
    assert summarize_affect_mutations(entries) == (None, None)


def test_single_joy_tag_yields_vector_with_joy_at_index_0() -> None:
    """joy is slot 0 — AffectTagEmitter multiplies strength by MOOD_ALPHA=0.15."""
    entries = [_M(op="add", path="mood.joy", value=1.0 * 0.15)]
    vec, intensity = summarize_affect_mutations(entries)
    assert vec is not None and intensity is not None
    assert len(vec) == 6
    assert vec[0] == pytest.approx(0.15)
    assert vec[1:] == [0.0, 0.0, 0.0, 0.0, 0.0]


def test_full_strength_single_tag_intensity_is_one() -> None:
    """strength=1.0 through MOOD_ALPHA scaling normalizes to intensity=1.0."""
    entries = [_M(op="add", path="mood.excitement", value=0.15)]
    vec, intensity = summarize_affect_mutations(entries)
    assert vec is not None
    assert intensity == pytest.approx(1.0)
    # excitement is slot 5 (last)
    assert vec[5] == pytest.approx(0.15)
    assert sum(abs(v) for v in vec[:5]) == 0.0


def test_multiple_tags_accumulate_and_preserve_order() -> None:
    entries = [
        _M(op="add", path="mood.joy", value=0.15),
        _M(op="add", path="mood.fear", value=0.075),
        _M(op="add", path="mood.calm", value=0.045),
    ]
    vec, intensity = summarize_affect_mutations(entries)
    assert vec is not None
    assert vec[0] == pytest.approx(0.15)   # joy
    assert vec[3] == pytest.approx(0.075)  # fear
    assert vec[4] == pytest.approx(0.045)  # calm
    # intensity = peak / MOOD_ALPHA = 0.15/0.15 = 1.0
    assert intensity == pytest.approx(1.0)


def test_same_tag_applied_twice_sums_deltas() -> None:
    entries = [
        _M(op="add", path="mood.joy", value=0.05),
        _M(op="add", path="mood.joy", value=0.08),
    ]
    vec, _ = summarize_affect_mutations(entries)
    assert vec is not None
    assert vec[0] == pytest.approx(0.13)


def test_negative_delta_reflected_in_vector() -> None:
    """A negative mood delta (e.g. regret) must survive in the vector."""
    entries = [_M(op="add", path="mood.joy", value=-0.10)]
    vec, intensity = summarize_affect_mutations(entries)
    assert vec is not None
    assert vec[0] == pytest.approx(-0.10)
    # intensity uses |peak|
    assert intensity == pytest.approx(0.10 / 0.15)


def test_intensity_clamps_to_one_for_super_intense_turns() -> None:
    """Multiple stacked strong deltas on one tag cannot exceed intensity=1.0."""
    entries = [
        _M(op="add", path="mood.anger", value=0.30),
        _M(op="add", path="mood.anger", value=0.20),
    ]
    _, intensity = summarize_affect_mutations(entries)
    assert intensity == pytest.approx(1.0)


def test_non_numeric_value_is_skipped_not_raised() -> None:
    """Defensive — a bad value on one entry must not kill the summary."""
    entries = [
        _M(op="add", path="mood.joy", value="not a number"),
        _M(op="add", path="mood.sadness", value=0.15),
    ]
    vec, intensity = summarize_affect_mutations(entries)
    assert vec is not None
    assert vec[0] == 0.0
    assert vec[1] == pytest.approx(0.15)
    assert intensity == pytest.approx(1.0)


def test_unknown_mood_tag_is_ignored() -> None:
    """mood.curiosity isn't in the closed tag set — skip without error."""
    entries = [
        _M(op="add", path="mood.curiosity", value=0.5),
        _M(op="add", path="mood.joy", value=0.15),
    ]
    vec, _ = summarize_affect_mutations(entries)
    assert vec is not None
    assert vec[0] == pytest.approx(0.15)


def test_accepts_real_mutation_buffer() -> None:
    """Integration: works with the actual MutationBuffer, not just the test double."""
    from service.state.schema.mutation import MutationBuffer

    buf = MutationBuffer()
    buf.append(op="add", path="mood.joy", value=0.15, source="test")
    buf.append(op="add", path="bond.affection", value=0.5, source="test")  # ignored
    vec, intensity = summarize_affect_mutations(buf)
    assert vec is not None
    assert vec[0] == pytest.approx(0.15)
    assert intensity == pytest.approx(1.0)


def test_round_trip_with_x6_1_encode_helpers() -> None:
    """Storage round-trip: summary → encode → decode → mixin-ready vector."""
    from service.affect import decode_emotion_vec, encode_emotion_vec

    entries = [
        _M(op="add", path="mood.joy", value=0.12),
        _M(op="add", path="mood.calm", value=0.06),
    ]
    vec, _ = summarize_affect_mutations(entries)
    roundtripped = decode_emotion_vec(encode_emotion_vec(vec))
    assert roundtripped == vec
