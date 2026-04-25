"""Unit tests for service.hitl.install_pipeline_resume_requester (G2.5)."""

from __future__ import annotations

from typing import Any, Dict

from service.hitl.install import (
    HITL_STAGE_ORDER,
    install_pipeline_resume_requester,
)


# ── stubs ─────────────────────────────────────────────────────────────


class _SlotLike:
    def __init__(self, strategy: Any) -> None:
        self.strategy = strategy


class _FakeHITLStage:
    name: str = "hitl"

    def __init__(self) -> None:
        self._slots: Dict[str, _SlotLike] = {
            "requester": _SlotLike(strategy=object()),
            "timeout": _SlotLike(strategy=object()),
        }

    def get_strategy_slots(self) -> Dict[str, _SlotLike]:
        return self._slots


class _StageWithoutSlots:
    name: str = "hitl"


class _FakePipeline:
    """Stand-in carrying the surface PipelineResumeRequester needs.

    The real :class:`Pipeline` provides ``_pending_hitl: Dict``;
    the requester writes to it. We don't actually exercise the
    requester here, just check that the install swaps the slot.
    """

    def __init__(self, stage: Any | None) -> None:
        self._stages = {HITL_STAGE_ORDER: stage} if stage is not None else {}
        self._pending_hitl: Dict[str, Any] = {}

    def get_stage(self, order: int):
        return self._stages.get(order)


# ── no-op paths ──────────────────────────────────────────────────────


def test_none_pipeline_is_no_op() -> None:
    assert install_pipeline_resume_requester(None) is None


def test_missing_stage_is_no_op() -> None:
    pipe = _FakePipeline(stage=None)
    assert install_pipeline_resume_requester(pipe) is None


def test_stage_without_slots_is_no_op() -> None:
    pipe = _FakePipeline(_StageWithoutSlots())
    assert install_pipeline_resume_requester(pipe) is None


def test_stage_without_requester_slot_is_no_op() -> None:
    stage = _FakeHITLStage()
    stage._slots.pop("requester", None)
    pipe = _FakePipeline(stage)
    assert install_pipeline_resume_requester(pipe) is None


# ── happy paths ──────────────────────────────────────────────────────


def test_swaps_requester_to_pipeline_resume_requester() -> None:
    from geny_executor.stages.s15_hitl import PipelineResumeRequester

    stage = _FakeHITLStage()
    pipe = _FakePipeline(stage)
    requester = install_pipeline_resume_requester(pipe)
    assert requester is not None
    assert isinstance(requester, PipelineResumeRequester)
    assert stage._slots["requester"].strategy is requester


def test_idempotent_reseats_requester() -> None:
    stage = _FakeHITLStage()
    pipe = _FakePipeline(stage)
    first = install_pipeline_resume_requester(pipe)
    second = install_pipeline_resume_requester(pipe)
    assert first is not None and second is not None
    assert first is not second  # fresh instance each call
    assert stage._slots["requester"].strategy is second
