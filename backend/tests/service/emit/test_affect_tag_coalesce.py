"""Plan/Phase03 §3.2 — same-path coalescing in AffectTagEmitter.

Multiple tags that target the same path (e.g. ``[joy] [joy]`` both
push ``mood.joy``) collapse into a single mutation per path within
one turn, with the values summed. Source string lists up to three
contributing tags joined by ``+``.
"""

from __future__ import annotations

import pytest
from geny_executor.core.state import PipelineState

from service.emit.affect_tag_emitter import AffectTagEmitter, MOOD_ALPHA
from service.state import MUTATION_BUFFER_KEY, MutationBuffer


def _state(text: str) -> tuple[PipelineState, MutationBuffer]:
    state = PipelineState()
    state.final_text = text
    buf = MutationBuffer()
    state.shared[MUTATION_BUFFER_KEY] = buf
    return state, buf


def _by_path(buf: MutationBuffer, path: str):
    return [m for m in buf.items if m.path == path]


@pytest.mark.asyncio
async def test_same_tag_repeated_collapses_to_single_mutation() -> None:
    """``[joy] [joy] [joy]`` → one ``mood.joy`` entry summing all 3."""
    # Cap=3 so all three contribute; otherwise default cap=2 limits us.
    state, buf = _state("[joy] [joy] [joy]")
    await AffectTagEmitter(max_tags_per_turn=3).emit(state)

    joys = _by_path(buf, "mood.joy")
    assert len(joys) == 1
    assert joys[0].value == pytest.approx(3 * MOOD_ALPHA)


@pytest.mark.asyncio
async def test_two_different_tags_same_path_coalesce() -> None:
    """``[joy]`` (bond.affection +0.5) + ``[calm]`` (bond.affection +0.5)
    → one bond.affection entry of +1.0."""
    state, buf = _state("[joy] [calm]")
    await AffectTagEmitter(max_tags_per_turn=2).emit(state)

    aff = _by_path(buf, "bond.affection")
    assert len(aff) == 1
    assert aff[0].value == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_coalesced_source_lists_contributing_tags() -> None:
    state, buf = _state("[joy] [calm]")
    await AffectTagEmitter(max_tags_per_turn=2).emit(state)

    aff = _by_path(buf, "bond.affection")[0]
    assert aff.source.startswith("emit:affect_tag/")
    parts = aff.source.split("/", 1)[1].split("+")
    assert set(parts) == {"joy", "calm"}


@pytest.mark.asyncio
async def test_coalesced_source_caps_at_three_tags() -> None:
    """Per-path source list keeps at most 3 contributors for log brevity."""
    state, buf = _state("[joy] [calm] [satisfaction] [excitement]")
    await AffectTagEmitter(max_tags_per_turn=4).emit(state)

    aff = _by_path(buf, "bond.affection")
    assert len(aff) == 1
    parts = aff[0].source.split("/", 1)[1].split("+")
    assert len(parts) <= 3


@pytest.mark.asyncio
async def test_distinct_paths_remain_separate() -> None:
    """Coalescing is per-path, not global — different paths stay split."""
    state, buf = _state("[joy] [anger]")
    await AffectTagEmitter(max_tags_per_turn=2).emit(state)

    assert len(_by_path(buf, "mood.joy")) == 1
    assert len(_by_path(buf, "mood.anger")) == 1
    # joy → bond.affection; anger → bond.trust → also distinct.
    assert len(_by_path(buf, "bond.affection")) == 1
    assert len(_by_path(buf, "bond.trust")) == 1


@pytest.mark.asyncio
async def test_coalesce_preserves_strength_weighting() -> None:
    """``[joy:2] [joy:1]`` → mood.joy = (2+1) * MOOD_ALPHA = 3 * MOOD_ALPHA."""
    state, buf = _state("[joy:2] [joy:1]")
    await AffectTagEmitter(max_tags_per_turn=2).emit(state)
    joys = _by_path(buf, "mood.joy")
    assert len(joys) == 1
    assert joys[0].value == pytest.approx(3 * MOOD_ALPHA)
