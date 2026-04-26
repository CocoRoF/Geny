"""Background task REST endpoints (PR-A.5.4).

Wraps the BackgroundTaskRunner + TaskRegistry surface from
geny-executor 1.1.0 as plain REST under /api/agents/{session_id}/tasks/.

Endpoints:
    POST   /api/agents/{sid}/tasks                 — create + submit
    GET    /api/agents/{sid}/tasks                 — list (status filter)
    GET    /api/agents/{sid}/tasks/{tid}           — fetch one
    DELETE /api/agents/{sid}/tasks/{tid}           — cancel
    GET    /api/agents/{sid}/tasks/{tid}/output    — stream output bytes

The session_id is currently informational — task state is
process-global (per the runner's registry). When the runner is
swapped to a per-session backend, the path can be filtered without
breaking clients.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FPath, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agent-tasks"])


# ── Schemas ──────────────────────────────────────────────────────────


class TaskCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = None


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str


class TaskRecordResponse(BaseModel):
    task_id: str
    kind: str
    status: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    output_path: Optional[str] = None


class TaskListResponse(BaseModel):
    tasks: List[TaskRecordResponse]


# ── Helpers ──────────────────────────────────────────────────────────


def _registry(request: Request):
    reg = getattr(request.app.state, "task_registry", None)
    if reg is None:
        raise HTTPException(503, "task_registry not configured")
    return reg


def _runner(request: Request):
    runner = getattr(request.app.state, "task_runner", None)
    if runner is None:
        raise HTTPException(503, "task_runner not configured")
    return runner


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("/{session_id}/tasks", response_model=TaskCreateResponse)
async def create_task(
    request: Request,
    body: TaskCreateRequest,
    session_id: str = FPath(..., min_length=1),
    _auth: dict = Depends(require_auth),
):
    runner = _runner(request)
    registry = _registry(request)
    from geny_executor.stages.s13_task_registry import TaskRecord

    record = TaskRecord(
        task_id=body.task_id or str(uuid.uuid4()),
        kind=body.kind,
        payload={**body.payload, "_session_id": session_id},
    )
    task_id = await runner.submit(record)
    rec = registry.get(task_id)
    return TaskCreateResponse(
        task_id=task_id,
        status=(rec.status.value if rec else "submitted"),
    )


@router.get("/{session_id}/tasks", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    session_id: str = FPath(..., min_length=1),
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    _auth: dict = Depends(require_auth),
):
    registry = _registry(request)
    from geny_executor.stages.s13_task_registry import TaskFilter, TaskStatus

    parsed_status: Optional[TaskStatus] = None
    if status:
        try:
            parsed_status = TaskStatus(status)
        except ValueError:
            raise HTTPException(400, f"unknown status: {status}")

    rows = registry.list_filtered(
        TaskFilter(status=parsed_status, kind=kind, limit=limit),
    )
    return TaskListResponse(
        tasks=[TaskRecordResponse(**_serialize(r)) for r in rows],
    )


@router.get("/{session_id}/tasks/{task_id}", response_model=TaskRecordResponse)
async def get_task(
    request: Request,
    session_id: str = FPath(..., min_length=1),
    task_id: str = FPath(..., min_length=1),
    _auth: dict = Depends(require_auth),
):
    registry = _registry(request)
    rec = registry.get(task_id)
    if rec is None:
        raise HTTPException(404, "task not found")
    return TaskRecordResponse(**_serialize(rec))


@router.delete("/{session_id}/tasks/{task_id}")
async def stop_task(
    request: Request,
    session_id: str = FPath(..., min_length=1),
    task_id: str = FPath(..., min_length=1),
    _auth: dict = Depends(require_auth),
):
    runner = _runner(request)
    stopped = await runner.stop(task_id)
    if not stopped:
        raise HTTPException(404, "task not found or already terminal")
    return {"task_id": task_id, "stopped": True}


@router.get("/{session_id}/tasks/{task_id}/output")
async def stream_task_output(
    request: Request,
    session_id: str = FPath(..., min_length=1),
    task_id: str = FPath(..., min_length=1),
    _auth: dict = Depends(require_auth),
):
    registry = _registry(request)

    async def gen():
        async for chunk in registry.stream_output(task_id):
            yield chunk

    return StreamingResponse(gen(), media_type="application/octet-stream")


# ── Helpers ──────────────────────────────────────────────────────────


def _serialize(rec) -> Dict[str, Any]:
    return {
        "task_id": rec.task_id,
        "kind": rec.kind,
        "status": rec.status.value,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
        "error": rec.error,
        "payload": dict(rec.payload or {}),
        "output_path": rec.output_path,
    }
