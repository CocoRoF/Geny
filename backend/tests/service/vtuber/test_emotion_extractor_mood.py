"""Mood-aware ``EmotionExtractor.resolve_emotion`` — PR-X3-9.

The extractor gains a third input source: a hydrated
:class:`MoodVector` from ``CreatureState``. These tests pin:

1. The priority chain — explicit text tag > mood > agent state > neutral.
2. Calm / ``None`` mood defers (doesn't clobber a useful agent_state).
3. ``excitement`` maps to ``surprise`` (closest facial slot in the
   default Live2D emotionMap).
4. Classic callers (no ``mood=`` kwarg) keep their old two-argument
   priority exactly — the kwarg is purely additive.
5. ``MoodVector`` subclasses / look-alikes that raise from ``dominant``
   never take down avatar emission.
"""

from __future__ import annotations

from typing import Dict

import pytest

from service.state.schema.mood import MoodVector
from service.vtuber.emotion_extractor import EmotionExtractor


# Match the default Live2D emotionMap shape Geny ships with — these
# are the six slots every model registry supplies, so the resolver
# always has an index to hand back.
_EMOTION_MAP: Dict[str, int] = {
    "neutral": 0,
    "joy": 1,
    "sadness": 2,
    "anger": 3,
    "fear": 4,
    "surprise": 5,
}


def _make() -> EmotionExtractor:
    return EmotionExtractor(_EMOTION_MAP)


# ── map_mood_to_emotion — pure unit ─────────────────────────────────


def test_map_mood_none_returns_none() -> None:
    assert EmotionExtractor.map_mood_to_emotion(None) is None


def test_map_mood_calm_defaults_defer() -> None:
    """Default MoodVector is calm-dominant; resolver must defer."""
    assert EmotionExtractor.map_mood_to_emotion(MoodVector()) is None


def test_map_mood_joy_above_threshold() -> None:
    mood = MoodVector(joy=0.6)
    assert EmotionExtractor.map_mood_to_emotion(mood) == "joy"


def test_map_mood_basic_below_threshold_defers() -> None:
    """Strongest basic emotion still under 0.15 → calm → None."""
    mood = MoodVector(joy=0.10, sadness=0.05)
    assert EmotionExtractor.map_mood_to_emotion(mood) is None


def test_map_mood_excitement_maps_to_surprise() -> None:
    """``excitement`` has no Live2D slot; we surface it as surprise."""
    mood = MoodVector(excitement=0.8)
    assert EmotionExtractor.map_mood_to_emotion(mood) == "surprise"


def test_map_mood_negative_emotion_wins() -> None:
    mood = MoodVector(anger=0.5, fear=0.2, joy=0.1)
    assert EmotionExtractor.map_mood_to_emotion(mood) == "anger"


def test_map_mood_threshold_override() -> None:
    """Caller can raise the bar — 0.5 threshold drops a 0.3 joy."""
    mood = MoodVector(joy=0.3)
    assert EmotionExtractor.map_mood_to_emotion(mood, threshold=0.5) is None


def test_map_mood_survives_dominant_exception() -> None:
    """A broken mood-like object must not crash — defer instead."""

    class _Broken:
        def dominant(self, **_: object) -> str:
            raise RuntimeError("boom")

    assert EmotionExtractor.map_mood_to_emotion(_Broken()) is None  # type: ignore[arg-type]


# ── resolve_emotion priority chain ──────────────────────────────────


def test_resolve_text_tag_beats_mood() -> None:
    """An explicit ``[sadness]`` tag overrides a joyful mood — the LLM
    is telling us how *this* utterance should land."""
    mood = MoodVector(joy=0.9)
    emotion, index = _make().resolve_emotion("[sadness] oh", None, mood=mood)
    assert emotion == "sadness"
    assert index == _EMOTION_MAP["sadness"]


def test_resolve_mood_beats_agent_state() -> None:
    """No tag + real mood → mood wins over the operational default."""
    mood = MoodVector(anger=0.7)
    emotion, index = _make().resolve_emotion("hello there", "completed", mood=mood)
    assert emotion == "anger"
    assert index == _EMOTION_MAP["anger"]


