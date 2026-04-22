"""AffectTagEmitter behaviour (cycle 20260421_9 PR-X3-7)."""

from __future__ import annotations

from typing import List

import pytest
from geny_executor.core.state import PipelineState

from service.emit.affect_tag_emitter import (
    AFFECT_TAG_RE,
    AFFECT_TAGS,
    MOOD_ALPHA,
    AffectTagEmitter,
)
from service.state import MUTATION_BUFFER_KEY, MutationBuffer


def _state_with_buffer(text: str) -> tuple[PipelineState, MutationBuffer]:
    state = PipelineState()
    state.final_text = text
    buf = MutationBuffer()
    state.shared[MUTATION_BUFFER_KEY] = buf
    return state, buf


def _by_path(buf: MutationBuffer, path: str) -> List:
    return [m for m in buf.items if m.path == path]


def test_regex_covers_all_six_tags() -> None:
    for tag in AFFECT_TAGS:
        assert AFFECT_TAG_RE.search(f"hi [{tag}] there")


def test_regex_matches_optional_strength() -> None:
    text = "start [joy:2.5] mid [sadness] end [anger:0.3]"
    matches = AFFECT_TAG_RE.findall(text)
    assert matches == [("joy", "2.5"), ("sadness", ""), ("anger", "0.3")]


def test_regex_is_case_insensitive() -> None:
    assert AFFECT_TAG_RE.search("[JOY]")
    assert AFFECT_TAG_RE.search("[Sadness:2]")


def test_regex_tolerates_trailing_space_before_bracket() -> None:
    # ``\s*\]`` allows trim-tolerance for models that pad before ``]``.
    assert AFFECT_TAG_RE.search("[joy ]")
    assert AFFECT_TAG_RE.search("[joy:2 ]")


@pytest.mark.asyncio
async def test_emit_joy_pushes_mood_and_bond_affection() -> None:
    state, buf = _state_with_buffer("I'm glad you came! [joy:2]")
    result = await AffectTagEmitter().emit(state)

    assert result.emitted is True
    assert result.metadata["matches"] == 1
    assert result.metadata["applied"] == 1

    mood = _by_path(buf, "mood.joy")
    bond = _by_path(buf, "bond.affection")
    assert len(mood) == 1 and mood[0].value == pytest.approx(2 * MOOD_ALPHA)
    assert len(bond) == 1 and bond[0].value == pytest.approx(2 * 0.5)


@pytest.mark.asyncio
async def test_emit_anger_pushes_mood_and_bond_trust_down() -> None:
    state, buf = _state_with_buffer("You never listen [anger:1]")
    await AffectTagEmitter().emit(state)

    assert _by_path(buf, "mood.anger")[0].value == pytest.approx(MOOD_ALPHA)
    trust = _by_path(buf, "bond.trust")
    assert len(trust) == 1 and trust[0].value == pytest.approx(-0.3)


@pytest.mark.asyncio
async def test_calm_bumps_affection_fear_drops_trust() -> None:
    state, buf = _state_with_buffer("okay [calm] wait [fear]")
    await AffectTagEmitter().emit(state)

    assert _by_path(buf, "bond.affection")[0].value == pytest.approx(0.5)
    assert _by_path(buf, "bond.trust")[0].value == pytest.approx(-0.3)


@pytest.mark.asyncio
async def test_strength_defaults_to_one_when_absent() -> None:
    state, buf = _state_with_buffer("hmm [sadness]")
    await AffectTagEmitter().emit(state)
    assert _by_path(buf, "mood.sadness")[0].value == pytest.approx(MOOD_ALPHA)


@pytest.mark.asyncio
async def test_emit_strips_all_tags_from_final_text() -> None:
    state, _ = _state_with_buffer("hi [joy:2] there [excitement] done")
    await AffectTagEmitter().emit(state)
    assert "[" not in state.final_text
    assert "joy" not in state.final_text.lower() or "joy" not in "hi there done".lower()
    assert "hi" in state.final_text and "there" in state.final_text and "done" in state.final_text


@pytest.mark.asyncio
async def test_emit_collapses_double_spaces_after_strip() -> None:
    state, _ = _state_with_buffer("hi  [joy]  there")
    await AffectTagEmitter().emit(state)
    assert "  " not in state.final_text


