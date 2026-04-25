"""Install :class:`PipelineResumeRequester` into Stage 15 of a built pipeline.

Stage 15 (HITL) carries a ``null`` requester placeholder in the
manifest — the safe always-approve default. To enable real
cross-request HITL we need a :class:`PipelineResumeRequester`
that takes the Pipeline by reference and registers each pending
request on ``pipeline._pending_hitl`` so an external endpoint can
later call :meth:`Pipeline.resume(token, decision)`.

The Pipeline reference is session-scoped (and not manifest-
serialisable), so this swap happens at runtime — same pattern as
``service.persist.install_file_persister``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# geny-executor 1.0+ Sub-phase 9a: HITL landed at order 15.
HITL_STAGE_ORDER: int = 15


def _get_hitl_stage(pipeline: Any) -> Any:
    getter = getattr(pipeline, "get_stage", None)
    if callable(getter):
        return getter(HITL_STAGE_ORDER)
    stages = getattr(pipeline, "_stages", None)
    if isinstance(stages, dict):
        return stages.get(HITL_STAGE_ORDER)
    return None


def install_pipeline_resume_requester(pipeline: Any) -> Optional[Any]:
    """Wire a :class:`PipelineResumeRequester` into Stage 15.

    Returns the requester instance on success, ``None`` when the
    helper was a no-op (no Stage 15, no requester slot, or no
    Pipeline reference). Idempotent — calling twice replaces the
    existing requester with a fresh instance bound to the same
    pipeline.
    """
    if pipeline is None:
        return None

    stage = _get_hitl_stage(pipeline)
    if stage is None:
        logger.debug(
            "install_pipeline_resume_requester: pipeline has no stage at order %d; skipping",
            HITL_STAGE_ORDER,
        )
        return None

    slots = stage.get_strategy_slots() if hasattr(stage, "get_strategy_slots") else None
    if not slots or "requester" not in slots:
        logger.debug(
            "install_pipeline_resume_requester: stage %r has no requester slot; skipping",
            getattr(stage, "name", type(stage).__name__),
        )
        return None

    # Local import keeps this module importable on hosts that haven't
    # yet pinned geny-executor 1.0.
    from geny_executor.stages.s15_hitl import PipelineResumeRequester

    requester = PipelineResumeRequester(pipeline)
    slots["requester"].strategy = requester
    logger.info(
        "install_pipeline_resume_requester: Stage %d wired to PipelineResumeRequester",
        HITL_STAGE_ORDER,
    )
    return requester


__all__ = [
    "HITL_STAGE_ORDER",
    "install_pipeline_resume_requester",
]