def test_resolve_calm_mood_falls_through_to_agent_state() -> None:
    """Calm-only mood → defer to the operational signal."""
    emotion, index = _make().resolve_emotion("hello", "executing", mood=MoodVector())
    # map_state_to_emotion("executing") → "surprise"
    assert emotion == "surprise"
    assert index == _EMOTION_MAP["surprise"]


def test_resolve_no_mood_keeps_classic_behaviour() -> None:
    """Without the kwarg the resolver must behave exactly like X1/X2."""
    emotion, index = _make().resolve_emotion("plain text", "completed")
    # No tags, no mood, completed → joy
    assert emotion == "joy"
    assert index == _EMOTION_MAP["joy"]


def test_resolve_mood_none_equivalent_to_missing_kwarg() -> None:
    a = _make().resolve_emotion("x", "completed", mood=None)
    b = _make().resolve_emotion("x", "completed")
    assert a == b


def test_resolve_mood_with_no_agent_state_and_no_text() -> None:
    """Bare mood call must still resolve — this is the tick-driven
    update path where neither text nor agent_state is available."""
    mood = MoodVector(fear=0.5)
    emotion, index = _make().resolve_emotion(None, None, mood=mood)
    assert emotion == "fear"
    assert index == _EMOTION_MAP["fear"]


def test_resolve_default_when_all_sources_silent() -> None:
    emotion, index = _make().resolve_emotion(None, None, mood=MoodVector())
    assert emotion == "neutral"
    assert index == _EMOTION_MAP["neutral"]


def test_resolve_mood_excitement_surfaces_as_surprise() -> None:
    mood = MoodVector(excitement=0.9)
    emotion, _ = _make().resolve_emotion(None, "completed", mood=mood)
    assert emotion == "surprise"


def test_resolve_mood_missing_slot_in_emotion_map_yields_zero_index() -> None:
    """A model that only ships ``neutral`` still returns a stable
    (name, 0) pair without blowing up."""
    extractor = EmotionExtractor({"neutral": 0})
    mood = MoodVector(joy=0.7)
    emotion, index = extractor.resolve_emotion(None, None, mood=mood)
    assert emotion == "joy"
    assert index == 0


def test_resolve_text_tag_with_invalid_name_falls_to_mood() -> None:
    """``[whatever]`` is stripped but not counted as a tag; the mood
    signal should still be honoured on the fallback path."""
    mood = MoodVector(joy=0.8)
    emotion, _ = _make().resolve_emotion("[whatever] hi", "completed", mood=mood)
    assert emotion == "joy"


def test_resolve_mood_kwarg_is_keyword_only() -> None:
    """Positional call with three args must raise — we don't want
    callers accidentally drifting into the new mood slot."""
    with pytest.raises(TypeError):
        _make().resolve_emotion("x", "completed", MoodVector(joy=0.6))  # type: ignore[misc]


# ── Cycle 20260422_5 follow-up: ``:strength`` suffix tolerance ──────


def test_strength_decorated_tag_is_recognized() -> None:
    """``[joy:0.7]`` must register as joy, not be ignored. User-reported
    leak: before this fix the regex only matched ``[joy]``, so strength-
    decorated tags were neither counted nor stripped."""
    extractor = _make()
    result = extractor.extract("[joy:0.7] hello")
    assert result.primary_emotion == "joy"
    assert "[joy:0.7]" not in result.cleaned_text
    assert result.cleaned_text == "hello"


def test_strength_decorated_tag_is_stripped_from_cleaned_text() -> None:
    """Even when the tag is *invalid* (not in the emotion_map), the
    bracket + strength must still be removed from display text."""
    extractor = _make()
    result = extractor.extract("[wonder:1.5] cool")
    # "wonder" isn't in _EMOTION_MAP → no emotion, but text must be clean
    assert "[wonder:1.5]" not in result.cleaned_text
    assert result.cleaned_text == "cool"


def test_remove_tags_also_strips_strength_suffix() -> None:
    extractor = _make()
    assert (
        extractor.remove_tags("[excitement:0.7] 좋아 [calm] 차분")
        == "좋아 차분"
    )


def test_whitespace_inside_bracket_still_strips() -> None:
    extractor = _make()
    result = extractor.extract("[ joy : 0.5 ] hi")
    assert result.primary_emotion == "joy"
    assert result.cleaned_text == "hi"
