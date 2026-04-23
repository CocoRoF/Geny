"""Plan/Phase03 §3.5 — dominant() determinism + raised threshold.

Three properties under test:

1. Default threshold raised from 0.15 to 0.30 — weak EMA noise
   (e.g. 0.2 transient joy) no longer flips the surfaced dominant.
2. Iteration order is the explicit tie-breaker — exactly equal
   values resolve to the earlier name in the canonical priority list
   (joy, excitement, anger, fear, sadness).
3. ``calm`` is the fallback when no basic emotion clears the
   threshold, *regardless* of the stored ``calm`` axis value.
"""

from __future__ import annotations

from service.state.schema.mood import MoodVector


def test_default_threshold_is_thirty_hundredths() -> None:
    # 0.20 is below the new default → fallback to calm.
    m = MoodVector(joy=0.20)
    assert m.dominant() == "calm"


def test_above_new_threshold_returns_strongest() -> None:
    m = MoodVector(joy=0.31)
    assert m.dominant() == "joy"


def test_threshold_boundary_is_strict() -> None:
    """Exactly at threshold counts as below (strictly >)."""
    m = MoodVector(joy=0.30)
    assert m.dominant() == "calm"


def test_tie_breaker_follows_canonical_order_joy_first() -> None:
    m = MoodVector(joy=0.5, excitement=0.5, anger=0.5)
    assert m.dominant() == "joy"


def test_tie_breaker_picks_excitement_over_anger() -> None:
    m = MoodVector(excitement=0.6, anger=0.6)
    assert m.dominant() == "excitement"


def test_tiny_floating_point_noise_does_not_flip_dominant() -> None:
    """1e-12 jitter on the loser must not flip the dominant — the
    `+ 1e-9` slack in the comparison is what guarantees this."""
    m1 = MoodVector(joy=0.6, excitement=0.6 + 1e-12)
    m2 = MoodVector(joy=0.6, excitement=0.6 - 1e-12)
    # Both should resolve to joy (canonical priority over noise).
    assert m1.dominant() == "joy"
    assert m2.dominant() == "joy"


def test_calm_fallback_ignores_stored_calm_value() -> None:
    """When all basic emotions are below threshold, dominant is "calm"
    even if the stored ``calm`` axis is 0 — the label is purely
    "no strong emotion", not "looks composed"."""
    m = MoodVector(joy=0.05, calm=0.0)
    assert m.dominant() == "calm"


def test_explicit_threshold_kwarg_overrides_default() -> None:
    """Callers that already pass an explicit threshold (legacy code)
    keep their old behavior — only the *default* changed."""
    m = MoodVector(joy=0.20)
    assert m.dominant(threshold=0.15) == "joy"
