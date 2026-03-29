"""
Agent Session Controller

REST API endpoints for AgentSession (LangGraph + Claude CLI) management.

Manages sessions based on AgentSession(CompiledStateGraph).

AgentSession API:   /api/agents (primary)
Legacy Session API: /api/sessions (deprecated, backward compatibility)
"""
import asyncio
import json
import time
from logging import getLogger
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Path, Query, Request
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.claude_manager.models import (
    CreateSessionRequest,
    SessionInfo,
    SessionRole,
    ExecuteRequest,
    ExecuteResponse,
    StorageFile,
    StorageListResponse,
    StorageFileContent,
)
from service.langgraph import (
    get_agent_session_manager,
    AgentSession,
)
from service.logging.session_logger import get_session_logger
from service.claude_manager.session_store import get_session_store
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


class AgentInvokeRequest(BaseModel):
    """
    Request to invoke an AgentSession.

    Executes based on LangGraph state.
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


class UpgradeToAgentRequest(BaseModel):
    """
    Request to upgrade an existing session to an AgentSession.
    """
    enable_checkpointing: bool = Field(
        default=False,
        description="Enable state checkpointing"
    )


# ============================================================================
# Agent Session Management API
# ============================================================================


@router.post("", response_model=SessionInfo)
async def create_agent_session(request: CreateAgentRequest):
    """
    Create a new AgentSession.

    AgentSession operates based on a CompiledStateGraph and
    provides LangGraph's state management capabilities.
    """
    try:
        agent = await agent_manager.create_agent_session(
            request=request,
            enable_checkpointing=request.enable_checkpointing,
        )

        session_info = agent.get_session_info()
        logger.info(f"✅ AgentSession created: {agent.session_id}")
        return session_info

    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
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

    return agent.get_session_info()


class UpdateSystemPromptRequest(BaseModel):
    """Request to update an agent's system prompt."""
    system_prompt: Optional[str] = Field(
        default=None,
        description="New system prompt. Set to null or empty string to clear.",
    )


