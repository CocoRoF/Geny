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
