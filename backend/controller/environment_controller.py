"""Environment CRUD API — port of ``geny_executor_web.app.routers.environment``.

Mounts 15 REST endpoints under ``/api/environments`` for managing persisted
pipeline environments (``EnvironmentManifest`` v2 on disk). All request /
response shapes are byte-identical to the web console so a shared frontend
can target either app.

Auth: every endpoint carries ``Depends(require_auth)`` — Geny-wide policy.

from_session adaptation: the web console owns a ``mutation_service`` that
tracks per-session PipelineMutators; Geny does not. Here we resolve the
session via ``AgentSessionManager`` and wrap the live Pipeline with a
fresh ``PipelineMutator`` per call — stateless and cheap.
"""

from __future__ import annotations

from logging import getLogger

from fastapi import APIRouter, Depends, HTTPException, Request

from controller.agent_controller import agent_manager
from service.auth.auth_middleware import require_auth
from service.environment.exceptions import EnvironmentNotFoundError
from service.environment.schemas import (
    CreateEnvironmentRequest,
    CreateEnvironmentResponse,
    DiffBulkRequest,
    DiffBulkResponse,
    DiffBulkResultEntry,
    DiffEntry,
    DiffEnvironmentsRequest,
    DuplicateEnvironmentRequest,
    EnvironmentDetailResponse,
    EnvironmentDiffResponse,
    EnvironmentListResponse,
    EnvironmentSessionCountEntry,
    EnvironmentSessionCountsResponse,
    EnvironmentSessionSummary,
    EnvironmentSessionsResponse,
    EnvironmentSummaryResponse,
    ImportBulkResultEntry,
    ImportEnvironmentRequest,
    ImportEnvironmentsBulkRequest,
    ImportEnvironmentsBulkResponse,
    SaveEnvironmentRequest,
    ShareLinkResponse,
    UpdateEnvironmentRequest,
    UpdateManifestRequest,
    UpdateStageTemplateRequest,
)

logger = getLogger(__name__)

router = APIRouter(prefix="/api/environments", tags=["environments"])


# ── Helpers ──────────────────────────────────────────────


def _env_svc(request: Request):
    svc = getattr(request.app.state, "environment_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail="Environment service not configured",
        )
    return svc


def _detail_response(data: dict) -> EnvironmentDetailResponse:
    return EnvironmentDetailResponse(
        id=data["id"],
        name=data.get("name", ""),
        description=data.get("description", ""),
        tags=data.get("tags", []),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        manifest=data.get("manifest"),
        snapshot=data.get("snapshot"),
    )


def _resolve_session_mutator(session_id: str):
    """Return (agent_session, PipelineMutator) for a live Geny session.

    Raises 404 if the session doesn't exist or hasn't built its pipeline yet.
    The PipelineMutator is created fresh — it's a thin view over the live
    Pipeline, so a per-call wrapper matches the web console's semantics.
    """
    agent = agent_manager.get_agent(session_id)
    if agent is None or agent._pipeline is None:
        raise HTTPException(status_code=404, detail="Session not found")
    from geny_executor import PipelineMutator

    return agent, PipelineMutator(agent._pipeline)


# ── CRUD ─────────────────────────────────────────────────


@router.get("", response_model=EnvironmentListResponse)
async def list_environments(request: Request, auth: dict = Depends(require_auth)):
    envs = _env_svc(request).list_all()
    return EnvironmentListResponse(
        environments=[EnvironmentSummaryResponse(**e) for e in envs]
    )


@router.get("/session-counts", response_model=EnvironmentSessionCountsResponse)
async def list_environment_session_counts(
    request: Request,
    auth: dict = Depends(require_auth),
):
    """Return per-environment session counts in a single pass.

    Designed for the Environments tab card grid so it can render
    authoritative active/deleted/error counts without firing one
    RTT per card. Soft-deleted rows are always included in the
    ``deleted_count`` bucket.
    """
    from service.claude_manager.session_store import get_session_store

    store = get_session_store()
    records = store.list_all()

    buckets: dict[str, dict[str, int]] = {}
    for r in records:
        env_id = r.get("env_id")
        if not env_id:
            continue
        b = buckets.setdefault(
            env_id, {"active": 0, "deleted": 0, "error": 0}
        )
        if r.get("is_deleted"):
            b["deleted"] += 1
        else:
            b["active"] += 1
            if (r.get("status") or "") == "error":
                b["error"] += 1

    entries = [
        EnvironmentSessionCountEntry(
            env_id=eid,
            active_count=b["active"],
            deleted_count=b["deleted"],
            error_count=b["error"],
        )
        for eid, b in buckets.items()
    ]
    return EnvironmentSessionCountsResponse(counts=entries)


