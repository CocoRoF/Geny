"""
Agent Session Controller

REST API endpoints for AgentSession (geny-executor Pipeline) management.

AgentSession API: /api/agents
"""
import asyncio
import json
from urllib.parse import unquote
import time
from logging import getLogger
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Body, Depends, File, HTTPException, Path, Query, Request, UploadFile
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth
from service.cloud import owning_storage as _cloud_owning_storage
from service.utils.async_fs import rmtree_async

from service.sessions.models import (
    CreateSessionRequest,
    SessionInfo,
    SessionRole,
    ExecuteRequest,
    ExecuteResponse,
    StorageFile,
    StorageListResponse,
    StorageFileContent,
)
from service.executor import (
    get_agent_session_manager,
    AgentSession,
)
from service.lifecycle import LifecycleEvent
from service.logging.session_logger import get_session_logger
from service.sessions.store import get_session_store
from service.execution.agent_executor import (
    execute_command,
    start_command_background,
    get_execution_holder,
    cleanup_execution,
    AgentNotFoundError,
    AgentNotAliveError,
    AlreadyExecutingError,
)

logger = getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/agents", tags=["agents"])

# AgentSessionManager singleton
agent_manager = get_agent_session_manager()


def _enforce_scope_owner(scope_id: str, auth: dict) -> None:
    """Ownership for a storage scope. A cloud is the caller's by
    construction; a session is checked the usual way."""
    from service.cloud import is_cloud_scope

    if is_cloud_scope(scope_id):
        return
    _enforce_session_owner(scope_id, auth)


def _enforce_session_owner(session_id: str, auth: dict) -> None:
    """Ownership guard for /api/agents/{session_id}/* (audit S6).

    Resolves the session's owner cheaply from the store record (which now
    persists ``owner_username``), falling back to a live in-memory agent,
    then delegates to ``verify_session_ownership`` (403 on mismatch,
    fail-open on unknown owner, admin bypass). Single-admin deployments
    are unaffected — the owner always matches the caller.
    """
    from service.auth.auth_middleware import verify_session_ownership

    owner = None
    try:
        rec = get_session_store().get(session_id)
        if isinstance(rec, dict):
            owner = rec.get("owner_username")
    except Exception:  # noqa: BLE001 — never fail the request on lookup error
        owner = None
    if owner is None:
        try:
            live = agent_manager.get_agent(session_id)
        except Exception:  # noqa: BLE001
            live = None
        if live is not None:
            owner = getattr(live, "owner_username", None)
    verify_session_ownership(auth, owner)


# ============================================================================
# Request/Response Models
# ============================================================================


class CreateAgentRequest(CreateSessionRequest):
    """
    Request to create an AgentSession.

    Inherits from CreateSessionRequest and provides additional options.
    """
    enable_checkpointing: bool = Field(
        default=False,
        description="Enable state checkpointing for replay/resume"
    )
    env_id: Optional[str] = Field(
        default=None,
        description=(
            "EnvironmentManifest id — when set, the pipeline is built from "
            "the stored manifest instead of the GenyPresets path."
        ),
    )
    memory_config: Optional[dict] = Field(
        default=None,
        description=(
            "Per-session memory tuning overrides. May include a ``tuning`` "
            "sub-object with ``max_inject_chars`` / ``recent_turns`` / "
            "``enable_vector_search`` / ``enable_reflection`` to override "
            "the settings.json:memory.tuning defaults for this session only."
        ),
    )
    trigger_preset_id: Optional[str] = Field(
        default=None,
        description=(
            "Trigger preset id — VTuber sessions only. When set, the "
            "thinking-trigger runtime reads timing / phases / categories "
            "from the named preset; ``None`` keeps the bundled defaults. "
            "The frontend manages presets via the '트리거 관리' tab."
        ),
    )


class AgentInvokeRequest(BaseModel):
    """
    Request to invoke an AgentSession.

    Executes the session's `geny-executor` Pipeline.
    """
    input_text: str = Field(
        ...,
        description="Input text for the agent"
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="Thread ID for checkpointing (optional)"
    )
    max_iterations: Optional[int] = Field(
        default=None,
        description="Maximum graph iterations"
    )


class AgentInvokeResponse(BaseModel):
    """
    Response from an AgentSession invoke.
    """
    success: bool
    session_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    thread_id: Optional[str] = None


class AgentStateResponse(BaseModel):
    """
    Response for an AgentSession state query.
    """
    session_id: str
    current_step: Optional[str] = None
    last_output: Optional[str] = None
    iteration: Optional[int] = None
    error: Optional[str] = None
    is_complete: bool = False


# ============================================================================
# Agent Session Management API
# ============================================================================


@router.post("", response_model=SessionInfo)
async def create_agent_session(request: CreateAgentRequest, auth: dict = Depends(require_auth)):
    """
    Create a new AgentSession.

    AgentSession wraps a `geny-executor` Pipeline and manages its
    lifecycle (tool attach, memory integration, idle monitoring).
    """
    try:
        owner_username = auth.get("sub", "anonymous")
        agent = await agent_manager.create_agent_session(
            request=request,
            enable_checkpointing=request.enable_checkpointing,
            owner_username=owner_username,
            env_id=request.env_id,
            memory_config=request.memory_config,
            trigger_preset_id=request.trigger_preset_id,
        )

        session_info = agent.get_session_info()
        logger.info(f"✅ AgentSession created: {agent.session_id}")
        return session_info

    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LookupError as e:
        # EnvironmentNotFoundError when env_id references a missing manifest.
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Failed to create AgentSession: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _enrich_env_fields(data: dict) -> None:
    """Resolve model / provider / env name from the ENVIRONMENT manifest for
    store-backed (dormant) records — mirrors AgentSession.get_info: the
    manifest is what actually runs, so a stored legacy claude-* model must
    not shadow a non-Anthropic environment."""
    env_id = data.get("env_id")
    if not env_id:
        return
    try:
        from service.environment import get_environment_service

        svc = get_environment_service()
        manifest = svc.load_manifest(env_id) if svc else None
        if manifest is None:
            return
        if not data.get("env_name"):
            data["env_name"] = (manifest.metadata.name or "").strip() or None
        env_model = ((manifest.model or {}).get("model") or "").strip() or None
        for entry in manifest.stage_entries():
            if entry.order != 6 or entry.name != "api":
                continue
            if entry.active:
                data["model_provider"] = str(
                    (entry.config or {}).get("provider")
                    or (entry.strategies or {}).get("provider")
                    or ""
                ).strip() or None
                # Stage-6 커스텀 model override beats the pipeline-wide model
                # at runtime — mirror that priority in the display.
                override_model = (
                    (entry.model_override or {}).get("model") or ""
                ).strip() or None
                if override_model:
                    env_model = override_model
            break
        if env_model:
            data["model"] = env_model
    except Exception:  # noqa: BLE001 — enrichment must never break listing
        logger.debug("dormant env enrichment failed", exc_info=True)


def _dormant_session_info(rec: dict) -> Optional[SessionInfo]:
    """Build a ``SessionInfo`` for a session that exists in the persistent
    store but is not currently live in memory (dormant after a restart).

    Records are serialized ``SessionInfo`` dumps (+ store bookkeeping keys),
    so we filter to known fields and validate. Status is normalized to
    ``stopped`` (restorable) except ``error`` is preserved so failed sessions
    still surface in the UI's error count.
    """
    try:
        fields = set(SessionInfo.model_fields.keys())
        data = {k: v for k, v in rec.items() if k in fields}
        if not data.get("session_id"):
            return None
        stored = str(rec.get("status") or "stopped")
        data["status"] = "error" if stored == "error" else "stopped"
        _enrich_env_fields(data)
        return SessionInfo.model_validate(data)
    except Exception as e:  # noqa: BLE001 — never let one bad record break the list
        logger.debug(f"Skipping dormant session record: {e}")
        return None


@router.get("", response_model=List[SessionInfo])
async def list_agent_sessions(auth: dict = Depends(require_auth)):
    """
    List all sessions — live (in memory) + dormant (persisted, awaiting
    lazy re-hydration after a restart).

    Lazy restore (session-persistence): the live registry starts empty on
    every boot, so the list is the UNION of in-memory ``AgentSession``s and
    non-deleted store records that aren't live yet. Dormant sessions render
    with ``status="stopped"`` and re-hydrate on first access (open / message
    / ``POST /{id}/resume``). This is what makes sessions survive a redeploy,
    restart, or crash.

    Auth (R7 / audit 20260425_3 §1.5): the listing exposes session
    names + roles + statuses, which is operator-relevant metadata.
    """
    agents = agent_manager.list_agents()
    live = {a.session_id: a.get_session_info() for a in agents}

    merged: List[SessionInfo] = list(live.values())
    try:
        store = get_session_store()
        for rec in store.list_active():
            sid = rec.get("session_id")
            if not sid or sid in live:
                continue
            info = _dormant_session_info(rec)
            if info is not None:
                merged.append(info)
    except Exception as e:  # noqa: BLE001 — degrade to live-only on store failure
        logger.warning(f"Could not merge dormant sessions into list: {e}")

    return merged


# ============================================================================
# Session Store API (MUST be before /{session_id} to avoid path capture)
# ============================================================================


@router.get("/store/deleted", response_model=List[dict])
async def list_deleted_sessions(auth: dict = Depends(require_auth)):
    """
    List all soft-deleted sessions from the persistent store.

    Auth (R7): same rationale as ``list_agent_sessions``.
    """
    store = get_session_store()
    return store.list_deleted()


@router.get("/store/all", response_model=List[dict])
async def list_all_stored_sessions(auth: dict = Depends(require_auth)):
    """
    List ALL sessions from the persistent store (active + deleted).

    Auth (R7): same rationale as ``list_agent_sessions``.
    """
    store = get_session_store()
    return store.list_all()


@router.delete("/store/deleted")
async def purge_deleted_sessions(auth: dict = Depends(require_auth)):
    """
    Permanently delete ALL soft-deleted sessions — empties the trash.

    Irreversible: each record is removed from the store (DB + JSON) and its
    on-disk storage directory (memory, transcripts, checkpoints) is deleted.
    Powers the "전체 삭제 / Delete all" button in the deleted-sessions list.
    Live (non-deleted) sessions are never touched.
    """
    import shutil
    from pathlib import Path as FilePath

    store = get_session_store()
    deleted_records = store.list_deleted()

    purged = 0
    errors = 0
    for rec in deleted_records:
        sid = rec.get("session_id")
        if not sid:
            continue
        try:
            storage_path = rec.get("storage_path")
            if storage_path:
                sp = FilePath(storage_path)
                if sp.is_dir():
                    try:
                        # Off-loop: a session tree is thousands of files, and
                        # deleting it inline stalls the whole process.
                        await rmtree_async(sp)
                    except Exception as e:  # noqa: BLE001 — best effort
                        logger.warning(f"Failed to cleanup storage {storage_path}: {e}")
            # The agent itself, not just its row. `/api/agents` lists what the
            # MANAGER holds, so an agent left in memory keeps appearing in the
            # app — a session you can click, with no record behind it, which
            # then resolves a brand new chat room. Tear it down first, while
            # the record still exists to tear down against.
            try:
                if agent_manager.has_agent(sid):
                    await agent_manager.delete_session(sid, cleanup_storage=False)
            except Exception as e:  # noqa: BLE001 — the record still goes
                logger.warning(f"Failed to unload agent {sid} during purge: {e}")

            if store.permanent_delete(sid):
                purged += 1
        except Exception as e:  # noqa: BLE001 — never let one bad record abort the purge
            errors += 1
            logger.warning(f"Failed to purge deleted session {sid}: {e}")

    logger.info(f"🗑️ Purged {purged} soft-deleted sessions ({errors} errors)")
    return {"success": True, "purged": purged, "errors": errors}


