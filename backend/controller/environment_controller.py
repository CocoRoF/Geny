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
    UpdateModelConfigRequest,
    UpdatePipelineConfigRequest,
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


def _affected_sessions_summary(env_id: str):
    """D.3 (cycle 20260426_1) — count + name list of *active* sessions
    bound to ``env_id``.

    Each AgentSession holds a frozen runtime snapshot via
    ``Pipeline.attach_runtime`` from the moment ``initialize()`` runs.
    Mutating the manifest on disk has no effect on these — the operator
    must restart them to pick up the new manifest. This helper exposes
    that fact in a single response shape so the FE can surface it
    immediately after a save without an extra round-trip.

    "Active" = soft-deleted records excluded; status irrelevant
    (running / idle / error all hold their snapshot until restart).
    """
    from service.environment.schemas import AffectedSessionsSummary

    try:
        from service.sessions.store import get_session_store

        store = get_session_store()
        records = store.list_active()
    except Exception:  # noqa: BLE001
        # Session store unavailable in some test contexts — surface zero
        # affected so the API still returns a valid response.
        return AffectedSessionsSummary()

    matching = [r for r in records if r.get("env_id") == env_id]
    return AffectedSessionsSummary(
        count=len(matching),
        session_ids=[str(r.get("session_id", "")) for r in matching],
        session_names=[str(r.get("session_name") or r.get("session_id", "")) for r in matching],
    )


async def _propagate_manifest_to_sessions(env_id: str) -> None:
    """Flag every live session bound to ``env_id`` so it rebuilds from the
    just-saved manifest on its next turn (applied between turns, never
    mid-turn). Best-effort — a propagation hiccup must not fail the save.
    """
    try:
        from service.executor import get_agent_session_manager

        await get_agent_session_manager().propagate_env_update(env_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"env propagation skipped for {env_id}: {e}")


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


@router.get("/preset-catalog")
async def get_preset_catalog(auth: dict = Depends(require_auth)):
    """The geny-executor base preset catalog (worker / vtuber + Claude Code
    presets). Geny's own environment templates are built on top of these —
    the library provides the generalised base, Geny customises (tools,
    providers) into the seeded templates the user sees in the list."""
    try:
        from geny_executor import preset_catalog
        catalog = [d.to_dict() for d in preset_catalog()]
    except Exception:  # noqa: BLE001 — older executor without the catalog
        catalog = []
    return {"presets": catalog}


@router.post("/reseed-templates")
async def reseed_templates(request: Request, auth: dict = Depends(require_auth)):
    """Rewrite the built-in template seed environments from the canonical
    manifest, re-resolving the Stage-6 provider from the *current* credential
    bundle.

    Boot already does this once (``install_environment_templates``), but the
    resolved provider is frozen at that moment — a fresh install with no keys
    seeds ``anthropic`` (the last-resort fallback). When the user configures a
    backend *after* boot (e.g. points Geny at a local Ollama in the first-run
    wizard), the seed envs still pin the old provider. This endpoint re-runs
    the seed so they adopt the now-active backend, with no restart.

    Only the three template seeds are rewritten; user-created environments
    are never touched (same guarantee as the boot path).
    """
    svc = _env_svc(request)
    tool_loader = getattr(request.app.state, "tool_loader", None)
    from service.environment.templates import (
        ROUTER_PROVIDER,
        install_environment_templates,
    )

    names = tool_loader.get_all_names() if tool_loader is not None else None
    count = install_environment_templates(
        svc, external_tool_names=names, tool_loader=tool_loader
    )
    return {"reseeded": count, "active_provider": ROUTER_PROVIDER}


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
    from service.sessions.store import get_session_store

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


@router.get("/{env_id}", response_model=EnvironmentDetailResponse)
async def get_environment(
    request: Request, env_id: str, auth: dict = Depends(require_auth)
):
    data = _env_svc(request).load(env_id)
    if data is None:
        raise HTTPException(404, "Environment not found")
    return _detail_response(data)


# ── PR-E.1.3 — Resolved built-in tool list ───────────────


@router.get("/{env_id}/tools/resolved")
async def get_resolved_tools(
    request: Request, env_id: str, auth: dict = Depends(require_auth)
):
    """Return manifest's ``tools.built_in`` enriched with executor metadata.

    The manifest only stores tool *names*. The frontend (Environments
    tab → tool list) needs description / feature_group / capabilities to
    render the same way as the global Tool Catalog. This endpoint is the
    join point — it cross-references each name against the executor's
    BUILT_IN_TOOL_CLASSES registry.

    Response::

        {
          "tools": [FrameworkToolDetail, ...],   # known + resolved
          "unknown": [str, ...],                 # names not in registry
          "total": int                           # tools.length
        }

    Unknown names are surfaced rather than dropped so operators see
    stale manifests caused by tool removals across executor versions.
    """
    data = _env_svc(request).load(env_id)
    if data is None:
        raise HTTPException(404, "Environment not found")

    manifest = data.get("manifest") or {}
    manifest_tools = manifest.get("tools") or {}
    raw_names = list(manifest_tools.get("built_in") or [])

    from controller.tool_controller import build_framework_tool_index

    index = build_framework_tool_index()
    resolved = []
    unknown = []
    for name in raw_names:
        detail = index.get(name)
        if detail is None:
            unknown.append(name)
        else:
            resolved.append(detail.model_dump())

    return {
        "tools": resolved,
        "unknown": unknown,
        "total": len(resolved),
    }


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

    from service.sessions.store import get_session_store

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
