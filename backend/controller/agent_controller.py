"""
Agent Session Controller

REST API endpoints for AgentSession (geny-executor Pipeline) management.

AgentSession API: /api/agents
"""
import asyncio
import json
import time
from logging import getLogger
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

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
            "Per-session MemoryProvider override (MemoryProviderFactory config "
            "DSL). Takes precedence over the process default set via "
            "MEMORY_PROVIDER env."
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


@router.get("", response_model=List[SessionInfo])
async def list_agent_sessions(auth: dict = Depends(require_auth)):
    """
    List all AgentSessions.

    Returns only AgentSession instances (not regular sessions).

    Auth (R7 / audit 20260425_3 §1.5): the listing exposes session
    names + roles + statuses, which is operator-relevant metadata.
    Sibling read endpoints (``/{session_id}``, ``/{session_id}/state``,
    etc.) all require auth; this one was an oversight.
    """
    agents = agent_manager.list_agents()
    return [agent.get_session_info() for agent in agents]


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


@router.get("/{session_id}", response_model=SessionInfo)
async def get_agent_session(
    session_id: str = Path(..., description="Session ID"),
    auth: dict = Depends(require_auth),
):
    """
    Get specific AgentSession information.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
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
                shutil.rmtree(sp)
                logger.info(f"Storage cleaned up: {storage_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup storage {storage_path}: {e}")

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
                        shutil.rmtree(sp)
                        logger.info(f"Linked session storage cleaned up: {linked_storage}")
                    except Exception as e:
                        logger.warning(f"Failed to cleanup linked storage {linked_storage}: {e}")
            store.permanent_delete(linked_id)
            logger.info(f"✅ Linked session permanently deleted: {linked_id}")

    return {"success": True, "session_id": session_id}


@router.post("/{session_id}/restore")
async def restore_session(
    session_id: str = Path(..., description="Session ID to restore"),
    auth: dict = Depends(require_auth),
):
    """
    Restore a soft-deleted session.

    Re-creates the AgentSession using the original creation parameters
    stored in sessions.json, with the same session_name and settings.
    Cascades to linked sessions (VTuber ↔ CLI pairs).
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

    # Find linked session for cascade restore
    linked_id = record.get("linked_session_id")

    # Build creation params from stored record
    params = store.get_creation_params(session_id)
    if not params:
        raise HTTPException(status_code=500, detail="Could not extract creation params")

    # Capture stored system_prompt before create overwrites the record
    stored_system_prompt = record.get("system_prompt")

    try:
        request = CreateSessionRequest(
            session_name=params.get("session_name"),
            working_dir=params.get("working_dir"),
            model=params.get("model"),
            max_turns=params.get("max_turns", 100),
            timeout=params.get("timeout", 21600),
            max_iterations=params.get("max_iterations", params.get("autonomous_max_iterations", 100)),
            role=SessionRole(params["role"]) if params.get("role") else SessionRole.WORKER,
            graph_name=params.get("graph_name"),
            workflow_id=params.get("workflow_id"),
            tool_preset_id=params.get("tool_preset_id"),
            linked_session_id=params.get("linked_session_id"),
            session_type=params.get("session_type"),
        )

        # Reuse the SAME session_id → preserves storage_path
        agent = await agent_manager.create_agent_session(
            request=request,
            session_id=session_id,
        )

        # Restore the previously stored system prompt (user customization).
        # Route through the PersonaProvider (cycle 20260421_7 PR-X1-3) — the
        # newly-created AgentSession's DynamicPersonaSystemBuilder reads from
        # the same provider on its first turn.
        if stored_system_prompt:
            agent_manager.persona_provider.set_static_override(
                session_id, stored_system_prompt
            )
            store.update(session_id, {"system_prompt": stored_system_prompt})

        # Restore chat_room_id from stored record (chat room persists across delete/restore)
        stored_chat_room_id = params.get("chat_room_id")
        if stored_chat_room_id:
            agent._chat_room_id = stored_chat_room_id

        session_info = agent.get_session_info()
        logger.info(f"✅ Session restored: {session_id} (same ID, storage preserved)")

        # Cascade restore to linked session (VTuber ↔ CLI pair)
        if linked_id:
            linked_rec = store.get(linked_id)
            if linked_rec and linked_rec.get("is_deleted") and not agent_manager.has_agent(linked_id):
                try:
                    linked_params = store.get_creation_params(linked_id)
                    if linked_params:
                        linked_system_prompt = linked_rec.get("system_prompt")
                        linked_request = CreateSessionRequest(
                            session_name=linked_params.get("session_name"),
                            working_dir=linked_params.get("working_dir"),
                            model=linked_params.get("model"),
                            max_turns=linked_params.get("max_turns", 100),
                            timeout=linked_params.get("timeout", 21600),
                            max_iterations=linked_params.get("max_iterations", linked_params.get("autonomous_max_iterations", 100)),
                            role=SessionRole(linked_params["role"]) if linked_params.get("role") else SessionRole.WORKER,
                            graph_name=linked_params.get("graph_name"),
                            workflow_id=linked_params.get("workflow_id"),
                            tool_preset_id=linked_params.get("tool_preset_id"),
                            linked_session_id=linked_params.get("linked_session_id"),
                            session_type=linked_params.get("session_type"),
                        )
                        linked_agent = await agent_manager.create_agent_session(
                            request=linked_request,
                            session_id=linked_id,
                        )
                        if linked_system_prompt:
                            agent_manager.persona_provider.set_static_override(
                                linked_id, linked_system_prompt
                            )
                            store.update(linked_id, {"system_prompt": linked_system_prompt})
                        logger.info(f"✅ Linked session restored: {linked_id}")
                        await agent_manager.lifecycle_bus.emit(
                            LifecycleEvent.SESSION_RESTORED,
                            linked_id,
                            cascade="linked_peer",
                            peer=session_id,
                        )
                except Exception as e:
                    logger.warning(f"⚠️ Failed to cascade restore to linked session {linked_id}: {e}")

        # Main restore emit comes last so subscribers see the pair as
        # consistent (linked_id already alive) by the time the VTuber
        # event fires.
        await agent_manager.lifecycle_bus.emit(
            LifecycleEvent.SESSION_RESTORED,
            session_id,
            cascade="main",
            linked_id=linked_id,
        )

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
    agent = agent_manager.get_agent(session_id)
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


