"""Cron REST endpoints (PR-A.8.3).

Five endpoints mirroring the executor's three cron tools plus an
adhoc trigger:

    GET    /api/cron/jobs               list (only_enabled query)
    POST   /api/cron/jobs               create
    GET    /api/cron/jobs/{name}        fetch one
    DELETE /api/cron/jobs/{name}        delete
    POST   /api/cron/jobs/{name}/run-now adhoc fire (out-of-schedule)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FPath, Query, Request
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cron", tags=["cron"])


class CronJobCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    cron_expr: str
    target_kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None


class CronJobResponse(BaseModel):
    name: str
    cron_expr: str
    target_kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    last_fired_at: Optional[str] = None
    last_task_id: Optional[str] = None


def _store(request: Request):
    store = getattr(request.app.state, "cron_store", None)
    if store is None:
        raise HTTPException(503, "cron_store not configured")
    return store


def _runner(request: Request):
    runner = getattr(request.app.state, "cron_runner", None)
    if runner is None:
        raise HTTPException(503, "cron_runner not configured")
    return runner


def _serialize(job) -> Dict[str, Any]:
    return {
        "name": job.name,
        "cron_expr": job.cron_expr,
        "target_kind": job.target_kind,
        "payload": dict(job.payload or {}),
        "description": job.description,
        "status": job.status.value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "last_fired_at": job.last_fired_at.isoformat() if job.last_fired_at else None,
        "last_task_id": job.last_task_id,
    }


@router.get("/jobs", response_model=List[CronJobResponse])
async def list_cron_jobs(
    request: Request,
    only_enabled: bool = Query(False),
    _auth: dict = Depends(require_auth),
):
    store = _store(request)
    jobs = await store.list(only_enabled=only_enabled)
    return [CronJobResponse(**_serialize(j)) for j in jobs]


@router.post("/jobs", response_model=CronJobResponse)
async def create_cron_job(
    request: Request,
    body: CronJobCreateRequest,
    _auth: dict = Depends(require_auth),
):
    store = _store(request)
    runner = _runner(request)
    try:
        from croniter import croniter, CroniterBadCronError  # type: ignore[import-not-found]
        try:
            croniter(body.cron_expr)
        except (CroniterBadCronError, ValueError, KeyError) as exc:
            raise HTTPException(400, f"invalid cron_expr: {exc}")
    except ImportError:
        pass  # croniter optional; runner will catch bad exprs at fire time

    if await store.get(body.name) is not None:
        raise HTTPException(409, f"job {body.name!r} already exists")

    from geny_executor.cron import CronJob
    job = CronJob(
        name=body.name,
        cron_expr=body.cron_expr,
        target_kind=body.target_kind,
        payload=dict(body.payload),
        description=body.description,
    )
    await store.put(job)
    await runner.refresh()
    return CronJobResponse(**_serialize(job))


@router.get("/jobs/{name}", response_model=CronJobResponse)
async def get_cron_job(
    request: Request,
    name: str = FPath(..., min_length=1),
    _auth: dict = Depends(require_auth),
):
    store = _store(request)
    job = await store.get(name)
    if job is None:
        raise HTTPException(404, f"job {name!r} not found")
    return CronJobResponse(**_serialize(job))


@router.delete("/jobs/{name}")
async def delete_cron_job(
    request: Request,
    name: str = FPath(..., min_length=1),
    _auth: dict = Depends(require_auth),
):
    store = _store(request)
    deleted = await store.delete(name)
    if not deleted:
        raise HTTPException(404, f"job {name!r} not found")
    await _runner(request).refresh()
    return {"deleted": name}


@router.post("/jobs/{name}/run-now")
async def run_now(
    request: Request,
    name: str = FPath(..., min_length=1),
    _auth: dict = Depends(require_auth),
):
    """Adhoc fire — out of schedule. Useful for testing a job's
    target_kind + payload before letting cron pick it up naturally."""
    store = _store(request)
    job = await store.get(name)
    if job is None:
        raise HTTPException(404, f"job {name!r} not found")
    task_runner = getattr(request.app.state, "task_runner", None)
    if task_runner is None:
        raise HTTPException(503, "task_runner not configured")
    from geny_executor.stages.s13_task_registry import TaskRecord
    record = TaskRecord(
        task_id=str(uuid.uuid4()),
        kind=job.target_kind,
        payload={
            **dict(job.payload or {}),
            "_cron_name": job.name,
            "_scheduled_for": datetime.now(timezone.utc).isoformat(),
            "_adhoc": True,
        },
    )
    task_id = await task_runner.submit(record)
    return {"task_id": task_id, "name": name}
