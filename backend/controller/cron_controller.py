"""Cron REST endpoints (PR-A.8.3 + PR-F.4.x).

Endpoints:

    GET    /api/cron/jobs                  list (only_enabled query)
    POST   /api/cron/jobs                  create
    GET    /api/cron/jobs/{name}           fetch one
    PATCH  /api/cron/jobs/{name}/status    enable / disable (PR-F.4.1)
    DELETE /api/cron/jobs/{name}           delete
    POST   /api/cron/jobs/{name}/run-now   adhoc fire
    GET    /api/cron/jobs/{name}/history   recent fires (PR-F.4.4)

PR-F.4.1 also enriches list/get responses with ``next_fire_at``
computed from the cron expression so the UI can show a countdown
without re-implementing croniter on the frontend.
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
    next_fire_at: Optional[str] = Field(
        None,
        description="ISO timestamp of the next scheduled fire (PR-F.4.1).",
    )


class CronStatusPatch(BaseModel):
    """PR-F.4.1 — flip a job between enabled / disabled."""
    status: str  # "enabled" | "disabled"


class CronJobHistoryEntry(BaseModel):
    fired_at: str
    task_id: Optional[str] = None
    status: Optional[str] = None  # ok | error | skipped (depending on runner)
    error: Optional[str] = None


class CronJobHistoryResponse(BaseModel):
    name: str
    fires: List[CronJobHistoryEntry] = Field(default_factory=list)


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


def _next_fire_iso(cron_expr: str, base: Optional[datetime] = None) -> Optional[str]:
    """PR-F.4.1 — compute the next scheduled fire, or None if croniter
    isn't installed or the expression is invalid."""
    try:
        from croniter import croniter  # type: ignore[import-not-found]
    except ImportError:
        return None
    base_dt = base or datetime.now(timezone.utc)
    try:
        nxt = croniter(cron_expr, base_dt).get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        return nxt.isoformat()
    except Exception:
        return None


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
        # job.next_fire_at is set by the runner only after the first
        # tick — until then compute one from the expression so the UI
        # countdown lights up immediately on create.
        "next_fire_at": (
            job.next_fire_at.isoformat() if getattr(job, "next_fire_at", None) else None
        ) or _next_fire_iso(job.cron_expr),
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


@router.patch("/jobs/{name}/status", response_model=CronJobResponse)
async def patch_status(
    request: Request,
    body: CronStatusPatch,
    name: str = FPath(..., min_length=1),
    _auth: dict = Depends(require_auth),
):
    """PR-F.4.1 — flip the job between enabled / disabled.

    Disabled jobs stay in the store but the runner skips them at tick
    time. The status patch is durable so the next process boot still
    sees the disabled state.
    """
    target = body.status.strip().lower()
    if target not in {"enabled", "disabled"}:
        raise HTTPException(400, f"status must be 'enabled' or 'disabled'; got {body.status!r}")
    store = _store(request)
    job = await store.get(name)
    if job is None:
        raise HTTPException(404, f"job {name!r} not found")
    from geny_executor.cron import CronJobStatus

    job.status = CronJobStatus(target)
    await store.put(job)
    await _runner(request).refresh()
    return CronJobResponse(**_serialize(job))


@router.get("/jobs/{name}/history", response_model=CronJobHistoryResponse)
async def get_history(
    request: Request,
    name: str = FPath(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    _auth: dict = Depends(require_auth),
):
    """PR-F.4.4 — recent fire history for one job.

    Reads from the Geny-side cron_history ring; the runner's
    audit_callback is responsible for populating it as fires happen.
    Empty list means either the job hasn't fired yet or the runner
    isn't wired to call ``record_fire`` (older Geny builds).
    """
    store = _store(request)
    if await store.get(name) is None:
        raise HTTPException(404, f"job {name!r} not found")
    from service.telemetry.cron_history import history

    rows = history(name, limit=limit)
    return CronJobHistoryResponse(
        name=name,
        fires=[CronJobHistoryEntry(**r) for r in rows],
    )


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
    # PR-F.4.4 — capture the adhoc fire in the Geny-side history ring
    # too, so the UI shows it alongside scheduled fires.
    try:
        from service.telemetry.cron_history import record_fire

        record_fire(name, task_id=task_id, status="adhoc")
    except Exception:  # noqa: BLE001
        pass
    return {"task_id": task_id, "name": name}
