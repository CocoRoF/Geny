"""
Agent Session Controller

REST API endpoints for AgentSession (geny-executor Pipeline) management.

AgentSession API: /api/agents
"""
import asyncio
import json
import time
from logging import getLogger
from typing import List, Optional
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
async def list_agent_sessions():
    """
    List all AgentSessions.

    Returns only AgentSession instances (not regular sessions).
    """
    agents = agent_manager.list_agents()
    return [agent.get_session_info() for agent in agents]


# ============================================================================
# Session Store API (MUST be before /{session_id} to avoid path capture)
# ============================================================================


@router.get("/store/deleted", response_model=List[dict])
async def list_deleted_sessions():
    """
    List all soft-deleted sessions from the persistent store.
    """
    store = get_session_store()
    return store.list_deleted()


@router.get("/store/all", response_model=List[dict])
async def list_all_stored_sessions():
    """
    List ALL sessions from the persistent store (active + deleted).
    """
    store = get_session_store()
    return store.list_all()


@router.get("/store/{session_id}")
async def get_stored_session_info(
    session_id: str = Path(..., description="Session ID"),
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
    session_id: str = Path(..., description="Session ID")
):
    """
    Get specific AgentSession information.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        # Attempt lookup from existing sessions
        session_info = agent_manager.get_session_info(session_id)
        if session_info:
            raise HTTPException(
                status_code=400,
                detail=f"Session {session_id} is not an AgentSession. Use /api/agents/{session_id}/upgrade to convert it."
            )
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
    thread_id: Optional[str] = Query(None, description="Thread ID")
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
    thread_id: Optional[str] = Query(None, description="Thread ID")
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
    path: str = Query("", description="Subdirectory path")
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
    encoding: str = Query("utf-8", description="File encoding")
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