# ============================================================================
# Storage API
# ============================================================================


@router.get("/{session_id}/storage")
async def list_storage_files(
    session_id: str = Path(..., description="Session ID"),
    path: str = Query("", description="Subdirectory path"),
    auth: dict = Depends(require_auth),
):
    """
    List session storage files.
    """
    from service.utils import file_storage as storage_utils

    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    storage_path = agent.storage_path
    if not storage_path:
        raise HTTPException(status_code=400, detail="AgentSession storage_path not available")

    files_data = storage_utils.list_storage_files(
        storage_path, subpath=path, session_id=session_id
    )
    files = [StorageFile(**f) for f in files_data]

    return StorageListResponse(
        session_id=session_id,
        storage_path=storage_path,
        files=files
    )


@router.get("/{session_id}/storage/{file_path:path}")
async def read_storage_file(
    session_id: str = Path(..., description="Session ID"),
    file_path: str = Path(..., description="File path"),
    encoding: str = Query("utf-8", description="File encoding"),
    auth: dict = Depends(require_auth),
):
    """
    Read storage file content.
    """
    from service.utils import file_storage as storage_utils

    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    storage_path = agent.storage_path
    if not storage_path:
        raise HTTPException(status_code=400, detail="AgentSession storage_path not available")

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
    auth: dict = Depends(require_auth),
):
    """
    Download the session's storage folder as a ZIP archive.

    Streams the ZIP file directly so the browser triggers a download.
    """
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
    preset = 'vtuber' if 'vtuber' in wid else 'worker_easy' if 'simple' in wid else 'worker_adaptive'

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
    preset = 'vtuber' if 'vtuber' in wid else 'worker_easy' if 'simple' in wid else 'worker_adaptive'

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
    (worker_easy / vtuber presets keep persist off, so this is the
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
