"""Plan/Phase04 — AffectTagEmitter must skip mutations for non-VTubers.

The emitter is shared across all pipelines (VTuber + Worker), so the
guard inside ``emit()`` is the chokepoint that protects worker turns
from accidentally accruing mood / bond mutations on a CreatureState
they were never supposed to own.
"""

from __future__ import annotations

import pytest
from geny_executor.core.state import PipelineState

from service.emit.affect_tag_emitter import AffectTagEmitter
from service.state import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    SESSION_META_KEY,
    MutationBuffer,
)
from service.state.schema.creature_state import (
    CHARACTER_ROLE_OTHER,
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
    CreatureState,
)


def _state_with_role(text: str, role: str) -> tuple[PipelineState, MutationBuffer, CreatureState]:
    state = PipelineState()
    state.final_text = text
    buf = MutationBuffer()
    snap = CreatureState(character_id="c", owner_user_id="u", character_role=role)
    state.shared[MUTATION_BUFFER_KEY] = buf
    state.shared[CREATURE_STATE_KEY] = snap
    state.shared[SESSION_META_KEY] = {"character_role": role}
    return state, buf, snap


@pytest.mark.asyncio
async def test_worker_turn_strips_tags_but_emits_no_mutations() -> None:
    state, buf, _ = _state_with_role("hello [joy:2] world", CHARACTER_ROLE_WORKER)
    result = await AffectTagEmitter().emit(state)

    # Tags are still removed from the visible text.
    assert "[joy" not in (state.final_text or "")
    # No mutations recorded.
    assert len(buf.items) == 0
    # Telemetry flag for the suppression branch.
    assert result.emitted is False
    assert result.metadata["reason"] == "non_vtuber_role"
    assert result.metadata["applied"] == 0
    assert result.metadata["stripped"] is True


@pytest.mark.asyncio
async def test_other_role_also_suppressed() -> None:
    state, buf, _ = _state_with_role("[anger:1]", CHARACTER_ROLE_OTHER)
    result = await AffectTagEmitter().emit(state)
    assert len(buf.items) == 0
    assert result.metadata["reason"] == "non_vtuber_role"


@pytest.mark.asyncio
async def test_vtuber_turn_still_mutates() -> None:
    state, buf, _ = _state_with_role("[joy:1]", CHARACTER_ROLE_VTUBER)
    result = await AffectTagEmitter().emit(state)
    assert result.emitted is True
    assert len(buf.items) > 0


@pytest.mark.asyncio
async def test_no_snapshot_falls_back_to_legacy_mutate_path() -> None:
    """When CREATURE_STATE_KEY is absent, treat as legacy / VTuber-only
    pipelines that hydrated the buffer without surfacing the snapshot
    in shared. The mutate path must still fire so existing behaviour
    is preserved."""
    state = PipelineState()
    state.final_text = "[joy:1]"
    buf = MutationBuffer()
    state.shared[MUTATION_BUFFER_KEY] = buf
    # No CREATURE_STATE_KEY, no SESSION_META_KEY.
    result = await AffectTagEmitter().emit(state)
    assert result.emitted is True
    assert len(buf.items) > 0


@pytest.mark.asyncio
async def test_session_meta_role_alone_can_suppress() -> None:
    """Even if no snapshot is in shared, an explicit non-VTuber
    session_meta still flips the guard. Wait — defense uses
    ``snap is not None and not role_is_vtuber``, so this path
    actually mutates. Pin that contract: meta alone does not
    suppress; the snapshot must exist for the guard to fire."""
    state = PipelineState()
    state.final_text = "[joy:1]"
    buf = MutationBuffer()
    state.shared[MUTATION_BUFFER_KEY] = buf
    state.shared[SESSION_META_KEY] = {"character_role": CHARACTER_ROLE_WORKER}
    # No snapshot — no suppression. Mutations land.
    result = await AffectTagEmitter().emit(state)
    assert result.emitted is True
    assert len(buf.items) > 0