@router.get("/store/{session_id}")
async def get_stored_session_info(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """
    Get detailed metadata for any session (active or deleted) from the store.
    """
    store = get_session_store()
    record = store.get(session_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found in store")

    # Resolve effective model name if not stored
    if not record.get("model"):
        import os
        effective_model = os.environ.get('ANTHROPIC_MODEL')
        if not effective_model:
            try:
                from service.config.manager import get_config_manager
                from service.config.sub_config.general.api_config import APIConfig
                api_cfg = get_config_manager().load_config(APIConfig)
                effective_model = api_cfg.anthropic_model or None
            except Exception:
                pass
        if effective_model:
            record["model"] = effective_model

    return record


# ============================================================================
# Session CRUD (with /{session_id} path parameter)
# ============================================================================


@router.get("/storage/summary")
async def storage_summary(auth: dict = Depends(require_auth)):
    """Per-agent workspace usage for every session the caller owns.

    The Drive UI shows a usage bar per connected agent; without this it
    would issue one /storage/changes per agent just to read used_bytes.
    Sizes come from the sync index (cheap SQL, computed off-loop); sessions
    with no index yet report null — a GET must neither create index files
    in untouched sessions nor claim "0 B" for workspaces it never scanned.
    """
    from service.utils import workspace_sync

    out: List[Dict[str, Any]] = []
    quota = workspace_sync.quota_bytes()
    try:
        records = get_session_store().list_all() or []
    except Exception:  # noqa: BLE001
        records = []
    seen: set = set()
    for rec in records:
        sid = str(rec.get("session_id") or "")
        if not sid or sid in seen or rec.get("is_deleted"):
            continue
        seen.add(sid)
        try:
            _enforce_session_owner(sid, auth)
        except HTTPException:
            continue  # not the caller's session — omit silently
        try:
            storage_path = _storage_root_live_or_dormant(sid)
            # Per-agent usage is a SLICE of the cloud now (agents/<sid>/),
            # not a journal of its own.
            _owner, _prefix = await asyncio.to_thread(
                _cloud_owning_storage, storage_path,
            )
            if _prefix:
                used = await asyncio.to_thread(
                    workspace_sync.used_bytes_under, _owner, _prefix,
                )
            else:
                used = await asyncio.to_thread(
                    workspace_sync.used_bytes_if_indexed, _owner,
                )
        except Exception:  # noqa: BLE001
            used = None
        out.append(
            {
                "session_id": sid,
                "session_name": rec.get("session_name"),
                "used_bytes": used,
                "quota_bytes": quota,
            }
        )
    return {"agents": out, "quota_bytes": quota}


@router.get("/{session_id}", response_model=SessionInfo)
async def get_agent_session(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """
    Get specific AgentSession information.

    Tolerates dormant (post-restart) sessions: if not live in memory, falls
    back to the persisted store record (status "stopped") instead of 404ing,
    so opening a session that hasn't been re-hydrated yet still shows its
    metadata. Actual re-hydration happens on message / explicit resume.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        store = get_session_store()
        rec = store.get(session_id)
        if rec and not rec.get("is_deleted"):
            info = _dormant_session_info(rec)
            if info is not None:
                return info
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    info = agent.get_session_info()
    # X7 (cycle 20260422_5): enrich with the Tamagotchi snapshot for
    # sessions that have a state_provider. Returns None for classic
    # sessions — the frontend UI hides the panel in that case.
    info.creature_state = await agent.load_creature_state_snapshot()
    return info


class UpdateSystemPromptRequest(BaseModel):
    """Request to update an agent's system prompt."""
    system_prompt: Optional[str] = Field(
        default=None,
        description="New system prompt. Set to null or empty string to clear.",
    )


class UpdateThinkingTriggerRequest(BaseModel):
    """Request to enable/disable thinking trigger for a session."""
    enabled: bool = Field(
        ...,
        description="Whether thinking trigger is enabled for this session.",
    )


class AttachTriggerPresetRequest(BaseModel):
    """Request to attach (or detach) a trigger preset for a VTuber session.

    Pass ``trigger_preset_id=None`` to revert the session to the bundled
    defaults. Idempotent — re-binding the same preset is a no-op.
    """

    trigger_preset_id: Optional[str] = Field(
        default=None,
        description=(
            "Trigger preset id, or ``null`` to detach and use the bundled "
            "defaults."
        ),
    )


class ChangeEnvRequest(BaseModel):
    """Request to rebind a session to a different environment.

    Targets exactly one session id (the path param). For a VTuber/Sub-Worker
    pair the caller issues two separate requests — one per session — so each
    side can run a different environment.
    """

    env_id: str = Field(..., description="The environment id to bind to.")


class RouteRef(BaseModel):
    """One hop: an account, and the model to ask it for."""

    accountId: str = Field(..., description="Model account id.")
    model: Optional[str] = Field(None, description="Model id; omitted → the account's default.")
    effort: Optional[str] = Field(None, description="low | medium | high | xhigh | max.")


class ChangeRouteRequest(BaseModel):
    """Which model accounts this session should use, in order.

    The primary answers; the fallbacks are tried, in order, only when a hop
    fails in a way another account could survive — a usage limit, a dead
    login, an outage.
    """

    primary: RouteRef
    fallbacks: List[RouteRef] = Field(default_factory=list)


@router.put("/{session_id}/system-prompt")
async def update_system_prompt(
    request: UpdateSystemPromptRequest,
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """
    Update the system prompt of a running AgentSession.

    The new prompt takes effect on the next execution.
    Pass null or empty string to clear the system prompt.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    new_prompt = request.system_prompt if request.system_prompt else None

    # Route through the PersonaProvider (cycle 20260421_7 PR-X1-3). The
    # provider replaces the legacy ``agent._system_prompt`` write; the
    # pipeline's DynamicPersonaSystemBuilder picks up the new override on
    # the next turn. Persisting to session_store is unchanged so restore
    # can re-stage the override.
    agent_manager.persona_provider.set_static_override(session_id, new_prompt)

    # Persist to session store so the change survives delete/restore
    store = get_session_store()
    store.update(session_id, {"system_prompt": new_prompt or ""})

    logger.info(
        f"[{session_id}] System prompt updated "
        f"({len(new_prompt) if new_prompt else 0} chars)"
    )
    return {"success": True, "session_id": session_id, "system_prompt_length": len(new_prompt) if new_prompt else 0}


@router.get("/{session_id}/thinking-trigger")
async def get_thinking_trigger(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Get thinking trigger status for a VTuber session."""
    from service.vtuber.thinking_trigger import get_thinking_trigger_service
    service = get_thinking_trigger_service()
    status = service.get_status(session_id)
    return {"session_id": session_id, **status}


@router.put("/{session_id}/thinking-trigger")
async def update_thinking_trigger(
    request: UpdateThinkingTriggerRequest,
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Enable or disable thinking trigger for a VTuber session."""
    from service.vtuber.thinking_trigger import get_thinking_trigger_service
    service = get_thinking_trigger_service()
    if request.enabled:
        service.enable(session_id)
    else:
        service.disable(session_id)
    return {"success": True, "session_id": session_id, **service.get_status(session_id)}


@router.post("/{session_id}/trigger-preset/own")
async def make_own_trigger_preset(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Give this agent a ladder of its own, and return it.

    Editing when an agent speaks used to mean editing a preset every agent
    sharing it would feel — or building another environment to hold a
    different one. So the editor calls this first: if the session already has
    its own ladder it comes back unchanged, and if it is running the shared
    default it gets a private copy of exactly what it is running now, attached.
    Idempotent: asking twice changes nothing.
    """
    _enforce_session_owner(session_id, auth)

    from service.trigger_preset import get_trigger_preset_service
    from service.vtuber.thinking_trigger import get_thinking_trigger_service

    presets = get_trigger_preset_service()
    if presets is None:
        raise HTTPException(status_code=503, detail="Trigger presets unavailable")
    triggers = get_thinking_trigger_service()

    record = None
    own_id = triggers.get_attached_preset(session_id)
    if own_id:
        record = presets.get(own_id)
    if record is None:
        store = get_session_store()
        name = (store.get(session_id) or {}).get("session_name") or session_id[:8]
        source = presets.get_default()
        # Copy what it is running right now, so "edit" starts from what the
        # user has been hearing rather than from a blank ladder.
        own_id = presets.create(
            name=f"{name} 트리거",
            description="이 에이전트 전용",
            clone_from=source.id if source else None,
        )
        record = presets.get(own_id)
        triggers.attach_preset(session_id, own_id)
        try:
            get_session_store().update(session_id, {"trigger_preset_id": own_id})
        except Exception:  # noqa: BLE001
            logger.debug("[%s] could not persist trigger_preset_id", session_id, exc_info=True)

    return {
        "session_id": session_id,
        "trigger_preset_id": record.id,
        "name": record.name,
        "manifest": record.manifest.model_dump(mode="json"),
    }


@router.put("/{session_id}/trigger-preset")
async def attach_trigger_preset(
    request: AttachTriggerPresetRequest,
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Attach (or detach) a trigger preset for a VTuber session.

    The trigger runtime starts using the new preset on the next tick —
    no restart required. ``trigger_preset_id=null`` reverts the session
    to the bundled default ladder.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    # Validate the preset exists (when one is requested) so the FE
    # surfaces a 404 instead of silently no-op'ing on a typo.
    if request.trigger_preset_id:
        from service.trigger_preset import get_trigger_preset_service
        svc = get_trigger_preset_service()
        if svc is not None and svc.get(request.trigger_preset_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Trigger preset not found: {request.trigger_preset_id}",
            )

    from service.vtuber.thinking_trigger import get_thinking_trigger_service
    get_thinking_trigger_service().attach_preset(
        session_id, request.trigger_preset_id
    )

    # Persist on the session record so reverse-lookups + reads through
    # SessionStore reflect the change.
    try:
        store = get_session_store()
        store.update(session_id, {"trigger_preset_id": request.trigger_preset_id})
    except Exception:
        logger.debug(
            "[%s] Failed to persist trigger_preset_id; runtime binding "
            "still active",
            session_id,
            exc_info=True,
        )

    return {
        "success": True,
        "session_id": session_id,
        "trigger_preset_id": request.trigger_preset_id,
    }


@router.get("/{session_id}/sub-agent")
async def get_session_sub_agent(
    request: Request,
    session_id: str = Path(..., description="VTuber session ID"),
    auth: dict = Depends(require_auth),
):
    """View the executor persistent sub-agent owned by a VTuber session.

    The cutover (GENY_VTUBER_SUBAGENT_MODE=executor) makes a VTuber own a
    geny-executor persistent sub-agent rather than a bespoke paired session.
    It is not a session, so it has no sidebar entry — this read-only endpoint
    surfaces its status + recent conversation + pending notifications so the
    UI can render the "확인만" view (decision 4).
    """
    manager = getattr(request.app.state, "subagent_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="subagent_manager not configured")
    try:
        rec = get_session_store().get(session_id) or {}
    except Exception:
        rec = {}
    sa_id = rec.get("executor_sub_agent_id")
    if not sa_id:
        raise HTTPException(status_code=404, detail="session has no executor sub-agent")
    inbox_count = manager.inbox.count(session_id)
    agent = manager.get(sa_id)
    if agent is None:
        # Not live in-memory (e.g. before first access after restart).
        return {
            "sub_agent_id": sa_id,
            "owner_session_id": session_id,
            "status": "dormant",
            "conversation": [],
            "inbox_count": inbox_count,
        }
    summary = agent.summary()
    messages = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in (getattr(agent.state, "messages", []) or [])[-20:]
    ]
    return {**summary, "conversation": messages, "inbox_count": inbox_count}


@router.put("/{session_id}/env")
async def change_session_env(
    request: ChangeEnvRequest,
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Rebind a session to a different environment.

    Works for both live and dormant (post-restart) sessions — the new
    binding is persisted to the store and a live session reloads its
    pipeline from the new manifest on the next access *between turns*
    (storage / memory / conversation are preserved). For a VTuber pair,
    call this once per session id (the VTuber's and the Sub-Worker's) to
    change each side independently.

    Returns 404 when the session is unknown, 400 when the target env is
    unknown or its provider has no credentials.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    try:
        result = await agent_manager.change_session_env(
            session_id, request.env_id
        )
    except ValueError as exc:
        msg = str(exc)
        status = 404 if "session not found" in msg else 400
        raise HTTPException(status_code=status, detail=msg)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"success": True, **result}


@router.get("/{session_id}/route")
async def get_session_route(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Which model accounts this session uses, and who answered last turn."""
    _enforce_session_owner(session_id, auth)
    return agent_manager.get_session_route(session_id)


@router.get("/{session_id}/harness")
async def get_session_harness(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """What this agent's harness is ACTUALLY running.

    Read from the session's live pipeline, not from its manifest: Geny
    declares placeholders in the manifest and installs the real
    implementations when the session is built, so a manifest-rendered page
    would show ``no_persist`` on a stage that persists and an empty guard
    chain on a session that guards.

    Every value carries where it came from — ``default`` / ``manifest`` /
    ``runtime`` / ``session`` — because knowing what runs is only half of
    what a settings page has to answer. The other half is whether changing
    it will stick.
    """
    _enforce_session_owner(session_id, auth)
    agent = await agent_manager.ensure_session_live(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")
    try:
        return await agent_manager.session_harness(agent)
    except Exception as exc:  # noqa: BLE001 — a settings page never 500s the app
        logger.warning("harness view failed for %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"harness view unavailable: {exc}")


@router.put("/{session_id}/route")
async def change_session_route(
    request: ChangeRouteRequest,
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Switch which model answers — without ending the conversation.

    A live session has its Stage 6 credentials swapped in place, so the next
    turn goes to the new account and everything else (history, tools, memory,
    hooks, permission policy) carries on untouched. A dormant session picks
    the route up on its next wake.

    Returns 404 when the session is unknown, 400 when the route named no
    usable account — in which case the session keeps the route it had.
    """
    _enforce_session_owner(session_id, auth)
    try:
        result = await agent_manager.change_session_route(
            session_id, request.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "session not found" in message else 400
        raise HTTPException(status_code=status, detail=message)
    return {"success": True, **result}


@router.delete("/{session_id}")
async def delete_agent_session(
    session_id: str = Path(..., description="Session ID"),
    cleanup_storage: bool = Query(False, description="Also delete storage (default: False to preserve files)"),
    auth: dict = Depends(require_auth),
):
    """
    Delete AgentSession (soft-delete — metadata preserved in sessions.json).

    Storage is preserved by default so the session can be restored later.
    Pass cleanup_storage=true to also remove the storage directory.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    success = await agent_manager.delete_session(session_id, cleanup_storage)
    if not success:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    logger.info(f"✅ AgentSession soft-deleted: {session_id}")
    return {"success": True, "session_id": session_id}


@router.delete("/{session_id}/permanent")
async def permanent_delete_session(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """
    Permanently delete a session from the persistent store.
    The session record is irrecoverably removed from sessions.json
    and its storage directory is deleted from disk.
    Cascades to linked sessions (VTuber ↔ CLI pairs).
    """
    import shutil
    from pathlib import Path as FilePath

    store = get_session_store()

    # Get record and find linked session before deleting
    record = store.get(session_id)
    storage_path = record.get("storage_path") if record else None
    linked_id = record.get("linked_session_id") if record else None

    # Also delete from live agents if still active
    if agent_manager.has_agent(session_id):
        await agent_manager.delete_session(session_id, cleanup_storage=True)
    elif storage_path:
        # Agent not live — clean up storage directory from disk
        sp = FilePath(storage_path)
        if sp.is_dir():
            try:
                await rmtree_async(sp)
                logger.info(f"Storage cleaned up: {storage_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup storage {storage_path}: {e}")

    # GAPT workspace: a live session already archived it via delete_session,
    # but a dormant one (deleted post-restart) took the direct-rmtree branch
    # above and never touched GAPT. Call the idempotent helper unconditionally
    # so the agent's workspace is gone either way.
    try:
        from service.gapt import delete_workspace_for_session
        await delete_workspace_for_session(session_id)
    except Exception:  # noqa: BLE001 — never block permanent delete
        logger.debug(f"[{session_id}] gapt cleanup on permanent delete failed", exc_info=True)

    removed = store.permanent_delete(session_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found in store")
    logger.info(f"✅ Session permanently deleted: {session_id}")

    # Cascade to linked session (VTuber ↔ CLI pair)
    if linked_id:
        linked_rec = store.get(linked_id)
        if linked_rec:
            linked_storage = linked_rec.get("storage_path")
            if agent_manager.has_agent(linked_id):
                await agent_manager.delete_session(linked_id, cleanup_storage=True)
            elif linked_storage:
                sp = FilePath(linked_storage)
                if sp.is_dir():
                    try:
                        await rmtree_async(sp)
                        logger.info(f"Linked session storage cleaned up: {linked_storage}")
                    except Exception as e:
                        logger.warning(f"Failed to cleanup linked storage {linked_storage}: {e}")
            try:
                from service.gapt import delete_workspace_for_session
                await delete_workspace_for_session(linked_id)
            except Exception:  # noqa: BLE001
                logger.debug(f"[{linked_id}] gapt cleanup on permanent delete failed", exc_info=True)
            store.permanent_delete(linked_id)
            logger.info(f"✅ Linked session permanently deleted: {linked_id}")

    return {"success": True, "session_id": session_id}


@router.post("/{session_id}/resume", response_model=SessionInfo)
async def resume_session(
    session_id: str = Path(..., description="Session ID to resume"),
    auth: dict = Depends(require_auth),
):
    """
    Resume a dormant session — idempotent lazy re-hydration.

    After a redeploy / restart / crash the live registry is empty but the
    session still exists in the store (non-deleted). This reconstructs the
    ``AgentSession`` from its on-disk storage (memory, transcripts,
    checkpoints) so the conversation continues, and cascades to the linked
    peer. If the session is already live it just returns the current info.
    The frontend calls this when the user opens a ``stopped`` session.
    """
    if agent_manager.has_agent(session_id):
        return agent_manager.get_agent(session_id).get_session_info()

    agent = await agent_manager.ensure_session_live(session_id)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found or was deleted — nothing to resume",
        )
    logger.info(f"✅ Session resumed: {session_id}")
    return agent.get_session_info()


@router.post("/{session_id}/restore")
async def restore_session(
    session_id: str = Path(..., description="Session ID to restore"),
    auth: dict = Depends(require_auth),
):
    """
    Restore a soft-deleted (explicitly removed) session.

    Un-deletes the store record, then re-creates the AgentSession with the
    same session_id (preserving storage_path) via the shared re-hydration
    path used by lazy restore. Cascades to linked sessions (VTuber ↔ CLI).
    """
    store = get_session_store()
    record = store.get(session_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found in store")
    if not record.get("is_deleted"):
        raise HTTPException(status_code=400, detail="Session is not deleted — nothing to restore")

    # Check not already live
    if agent_manager.has_agent(session_id):
        raise HTTPException(status_code=400, detail="Session is already running")

    # Un-delete first so the shared re-hydration path (which refuses deleted
    # records) accepts it; cascade un-delete the linked peer too.
    store.restore(session_id)
    linked_id = record.get("linked_session_id")
    if linked_id:
        linked_rec = store.get(linked_id)
        if linked_rec and linked_rec.get("is_deleted"):
            store.restore(linked_id)

    try:
        agent = await agent_manager._rehydrate(session_id)
        if agent is None:
            raise RuntimeError("re-hydration returned no session")
        session_info = agent.get_session_info()
        logger.info(f"✅ Session restored: {session_id} (same ID, storage preserved)")
        return session_info
    except Exception as e:
        logger.error(f"❌ Failed to restore session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Agent Graph Execution API
# ============================================================================


@router.post("/{session_id}/invoke", response_model=AgentInvokeResponse)
async def invoke_agent(
    session_id: str = Path(..., description="Session ID"),
    request: AgentInvokeRequest = ...,
    auth: dict = Depends(require_auth),
):
    """
    Invoke AgentSession — runs the session's `geny-executor` Pipeline.

    If checkpointing is enabled, state is restored/saved using thread_id.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    # Hydrate-on-access: transparently re-hydrate a dormant (post-restart)
    # session so messaging a "stopped" session just resumes it.
    agent = await agent_manager.ensure_session_live(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    if not agent.is_initialized:
        raise HTTPException(
            status_code=400,
            detail=f"AgentSession is not initialized"
        )

    # Session logger
    session_logger = get_session_logger(session_id, create_if_missing=False)

    try:
        # Log input
        if session_logger:
            session_logger.log_command(
                prompt=request.input_text,
                max_turns=request.max_iterations,
            )

        # Run the session's Pipeline
        result = await agent.invoke(
            input_text=request.input_text,
            thread_id=request.thread_id,
            max_iterations=request.max_iterations,
        )
        output = result.get("output", "") if isinstance(result, dict) else str(result)

        # Log response
        if session_logger:
            session_logger.log_response(
                success=True,
                output=output,
            )

        return AgentInvokeResponse(
            success=True,
            session_id=session_id,
            output=output,
            thread_id=request.thread_id,
        )

    except Exception as e:
        logger.error(f"❌ Agent invoke failed: {e}", exc_info=True)

        if session_logger:
            session_logger.log_response(
                success=False,
                error=str(e),
            )

        return AgentInvokeResponse(
            success=False,
            session_id=session_id,
            error=str(e),
            thread_id=request.thread_id,
        )


@router.post("/{session_id}/execute", response_model=ExecuteResponse)
async def execute_agent_prompt(
    session_id: str = Path(..., description="Session ID"),
    request: ExecuteRequest = ...,
    auth: dict = Depends(require_auth),
):
    """
    Execute prompt with AgentSession via the compiled StateGraph.

    Delegates to the unified ``execute_command`` function which handles
    auto-revival, session logging, cost tracking, and double-execution
    prevention.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    try:
        result = await execute_command(
            session_id=session_id,
            prompt=request.prompt,
            timeout=request.timeout,
            system_prompt=request.system_prompt,
            max_turns=request.max_turns,
        )
        return ExecuteResponse(
            success=result.success,
            session_id=session_id,
            output=result.output,
            error=result.error,
            cost_usd=result.cost_usd,
            duration_ms=result.duration_ms,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")
    except AgentNotAliveError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AlreadyExecutingError:
        raise HTTPException(status_code=409, detail="Execution already in progress")
    except Exception as e:
        logger.error(f"❌ Agent execute failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: SSE helpers (_sse, _emit_avatar_state_for_log, _stream_execution_sse)
# and SSE endpoints (GET /execute/events, POST /execute/stream) have been removed.
# Execution streaming is now handled by ws/execute_stream.py (WebSocket).


async def _emit_avatar_state_for_log(entry_dict: dict, session_id: str, app_state) -> None:
    """
    Inspect a log entry and emit avatar state changes if relevant.

    Called during SSE streaming for each log entry to automatically
    update the Live2D avatar expression based on:
    1. LLM response text → emotion tag extraction ([joy], [anger], etc.)
    2. Agent execution state → state-to-emotion mapping
    """
    if not hasattr(app_state, "avatar_state_manager") or not hasattr(app_state, "live2d_model_manager"):
        return

    state_manager = app_state.avatar_state_manager
    model_manager = app_state.live2d_model_manager

    model = model_manager.get_agent_model(session_id)
    if not model:
        return

    level = entry_dict.get("level", "")
    message = entry_dict.get("message", "")

    try:
        from service.vtuber.emotion_extractor import EmotionExtractor
        extractor = EmotionExtractor(model.emotionMap)

        if level == "RESPONSE":
            # LLM response — extract emotion tags
            emotion, index = extractor.resolve_emotion(message, None)
            await state_manager.update_state(
                session_id=session_id,
                emotion=emotion,
                expression_index=index,
                trigger="agent_output",
            )
        elif level == "TOOL":
            # Tool usage — show "working" expression
            await state_manager.update_state(
                session_id=session_id,
                emotion="surprise",
                expression_index=model.emotionMap.get("surprise", 0),
                trigger="state_change",
            )
        elif level == "GRAPH":
            if "error" in message.lower() or "fail" in message.lower():
                await state_manager.update_state(
                    session_id=session_id,
                    emotion="fear",
                    expression_index=model.emotionMap.get("fear", 0),
                    trigger="state_change",
                )
            elif "complet" in message.lower() or "success" in message.lower():
                await state_manager.update_state(
                    session_id=session_id,
                    emotion="joy",
                    expression_index=model.emotionMap.get("joy", 0),
                    trigger="state_change",
                )
    except Exception:
        pass  # Avatar state is best-effort; never break the SSE stream



# ── Execution endpoints (delegating to agent_executor) ────────────────────────


@router.get("/{session_id}/execute/status")
async def get_execution_status(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """
    Lightweight polling endpoint — check whether an execution is active.

    Returns:
      - ``active: true``  + ``done`` flag while the holder exists.
      - ``active: false`` when there is no execution for this session.

    Designed for the frontend to call on page load / visibility-change
    so it can reconnect to ``GET /execute/events`` if needed.
    """
    holder = get_execution_holder(session_id)
    if not holder:
        return {"active": False, "session_id": session_id}

    now = time.time()
    start_time = holder.get("start_time", now)
    elapsed_ms = int((now - start_time) * 1000)

    # Compute last activity from session logger
    session_logger = get_session_logger(session_id, create_if_missing=False)
    now_mono = time.monotonic()
    last_write = session_logger.get_last_write_at() if session_logger else 0
    last_activity_ms = int((now_mono - last_write) * 1000) if last_write > 0 else elapsed_ms

    entry_info = session_logger.get_last_entry_info() if session_logger else {}

    return {
        "active": True,
        "done": holder.get("done", False),
        "has_error": holder.get("error") is not None,
        "session_id": session_id,
        "elapsed_ms": elapsed_ms,
        "last_activity_ms": last_activity_ms,
        "last_event_level": entry_info.get("level"),
        "last_tool_name": entry_info.get("tool_name"),
    }



# ============================================================================
# Agent State API
# ============================================================================


@router.get("/{session_id}/state", response_model=AgentStateResponse)
async def get_agent_state(
    session_id: str = Path(..., description="Session ID"),
    thread_id: Optional[str] = Query(None, description="Thread ID"),
    auth: dict = Depends(require_auth),
):
    """
    Get current AgentSession state.

    State can only be queried if checkpointing is enabled.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    state = agent.get_state(thread_id=thread_id)

    if state is None:
        return AgentStateResponse(
            session_id=session_id,
            error="State not available (checkpointing disabled or no execution yet)",
        )

    metadata = state.get("metadata", {})

    return AgentStateResponse(
        session_id=session_id,
        current_step=state.get("current_step"),
        last_output=state.get("last_output"),
        iteration=metadata.get("iteration"),
        error=state.get("error"),
        is_complete=state.get("is_complete", False),
    )


@router.get("/{session_id}/history")
async def get_agent_history(
    session_id: str = Path(..., description="Session ID"),
    thread_id: Optional[str] = Query(None, description="Thread ID"),
    auth: dict = Depends(require_auth),
):
    """
    Get AgentSession execution history.

    History can only be queried if checkpointing is enabled.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    history = agent.get_history(thread_id=thread_id)

    return {
        "session_id": session_id,
        "thread_id": thread_id,
        "history": history,
    }


# ============================================================================
# ============================================================================
# Stop Execution API
# ============================================================================


@router.post("/{session_id}/stop")
async def stop_execution(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """
    Stop the current execution for a session.

    Graph execution is synchronous — cancel the HTTP request to stop.
    This endpoint marks the intent to stop.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    logger.info(f"[{session_id}] Stop requested — graph execution is synchronous, cancel the HTTP request")
    return {
        "success": True,
        "message": "Graph executes synchronously. Cancel the HTTP request to stop execution.",
    }


@router.put("/{session_id}/persona")
async def set_session_persona(
    session_id: str = Path(..., description="Session ID"),
    body: Dict[str, Any] = Body(default_factory=dict),
    auth: dict = Depends(require_auth),
):
    """Give this session its own persona, or hand it back to its env.

    ``{"persona_preset_id": "<id>"}`` overrides; ``null`` clears the
    override so the session follows its environment again.

    Until now a persona was a property of the ENVIRONMENT alone: the only
    way to give one session a different character was to build it another
    environment, and the only way to change one was to edit an environment
    that every session on it shares.

    Persisted first, so the choice survives eviction and restart. A live
    and idle session rebuilds immediately (``applied_now``); one that is
    mid-turn is flagged and picks it up between turns rather than being
    torn down underneath a running answer.
    """
    raw = body.get("persona_preset_id", None)
    if raw is not None and not isinstance(raw, str):
        raise HTTPException(
            status_code=400, detail="persona_preset_id must be a string or null",
        )
    _enforce_session_owner(session_id, auth)
    try:
        return {"success": True, **await agent_manager.set_session_persona(session_id, raw)}
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=404 if "not found" in msg else 400, detail=msg)


@router.post("/{session_id}/restart")
async def restart_session(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Rebuild this session now, keeping everything it remembers.

    Storage, memory, transcripts and the conversation are on disk and
    survive; only the running pipeline is replaced. It exists as its own
    button because every other way to get a rebuild was a side effect of
    changing something else — so "apply what I already set" had no way to
    say so.

    409 while a turn is running: a rebuild mid-answer loses the answer.
    """
    _enforce_session_owner(session_id, auth)
    try:
        return {"success": True, **await agent_manager.restart_session(session_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.put("/{session_id}/always-on")
async def set_always_on(
    session_id: str = Path(..., description="Session ID"),
    body: Dict[str, Any] = Body(default_factory=dict),
    auth: dict = Depends(require_auth),
):
    """Pin this session awake, release it, or hand it back to host policy.

    ``{"always_on": true}`` keeps the session resident no matter what the
    host's idle policy says; ``false`` lets it be reclaimed even while the
    host keeps everything else awake; ``null`` follows the policy.

    Written to the store FIRST: the pin exists to survive eviction and
    restart, so persisting it is the operation — updating the live object
    is just making it take effect now. A session that is currently
    dormant can be pinned too, which is why this does not require a live
    agent.
    """
    raw = body.get("always_on", None)
    if raw is not None and not isinstance(raw, bool):
        raise HTTPException(
            status_code=400,
            detail="always_on must be true, false, or null",
        )

    _enforce_session_owner(session_id, auth)
    store = get_session_store()
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    store.update(session_id, {"always_on": raw})
    agent = agent_manager.get_agent(session_id)
    if agent is not None:
        agent.set_always_on(raw)

    logger.info(
        "[%s] always_on set to %s (%s)",
        session_id, raw, "live" if agent is not None else "dormant record",
    )
    return {"session_id": session_id, "always_on": raw, "applied_live": agent is not None}


# ============================================================================
# Storage API
# ============================================================================


def _resolve_storage_scope(scope_id: str, auth: dict) -> tuple:
    """Storage path + change-notification key for a storage SCOPE.

    The storage API is scope-generic. A scope is normally a session (the
    agent's own workspace), and ``_cloud`` addresses the CALLING USER'S
    GenyCloud — the folder that sits above agents and gathers everything.

    Security note: a cloud path is derived from the caller's own token,
    never from the id, so ``_cloud`` cannot be pointed at another user's
    cloud no matter what is sent.
    """
    from service.cloud import cloud_notify_key, cloud_storage_path, is_cloud_scope

    if is_cloud_scope(scope_id):
        user = (auth or {}).get("sub") or "anonymous"
        return cloud_storage_path(user), cloud_notify_key(user)
    return _storage_root_live_or_dormant(scope_id), scope_id


def _storage_root_live_or_dormant(session_id: str) -> str:
    """Session storage root for live OR dormant sessions.

    Storage endpoints must keep working after a backend restart (lazy
    restore leaves sessions dormant until touched) — the files are on
    disk regardless of liveness, so fall back to the session store
    record when no live agent exists. 404 only for unknown/deleted ids.
    """
    agent = agent_manager.get_agent(session_id)
    storage_path = getattr(agent, "storage_path", None) if agent else None
    if not storage_path:
        record = None
        try:
            record = get_session_store().get(session_id)
        except Exception:  # noqa: BLE001 — store may be unavailable; fall through
            record = None
        if record and record.get("is_deleted"):
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        if record:
            storage_path = record.get("storage_path")
    if not storage_path:
        # No live agent and no store record — but the session's files survive on
        # disk after the store record is idle-evicted / pruned, and storage
        # endpoints (download / preview / list) must keep serving them. Derive
        # <storage_root>/<session_id> when it actually exists. Validate the id to
        # a safe leaf so this can't traverse or probe arbitrary paths; the
        # per-endpoint owner guard still applies.
        import re as _re
        from pathlib import Path as _P

        from service.utils.platform import DEFAULT_STORAGE_ROOT

        if _re.match(r"^[A-Za-z0-9_-]{1,128}$", session_id):
            cand = _P(DEFAULT_STORAGE_ROOT) / session_id
            if cand.is_dir():
                storage_path = str(cand)
    if not storage_path:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return storage_path


@router.get("/{session_id}/storage")
async def list_storage_files(
    session_id: str = Path(..., description="Session ID"),
    path: str = Query("", description="Subdirectory path"),
    scope: str = Query(
        "all",
        description="'workspace' roots the listing at the agent's workspace/ "
                    "(the user-facing files); 'all' shows the whole session "
                    "dir including internal state (memory, transcripts, db).",
    ),
    auth: dict = Depends(require_auth),
):
    """
    List session storage files. Works for dormant sessions too.
    """
    _enforce_scope_owner(session_id, auth)  # audit S6
    import os as _os

    from service.utils import file_storage as storage_utils

    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    if scope == "workspace":
        storage_path = _os.path.join(storage_path, "workspace")
        _os.makedirs(storage_path, exist_ok=True)

    # OFF-LOOP: this walks the whole scope (scope=all includes the memory
    # vault — thousands of entries) and the UI polls it. Run synchronously
    # it seizes the event loop and starves every other endpoint (observed:
    # storage/changes timing out, all sync engines wedged in 'syncing').
    # The one legitimate way out of this scope: a connected agent's
    # `workspace/cloud` link into the caller's OWN cloud. Passed explicitly
    # and only when the connection exists, so the listing follows that link
    # and nothing else.
    extra_roots: List[str] = []
    try:
        from service.cloud import cloud_workspace, is_cloud_scope, is_connected

        _user = (auth or {}).get("sub") or ""
        if _user and not is_cloud_scope(session_id) and is_connected(_user, session_id):
            extra_roots.append(cloud_workspace(_user))
    except Exception:  # noqa: BLE001
        logger.debug("cloud root resolution skipped for listing", exc_info=True)

    files_data = await asyncio.to_thread(
        storage_utils.list_storage_files,
        storage_path, subpath=path, session_id=session_id,
        extra_roots=extra_roots,
    )
    files = [StorageFile(**f) for f in files_data]

    return StorageListResponse(
        session_id=session_id,
        storage_path=storage_path,
        files=files
    )


#: Per-file cap for workspace writes (browser upload AND sync PUT).
#: Env-tunable so operators can raise/lower without a release; the
#: connector reads the same limit from /storage/changes responses.
def _workspace_max_file_bytes() -> int:
    import os as _os

    try:
        return int(_os.environ.get("GENY_WORKSPACE_MAX_FILE_MB", "500")) * 1024 * 1024
    except ValueError:
        return 500 * 1024 * 1024




async def _sync_touch(notify_key: str, storage_path: str) -> int:
    """After any workspace write: refresh the sync index (off-loop —
    hashing/sqlite are blocking) and wake connected replicas. Returns the
    new latest_seq. Never raises — sync bookkeeping must not fail the
    user's operation."""
    try:
        from service.utils import workspace_sync
        from ws.workspace_stream import notify_workspace_changed

        stats = await asyncio.to_thread(
            workspace_sync.refresh_index, storage_path, notify_key, force=True
        )
        seq = int(stats.get("latest_seq", 0))
        notify_workspace_changed(notify_key, seq)
        return seq
    except Exception as exc:  # noqa: BLE001
        logger.debug("[%s] sync index refresh failed: %s", notify_key, exc)
        return 0


def _within_scope(root: "Path", target: "Path") -> bool:
    """Is *target* inside this scope, counting its workspace wherever it lives?

    One rule, in ``service.utils.file_storage`` — the JSON reader had its own
    and it was the plain ``relative_to`` check, so an adopted agent (whose
    ``workspace`` is a symlink into the cloud) could list every file it had
    ever written and open none of them.
    """
    from service.utils.file_storage import within_scope

    return within_scope(root, target)


def _ws_path(ws: "Path", target: "Path") -> str:
    """API path (``workspace/...``) for a target inside the workspace.

    Reporting it as ``target.relative_to(storage_root)`` broke the moment an
    agent's workspace became a symlink into the cloud: the resolved target is
    under the cloud, not under the session root, so building the response
    raised — after the operation had already succeeded. Anchoring on the
    workspace instead is stable wherever the bytes physically live.
    """
    rel = str(target.relative_to(ws)).replace("\\", "/")
    return "workspace" if rel == "." else f"workspace/{rel}"


def _workspace_target(storage_path: str, rel_path: str) -> "tuple":
    """Resolve *rel_path* (storage-root-relative, e.g. 'workspace/uploads/x')
    and enforce that it stays INSIDE the scope's workspace/ — the only
    place UI-driven writes are allowed. Internal state (memory/, transcripts/,
    synapse.db, checkpoints/) is never reachable from these endpoints.

    Takes a resolved STORAGE PATH, not a scope id: the caller has already
    resolved (and thereby authorised) the scope, and a cloud path can only
    be produced from the caller's own token."""
    from pathlib import Path as _P

    root = _P(storage_path).resolve()
    ws = (root / "workspace").resolve()
    target = (root / (rel_path or "")).resolve()
    try:
        target.relative_to(ws)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Write operations are allowed only inside workspace/",
        )
    if target == ws and rel_path.rstrip("/") != "workspace":
        # normalise edge: '' would resolve to root
        pass
    return root, ws, target


class StorageRenameRequest(BaseModel):
    src: str
    dst: str


@router.post("/{session_id}/storage/mkdir")
async def storage_mkdir(
    # Defaulted so the handler stays directly callable in unit tests;
    # FastAPI injects the live Request from the annotation regardless.
    http_request: Request = None,  # type: ignore[assignment]
    session_id: str = Path(..., description="Session ID"),
    path: str = Query(..., description="New folder path (storage-root relative, under workspace/)"),
    auth: dict = Depends(require_auth),
):
    """Create a folder inside the agent workspace (explorer 새 폴더)."""
    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    root, ws, target = _workspace_target(storage_path, path)
    if target.exists():
        raise HTTPException(status_code=409, detail="Already exists")
    target.mkdir(parents=True, exist_ok=False)
    await _sync_touch(_notify_key, str(root))
    await _history(storage_path, http_request, auth, "mkdir",
                   _ws_path(ws, target))
    return {"ok": True, "path": _ws_path(ws, target)}


@router.post("/{session_id}/storage/rename")
async def storage_rename(
    request: StorageRenameRequest,
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Rename/move a file or folder within the workspace."""
    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    from service.utils import workspace_sync

    root, ws, src = _workspace_target(storage_path, request.src)
    _root2, _ws2, dst = _workspace_target(storage_path, request.dst)
    if src == ws or dst == ws:
        raise HTTPException(status_code=403, detail="Cannot rename the workspace root")
    # Locked no-clobber rename: os.rename silently replaces an existing
    # dst on POSIX, so the exists-check must be atomic with the rename
    # against concurrent PUT/chunk commits.
    outcome = await asyncio.to_thread(workspace_sync.locked_rename, str(root), src, dst)
    if outcome == "src_missing":
        raise HTTPException(status_code=404, detail="Source not found")
    if outcome == "dst_exists":
        raise HTTPException(status_code=409, detail="Destination already exists")
    await _sync_touch(_notify_key, str(root))
    await _history(storage_path, None, auth, "renamed",
                   _ws_path(ws, dst),
                   detail=f"from {_ws_path(ws, src)}")
    return {"ok": True, "path": _ws_path(ws, dst)}


@router.delete("/{session_id}/storage/entry")
async def storage_delete(
    # Defaulted so the handler stays directly callable in unit tests;
    # FastAPI injects the live Request from the annotation regardless.
    http_request: Request = None,  # type: ignore[assignment]
    session_id: str = Path(..., description="Session ID"),
    path: str = Query(..., description="Path to delete (under workspace/)"),
    base_sha: Optional[str] = Query(
        None,
        description="Sync guard: expected current sha256 of the file. "
        "Mismatch → 409 (someone changed it since the replica last saw it).",
    ),
    auth: dict = Depends(require_auth),
):
    """Delete a file or folder (recursive) inside the workspace."""
    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    from service.utils import workspace_sync

    _root, ws, target = _workspace_target(storage_path, path)
    if target == ws:
        raise HTTPException(status_code=403, detail="Cannot delete the workspace root")
    # Verify+delete under the storage lock (off-loop — rmtree of a big
    # tree must never stall the event loop), so a guarded delete can't
    # destroy a PUT that committed after the caller's pre-check.
    try:
        clash = await asyncio.to_thread(
            workspace_sync.locked_delete, str(_root), target, base_sha
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Not found")
    if clash is not None:
        raise HTTPException(
            status_code=409,
            detail={"conflict": "delete", "current_sha": clash},
        )
    await _sync_touch(_notify_key, str(_root))
    await _history(storage_path, http_request, auth, "deleted",
                   _ws_path(ws, target))
    return {"ok": True}


@router.post("/{session_id}/storage/upload")
async def upload_to_workspace(
    # Defaulted so the handler stays directly callable in unit tests;
    # FastAPI injects the live Request from the annotation regardless.
    http_request: Request = None,  # type: ignore[assignment]
    session_id: str = Path(..., description="Session ID"),
    subdir: str = Query(
        "uploads",
        description="Destination under workspace/ (default: uploads).",
    ),
    file: UploadFile = File(...),
    auth: dict = Depends(require_auth),
):
    """Upload a user file INTO the agent's workspace.

    Lands under ``<storage>/workspace/<subdir>/`` — the same directory the
    GAPT sandbox bind-mounts at ``/workspace`` and the agent's file tools work
    in, so the agent (and its sub-agents) can immediately Read/process the
    file. This is the missing half of the workspace story: SendUserFile
    already delivers agent→user via workspace/outputs; this is user→agent.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    import os as _os
    import re as _re
    from pathlib import Path as _P

    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    root = _P(storage_path).resolve()
    ws = (root / "workspace").resolve()

    # Destination guard: subdir must stay inside workspace/.
    sub = (ws / (subdir or "uploads")).resolve()
    try:
        sub.relative_to(ws)
    except ValueError:
        raise HTTPException(status_code=403, detail="subdir escapes workspace")
    sub.mkdir(parents=True, exist_ok=True)
    await _enforce_workspace_quota(str(root), 0)

    # Filename: keep the user's name, defanged (no separators/controls).
    raw_name = _os.path.basename(file.filename or "upload.bin")
    name = _re.sub(r"[^\w.\-\uAC00-\uD7A3\u3131-\u318E ()\[\]]", "_", raw_name).strip() or "upload.bin"
    dest = sub / name
    # No silent overwrite: suffix duplicates.
    if dest.exists():
        stem, dot, ext = name.partition(".")
        for i in range(1, 1000):
            cand = sub / (f"{stem}({i}){dot}{ext}" if dot else f"{stem}({i})")
            if not cand.exists():
                dest = cand
                break

    # Atomic: stage in .geny-sync-tmp then os.replace — a half-written
    # file must never be visible at its final name (the agent's GAPT
    # bind and sync replicas would pick up the partial bytes).
    import uuid as _uuid

    max_bytes = _workspace_max_file_bytes()
    tmp_dir = root / ".geny-sync-tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"upload-{_uuid.uuid4().hex}"
    size = 0
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"file exceeds {max_bytes // (1024*1024)} MiB",
                    )
                out.write(chunk)
        _os.replace(tmp, dest)
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except Exception:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="upload write failed")

    rel = _ws_path(ws, dest)
    await _sync_touch(_notify_key, str(root))
    await _history(storage_path, http_request, auth, "uploaded", rel, size)
    return {
        "ok": True,
        "session_id": session_id,
        "path": rel,
        "workspace_path": str(dest.relative_to(ws)),
        "size": size,
    }


@router.get("/{session_id}/storage/changes")
async def storage_changes(
    session_id: str = Path(..., description="Session ID"),
    since: int = Query(0, ge=0, description="Cursor: last seq this replica applied (0 = bootstrap snapshot)"),
    auth: dict = Depends(require_auth),
):
    """Sync read model: workspace changes after ``since``.

    ``since=0`` returns every live entry (fresh replica bootstrap);
    ``since>0`` returns adds/updates/tombstones with ``seq > since``.
    A throttled incremental rescan runs first so agent-driven writes are
    included without any executor hook.
    """
    _enforce_scope_owner(session_id, auth)
    from service.utils import workspace_sync

    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    await asyncio.to_thread(workspace_sync.refresh_index, storage_path, _notify_key)
    result = await asyncio.to_thread(workspace_sync.changes_since, storage_path, since)
    result["max_file_bytes"] = _workspace_max_file_bytes()
    result["quota_bytes"] = workspace_sync.quota_bytes()
    result["used_bytes"] = await asyncio.to_thread(workspace_sync.used_bytes, storage_path)
    return result


async def _enforce_workspace_quota(storage_path: str, incoming: int) -> None:
    """507 when the workspace total would exceed the quota (0 disables)."""
    from service.utils import workspace_sync as _wsync

    quota = _wsync.quota_bytes()
    if quota <= 0:
        return
    # Measure the journal that OWNS these bytes. An adopted agent holds none
    # of its own — they are in the cloud — so reading its storage root would
    # report 0 and switch the quota off for every agent write. The quota is
    # the user's total, and the cloud is where the total lives.
    from service.cloud import owning_storage

    owner_path, _prefix = await asyncio.to_thread(owning_storage, storage_path)
    used = await asyncio.to_thread(_wsync.used_bytes, owner_path)
    if used + max(0, incoming) > quota:
        raise HTTPException(
            status_code=507,
            detail={
                "error": "workspace quota exceeded",
                "quota_bytes": quota,
                "used_bytes": used,
            },
        )


@router.put("/{session_id}/storage/file")
async def put_workspace_file(
    request: Request,
    session_id: str = Path(..., description="Session ID"),
    path: str = Query(..., description="Exact destination (storage-root relative, under workspace/)"),
    base_sha: str = Query(
        "",
        description="sha256 the replica believes the server currently has. "
        "'' = replica thinks the file is new. Mismatch → 409 with the "
        "server's current sha (conflict signal — resolve client-side).",
    ),
    device: str = Query("", description="Replica device id (telemetry only)"),
    auth: dict = Depends(require_auth),
):
    """Sync write model: put raw bytes at an EXACT workspace path.

    Unlike /storage/upload (browser multipart, name-defanged, no-clobber
    suffixing) this is the replication primitive: the path is honoured
    verbatim, writes are atomic (temp file → os.replace), and optimistic
    concurrency runs on ``base_sha`` so two PCs can't silently clobber
    each other.
    """
    import os as _os
    import uuid as _uuid

    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    from service.utils import workspace_sync

    root, ws, target = _workspace_target(storage_path, path)
    if target == ws:
        raise HTTPException(status_code=403, detail="path must name a file")

    # Optimistic concurrency: compare against what's on disk right now.
    if target.exists():
        if target.is_dir():
            raise HTTPException(status_code=409, detail={"conflict": "is_dir"})
        cur = await asyncio.to_thread(workspace_sync.hash_file, target)
        if cur != base_sha:
            raise HTTPException(
                status_code=409,
                detail={"conflict": "modified", "current_sha": cur},
            )
    elif base_sha:
        # Replica thinks it's updating, but the file is gone server-side
        # (edit-vs-delete). Edit wins: accept the write (resurrect).
        pass

    # Quota: use Content-Length when the client sends one; the streaming
    # cap below still enforces the hard per-file limit either way.
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    await _enforce_workspace_quota(str(root), declared)

    max_bytes = _workspace_max_file_bytes()
    tmp_dir = root / ".geny-sync-tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"put-{_uuid.uuid4().hex}"

    import hashlib as _hashlib

    h = _hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"file exceeds {max_bytes // (1024*1024)} MiB",
                    )
                h.update(chunk)
                out.write(chunk)
        # Final re-verify + replace under the storage lock: the pre-check
        # above is stale after seconds of streaming — two PCs racing the
        # same path must produce a 409 (conflict flow), never a silent
        # last-writer-wins.
        clash = await asyncio.to_thread(
            workspace_sync.commit_file, str(root), tmp, target, base_sha
        )
        if clash == "__is_dir__":
            raise HTTPException(status_code=409, detail={"conflict": "is_dir"})
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail={"conflict": "modified", "current_sha": clash},
            )
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except Exception:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="write failed")

    latest = await _sync_touch(_notify_key, str(root))
    # A replica push: attribute it to the machine, not to "the agent". The
    # scan would otherwise see the same bytes land and file it as agent work.
    await _history(storage_path, request, auth,
                   "updated" if base_sha else "added",
                   _ws_path(ws, target), size)
    return {
        "ok": True,
        "path": _ws_path(ws, target),
        "sha256": h.hexdigest(),
        "size": size,
        "latest_seq": latest,
    }


# ── chunked / resumable upload (files above the connector's single-PUT
#    threshold). Sequential parts into .geny-sync-tmp/chunks/<id>.part,
#    then an atomic commit with the same base_sha conflict dance. ──────


@router.post("/{session_id}/storage/file/chunks/start")
async def chunk_upload_start(
    session_id: str = Path(..., description="Session ID"),
    path: str = Query(..., description="Final destination (storage-root relative, under workspace/)"),
    size: int = Query(..., ge=1, description="Total file size in bytes"),
    sha256: str = Query(..., min_length=64, max_length=64, description="sha256 of the full file"),
    auth: dict = Depends(require_auth),
):
    import json as _json
    import uuid as _uuid

    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    from service.utils import workspace_sync

    root, ws, target = _workspace_target(storage_path, path)
    if target == ws:
        raise HTTPException(status_code=403, detail="path must name a file")
    if size > _workspace_max_file_bytes():
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {_workspace_max_file_bytes() // (1024*1024)} MiB",
        )
    await _enforce_workspace_quota(str(root), size)

    cdir = workspace_sync.chunk_dir(str(root))
    cdir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(workspace_sync.gc_stale_uploads, str(root))

    upload_id = _uuid.uuid4().hex
    (cdir / f"{upload_id}.part").touch()
    (cdir / f"{upload_id}.meta").write_text(
        _json.dumps({"path": path, "size": size, "sha256": sha256}),
        encoding="utf-8",
    )
    return {"upload_id": upload_id, "received": 0}


def _chunk_paths(session_id: str, upload_id: str):
    from pathlib import Path as _P

    from service.utils import workspace_sync

    if not workspace_sync.valid_upload_id(upload_id):
        raise HTTPException(status_code=400, detail="bad upload id")
    root = _P(_storage_root_live_or_dormant(session_id)).resolve()
    cdir = workspace_sync.chunk_dir(str(root))
    part = cdir / f"{upload_id}.part"
    meta = cdir / f"{upload_id}.meta"
    if not meta.exists():
        raise HTTPException(status_code=404, detail="unknown upload (expired?)")
    return root, part, meta


@router.get("/{session_id}/storage/file/chunks/{upload_id}")
async def chunk_upload_state(
    session_id: str = Path(...),
    upload_id: str = Path(...),
    auth: dict = Depends(require_auth),
):
    """Resume point: how many bytes the server already holds."""
    _enforce_session_owner(session_id, auth)
    _root, part, _meta = _chunk_paths(session_id, upload_id)
    return {"received": part.stat().st_size if part.exists() else 0}


@router.put("/{session_id}/storage/file/chunks/{upload_id}")
async def chunk_upload_part(
    request: Request,
    session_id: str = Path(...),
    upload_id: str = Path(...),
    offset: int = Query(..., ge=0, description="Byte offset — must equal bytes already received (sequential)"),
    auth: dict = Depends(require_auth),
):
    import json as _json

    _enforce_session_owner(session_id, auth)
    _root, part, meta = _chunk_paths(session_id, upload_id)
    info = _json.loads(meta.read_text(encoding="utf-8"))
    received = part.stat().st_size if part.exists() else 0
    if offset != received:
        # Out-of-order / duplicate part → tell the client where to resume.
        raise HTTPException(status_code=409, detail={"received": received})

    total = int(info["size"])
    written = 0
    with part.open("ab") as out:
        async for chunk in request.stream():
            written += len(chunk)
            if received + written > total:
                raise HTTPException(status_code=413, detail="exceeds declared size")
            out.write(chunk)
    return {"received": received + written}


@router.post("/{session_id}/storage/file/chunks/{upload_id}/commit")
async def chunk_upload_commit(
    session_id: str = Path(...),
    upload_id: str = Path(...),
    base_sha: str = Query("", description="Same conflict contract as PUT /storage/file"),
    auth: dict = Depends(require_auth),
):
    import json as _json
    import os as _os

    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    from service.utils import workspace_sync

    root, part, meta = _chunk_paths(session_id, upload_id)
    info = _json.loads(meta.read_text(encoding="utf-8"))

    received = part.stat().st_size if part.exists() else 0
    if received != int(info["size"]):
        raise HTTPException(
            status_code=409, detail={"received": received, "expected": int(info["size"])}
        )
    actual_sha = await asyncio.to_thread(workspace_sync.hash_file, part)
    if actual_sha != info["sha256"]:
        part.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="content hash mismatch — restart upload")

    _root2, ws, target = _workspace_target(storage_path, info["path"])
    # Quota re-check at commit: the start-time check can be stale after
    # other uploads landed in between.
    if not target.exists():
        await _enforce_workspace_quota(str(root), received)
    # Atomic verify+replace under the storage lock (same anti-race
    # contract as PUT). On conflict the staged part is dropped — the
    # replica re-uploads after resolving.
    clash = await asyncio.to_thread(
        workspace_sync.commit_file, str(root), part, target, base_sha
    )
    if clash == "__is_dir__":
        meta.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail={"conflict": "is_dir"})
    if clash is not None:
        meta.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409, detail={"conflict": "modified", "current_sha": clash}
        )
    meta.unlink(missing_ok=True)

    latest = await _sync_touch(_notify_key, str(root))
    return {
        "ok": True,
        "path": _ws_path(ws, target),
        "sha256": actual_sha,
        "size": received,
        "latest_seq": latest,
    }


#: Where a session records which of its workspace subdirectories are
#: LINKED FOLDERS — folders that live on a user's computer and are shared
#: into this agent through GenyDrive. Kept OUTSIDE workspace/ on purpose:
#: anything inside it would sync straight back into the user's own folder.
_LINKS_FILE = ".geny-links.json"


def _links_path(storage_path: str) -> str:
    import os as _os

    return _os.path.join(storage_path, _LINKS_FILE)


def _actor_of(request: Optional[Request], auth: dict) -> tuple:
    """Who is making this call: a replica, or a person on the web?

    A replica identifies itself with `X-Geny-Device-Id`/`-Name` (the same
    identity it uses on the sync socket). Anything else is a human in the
    browser. The distinction is the whole point of the history: "a file you
    did not touch changed" is only answerable if the actor is recorded at
    the moment of the change.
    """
    user = str((auth or {}).get("display_name") or (auth or {}).get("sub") or "")
    if request is not None:
        device_id = request.headers.get("X-Geny-Device-Id") or ""
        if device_id:
            # The header is percent-encoded so a non-ASCII machine name
            # ("내-데스크톱") survives HTTP header transport intact.
            raw = request.headers.get("X-Geny-Device-Name") or ""
            name = unquote(raw) if raw else device_id[:8]
            return "device", name or device_id[:8]
    return "web", user


async def _history(
    storage_path: str, request: Optional[Request], auth: dict,
    action: str, path: str = "", size: int = 0, detail: str = "",
) -> None:
    """Record one history row for a COMPLETED operation.

    Off-loop (SQLite) and swallowing (this runs after the operation already
    succeeded — the screen-observation outage was exactly a bookkeeping step
    turning finished work into a 500).
    """
    from service.utils import workspace_sync

    kind, actor = _actor_of(request, auth)
    # Normalise to WORKSPACE-relative, the same frame the scan uses. The
    # handlers work in storage-root-relative paths ("workspace/a/b"), and
    # without this the de-duplication never matches its own scan row — every
    # attributed change got filed twice, once correctly and once as "agent".
    rel = path[len("workspace/"):] if path.startswith("workspace/") else path
    try:
        await asyncio.to_thread(
            workspace_sync.record_event, storage_path,
            actor_kind=kind, actor=actor, action=action,
            path=rel, size=size, detail=detail,
        )
    except Exception:  # noqa: BLE001
        logger.debug("history record skipped", exc_info=True)


@router.get("/{session_id}/storage/history")
async def storage_history(
    session_id: str = Path(..., description="Storage scope"),
    limit: int = Query(200, ge=1, le=500),
    before_id: int = Query(0, ge=0),
    auth: dict = Depends(require_auth),
):
    """Newest-first history of everything that happened to this storage."""
    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    from service.utils import workspace_sync

    return await asyncio.to_thread(
        workspace_sync.list_events, storage_path, limit, before_id,
    )


@router.get("/{session_id}/storage/device-state")
async def get_device_state(
    session_id: str = Path(..., description="Storage scope"),
    device_id: str = Query(..., min_length=1, max_length=64),
    auth: dict = Depends(require_auth),
):
    """The last cursor this device and the server agreed on.

    A replica reads this when its own merge base is gone (torn index after a
    power cut, reinstall, new disk). Without it the replica cannot tell a
    server-side deletion from a local creation and resurrects every deleted
    file — measured: 10/10 deletions came back and were pushed into the
    cloud. With it, the deletions are still in the delta from this cursor.
    """
    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    from service.utils import workspace_sync

    state = await asyncio.to_thread(
        workspace_sync.get_device_state, storage_path, device_id,
    )
    return {"state": state}


@router.put("/{session_id}/storage/device-state")
async def put_device_state(
    payload: Dict[str, Any],
    session_id: str = Path(..., description="Storage scope"),
    auth: dict = Depends(require_auth),
):
    """Advance this device's agreement pointer after a clean round.

    Also pins journal retention: tombstones above a live device's cursor are
    the only record that a deletion happened, so they survive the age-based
    prune while that device is still around.
    """
    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    from service.utils import workspace_sync

    device_id = str(payload.get("device_id") or "").strip()[:64]
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
    try:
        cursor = int(payload.get("cursor") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="cursor must be an integer") from None
    return await asyncio.to_thread(
        workspace_sync.set_device_state, storage_path, device_id, cursor,
        str(payload.get("device_name") or "")[:64],
    )


@router.get("/{session_id}/storage/links")
async def get_storage_links(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Linked folders projected into this workspace.

    The binding graph ([폴더 ↔ GenyDrive] × [GenyDrive ↔ 에이전트]) lives in
    the connector, so without this the web explorer cannot tell a linked
    folder from an ordinary directory — it would show someone's laptop
    folder as if the agent had created it.
    """
    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    try:
        with open(_links_path(storage_path), "r", encoding="utf-8") as f:
            data = json.load(f)
        links = data.get("links") or []
    except (OSError, ValueError):
        links = []
    return {"links": links}


@router.put("/{session_id}/storage/links")
async def put_storage_links(
    payload: Dict[str, Any],
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Publish this device's linked-folder set for the session.

    Written by the connector whenever the drive is reconciled. Entries are
    {name, device} — never the local path: which folder on which machine
    is the user's business, and the workspace is shared with an agent.
    """
    _enforce_scope_owner(session_id, auth)
    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    incoming = payload.get("links")
    if not isinstance(incoming, list):
        raise HTTPException(status_code=400, detail="links must be a list")
    links = []
    for item in incoming[:200]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or "/" in name or "\\" in name or name.startswith("."):
            continue
        # `agents/` and `gapt/` are the cloud's own structure. A linked folder
        # taking one of those names would be mirrored on top of it.
        from service.cloud import RESERVED_CLOUD_NAMES

        if name.lower() in RESERVED_CLOUD_NAMES:
            logger.warning("link name %r is reserved by the cloud — skipped", name)
            continue
        links.append({
            "name": name[:200],
            "device": str(item.get("device") or "")[:100],
            # Stable attribution. `device` is a hostname, which two machines
            # can share and a user can change; the id survives both.
            "device_id": str(item.get("device_id") or "")[:64],
        })
    body = json.dumps({"links": links}, ensure_ascii=False)

    def _write() -> None:
        with open(_links_path(storage_path), "w", encoding="utf-8") as f:
            f.write(body)

    await asyncio.to_thread(_write)
    return {"ok": True, "links": links}


@router.get("/cloud/members")
async def cloud_members(auth: dict = Depends(require_auth)):
    """Which of the caller's agents are connected to their GenyCloud."""
    from service.cloud import connected_sessions

    user = (auth or {}).get("sub") or "anonymous"
    return {"sessions": connected_sessions(user)}


@router.get("/cloud/devices")
async def cloud_devices(auth: dict = Depends(require_auth)):
    """The caller's computers attached to their cloud, and what each shares.

    One of the three things that hang off a cloud — machines, agents, and
    (through a machine) individual folders. The rail needs all three, and a
    machine has to stay listed while it is asleep: a laptop that vanished on
    sleep would read as unpaired, and the folders it shares would lose the
    machine they belong to.

    So the answer is the union of the persisted pairings and the live socket
    list, with `online` marking which is which. Folders are attributed to
    their machine by device_id, falling back to the machine NAME for ledgers
    written by connectors that predate device_id in the link entries.
    """
    from service.cloud import cloud_notify_key, cloud_storage_path, known_devices
    from ws.workspace_stream import get_workspace_hub

    user = (auth or {}).get("sub") or "anonymous"
    hub_key = cloud_notify_key(user)
    live = {d["device_id"]: d for d in get_workspace_hub().devices(hub_key)}

    def _read_links() -> list:
        try:
            with open(_links_path(cloud_storage_path(user)), "r", encoding="utf-8") as f:
                return (json.load(f) or {}).get("links") or []
        except (OSError, ValueError):
            return []

    known, links = await asyncio.gather(
        asyncio.to_thread(known_devices, user),
        asyncio.to_thread(_read_links),
    )

    rows = {d["device_id"]: dict(d) for d in known}
    for device_id, d in live.items():          # a live machine not yet persisted
        rows.setdefault(device_id, {"device_id": device_id, "device_name": d.get("device_name") or ""})

    out = []
    for device_id, row in rows.items():
        name = row.get("device_name") or ""
        out.append({
            "device_id": device_id,
            "device_name": name,
            "online": device_id in live,
            "last_seen": row.get("last_seen"),
            "links": [
                {"name": link.get("name")}
                for link in links
                if link.get("device_id") == device_id
                or (not link.get("device_id") and link.get("device") == name)
            ],
        })
    # Online first, then most recently seen — the machine the user is sitting
    # at should not be below one they last used in March.
    out.sort(key=lambda d: (not d["online"], -(d.get("last_seen") or 0)))

    # Folders whose machine is unknown (ledger written before device_id, and
    # no name match) would otherwise disappear from the UI entirely.
    claimed = {link["name"] for d in out for link in d["links"]}
    orphans = [{"name": link.get("name")} for link in links if link.get("name") not in claimed]
    return {"devices": out, "unassigned_links": orphans}


@router.put("/{session_id}/cloud")
async def set_cloud_connection(
    payload: Dict[str, Any],
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Connect or disconnect ONE agent to the user's GenyCloud.

    Connecting gives the agent a `cloud/` path inside its workspace that
    resolves to the shared cloud — a reference, so the agent operates on
    the same bytes as the user's devices and every other connected agent.
    Disconnecting removes the reference; **nothing in the cloud is
    deleted** (it was never this agent's copy) and the agent's own
    workspace is untouched.

    Takes effect immediately for new turns; a live pipeline picks the new
    root up when its tools are next built.
    """
    _enforce_session_owner(session_id, auth)
    from service.cloud import adopt_agent_space, set_connected

    user = (auth or {}).get("sub") or "anonymous"
    connected = bool(payload.get("connected"))
    storage_path = _storage_root_live_or_dormant(session_id)

    if connected:
        # The agent's space is inside the cloud either way; connecting only
        # widens what it may reach from its own directory to the whole shared
        # tree. Adoption is idempotent, so calling it here just makes sure the
        # space exists before the roots are rebound.
        await asyncio.to_thread(adopt_agent_space, user, storage_path, session_id)

    sessions = await asyncio.to_thread(set_connected, user, session_id, connected)
    # The link changes what the agent can reach, so its tools must be
    # rebuilt — otherwise the running pipeline keeps the old allowed_paths.
    try:
        agent = agent_manager.get_agent(session_id)
        if agent is not None and hasattr(agent, "rebind_tool_roots"):
            agent.rebind_tool_roots()
        # Host-side roots are re-read per turn; the SANDBOX bind is baked into
        # its container mount, so it has to be rebuilt to follow the toggle.
        if agent is not None and hasattr(agent, "invalidate_sandbox_binding"):
            await agent.invalidate_sandbox_binding()
    except Exception:  # noqa: BLE001 — worst case it applies next build
        pass
    return {"connected": connected, "sessions": sessions}


@router.get("/{session_id}/storage/sync-devices")
async def storage_sync_devices(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Replicas currently attached to this workspace (web UI chip)."""
    _enforce_session_owner(session_id, auth)
    from ws.workspace_stream import get_workspace_hub

    return {"devices": get_workspace_hub().devices(session_id)}


@router.get("/{session_id}/storage-raw/{file_path:path}")
async def download_storage_file_raw(
    session_id: str = Path(..., description="Session ID"),
    file_path: str = Path(..., description="File path relative to session storage"),
    auth: dict = Depends(require_auth),
):
    """Serve a session-storage file as raw bytes (binary download / inline view).

    The chat attachment renderer points ``<img src>`` / ``<a href>`` here for
    files the agent delivered via SendUserFile (workspace-canvas P1) — auth
    rides on the ``geny_auth_token`` cookie same-origin. Unlike the JSON
    ``/storage/{path}`` reader this streams bytes with the real content type.
    Works for dormant sessions too (storage_path from the session store), so
    links keep working after a backend restart.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    import mimetypes as _mimetypes
    from pathlib import Path as _FilePath

    from starlette.responses import FileResponse

    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    root = _FilePath(storage_path).resolve()
    target = (root / file_path).resolve()
    if not _within_scope(root, target):
        raise HTTPException(status_code=403, detail="Path escapes session storage")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    media_type = _mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type, filename=target.name)


# ── On-demand Canvas document preview (edit2docs, no agent / no LibreOffice) ──

_DOC_PREVIEW_EXTS = {".pptx", ".docx", ".xlsx", ".pdf"}
_DOC_PREVIEW_SEM = asyncio.Semaphore(2)  # bound concurrent CPU-bound renders


def _doc_page_num(p) -> int:
    import re as _re

    m = _re.search(r"(\d+)", p.stem)
    return int(m.group(1)) if m else 0


def _render_doc_preview(src, ext: str, cache_dir):
    """Render *src* into *cache_dir* → (kind, [page paths]). Runs in a thread."""
    import edit2docs

    if ext == ".pptx":
        edit2docs.preview_doc(str(src), out_dir=str(cache_dir))  # slide_NNN.svg
        pages = sorted(cache_dir.glob("slide_*.svg"))
        return ("svg", pages)
    if ext in (".docx", ".xlsx"):
        edit2docs.render_doc(str(src), to="png", out_dir=str(cache_dir), dpi=120)
        pages = sorted(cache_dir.glob("page-*.png"), key=_doc_page_num)
        return ("png", pages)
    if ext == ".pdf":
        from tools.built_in.document_tools import _pdf_to_pngs

        pages = _pdf_to_pngs(src, cache_dir)
        return ("png", pages)
    raise ValueError(f"unsupported preview ext {ext}")


@router.get("/{session_id}/doc-preview")
async def get_doc_preview(
    session_id: str = Path(..., description="Session ID"),
    path: str = Query(..., description="File path relative to session storage"),
    auth: dict = Depends(require_auth),
):
    """On-demand Canvas preview — render an office/pdf file to per-slide SVGs
    (pptx, via ``edit2docs.preview_doc``) or page PNGs (docx/xlsx via
    ``edit2docs.render_doc``; pdf via pdftoppm). No agent turn and — for the
    modern office formats — no LibreOffice. The result is cached under
    ``.canvas-preview/<key>/<mtime>/`` keyed on the source's mtime, so
    re-selecting a file is instant and an edited doc re-renders automatically.
    Returns page paths (relative to storage) that the client loads through the
    ``storage-raw`` endpoint. Works for dormant sessions too."""
    _enforce_session_owner(session_id, auth)  # audit S6
    import hashlib
    import shutil
    from pathlib import Path as _FilePath

    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)
    root = _FilePath(storage_path).resolve()
    src = (root / path).resolve()
    if not _within_scope(root, src):
        raise HTTPException(status_code=403, detail="Path escapes session storage")
    if not src.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    ext = src.suffix.lower()
    if ext not in _DOC_PREVIEW_EXTS:
        return {"kind": "unsupported", "count": 0, "pages": []}

    mtime = int(src.stat().st_mtime)
    key = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
    rel_base = f".canvas-preview/{key}/{mtime}"
    cache_dir = root / ".canvas-preview" / key / str(mtime)

    def _cached_pages():
        if not cache_dir.is_dir():
            return None
        svgs = sorted(cache_dir.glob("slide_*.svg"))
        if svgs:
            return ("svg", svgs)
        pngs = sorted(cache_dir.glob("page-*.png"), key=_doc_page_num)
        if pngs:
            return ("png", pngs)
        return None

    result = _cached_pages()
    if result is None:
        # Prune stale mtime dirs for this file so the cache doesn't grow forever.
        try:
            parent = cache_dir.parent
            if parent.is_dir():
                for old in parent.iterdir():
                    if old.is_dir() and old.name != str(mtime):
                        await rmtree_async(old, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
        cache_dir.mkdir(parents=True, exist_ok=True)
        async with _DOC_PREVIEW_SEM:
            result = _cached_pages()  # another request may have rendered it
            if result is None:
                try:
                    result = await asyncio.to_thread(
                        _render_doc_preview, src, ext, cache_dir
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "doc-preview render failed for %s: %s", path, e, exc_info=True
                    )
                    raise HTTPException(
                        status_code=422, detail=f"Preview render failed: {e}"
                    )

    kind, pages = result
    return {
        "kind": kind,
        "count": len(pages),
        "pages": [f"{rel_base}/{p.name}" for p in pages],
    }


@router.get("/{session_id}/storage/{file_path:path}")
async def read_storage_file(
    session_id: str = Path(..., description="Session ID"),
    file_path: str = Path(..., description="File path"),
    encoding: str = Query("utf-8", description="File encoding"),
    auth: dict = Depends(require_auth),
):
    """
    Read storage file content. Works for dormant sessions too.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    from service.utils import file_storage as storage_utils

    storage_path, _notify_key = _resolve_storage_scope(session_id, auth)

    file_content = storage_utils.read_storage_file(
        storage_path, file_path, encoding=encoding, session_id=session_id
    )
    if not file_content:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    return StorageFileContent(
        session_id=session_id,
        **file_content
    )


@router.get("/{session_id}/download-folder")
async def download_storage_folder(
    session_id: str = Path(..., description="Session ID"),
    path: str = Query("", description="Optional subfolder (storage-root relative) to zip instead of the whole storage"),
    auth: dict = Depends(require_auth),
):
    """
    Download the session's storage folder as a ZIP archive.

    Streams the ZIP file directly so the browser triggers a download.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    import os
    import io
    import zipfile
    from fastapi.responses import StreamingResponse

    # Resolve storage path — live agent first, then session store
    agent = agent_manager.get_agent(session_id)
    if agent and agent.storage_path:
        folder = agent.storage_path
    else:
        store = get_session_store()
        session_data = store.get(session_id)
        if session_data and session_data.get("storage_path"):
            folder = session_data["storage_path"]
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Session not found or no storage path: {session_id}",
            )

    if path:
        from pathlib import Path as _P

        sub = (_P(folder) / path).resolve()
        try:
            sub.relative_to(_P(folder).resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Path escapes session storage")
        folder = str(sub)

    if not os.path.isdir(folder):
        raise HTTPException(
            status_code=404, detail=f"Folder does not exist: {folder}"
        )

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(folder):
            for fname in files:
                abs_path = os.path.join(root, fname)
                arc_name = os.path.relpath(abs_path, folder)
                try:
                    zf.write(abs_path, arc_name)
                except (PermissionError, OSError):
                    pass  # skip unreadable files
    buf.seek(0)

    zip_filename = f"session-{session_id[:8]}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"'
        },
    )


# ============================================================================
# Graph Introspection API
# ============================================================================


class GraphNodeInfo(BaseModel):
    """Single node/state in the graph."""
    id: str
    label: str
    type: str = "node"  # node | start | end
    description: str = ""
    prompt_template: Optional[str] = None
    metadata: dict = {}


class GraphEdgeInfo(BaseModel):
    """Single edge in the graph."""
    source: str
    target: str
    label: str = ""
    type: str = "edge"  # edge | conditional
    condition_map: Optional[dict] = None


class GraphStructure(BaseModel):
    """Complete graph topology for visualization."""
    session_id: str
    session_name: str = ""
    graph_type: str = "simple"  # simple | autonomous
    nodes: list[GraphNodeInfo] = []
    edges: list[GraphEdgeInfo] = []



@router.get("/{session_id}/graph")
async def get_session_graph(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Get pipeline info for a session (replaces workflow graph)."""
    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    wid = getattr(agent, '_workflow_id', '') or ''
    preset = 'vtuber' if 'vtuber' in wid else 'worker_adaptive'

    return {
        "session_id": session_id,
        "preset": preset,
        "workflow_id": wid,
        "execution_backend": "pipeline",
    }


@router.get("/{session_id}/workflow")
async def get_session_workflow(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Get pipeline preset info (replaces workflow definition)."""
    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    wid = getattr(agent, '_workflow_id', '') or ''
    preset = 'vtuber' if 'vtuber' in wid else 'worker_adaptive'

    return {
        "id": wid or f"preset-{preset}",
        "name": preset,
        "preset": preset,
        "execution_backend": "pipeline",
    }


# ============================================================================
# G2.5 — HITL endpoints (Stage 15 / Pipeline.resume API)
# ============================================================================
#
# An external decision channel (typically the frontend HITL modal,
# reached over /api/agents) satisfies pending HITL requests by posting
# the operator's decision to /api/agents/{session_id}/hitl/resume.
# The endpoint dispatches to ``Pipeline.resume(token, decision)``,
# which resolves the asyncio.Future the HITLStage's
# PipelineResumeRequester is awaiting on.


class HITLResumeRequest(BaseModel):
    token: str = Field(..., description="HITL request token issued by the pipeline")
    decision: str = Field(..., description="approve | reject | cancel")


class HITLPendingItem(BaseModel):
    token: str


class HITLPendingResponse(BaseModel):
    session_id: str
    pending: List[HITLPendingItem]


def _resolve_pipeline(session_id: str):
    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    pipeline = getattr(agent, "_pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=409,
            detail=f"Session {session_id} has no built pipeline yet",
        )
    return pipeline


@router.get(
    "/{session_id}/hitl/pending",
    response_model=HITLPendingResponse,
    summary="List pending HITL request tokens",
)
async def list_pending_hitl(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Returns the tokens of unresolved HITL requests this session is
    awaiting. Drives the frontend HITL modal's "approval needed"
    indicator without forcing it to subscribe to the WebSocket
    event stream just to discover what's outstanding."""
    pipeline = _resolve_pipeline(session_id)
    list_pending = getattr(pipeline, "list_pending_hitl", None)
    if not callable(list_pending):
        # Pipelines built before geny-executor 1.0 / S9c.1 don't have
        # the resume API. Treat as "no pending" rather than 500 so
        # mixed-version deployments degrade gracefully.
        return HITLPendingResponse(session_id=session_id, pending=[])
    tokens: List[str] = list_pending() or []
    return HITLPendingResponse(
        session_id=session_id,
        pending=[HITLPendingItem(token=t) for t in tokens],
    )


@router.post(
    "/{session_id}/hitl/resume",
    summary="Resolve a pending HITL request",
)
async def resume_hitl(
    body: HITLResumeRequest,
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Resolve a pending HITL request by token + decision. Calls
    :meth:`Pipeline.resume(token, decision)` which sets the future
    the HITL stage's :class:`PipelineResumeRequester` is awaiting on,
    so the loop continues from where it paused.

    Returns 404 when the session is unknown, 409 when the pipeline
    has no resume API or the token is unknown / already resolved,
    400 when the decision string is unrecognised.
    """
    pipeline = _resolve_pipeline(session_id)
    resume = getattr(pipeline, "resume", None)
    if not callable(resume):
        raise HTTPException(
            status_code=409,
            detail="pipeline has no resume() — geny-executor < 1.0 in use",
        )
    try:
        resume(body.token, body.decision)
    except KeyError:
        raise HTTPException(status_code=409, detail=f"unknown HITL token: {body.token}")
    except RuntimeError as exc:  # already resolved
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:  # unknown decision
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "session_id": session_id,
        "token": body.token,
        "decision": body.decision,
        "resumed": True,
    }


@router.delete(
    "/{session_id}/hitl/{token}",
    summary="Cancel a pending HITL request",
)
async def cancel_hitl(
    session_id: str = Path(..., description="Session ID"),
    token: str = Path(..., description="HITL request token"),
    auth: dict = Depends(require_auth),
):
    """Cancel a pending HITL request. Equivalent to ``resume`` with
    decision ``cancel`` but a separate verb for "session terminated,
    drop in-flight approvals" cleanup paths.

    Returns 404 when the session is unknown, 409 when the pipeline
    has no resume API, and ``cancelled=False`` (with 200) when the
    token is unknown or already resolved.
    """
    pipeline = _resolve_pipeline(session_id)
    cancel = getattr(pipeline, "cancel_pending_hitl", None)
    if not callable(cancel):
        raise HTTPException(
            status_code=409,
            detail="pipeline has no cancel_pending_hitl() — geny-executor < 1.0",
        )
    cancelled = bool(cancel(token))
    return {"session_id": session_id, "token": token, "cancelled": cancelled}


# ============================================================================
# G7.1 — Checkpoint listing + restore (Stage 20 / restore_state_from_checkpoint)
# ============================================================================
#
# Stage 20 (Persist) writes checkpoint snapshots to disk via the
# session-scoped FilePersister installed by service.persist.install.
# These endpoints expose the read side: list available checkpoint ids
# and trigger a restore. The actual state rebuild happens inside the
# executor's ``restore_state_from_checkpoint`` helper (S9c.2). The
# endpoint here resolves the session's storage_path and dispatches.


class CheckpointInfo(BaseModel):
    checkpoint_id: str = Field(..., description="Stable id (filename stem)")
    written_at: float = Field(..., description="Unix mtime of the checkpoint file")
    size_bytes: int = Field(..., description="On-disk size")


class CheckpointListResponse(BaseModel):
    session_id: str
    checkpoints: List[CheckpointInfo]


class CheckpointRestoreRequest(BaseModel):
    checkpoint_id: str = Field(..., description="Checkpoint id from /checkpoints list")


def _resolve_storage_path(session_id: str) -> str:
    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    storage_path = getattr(agent, "storage_path", None)
    if not storage_path:
        raise HTTPException(
            status_code=409,
            detail=f"Session {session_id} has no storage_path — checkpoints unavailable",
        )
    return str(storage_path)


@router.get(
    "/{session_id}/checkpoints",
    response_model=CheckpointListResponse,
    summary="List crash-recovery checkpoints for a session",
)
async def list_checkpoints_endpoint(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Enumerate the checkpoints Stage 20 has written for *session_id*.

    Returns ``[]`` when the session has never written a checkpoint
    (the vtuber preset keeps persist off by default, so this is the
    expected response there).
    """
    storage_path = _resolve_storage_path(session_id)
    from service.persist.restore import list_checkpoints

    items = [CheckpointInfo(**c) for c in list_checkpoints(storage_path)]
    return CheckpointListResponse(session_id=session_id, checkpoints=items)


@router.post(
    "/{session_id}/checkpoints/restore",
    summary="Restore the agent's pipeline state from a checkpoint",
)
async def restore_checkpoint_endpoint(
    body: CheckpointRestoreRequest,
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """Rebuild a :class:`PipelineState` from the given checkpoint id
    and bind it onto the session's active pipeline.

    Runtime fields (``llm_client`` / ``session_runtime``) are
    intentionally *not* restored — they're rebound by the next pipeline
    run. This matches the executor's ``restore_state_from_checkpoint``
    contract.

    Returns 404 when the session is unknown, 409 when the session has
    no storage_path or the executor pin is too old, and 410 when the
    checkpoint id doesn't exist.
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    storage_path = _resolve_storage_path(session_id)
    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    from service.persist.restore import (
        CheckpointNotFoundError,
        restore_checkpoint,
    )

    try:
        state = await restore_checkpoint(storage_path, body.checkpoint_id)
    except ImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CheckpointNotFoundError:
        raise HTTPException(
            status_code=410,
            detail=f"Checkpoint not found: {body.checkpoint_id}",
        )

    # Apply the restored state to the session's pipeline. The pipeline
    # carries the runtime objects; we only swap the message / tasks /
    # memory_refs / turn_summary / etc. fields the persister captured.
    pipeline = getattr(agent, "_pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=409,
            detail=f"Session {session_id} has no built pipeline yet",
        )
    # Pipeline owns its state; assign on the next run via the standard
    # entry point. We expose the restored fields on the agent so the
    # next execute_command can pick them up. Each agent surface has
    # its own conventions; for now we surface the restored state
    # on the agent so the caller can inspect via /state.
    setattr(agent, "_restored_state", state)

    return {
        "session_id": session_id,
        "checkpoint_id": body.checkpoint_id,
        "restored": True,
        "messages_restored": len(getattr(state, "messages", []) or []),
    }


# ============================================================================
# G8.1 — Per-session MCP admin (Phase 6 MCPManager.connect / disconnect FSM)
# ============================================================================
#
# The executor's MCPManager lives on each pipeline (Pipeline._mcp_manager).
# These endpoints expose its public API so an operator can add /
# disable / enable / disconnect MCP servers on a *running* session
# without restarting the process. State changes flow back over the
# WebSocket as `mcp_server_state` events (G8.2 wires the bridge).


class MCPServerStateInfo(BaseModel):
    name: str
    state: str
    last_error: Optional[str] = None


class MCPServerListResponse(BaseModel):
    session_id: str
    servers: List[MCPServerStateInfo]


class MCPServerAddRequest(BaseModel):
    name: str = Field(..., description="Unique server name")
    config: Dict[str, Any] = Field(
        ..., description="Transport-specific config dict (command, url, env, etc.)"
    )


def _resolve_mcp_manager(session_id: str):
    pipeline = _resolve_pipeline(session_id)
    manager = getattr(pipeline, "_mcp_manager", None) or getattr(
        pipeline, "mcp_manager", None
    )
    if manager is None:
        raise HTTPException(
            status_code=409,
            detail=f"Session {session_id} pipeline has no MCPManager attached",
        )
    return manager


def _serialize_server(name: str, manager: Any) -> MCPServerStateInfo:
    """Best-effort: read state from MCPManager. The exact API varies by
    executor minor version (`get_state` / `state_of` / `_states[name]`),
    so try a couple of shapes before falling back to ``unknown``."""
    state = "unknown"
    last_error: Optional[str] = None
    for attr in ("get_state", "state_of"):
        getter = getattr(manager, attr, None)
        if callable(getter):
            try:
                value = getter(name)
                state = getattr(value, "value", str(value))
                break
            except Exception:
                continue
    states_dict = getattr(manager, "_states", None) or getattr(manager, "states", None)
    if state == "unknown" and isinstance(states_dict, dict) and name in states_dict:
        value = states_dict[name]
        state = getattr(value, "value", str(value))
    errors = getattr(manager, "_errors", None) or getattr(manager, "errors", None)
    if isinstance(errors, dict):
        err = errors.get(name)
        if err:
            last_error = str(err)
    return MCPServerStateInfo(name=name, state=state, last_error=last_error)


@router.get(
    "/{session_id}/mcp/servers",
    response_model=MCPServerListResponse,
    summary="List MCP servers attached to a session",
)
async def list_mcp_servers(
    session_id: str = Path(...),
    auth: dict = Depends(require_auth),
):
    """Return the MCPManager's current view of every server it knows
    about, including FSM state."""
    manager = _resolve_mcp_manager(session_id)
    names = []
    for attr in ("server_names", "list_servers"):
        getter = getattr(manager, attr, None)
        if callable(getter):
            try:
                names = list(getter())
                break
            except Exception:
                continue
        if isinstance(getter, (list, tuple, set)):
            names = list(getter)
            break
    if not names:
        configs = getattr(manager, "_configs", None) or getattr(manager, "configs", None)
        if isinstance(configs, dict):
            names = list(configs.keys())
    return MCPServerListResponse(
        session_id=session_id,
        servers=[_serialize_server(n, manager) for n in names],
    )


@router.post(
    "/{session_id}/mcp/servers",
    summary="Connect a new MCP server on a running session",
)
async def add_mcp_server(
    body: MCPServerAddRequest,
    session_id: str = Path(...),
    auth: dict = Depends(require_auth),
):
    """Dispatches to ``MCPManager.connect(name, config)``.

    Returns 409 when the executor pin doesn't expose the ``connect``
    method or the server name is already owned by the manifest
    (G8.4: manifest-declared servers win over runtime add — they
    survive session restarts and are auditable in git, so we refuse
    runtime mutation rather than silently shadowing them).
    """
    _enforce_session_owner(session_id, auth)  # audit S6
    manager = _resolve_mcp_manager(session_id)
    connect = getattr(manager, "connect", None)
    if not callable(connect):
        raise HTTPException(
            status_code=409,
            detail="MCPManager has no connect() — geny-executor < 1.0",
        )

    # G8.4: collision policy. Manifest server names live in
    # ``_manifest_server_names`` (a frozen set the install layer
    # populates from manifest.tools.mcp_servers) — when present, we
    # refuse a runtime add for the same name so the operator picks
    # an unambiguous slot. Falls open when the attribute doesn't
    # exist (older executor pin).
    manifest_owned = getattr(manager, "_manifest_server_names", None)
    if manifest_owned is None:
        # Best-effort: peek at configs that were registered before
        # any runtime add happened.
        configs = getattr(manager, "_configs", None) or getattr(manager, "configs", None)
        manifest_owned = set(configs.keys()) if isinstance(configs, dict) else set()
    if body.name in manifest_owned:
        logger.warning(
            "[%s] runtime MCP add for %r conflicts with manifest server; refused",
            session_id, body.name,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"server name '{body.name}' is already declared in the "
                "session manifest. Manifest servers are immutable at "
                "runtime — pick a different name or update the manifest "
                "and restart the session."
            ),
        )

    try:
        result = connect(body.name, body.config)
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"connect failed: {exc}")
    return {
        "session_id": session_id,
        "server": _serialize_server(body.name, manager).model_dump(),
    }


@router.delete(
    "/{session_id}/mcp/servers/{name}",
    summary="Disconnect an MCP server from a running session",
)
async def disconnect_mcp_server(
    session_id: str = Path(...),
    name: str = Path(...),
    auth: dict = Depends(require_auth),
):
    manager = _resolve_mcp_manager(session_id)
    disc = getattr(manager, "disconnect", None)
    if not callable(disc):
        raise HTTPException(status_code=409, detail="MCPManager has no disconnect()")
    try:
        result = disc(name)
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"disconnect failed: {exc}")
    return {"session_id": session_id, "name": name, "disconnected": True}


@router.post(
    "/{session_id}/mcp/servers/{name}/{action}",
    summary="Disable / enable / test an MCP server",
)
async def control_mcp_server(
    session_id: str = Path(...),
    name: str = Path(...),
    action: str = Path(..., description="One of: disable / enable / test"),
    auth: dict = Depends(require_auth),
):
    if action not in ("disable", "enable", "test"):
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    manager = _resolve_mcp_manager(session_id)
    method_name = {
        "disable": "disable_server",
        "enable": "enable_server",
        "test": "test_connection",
    }[action]
    fn = getattr(manager, method_name, None)
    if not callable(fn):
        raise HTTPException(
            status_code=409,
            detail=f"MCPManager has no {method_name}() — geny-executor < 1.0",
        )
    try:
        result = fn(name)
        if hasattr(result, "__await__"):
            result = await result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{action} failed: {exc}")
    return {
        "session_id": session_id,
        "name": name,
        "action": action,
        "result": str(result) if result is not None else "ok",
        "server": _serialize_server(name, manager).model_dump(),
    }


# ============================================================================
# G15 — Pipeline introspection (Dashboard heatmap source)
# ============================================================================
#
# Wraps geny_executor.core.introspection.introspect_all so the frontend
# Dashboard can render a per-stage strategy heatmap (green = override
# applied, red = default, grey = no slot of that name).


class StageIntrospectInfo(BaseModel):
    order: int
    name: str
    artifact: str
    strategy_slots: Dict[str, Any]
    strategy_chains: Dict[str, Any]


class PipelineIntrospectResponse(BaseModel):
    session_id: str
    stages: List[StageIntrospectInfo]


@router.get(
    "/{session_id}/pipeline/introspect",
    response_model=PipelineIntrospectResponse,
    summary="Snapshot of every registered stage + active strategies",
)
async def introspect_pipeline(
    session_id: str = Path(...),
    auth: dict = Depends(require_auth),
):
    """Returns each stage's order / name / artifact id plus the
    currently-active strategy id per slot. Drives the Dashboard's
    StageStrategyHeatmap (G15).

    409 when the executor's introspection helper isn't importable.
    """
    pipeline = _resolve_pipeline(session_id)
    try:
        from geny_executor.core.introspection import introspect_all
    except ImportError:
        raise HTTPException(
            status_code=409,
            detail="geny_executor.core.introspection unavailable",
        )

    # introspect_all walks the global stage catalog by default; pass
    # the pipeline-specific override map when one is available so we
    # report the active artifact per slot.
    artifact_overrides: Dict[str, str] = {}
    for stage in pipeline.stages:
        artifact_overrides[stage.name] = getattr(stage, "artifact", "default") or "default"

    try:
        rows = introspect_all(artifact_overrides=artifact_overrides)
    except TypeError:
        # Older signature didn't accept the kwarg.
        rows = introspect_all()

    out: List[StageIntrospectInfo] = []
    for row in rows:
        out.append(
            StageIntrospectInfo(
                order=getattr(row, "order", 0),
                name=getattr(row, "name", ""),
                artifact=getattr(row, "artifact", "default"),
                strategy_slots={
                    name: {
                        "active": getattr(slot, "active_name", None) or getattr(slot, "active", None),
                        "registered": list(getattr(slot, "registered_names", []) or []),
                    }
                    for name, slot in (getattr(row, "strategy_slots", {}) or {}).items()
                },
                strategy_chains={
                    name: {
                        "items": list(getattr(chain, "active_names", []) or []),
                        "registered": list(getattr(chain, "registered_names", []) or []),
                    }
                    for name, chain in (getattr(row, "strategy_chains", {}) or {}).items()
                },
            )
        )

    return PipelineIntrospectResponse(session_id=session_id, stages=out)