@router.post("", response_model=CreateEnvironmentResponse)
async def create_environment(
    request: Request,
    body: CreateEnvironmentRequest,
    auth: dict = Depends(require_auth),
):
    """Create a new environment in one of three modes."""
    svc = _env_svc(request)

    if body.mode == "from_session":
        agent, mutator = _resolve_session_mutator(body.session_id)
        env_id = svc.save(agent, mutator, body.name, body.description, body.tags)
        return CreateEnvironmentResponse(id=env_id)

    if body.mode == "from_preset":
        try:
            env_id = svc.create_from_preset(
                body.preset_name, body.name, body.description, body.tags
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return CreateEnvironmentResponse(id=env_id)

    # mode == "blank"
    try:
        env_id = svc.create_blank(
            body.name, body.description, body.tags, base_preset=body.preset_name
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return CreateEnvironmentResponse(id=env_id)


@router.post("/from-session", response_model=CreateEnvironmentResponse)
async def save_from_session(
    request: Request,
    body: SaveEnvironmentRequest,
    auth: dict = Depends(require_auth),
):
    """Back-compat alias: v0.7.x session-only create payload."""
    agent, mutator = _resolve_session_mutator(body.session_id)
    env_id = _env_svc(request).save(
        agent, mutator, body.name, body.description, body.tags
    )
    return CreateEnvironmentResponse(id=env_id)


@router.get("/{env_id}", response_model=EnvironmentDetailResponse)
async def get_environment(
    request: Request, env_id: str, auth: dict = Depends(require_auth)
):
    data = _env_svc(request).load(env_id)
    if data is None:
        raise HTTPException(404, "Environment not found")
    return _detail_response(data)


@router.put("/{env_id}")
async def update_environment(
    request: Request,
    env_id: str,
    body: UpdateEnvironmentRequest,
    auth: dict = Depends(require_auth),
):
    updated = _env_svc(request).update(env_id, body.model_dump(exclude_none=True))
    if updated is None:
        raise HTTPException(404, "Environment not found")
    return {"updated": True}


@router.put("/{env_id}/manifest", response_model=EnvironmentDetailResponse)
async def replace_manifest(
    request: Request,
    env_id: str,
    body: UpdateManifestRequest,
    auth: dict = Depends(require_auth),
):
    """Overwrite the manifest payload wholesale (template editor save)."""
    from geny_executor import EnvironmentManifest

    try:
        manifest = EnvironmentManifest.from_dict(body.manifest)
    except Exception as exc:  # noqa: BLE001 — surface any parse error as 400
        raise HTTPException(400, f"Invalid manifest: {exc}")
    try:
        record = _env_svc(request).update_manifest(env_id, manifest)
    except EnvironmentNotFoundError:
        raise HTTPException(404, "Environment not found")
    return _detail_response(record)


@router.patch("/{env_id}/stages/{order}", response_model=EnvironmentDetailResponse)
async def patch_stage(
    request: Request,
    env_id: str,
    order: int,
    body: UpdateStageTemplateRequest,
    auth: dict = Depends(require_auth),
):
    """Partial update of one stage entry inside the manifest."""
    try:
        record = _env_svc(request).update_stage(
            env_id, order, **body.model_dump(exclude_none=True)
        )
    except EnvironmentNotFoundError:
        raise HTTPException(404, "Environment not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _detail_response(record)


@router.post("/{env_id}/duplicate", response_model=CreateEnvironmentResponse)
async def duplicate_environment(
    request: Request,
    env_id: str,
    body: DuplicateEnvironmentRequest,
    auth: dict = Depends(require_auth),
):
    new_id = _env_svc(request).duplicate(env_id, body.new_name)
    if new_id is None:
        raise HTTPException(404, "Environment not found")
    return CreateEnvironmentResponse(id=new_id)


@router.delete("/{env_id}")
async def delete_environment(
    request: Request, env_id: str, auth: dict = Depends(require_auth)
):
    deleted = _env_svc(request).delete(env_id)
    if not deleted:
        raise HTTPException(404, "Environment not found")
    return {"deleted": True}


@router.get("/{env_id}/export")
async def export_environment(
    request: Request, env_id: str, auth: dict = Depends(require_auth)
):
    data = _env_svc(request).export_json(env_id)
    if data is None:
        raise HTTPException(404, "Environment not found")
    return {"data": data}


@router.post("/import", response_model=CreateEnvironmentResponse)
async def import_environment(
    request: Request,
    body: ImportEnvironmentRequest,
    auth: dict = Depends(require_auth),
):
    env_id = _env_svc(request).import_json(body.data)
    return CreateEnvironmentResponse(id=env_id)


@router.post("/import-bulk", response_model=ImportEnvironmentsBulkResponse)
async def import_environments_bulk(
    request: Request,
    body: ImportEnvironmentsBulkRequest,
    atomic: bool = False,
    auth: dict = Depends(require_auth),
):
    """Import a bundle produced by the Environments tab bulk-export.

    Default mode: each entry is imported independently — one bad entry
    does not abort the batch. Response enumerates per-entry
    success/failure so the client can render a report.

    `atomic=true`: stop at the first failure and delete every env
    that succeeded in this batch so far, effectively rolling back.
    Response still has shape `ImportEnvironmentsBulkResponse` but
    `succeeded=0` and each rolled-back entry gets `ok=False` with
    an `error` naming the rollback cause. Remaining entries that
    were never attempted are marked `not processed`.
    """
    svc = _env_svc(request)
    results: list[ImportBulkResultEntry] = []
    succeeded_ids: list[tuple[int, str]] = []  # (idx, new_id) for rollback
    fail_cause: str | None = None
    for idx, entry in enumerate(body.entries):
        if fail_cause is not None:
            # atomic mode; short-circuit the rest
            results.append(
                ImportBulkResultEntry(
                    env_id=entry.env_id,
                    ok=False,
                    error="not processed (atomic batch aborted)",
                )
            )
            continue
        try:
            new_id = svc.import_json(entry.data)
        except Exception as exc:  # noqa: BLE001 — surface all errors per-entry
            logger.warning(
                "bulk-import entry %d failed (env_id=%s): %s",
                idx,
                entry.env_id,
                exc,
            )
            results.append(
                ImportBulkResultEntry(
                    env_id=entry.env_id,
                    ok=False,
                    error=str(exc),
                )
            )
            if atomic:
                fail_cause = f"entry {idx}: {exc}"
            continue
        results.append(
            ImportBulkResultEntry(env_id=entry.env_id, new_id=new_id, ok=True)
        )
        succeeded_ids.append((idx, new_id))

    if fail_cause is not None and succeeded_ids:
        # Roll back: delete the envs that succeeded earlier in this batch
        # and rewrite their result entries as rolled-back failures.
        for idx, new_id in succeeded_ids:
            try:
                svc.delete(new_id)
            except Exception as exc:  # noqa: BLE001 — best-effort rollback
                logger.error(
                    "bulk-import rollback failed for new_id=%s: %s", new_id, exc
                )
            results[idx] = ImportBulkResultEntry(
                env_id=results[idx].env_id,
                ok=False,
                error=f"rolled back ({fail_cause})",
            )
        succeeded_ids = []

    succeeded = len(succeeded_ids)
    return ImportEnvironmentsBulkResponse(
        total=len(body.entries),
        succeeded=succeeded,
        failed=len(body.entries) - succeeded,
        results=results,
    )


@router.post("/diff", response_model=EnvironmentDiffResponse)
async def diff_environments(
    request: Request,
    body: DiffEnvironmentsRequest,
    auth: dict = Depends(require_auth),
):
    changes = _env_svc(request).diff(body.env_id_a, body.env_id_b)
    entries = [
        DiffEntry(
            path=c.get("path", c.get("key", "")),
            change_type=c.get("change_type", c.get("type", "changed")),
            old_value=c.get("old_value"),
            new_value=c.get("new_value"),
        )
        for c in changes
    ]
    summary = {"added": 0, "removed": 0, "changed": 0}
    for e in entries:
        summary[e.change_type] = summary.get(e.change_type, 0) + 1
    return EnvironmentDiffResponse(
        identical=len(entries) == 0,
        entries=entries,
        summary=summary,
    )


@router.post("/diff-bulk", response_model=DiffBulkResponse)
async def diff_environments_bulk(
    request: Request,
    body: DiffBulkRequest,
    auth: dict = Depends(require_auth),
):
    svc = _env_svc(request)
    results: list[DiffBulkResultEntry] = []
    ok_count = 0
    for pair in body.pairs:
        try:
            changes = svc.diff(pair.env_id_a, pair.env_id_b)
        except Exception as exc:
            logger.warning(
                "diff-bulk pair failed: %s vs %s: %s",
                pair.env_id_a,
                pair.env_id_b,
                exc,
            )
            results.append(
                DiffBulkResultEntry(
                    env_id_a=pair.env_id_a,
                    env_id_b=pair.env_id_b,
                    ok=False,
                    error=str(exc),
                )
            )
            continue
        summary = {"added": 0, "removed": 0, "changed": 0}
        for c in changes:
            kind = c.get("change_type", c.get("type", "changed"))
            summary[kind] = summary.get(kind, 0) + 1
        results.append(
            DiffBulkResultEntry(
                env_id_a=pair.env_id_a,
                env_id_b=pair.env_id_b,
                ok=True,
                identical=len(changes) == 0,
                summary=summary,
            )
        )
        ok_count += 1
    return DiffBulkResponse(
        total=len(body.pairs),
        ok=ok_count,
        failed=len(body.pairs) - ok_count,
        results=results,
    )


# ── Presets ──────────────────────────────────────────────


@router.post("/{env_id}/preset")
async def mark_as_preset(
    request: Request, env_id: str, auth: dict = Depends(require_auth)
):
    svc = _env_svc(request)
    env = svc.load(env_id)
    if env is None:
        raise HTTPException(404, "Environment not found")
    tags = env.get("tags", [])
    if "preset" not in tags:
        tags.append("preset")
        svc.update(env_id, {"tags": tags})
    return {"marked": True}


@router.delete("/{env_id}/preset")
async def unmark_preset(
    request: Request, env_id: str, auth: dict = Depends(require_auth)
):
    svc = _env_svc(request)
    env = svc.load(env_id)
    if env is None:
        raise HTTPException(404, "Environment not found")
    tags = env.get("tags", [])
    if "preset" in tags:
        tags.remove("preset")
        svc.update(env_id, {"tags": tags})
    return {"unmarked": True}


# ── Share ────────────────────────────────────────────────


@router.get("/{env_id}/share", response_model=ShareLinkResponse)
async def share_environment(
    request: Request, env_id: str, auth: dict = Depends(require_auth)
):
    data = _env_svc(request).export_json(env_id)
    if data is None:
        raise HTTPException(404, "Environment not found")
    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}/api/environments/{env_id}/export"
    return ShareLinkResponse(url=url)


# ── Reverse-lookup: sessions bound to this environment ──


@router.get("/{env_id}/sessions", response_model=EnvironmentSessionsResponse)
async def list_environment_sessions(
    request: Request,
    env_id: str,
    include_deleted: bool = False,
    auth: dict = Depends(require_auth),
):
    """Return every session currently bound to ``env_id``.

    Authoritative reverse-lookup over SessionStore — unlike the client-side
    aggregation over ``useAppStore.sessions`` this can include soft-deleted
    records when ``include_deleted=true``.
    """
    if _env_svc(request).load(env_id) is None:
        raise HTTPException(404, "Environment not found")

    from service.claude_manager.session_store import get_session_store

    store = get_session_store()
    records = store.list_all() if include_deleted else store.list_active()
    matching = [r for r in records if r.get("env_id") == env_id]

    summaries = [
        EnvironmentSessionSummary(
            session_id=r.get("session_id", ""),
            session_name=r.get("session_name"),
            status=r.get("status"),
            role=r.get("role"),
            env_id=r.get("env_id"),
            created_at=r.get("created_at") or r.get("registered_at"),
            is_deleted=bool(r.get("is_deleted", False)),
            deleted_at=r.get("deleted_at"),
            error_message=r.get("error_message"),
        )
        for r in matching
    ]

    active_count = sum(1 for s in summaries if not s.is_deleted)
    deleted_count = sum(1 for s in summaries if s.is_deleted)
    error_count = sum(1 for s in summaries if (s.status or "") == "error")

    return EnvironmentSessionsResponse(
        env_id=env_id,
        sessions=summaries,
        active_count=active_count,
        deleted_count=deleted_count,
        error_count=error_count,
    )
