"""Plan/Phase02 — turn-kind gating in AffectTagEmitter.

Autonomous (THINKING_TRIGGER) turns must NOT grow ``bond.affection``
or move ``bond.trust``. Mood axes still drift on every turn — the
character has an inner life even when no one is talking to them.
"""

from __future__ import annotations

import pytest
from geny_executor.core.state import PipelineState

from service.emit.affect_tag_emitter import AffectTagEmitter
from service.state import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    SESSION_META_KEY,
    TURN_KIND_TRIGGER,
    TURN_KIND_USER,
    MutationBuffer,
)
from service.state.schema.creature_state import (
    CHARACTER_ROLE_VTUBER,
    CreatureState,
)


def _state(text: str, *, turn_kind: str) -> tuple[PipelineState, MutationBuffer]:
    state = PipelineState()
    state.final_text = text
    buf = MutationBuffer()
    snap = CreatureState(
        character_id="c",
        owner_user_id="u",
        character_role=CHARACTER_ROLE_VTUBER,
    )
    state.shared[MUTATION_BUFFER_KEY] = buf
    state.shared[CREATURE_STATE_KEY] = snap
    state.shared[SESSION_META_KEY] = {
        "character_role": CHARACTER_ROLE_VTUBER,
        "turn_kind": turn_kind,
    }
    return state, buf


def _has_path(buf: MutationBuffer, path: str) -> bool:
    return any(m.path == path for m in buf.items)


@pytest.mark.asyncio
async def test_user_turn_grows_affection() -> None:
    state, buf = _state("ok [joy:1]", turn_kind=TURN_KIND_USER)
    await AffectTagEmitter().emit(state)
    assert _has_path(buf, "bond.affection")
    assert _has_path(buf, "mood.joy")


@pytest.mark.asyncio
async def test_trigger_turn_skips_affection() -> None:
    state, buf = _state("quiet [joy:1]", turn_kind=TURN_KIND_TRIGGER)
    await AffectTagEmitter().emit(state)
    # Mood still drifts.
    assert _has_path(buf, "mood.joy")
    # Bond does NOT.
    assert not _has_path(buf, "bond.affection")


@pytest.mark.asyncio
async def test_trigger_turn_skips_trust() -> None:
    """anger taxonomy entry decrements trust on user turns; on trigger
    turns it must skip the trust mutation entirely."""
    state, buf = _state("alone [anger:1]", turn_kind=TURN_KIND_TRIGGER)
    await AffectTagEmitter().emit(state)
    assert _has_path(buf, "mood.anger")
    assert not _has_path(buf, "bond.trust")


@pytest.mark.asyncio
async def test_user_turn_moves_trust_for_anger() -> None:
    state, buf = _state("[anger:1]", turn_kind=TURN_KIND_USER)
    await AffectTagEmitter().emit(state)
    assert _has_path(buf, "bond.trust")


@pytest.mark.asyncio
async def test_missing_meta_defaults_to_user_turn() -> None:
    """Legacy / classic-mode invocations without session_meta should
    behave as USER turns — the historical contract."""
    state = PipelineState()
    state.final_text = "[joy:1]"
    buf = MutationBuffer()
    state.shared[MUTATION_BUFFER_KEY] = buf
    # No SESSION_META_KEY at all.
    await AffectTagEmitter().emit(state)
    assert _has_path(buf, "bond.affection")
    assert _has_path(buf, "mood.joy")


@pytest.mark.asyncio
async def test_meta_without_turn_kind_defaults_to_user() -> None:
    state = PipelineState()
    state.final_text = "[joy:1]"
    buf = MutationBuffer()
    state.shared[MUTATION_BUFFER_KEY] = buf
    state.shared[SESSION_META_KEY] = {"session_id": "x"}
    await AffectTagEmitter().emit(state)
    assert _has_path(buf, "bond.affection")