@router.put("/{session_id}/system-prompt")
async def update_system_prompt(
    request: UpdateSystemPromptRequest,
    session_id: str = Path(..., description="Session ID"),
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

    # Update on AgentSession
    agent._system_prompt = new_prompt

    # Update on the underlying ClaudeProcess so --append-system-prompt uses it
    if agent.process:
        agent.process.system_prompt = new_prompt

    # Persist to session store so the change survives delete/restore
    store = get_session_store()
    store.update(session_id, {"system_prompt": new_prompt or ""})

    logger.info(
        f"[{session_id}] System prompt updated "
        f"({len(new_prompt) if new_prompt else 0} chars)"
    )
    return {"success": True, "session_id": session_id, "system_prompt_length": len(new_prompt) if new_prompt else 0}


@router.delete("/{session_id}")
async def delete_agent_session(
    session_id: str = Path(..., description="Session ID"),
    cleanup_storage: bool = Query(False, description="Also delete storage (default: False to preserve files)")
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
):
    """
    Permanently delete a session from the persistent store.
    The session record is irrecoverably removed from sessions.json
    and its storage directory is deleted from disk.
    """
    import shutil
    from pathlib import Path as FilePath

    store = get_session_store()

    # Get storage_path before deleting anything
    record = store.get(session_id)
    storage_path = record.get("storage_path") if record else None

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
    return {"success": True, "session_id": session_id}


@router.post("/{session_id}/restore")
async def restore_session(
    session_id: str = Path(..., description="Session ID to restore"),
):
    """
    Restore a soft-deleted session.

    Re-creates the AgentSession using the original creation parameters
    stored in sessions.json, with the same session_name and settings.
    Returns the new SessionInfo (note: session_id will be NEW).
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
        )

        # Reuse the SAME session_id → preserves storage_path
        agent = await agent_manager.create_agent_session(
            request=request,
            session_id=session_id,
        )

        # Restore the previously stored system prompt (user customization)
        if stored_system_prompt:
            agent._system_prompt = stored_system_prompt
            if agent.process:
                agent.process.system_prompt = stored_system_prompt
            store.update(session_id, {"system_prompt": stored_system_prompt})

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
    request: AgentInvokeRequest = ...
):
    """
    Invoke AgentSession with LangGraph state execution.

    Performs state-based graph execution.
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

        # Execute the LangGraph graph
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
    request: ExecuteRequest = ...
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


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    """Format a single SSE event string."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


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


# ── Shared SSE helpers ────────────────────────────────────────────────────────


async def _stream_execution_sse(holder: dict, session_id: str, app_state=None):
    """Yield SSE events for a running execution.

    Shared by ``/execute/events`` and ``/execute/stream``.
    Polls the session logger cache every 150ms for new log entries
    and streams them as ``log`` events until the execution completes.

    A heartbeat is sent every ~15 seconds of inactivity to keep the
    connection alive and report execution health (elapsed time, activity).

    If ``app_state`` is provided and the session has a Live2D model assigned,
    avatar state updates are automatically emitted based on log content.
    """
    session_logger = get_session_logger(session_id, create_if_missing=False)
    cache_cursor = holder.get("cache_cursor", 0)
    heartbeat_interval = 15.0  # seconds
    last_event_time = time.monotonic()
    start_time = holder.get("start_time", time.time())

    yield _sse("status", {"status": "running", "message": "Execution started"})
    last_event_time = time.monotonic()

    def _build_heartbeat() -> dict:
        """Build heartbeat payload with execution health data."""
        now = time.time()
        now_mono = time.monotonic()
        elapsed_ms = int((now - start_time) * 1000)
        last_write = session_logger.get_last_write_at() if session_logger else 0
        last_activity_ms = int((now_mono - last_write) * 1000) if last_write > 0 else elapsed_ms
        entry_info = session_logger.get_last_entry_info() if session_logger else {}
        return {
            "ts": now,
            "elapsed_ms": elapsed_ms,
            "last_activity_ms": last_activity_ms,
            "log_count": cache_cursor,
            "last_event_level": entry_info.get("level"),
            "last_tool_name": entry_info.get("tool_name"),
        }

    try:
        while not holder.get("done"):
            had_data = False
            if session_logger:
                new_entries, cache_cursor = session_logger.get_cache_entries_since(cache_cursor)
                for entry in new_entries:
                    entry_dict = entry.to_dict()
                    yield _sse("log", entry_dict)
                    # Emit avatar state change based on log content
                    if app_state:
                        await _emit_avatar_state_for_log(entry_dict, session_id, app_state)
                    had_data = True
            if had_data:
                last_event_time = time.monotonic()
            elif time.monotonic() - last_event_time >= heartbeat_interval:
                yield _sse("heartbeat", _build_heartbeat())
                last_event_time = time.monotonic()
            await asyncio.sleep(0.15)

        # Final drain — pick up entries written during last poll cycle
        await asyncio.sleep(0.05)
        if session_logger:
            final_entries, cache_cursor = session_logger.get_cache_entries_since(cache_cursor)
            for entry in final_entries:
                yield _sse("log", entry.to_dict())

    except Exception as e:
        logger.error(f"SSE stream error: {e}", exc_info=True)
        yield _sse("error", {"error": str(e)})

    # Emit final result or error
    if holder.get("error"):
        yield _sse("status", {"status": "error", "message": holder["error"]})
        yield _sse("result", holder.get("result", {}))
    else:
        yield _sse("status", {"status": "completed", "message": "Execution completed"})
        yield _sse("result", holder.get("result", {}))

    yield _sse("done", {})

    # Cleanup execution holder
    cleanup_execution(session_id)


# ── Execution endpoints (delegating to agent_executor) ────────────────────────


@router.post("/{session_id}/execute/start")
async def start_agent_execution(
    session_id: str = Path(..., description="Session ID"),
    request: ExecuteRequest = ...,
):
    """
    Start prompt execution in the background.

    Returns immediately while the graph runs asynchronously.
    Use the ``GET /execute/events`` SSE endpoint to stream
    real-time log events.

    All execution concerns (auto-revival, session logging, cost
    tracking, double-execution prevention) are handled by
    ``agent_executor.start_command_background``.
    """
    try:
        await start_command_background(
            session_id=session_id,
            prompt=request.prompt,
            timeout=request.timeout,
            system_prompt=request.system_prompt,
            max_turns=request.max_turns,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")
    except AgentNotAliveError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AlreadyExecutingError:
        raise HTTPException(status_code=409, detail="Execution already in progress")

    return {"session_id": session_id, "status": "started"}


@router.get("/{session_id}/execute/events")
async def stream_execution_events(
    session_id: str = Path(..., description="Session ID"),
    request: Request = None,
):
    """
    SSE event stream for a running execution.

    Call ``POST /execute/start`` first, then connect to this endpoint
    with ``EventSource`` (GET-based SSE).

    SSE event types emitted:
      - ``log``    : new log entry
      - ``status`` : execution status update
      - ``result`` : final execution result
      - ``done``   : stream complete sentinel
      - ``error``  : execution error
    """
    holder = get_execution_holder(session_id)
    if not holder:
        raise HTTPException(status_code=404, detail="No active execution for this session")

    app_state = request.app.state if request else None
    return StreamingResponse(
        _stream_execution_sse(holder, session_id, app_state=app_state),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.post("/{session_id}/execute/stream")
async def execute_agent_prompt_stream(
    session_id: str = Path(..., description="Session ID"),
    execute_request: ExecuteRequest = ...,
    http_request: Request = None,
):
    """
    Execute prompt with real-time SSE log streaming.

    Starts execution via ``start_command_background`` and streams
    log events in real time until completion.

    SSE event types:
      - log       : a new log entry (same shape as LogEntry)
      - status    : execution status update (running / completed / error)
      - result    : final execution result (ExecuteResponse shape)
      - done      : stream complete sentinel
      - error     : top-level error
    """
    app_state = http_request.app.state if http_request else None

    async def event_stream():
        try:
            holder = await start_command_background(
                session_id=session_id,
                prompt=execute_request.prompt,
                timeout=execute_request.timeout,
                system_prompt=execute_request.system_prompt,
                max_turns=execute_request.max_turns,
            )
        except (AgentNotFoundError, AgentNotAliveError, AlreadyExecutingError) as e:
            yield _sse("error", {"error": str(e)})
            yield _sse("done", {})
            return

        async for event in _stream_execution_sse(holder, session_id, app_state=app_state):
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
# Agent Upgrade API
# ============================================================================


@router.post("/{session_id}/upgrade", response_model=SessionInfo)
async def upgrade_to_agent_session(
    session_id: str = Path(..., description="Session ID"),
    request: UpgradeToAgentRequest = UpgradeToAgentRequest()
):
    """
    Upgrade existing ClaudeProcess session to AgentSession.

    Wraps the existing session's ClaudeProcess into an AgentSession while preserving it.
    """
    # Check if it is already an AgentSession
    if agent_manager.has_agent(session_id):
        agent = agent_manager.get_agent(session_id)
        logger.info(f"Session {session_id} is already an AgentSession")
        return agent.get_session_info()

    # Attempt upgrade
    agent = agent_manager.upgrade_to_agent(
        session_id=session_id,
        enable_checkpointing=request.enable_checkpointing,
    )

    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found or cannot be upgraded: {session_id}"
        )

    logger.info(f"✅ Session upgraded to AgentSession: {session_id}")
    return agent.get_session_info()


# ============================================================================
# Stop Execution API
# ============================================================================


@router.post("/{session_id}/stop")
async def stop_execution(
    session_id: str = Path(..., description="Session ID")
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
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    process = agent.process
    if not process:
        raise HTTPException(status_code=400, detail="AgentSession process not available")

    files_data = process.list_storage_files(path)
    files = [StorageFile(**f) for f in files_data]

    return StorageListResponse(
        session_id=session_id,
        storage_path=process.storage_path,
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
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    process = agent.process
    if not process:
        raise HTTPException(status_code=400, detail="AgentSession process not available")

    file_content = process.read_storage_file(file_path, encoding)
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
    if agent and agent.process:
        folder = agent.process.storage_path
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


def _build_graph_structure_from_workflow(
    session_id: str,
    session_name: str,
    workflow: "WorkflowDefinition",
) -> GraphStructure:
    """Build a GraphStructure from a WorkflowDefinition for visualization.

    Converts the workflow's nodes and edges into the GraphStructure format
    used by the frontend graph viewer.
    """
    nodes = []
    edges = []

    for node in workflow.nodes:
        node_type = "node"
        if node.node_type == "start":
            node_type = "start"
        elif node.node_type == "end":
            node_type = "end"
        elif node.node_type in ("context_guard", "post_model", "iteration_gate", "memory_inject"):
            node_type = "resilience"

        nodes.append(GraphNodeInfo(
            id=node.id,
            label=node.label,
            type=node_type,
            description=f"{node.node_type} node",
            metadata=dict(node.config) if node.config else {},
        ))

    # Group edges by source to detect conditional routing
    from collections import defaultdict
    edges_by_source = defaultdict(list)
    for edge in workflow.edges:
        edges_by_source[edge.source].append(edge)

    for source_id, source_edges in edges_by_source.items():
        targets = {e.target for e in source_edges}
        is_conditional = len(targets) > 1

        if is_conditional:
            # Build condition map for conditional edges
            condition_map = {}
            for e in source_edges:
                port = e.source_port or "default"
                condition_map[port] = e.target

            for e in source_edges:
                port = e.source_port or "default"
                edges.append(GraphEdgeInfo(
                    source=e.source,
                    target=e.target,
                    label=e.label or port,
                    type="conditional",
                    condition_map=condition_map,
                ))
        else:
            for e in source_edges:
                edges.append(GraphEdgeInfo(
                    source=e.source,
                    target=e.target,
                    label=e.label or "",
                    type="edge",
                ))

    return GraphStructure(
        session_id=session_id,
        session_name=session_name,
        graph_type=workflow.template_name or "custom",
        nodes=nodes,
        edges=edges,
    )


@router.get("/{session_id}/graph", response_model=GraphStructure)
async def get_session_graph(
    session_id: str = Path(..., description="Session ID"),
):
    """
    Get the LangGraph graph structure for a session.

    Returns all nodes, edges, conditional edges, and metadata
    for complete graph visualization. Uses the session's linked
    WorkflowDefinition instead of hardcoded structures.
    """
    from service.workflow.workflow_store import get_workflow_store

    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    session_name = agent.session_name or session_id[:8]

    # Use the linked workflow from the agent session
    workflow = agent.workflow
    if not workflow:
        # Fallback: try to load from workflow_id or template
        store = get_workflow_store()
        workflow_id = getattr(agent, '_workflow_id', None)
        if workflow_id:
            workflow = store.load(workflow_id)
        if not workflow:
            template_id = "template-autonomous" if agent.autonomous else "template-simple"
            workflow = store.load(template_id)
        if not workflow:
            raise HTTPException(
                status_code=404,
                detail=f"No workflow definition found for session {session_id}",
            )

    return _build_graph_structure_from_workflow(session_id, session_name, workflow)


@router.get("/{session_id}/workflow")
async def get_session_workflow(
    session_id: str = Path(..., description="Session ID"),
):
    """
    Get the workflow definition associated with a session.

    Returns the raw WorkflowDefinition (nodes, edges, positions)
    so the frontend can render it with the same ReactFlow-based
    editor used in the Workflow tab.

    Uses the session's linked WorkflowDefinition directly,
    falling back to store lookup if needed.
    """
    from service.workflow.workflow_store import get_workflow_store

    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # 1. Use the linked workflow from the agent session
    if agent.workflow:
        return agent.workflow.model_dump()

    # 2. Fallback: try workflow_id from store
    store = get_workflow_store()
    workflow_id = getattr(agent, '_workflow_id', None)
    if workflow_id:
        wf = store.load(workflow_id)
        if wf:
            return wf.model_dump()

    # 3. Fall back to built-in template based on graph_name
    template_id = "template-autonomous" if agent.autonomous else "template-simple"
    wf = store.load(template_id)
    if wf:
        return wf.model_dump()

    # 4. If nothing found, error
    raise HTTPException(
        status_code=404,
        detail=f"No workflow definition found for session {session_id}",
    )