@pytest.mark.asyncio
async def test_no_tags_returns_not_emitted() -> None:
    state, buf = _state_with_buffer("a plain sentence with no cues")
    result = await AffectTagEmitter().emit(state)
    assert result.emitted is False
    assert result.metadata["matches"] == 0
    assert buf.items == ()


@pytest.mark.asyncio
async def test_empty_final_text_is_safe() -> None:
    state = PipelineState()
    state.final_text = ""
    result = await AffectTagEmitter().emit(state)
    assert result.emitted is False


@pytest.mark.asyncio
async def test_missing_buffer_still_strips_text() -> None:
    state = PipelineState()
    state.final_text = "hey [joy:1] friend"
    result = await AffectTagEmitter().emit(state)

    assert result.emitted is False
    assert result.metadata["reason"] == "no_mutation_buffer"
    assert result.metadata["matches"] == 1
    assert "[joy" not in state.final_text


@pytest.mark.asyncio
async def test_per_turn_cap_caps_mutations_but_still_strips_all() -> None:
    emitter = AffectTagEmitter(max_tags_per_turn=2)
    state, buf = _state_with_buffer("[joy:1] [calm:1] [excitement:1] [joy:1]")
    result = await emitter.emit(state)

    assert result.metadata["applied"] == 2
    assert result.metadata["dropped"] == 2
    assert "[" not in state.final_text

    mood_entries = [m for m in buf.items if m.path.startswith("mood.")]
    assert len(mood_entries) == 2


@pytest.mark.asyncio
async def test_sources_are_emit_affect_tag_per_tag() -> None:
    state, buf = _state_with_buffer("[joy:1] [anger:2]")
    await AffectTagEmitter().emit(state)
    sources = {m.source for m in buf.items}
    assert "emit:affect_tag/joy" in sources
    assert "emit:affect_tag/anger" in sources


@pytest.mark.asyncio
async def test_malformed_strength_leaves_tag_unmatched() -> None:
    """``[joy:]`` lacks a numeric strength; our regex requires well-formed
    ``:N`` or nothing, so a colon-with-no-number simply doesn't match —
    safer than silently accepting garbage."""
    state, buf = _state_with_buffer("ok [joy:] wat")
    result = await AffectTagEmitter().emit(state)
    assert result.emitted is False
    assert buf.items == ()
    # Tag-like debris stays in final_text (the regex didn't match it).
    assert "[joy:]" in state.final_text


@pytest.mark.asyncio
async def test_only_six_whitelisted_tags_apply() -> None:
    state, buf = _state_with_buffer("[giddy] [joy]")
    result = await AffectTagEmitter().emit(state)
    assert result.metadata["matches"] == 1
    assert len(_by_path(buf, "mood.joy")) == 1


def test_constructor_rejects_negative_cap() -> None:
    with pytest.raises(ValueError):
        AffectTagEmitter(max_tags_per_turn=-1)


def test_emitter_name_is_affect_tag() -> None:
    assert AffectTagEmitter().name == "affect_tag"


@pytest.mark.asyncio
async def test_zero_cap_still_strips_tags_but_applies_none() -> None:
    emitter = AffectTagEmitter(max_tags_per_turn=0)
    state, buf = _state_with_buffer("[joy:1] hi")
    result = await emitter.emit(state)
    assert result.metadata["applied"] == 0
    assert result.metadata["dropped"] == 1
    assert "[joy" not in state.final_text
    assert buf.items == ()


@pytest.mark.asyncio
async def test_mood_only_for_sadness_excitement_no_secondary_bond() -> None:
    state, buf = _state_with_buffer("[sadness:1] [excitement:1]")
    await AffectTagEmitter().emit(state)

    assert _by_path(buf, "mood.sadness")
    assert _by_path(buf, "mood.excitement")
    assert _by_path(buf, "bond.affection") == []
    assert _by_path(buf, "bond.trust") == []


# ── PR-X6F-3: state.shared[AFFECT_TURN_SUMMARY_KEY] stash ───────────


