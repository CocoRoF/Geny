"""Geny-side helpers for the geny-executor 1.0 Stage 15 HITL slot.

Bridges the executor's :class:`PipelineResumeRequester` (S9c.1) into
Geny pipelines so an external decision channel — typically a
WebSocket / HTTP endpoint receiving the user's approve / reject —
can satisfy a paused HITL request via :meth:`Pipeline.resume`.
"""

from service.hitl.install import (
    HITL_STAGE_ORDER,
    install_pipeline_resume_requester,
)

__all__ = ["HITL_STAGE_ORDER", "install_pipeline_resume_requester"]
