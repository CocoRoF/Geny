"""Unit tests for service.persist.install_file_persister (G2.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from service.persist.install import (
    CHECKPOINT_SUBDIR,
    PERSIST_STAGE_ORDER,
    install_file_persister,
)


# ── stubs ─────────────────────────────────────────────────────────────


class _SlotLike:
    def __init__(self, strategy: Any) -> None:
        self.strategy = strategy


class _FakePersistStage:
    name: str = "persist"

    def __init__(self) -> None:
        # Mirror the executor's slot dict shape — only the persister
        # slot is exercised here.
        self._slots: Dict[str, _SlotLike] = {
            "persister": _SlotLike(strategy=object()),  # placeholder
            "frequency": _SlotLike(strategy=object()),
        }

    def get_strategy_slots(self) -> Dict[str, _SlotLike]:
        return self._slots


class _StageWithoutSlots:
    """Stage missing the get_strategy_slots / persister surface."""

    name: str = "persist"


class _FakePipeline:
    def __init__(self, stage: Any | None) -> None:
        self._stages = {PERSIST_STAGE_ORDER: stage} if stage is not None else {}

    def get_stage(self, order: int):
        return self._stages.get(order)


# ── no-op paths ──────────────────────────────────────────────────────


def test_no_storage_path_is_no_op() -> None:
    pipe = _FakePipeline(_FakePersistStage())
    assert install_file_persister(pipe, storage_path=None) is None
    assert install_file_persister(pipe, storage_path="") is None


def test_missing_stage_is_no_op(tmp_path) -> None:
    pipe = _FakePipeline(stage=None)
    assert install_file_persister(pipe, tmp_path) is None


def test_stage_without_slots_is_no_op(tmp_path) -> None:
    pipe = _FakePipeline(_StageWithoutSlots())
    assert install_file_persister(pipe, tmp_path) is None


def test_stage_without_persister_slot_is_no_op(tmp_path) -> None:
    stage = _FakePersistStage()
    stage._slots.pop("persister", None)
    pipe = _FakePipeline(stage)
    assert install_file_persister(pipe, tmp_path) is None


# ── happy paths ──────────────────────────────────────────────────────


def test_swaps_persister_to_file_persister(tmp_path) -> None:
    from geny_executor.stages.s20_persist import FilePersister

    stage = _FakePersistStage()
    pipe = _FakePipeline(stage)
    persister = install_file_persister(pipe, tmp_path)
    assert persister is not None
    assert isinstance(persister, FilePersister)
    # Swapped in place — the slot now points at the new instance.
    assert stage._slots["persister"].strategy is persister


def test_persister_rooted_at_storage_path_subdir(tmp_path) -> None:
    persister = install_file_persister(_FakePipeline(_FakePersistStage()), tmp_path)
    assert persister is not None
    assert persister.base_dir == tmp_path / CHECKPOINT_SUBDIR


def test_idempotent_reseats_persister(tmp_path) -> None:
    stage = _FakePersistStage()
    pipe = _FakePipeline(stage)
    first = install_file_persister(pipe, tmp_path)
    second = install_file_persister(pipe, tmp_path)
    assert first is not None and second is not None
    assert first is not second  # fresh instance
    assert stage._slots["persister"].strategy is second  # last call wins


def test_storage_path_accepts_str_and_path(tmp_path) -> None:
    stage = _FakePersistStage()
    pipe = _FakePipeline(stage)
    p1 = install_file_persister(pipe, str(tmp_path))
    p2 = install_file_persister(pipe, tmp_path)
    assert p1 is not None and p2 is not None
    assert p1.base_dir == tmp_path / CHECKPOINT_SUBDIR


# ── round-trip with executor PersistStage ────────────────────────────


def test_round_trip_with_real_persist_stage_writes_checkpoint(tmp_path) -> None:
    """End-to-end: install the FilePersister into a real PersistStage,
    execute it once, confirm a checkpoint file lands in the expected
    directory."""
    import asyncio

    from geny_executor.core.state import PipelineState, TokenUsage
    from geny_executor.stages.s20_persist import (
        EveryTurnFrequency,
        PersistStage,
    )

    stage = PersistStage(frequency=EveryTurnFrequency())
    # The PersistStage starts with NoPersister; install_file_persister
    # swaps it.
    pipe = _FakePipeline(stage)
    persister = install_file_persister(pipe, tmp_path)
    assert persister is not None

    state = PipelineState(session_id="sess-rt")
    state.iteration = 0
    state.token_usage = TokenUsage(input_tokens=1, output_tokens=1)

    async def _run():
        await stage.execute(input=None, state=state)

    asyncio.run(_run())

    # File landed under tmp_path/checkpoints/sess-rt/.
    session_dir = tmp_path / CHECKPOINT_SUBDIR / "sess-rt"
    files = list(session_dir.glob("*.json"))
    assert len(files) == 1, f"expected 1 checkpoint, got {len(files)} in {session_dir}"
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["session_id"] == "sess-rt"
    assert payload["iteration"] == 0
    assert "payload" in payload and "messages" in payload["payload"]
