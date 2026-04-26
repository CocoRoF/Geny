"""Agent workspace inspection + cleanup endpoints (PR-E.4.3).

Exposes the executor 1.3.0 WorkspaceStack that AgentSession seeds into
ToolContext.extras. EnterWorktreeTool / ExitWorktreeTool push and pop
on this stack; LSPTool reads workspace.cwd through it.

Endpoints:
  GET  /api/agents/{sid}/workspace          — snapshot of the stack
  POST /api/agents/{sid}/workspace/cleanup  — pop everything back to root

These are deliberately scoped to the per-agent stack rather than the
process-wide telemetry rings (PR-E.4.1/4.2) — workspace state is
session-local.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from controller.agent_controller import agent_manager
from service.auth.auth_middleware import require_auth

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