@pytest.mark.asyncio
async def test_emit_stashes_turn_summary_on_shared() -> None:
    """After a successful emit, the turn's affect summary lives on shared."""
    from service.affect.summary import (
        AFFECT_TURN_SUMMARY_KEY,
        AFFECT_VECTOR_TAGS,
        AffectTurnSummary,
    )

    state, _ = _state_with_buffer("sparks! [joy:1]")
    result = await AffectTagEmitter().emit(state)

    summary = state.shared.get(AFFECT_TURN_SUMMARY_KEY)
    assert isinstance(summary, AffectTurnSummary)
    assert len(summary.emotion_vec) == len(AFFECT_VECTOR_TAGS)
    # joy is slot 0 — strength 1.0 × MOOD_ALPHA = MOOD_ALPHA
    assert summary.emotion_vec[0] == pytest.approx(MOOD_ALPHA)
    # intensity = peak / MOOD_ALPHA = 1.0 for full-strength single tag
    assert summary.emotion_intensity == pytest.approx(1.0)
    assert result.metadata["summary_stashed"] is True


@pytest.mark.asyncio
async def test_no_tags_leaves_shared_untouched() -> None:
    """Emit with no matches must not pollute shared with a stale summary."""
    from service.affect.summary import AFFECT_TURN_SUMMARY_KEY

    state, _ = _state_with_buffer("nothing to see here")
    await AffectTagEmitter().emit(state)
    assert AFFECT_TURN_SUMMARY_KEY not in state.shared


@pytest.mark.asyncio
async def test_stashed_summary_is_frozen_snapshot() -> None:
    """The stashed value is a frozen dataclass — accidental mutation raises."""
    from dataclasses import FrozenInstanceError

    from service.affect.summary import AFFECT_TURN_SUMMARY_KEY

    state, _ = _state_with_buffer("[calm:1]")
    await AffectTagEmitter().emit(state)
    summary = state.shared[AFFECT_TURN_SUMMARY_KEY]
    with pytest.raises(FrozenInstanceError):
        summary.emotion_intensity = 0.0  # type: ignore[misc]


@pytest.mark.asyncio
async def test_summary_shape_matches_db_writer_kwargs() -> None:
    """End-to-end type check: the stashed summary's fields map 1:1 to
    db_stm_add_message(emotion_vec=, emotion_intensity=) kwargs."""
    from service.affect import decode_emotion_vec
    from service.affect.summary import AFFECT_TURN_SUMMARY_KEY
    from service.database.memory_db_helper import _coerce_emotion_vec

    state, _ = _state_with_buffer("[joy:1] [calm:1]")
    await AffectTagEmitter().emit(state)
    summary = state.shared[AFFECT_TURN_SUMMARY_KEY]

    # Writer can consume summary.emotion_vec directly (tuple of floats)
    raw = _coerce_emotion_vec(list(summary.emotion_vec))
    assert raw is not None
    assert decode_emotion_vec(raw) == list(summary.emotion_vec)
    # Writer can consume summary.emotion_intensity directly (float)
    assert isinstance(summary.emotion_intensity, float)
    assert 0.0 <= summary.emotion_intensity <= 1.0


@pytest.mark.asyncio
async def test_multi_tag_summary_accumulates_all_mood_paths() -> None:
    """Summary vector reflects every applied tag, not just the last one."""
    from service.affect.summary import AFFECT_TURN_SUMMARY_KEY, AFFECT_VECTOR_TAGS

    state, _ = _state_with_buffer("[joy:1] [fear:0.5] [calm:0.25]")
    await AffectTagEmitter().emit(state)
    summary = state.shared[AFFECT_TURN_SUMMARY_KEY]
    # Build by-name view for readability
    by_tag = dict(zip(AFFECT_VECTOR_TAGS, summary.emotion_vec))
    assert by_tag["joy"] == pytest.approx(MOOD_ALPHA)
    assert by_tag["fear"] == pytest.approx(0.5 * MOOD_ALPHA)
    assert by_tag["calm"] == pytest.approx(0.25 * MOOD_ALPHA)
    assert by_tag["sadness"] == 0.0
    assert by_tag["anger"] == 0.0
    assert by_tag["excitement"] == 0.0


@pytest.mark.asyncio
async def test_no_mutation_buffer_does_not_stash_summary() -> None:
    """When there's no buffer, no summary — and the emit path still
    short-circuits cleanly (reason='no_mutation_buffer')."""
    from service.affect.summary import AFFECT_TURN_SUMMARY_KEY

    state = PipelineState()
    state.final_text = "[joy:1]"
    # Intentionally no MUTATION_BUFFER_KEY on shared
    result = await AffectTagEmitter().emit(state)
    assert result.metadata.get("reason") == "no_mutation_buffer"
    assert AFFECT_TURN_SUMMARY_KEY not in state.shared
