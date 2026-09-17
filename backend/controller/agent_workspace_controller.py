"""The agent's workspace: where it is, and what it did there.

Running an agent on a server is the same bargain as installing Claude Code on
one and giving it jobs — nobody is watching it work, so the record has to be
exact. These endpoints are that record.

  GET  /api/agents/{sid}/workspace           where the agent is working now
  POST /api/agents/{sid}/workspace/cleanup   pop back to the root frame
  GET  /api/agents/{sid}/workspace/activity  what it did, in order
  GET  /api/agents/{sid}/workspace/summary   what changed while you were away

The first two read the executor's ``WorkspaceStack`` (seeded into
``ToolContext.extras``; EnterWorktree/ExitWorktree push and pop it), so they
answer only for a live session. The last two are derived from the session log,
which outlives the session — so the history of a finished, restarted or
deleted agent is still readable.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from controller.agent_controller import agent_manager
from service.auth.auth_middleware import require_auth
from service.workspace_activity import ACTIVITY_KINDS, build_activity, summarize_activity

logger = getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ── Schemas ──────────────────────────────────────────────


class WorkspaceFrame(BaseModel):
    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    lsp_session_id: Optional[str] = None
    env_vars: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceResponse(BaseModel):
    available: bool = Field(
        False,
        description="False when executor < 1.3.0 or pipeline not built yet.",
    )
    depth: int = 0
    current: Optional[WorkspaceFrame] = None
    stack: List[WorkspaceFrame] = Field(default_factory=list)


class CleanupResponse(BaseModel):
    available: bool
    popped: int = 0
    final_depth: int = 0


# ── Helpers ──────────────────────────────────────────────


def _get_workspace_stack(session_id: str):
    """Resolve the per-session WorkspaceStack from the agent's pipeline.

    Returns None when:
      - the session doesn't exist (caller raises 404),
      - the pipeline hasn't been built yet,
      - executor < 1.3.0 (no workspace_stack ever seeded),
      - the Tool stage isn't present (custom manifest).
    """
    agent = agent_manager.get_agent(session_id)
    if agent is None:
        raise HTTPException(404, f"Session not found: {session_id}")
    pipeline = getattr(agent, "_pipeline", None)
    if pipeline is None:
        return None

    # Tool stage is order 10 in the canonical layout.
    stage = None
    getter = getattr(pipeline, "get_stage", None)
    if callable(getter):
        try:
            stage = getter(10)
        except Exception:
            stage = None
    if stage is None:
        return None

    ctx = getattr(stage, "_context", None)
    if ctx is None:
        return None
    extras = getattr(ctx, "extras", None) or {}
    return extras.get("workspace_stack")


def _frame_from_workspace(ws: Any) -> WorkspaceFrame:
    return WorkspaceFrame(
        cwd=str(getattr(ws, "cwd", "")) if getattr(ws, "cwd", None) else None,
        git_branch=getattr(ws, "git_branch", None),
        lsp_session_id=getattr(ws, "lsp_session_id", None),
        env_vars=dict(getattr(ws, "env_vars", {}) or {}),
        metadata=dict(getattr(ws, "metadata", {}) or {}),
    )


# ── Endpoints ────────────────────────────────────────────


@router.get("/{session_id}/workspace", response_model=WorkspaceResponse)
async def get_workspace(
    session_id: str = Path(..., description="Session ID"),
    _auth: dict = Depends(require_auth),
):
    """Return the per-session WorkspaceStack snapshot."""
    stack = _get_workspace_stack(session_id)
    if stack is None:
        return WorkspaceResponse(available=False)

    snapshot_method = getattr(stack, "snapshot", None)
    items = list(snapshot_method()) if callable(snapshot_method) else []
    current = stack.current() if hasattr(stack, "current") else None
    depth = stack.depth() if hasattr(stack, "depth") else len(items)

    return WorkspaceResponse(
        available=True,
        depth=depth,
        current=_frame_from_workspace(current) if current else None,
        stack=[_frame_from_workspace(ws) for ws in items],
    )


@router.post("/{session_id}/workspace/cleanup", response_model=CleanupResponse)
async def cleanup_workspace(
    session_id: str = Path(..., description="Session ID"),
    _auth: dict = Depends(require_auth),
):
    """Pop every workspace frame above the root.

    Useful when EnterWorktreeTool ran but ExitWorktreeTool was never
    called (e.g. session crashed mid-task). The root frame (initial
    cwd) is preserved.
    """
    stack = _get_workspace_stack(session_id)
    if stack is None:
        return CleanupResponse(available=False)

    popped = 0
    while True:
        depth = stack.depth() if hasattr(stack, "depth") else 0
        if depth <= 1:
            break
        try:
            stack.pop()
            popped += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "workspace cleanup: pop failed at depth %d for %s: %s",
                depth, session_id, exc,
            )
            break

    final_depth = stack.depth() if hasattr(stack, "depth") else 0
    return CleanupResponse(available=True, popped=popped, final_depth=final_depth)


# ── What the agent did ───────────────────────────────────


@router.get("/{session_id}/workspace/activity")
async def get_workspace_activity(
    session_id: str = Path(..., description="Session ID"),
    limit: int = Query(200, ge=1, le=2000, description="Entries to return."),
    scan: int = Query(2000, ge=1, le=20000, description="Log entries to read while building."),
    kind: Optional[str] = Query(
        None,
        description=(
            "Comma-separated filter: " + " | ".join(ACTIVITY_KINDS) + ". "
            "Omitted → everything."
        ),
    ),
    oldest_first: bool = Query(False, description="Return in the order it happened."),
    _auth: dict = Depends(require_auth),
) -> Dict[str, Any]:
    """Every workspace action, newest first — each file written, each command
    run with its exit status and output, each failure, each turn boundary.

    Derived from the durable session log rather than written separately, so
    it cannot disagree with the log and it survives the session.
    """
    kinds: Optional[List[str]] = None
    if kind:
        kinds = [k.strip() for k in kind.split(",") if k.strip()]
        unknown = [k for k in kinds if k not in ACTIVITY_KINDS]
        if unknown:
            raise HTTPException(
                400, f"Unknown activity kind(s): {', '.join(unknown)}. "
                     f"Expected: {', '.join(ACTIVITY_KINDS)}"
            )
    return build_activity(
        session_id, limit=limit, scan=scan, kinds=kinds, newest_first=not oldest_first
    )


@router.get("/{session_id}/workspace/summary")
async def get_workspace_summary(
    session_id: str = Path(..., description="Session ID"),
    scan: int = Query(5000, ge=1, le=20000, description="Log entries to read while building."),
    _auth: dict = Depends(require_auth),
) -> Dict[str, Any]:
    """What changed while you were not looking: the files the agent touched
    (with line counts), the commands it ran, and everything that failed."""
    return summarize_activity(session_id, scan=scan)
