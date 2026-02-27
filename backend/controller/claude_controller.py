"""
Geny Agent API Controller

REST API endpoints for Claude session management.
Includes SSE streaming for real-time execution logs.
"""
import re
import json
import asyncio
from logging import getLogger
import uuid
from typing import List, AsyncGenerator
from datetime import datetime
from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import StreamingResponse

# Pattern to detect auto-continue signal from self-manager
CONTINUE_PATTERN = re.compile(r'\[CONTINUE:\s*(.+?)\]', re.IGNORECASE)
COMPLETE_PATTERN = re.compile(r'\[TASK_COMPLETE\]', re.IGNORECASE)

from service.claude_manager.models import (
    CreateSessionRequest,
    SessionInfo,
    SessionRole,
    ExecuteRequest,
    ExecuteResponse,
    StorageFile,
    StorageListResponse,
    StorageFileContent,
    ManagerEvent,
    ManagerEventType,
    DelegateTaskRequest,
    DelegateTaskResponse,
    WorkerStatus,
    ManagerDashboard
)
from service.claude_manager.session_manager import get_session_manager
from service.claude_manager.stream_parser import StreamEvent, StreamEventType
from service.logging.session_logger import get_session_logger

logger = getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# Singleton session manager
session_manager = get_session_manager()


# ========== Session Management API ==========

@router.post("", response_model=SessionInfo)
async def create_session(request: CreateSessionRequest):
    """
    Create a new Claude session.

    Creates a new session to run Claude Code.
    Each session has its own independent storage directory.
    """
    try:
        session = await session_manager.create_session(request)
        logger.info(f"✅ Session created: {session.session_id}")
        return session
    except Exception as e:
        logger.error(f"❌ Failed to create session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[SessionInfo])
async def list_sessions():
    """
    List all sessions.

    In multi-pod environments, returns sessions from all pods.
    """
    return session_manager.list_sessions()


@router.get("/managers", response_model=List[SessionInfo])
async def list_managers():
    """
    Get all manager sessions.

    Returns list of sessions with manager role.
    """
    return session_manager.get_managers()


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str = Path(..., description="Session ID")
):
    """
    Get specific session information.
    """
    session = session_manager.get_session_info(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return session


@router.delete("/{session_id}")
async def delete_session(
    session_id: str = Path(..., description="Session ID"),
    cleanup_storage: bool = Query(True, description="Also delete storage")
):
    """
    Delete session.

    Terminates the session and cleans up related resources.
    """
    success = await session_manager.delete_session(session_id, cleanup_storage)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    logger.info(f"✅ Session deleted: {session_id}")
    return {"success": True, "session_id": session_id}


# ========== Claude Execution API ==========

@router.post("/{session_id}/execute", response_model=ExecuteResponse)
async def execute_prompt(
    session_id: str = Path(..., description="Session ID"),
    request: ExecuteRequest = ...
):
    """
    Execute prompt with Claude.

    Sends a prompt to Claude in the session and returns the result.
    """
    process = session_manager.get_process(session_id)
    if not process:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if not process.is_alive():
        raise HTTPException(
            status_code=400,
            detail=f"Session is not running (status: {process.status})"
        )

    # Get session logger
    session_logger = get_session_logger(session_id, create_if_missing=False)

    try:
        # Log the command
        if session_logger:
            session_logger.log_command(
                prompt=request.prompt,
                timeout=request.timeout,
                system_prompt=request.system_prompt,
                max_turns=request.max_turns
            )

        result = await process.execute(
            prompt=request.prompt,
            timeout=request.timeout or process.timeout,
            skip_permissions=request.skip_permissions,
            system_prompt=request.system_prompt,
            max_turns=request.max_turns or process.max_turns
        )

        # Log the response with tool call details
        if session_logger:
            session_logger.log_response(
                success=result.get("success", False),
                output=result.get("output"),
                error=result.get("error"),
                duration_ms=result.get("duration_ms"),
                cost_usd=result.get("cost_usd"),
                tool_calls=result.get("tool_calls"),
                num_turns=result.get("num_turns")
            )

        # Detect CONTINUE pattern for auto-continue mode
        output = result.get("output") or ""
        should_continue = False
        continue_hint = None
        is_task_complete = False

        continue_match = CONTINUE_PATTERN.search(output)
        if continue_match and result.get("success", False):
            should_continue = True
            continue_hint = continue_match.group(1).strip()
            logger.info(f"[{session_id}] 🔄 Auto-continue detected: {continue_hint}")

        # Detect TASK_COMPLETE pattern
        if COMPLETE_PATTERN.search(output) and result.get("success", False):
            is_task_complete = True
            should_continue = False
            logger.info(f"[{session_id}] ✅ Task complete detected")

        # Convert tool_calls to ToolCallInfo objects
        tool_calls = result.get("tool_calls")
        tool_call_infos = None
        if tool_calls:
            from service.claude_manager.models import ToolCallInfo
            tool_call_infos = [
                ToolCallInfo(
                    id=tc.get("id"),
                    name=tc.get("name", "unknown"),
                    input=tc.get("input"),
                    timestamp=tc.get("timestamp")
                )
                for tc in tool_calls
            ]

        return ExecuteResponse(
            success=result.get("success", False),
            session_id=session_id,
            output=output,
            error=result.get("error"),
            cost_usd=result.get("cost_usd"),
            duration_ms=result.get("duration_ms"),
            tool_calls=tool_call_infos,
            num_turns=result.get("num_turns"),
            model=result.get("model"),
            stop_reason=result.get("stop_reason"),
            should_continue=should_continue,
            continue_hint=continue_hint,
            is_task_complete=is_task_complete
        )
    except Exception as e:
        logger.error(f"❌ Execution failed: {e}", exc_info=True)
        if session_logger:
            session_logger.error(f"Execution failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== SSE Streaming Execution API ==========

@router.post("/{session_id}/execute/stream")
async def execute_prompt_stream(
    session_id: str = Path(..., description="Session ID"),
    request: ExecuteRequest = ...
):
    """
    Execute prompt with Claude and stream events via SSE.

    Returns Server-Sent Events (SSE) stream with real-time execution events:
    - system_init: Model and available tools info
    - tool_use: When Claude invokes a tool
    - assistant: Assistant text messages
    - result: Final execution result

    Use this endpoint for real-time monitoring of Claude's execution.
    """
    process = session_manager.get_process(session_id)
    if not process:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if not process.is_alive():
        raise HTTPException(
            status_code=400,
            detail=f"Session is not running (status: {process.status})"
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from Claude execution."""
        event_queue: asyncio.Queue = asyncio.Queue()

        def on_stream_event(event: StreamEvent):
            """Callback for stream events - puts event in queue."""
            event_data = {
                "type": event.event_type.value,
                "timestamp": event.timestamp.isoformat(),
                "session_id": event.session_id
            }

            # Add type-specific data
            if event.event_type == StreamEventType.SYSTEM_INIT:
                event_data["model"] = event.model
                event_data["tools"] = event.tools
                event_data["mcp_servers"] = event.mcp_servers
            elif event.event_type == StreamEventType.TOOL_USE:
                event_data["tool_name"] = event.tool_name
                event_data["tool_id"] = event.tool_use_id
                event_data["tool_input"] = event.tool_input
            elif event.event_type == StreamEventType.ASSISTANT_MESSAGE:
                event_data["text"] = event.text
                event_data["stop_reason"] = event.stop_reason
            elif event.event_type == StreamEventType.RESULT:
                event_data["duration_ms"] = event.duration_ms
                event_data["cost_usd"] = event.total_cost_usd
                event_data["num_turns"] = event.num_turns
                event_data["is_error"] = event.is_error
                event_data["result"] = event.result_text

            # Put in queue (non-blocking)
            try:
                event_queue.put_nowait(event_data)
            except asyncio.QueueFull:
                pass

        # Start execution in background task
        async def run_execution():
            try:
                await process.execute(
                    prompt=request.prompt,
                    timeout=request.timeout or process.timeout,
                    skip_permissions=request.skip_permissions,
                    system_prompt=request.system_prompt,
                    max_turns=request.max_turns or process.max_turns,
                    on_event=on_stream_event
                )
            except Exception as e:
                logger.error(f"Streaming execution error: {e}")
                error_event = {
                    "type": "error",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }
                await event_queue.put(error_event)
            finally:
                # Signal end of stream
                await event_queue.put(None)

        # Start execution task
        execution_task = asyncio.create_task(run_execution())

        try:
            while True:
                event_data = await event_queue.get()

                if event_data is None:
                    # End of stream
                    break

                # Format as SSE
                sse_data = json.dumps(event_data, ensure_ascii=False)
                yield f"data: {sse_data}\n\n"

        except asyncio.CancelledError:
            execution_task.cancel()
            raise
        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            error_data = json.dumps({"type": "error", "error": str(e)})
            yield f"data: {error_data}\n\n"
        finally:
            if not execution_task.done():
                execution_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ========== Storage API ==========

@router.get("/{session_id}/storage", response_model=StorageListResponse)
async def list_storage_files(
    session_id: str = Path(..., description="Session ID"),
    path: str = Query("", description="Subdirectory path")
):
    """
    List session storage files.

    Returns file list from session-specific storage.
    """
    process = session_manager.get_process(session_id)
    if not process:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    files_data = process.list_storage_files(path)
    files = [StorageFile(**f) for f in files_data]

    return StorageListResponse(
        session_id=session_id,
        storage_path=process.storage_path,
        files=files
    )


@router.get("/{session_id}/storage/{file_path:path}", response_model=StorageFileContent)
async def read_storage_file(
    session_id: str = Path(..., description="Session ID"),
    file_path: str = Path(..., description="File path"),
    encoding: str = Query("utf-8", description="File encoding")
):
    """
    Read storage file content.

    Returns content of a specific file from session storage.
    """
    process = session_manager.get_process(session_id)
    if not process:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    file_content = process.read_storage_file(file_path, encoding)
    if not file_content:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    return StorageFileContent(
        session_id=session_id,
        **file_content
    )


# ========== Manager/Worker Hierarchical Management API ==========

@router.get("/{session_id}/workers", response_model=List[SessionInfo])
async def get_workers(
    session_id: str = Path(..., description="Manager session ID")
):
    """
    Get all worker sessions under a manager.

    Returns list of worker sessions that are managed by this manager.
    """
    # Verify the session exists and is a manager
    session = session_manager.get_session_info(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if session.role != SessionRole.MANAGER:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not a manager (role: {session.role})"
        )

    workers = session_manager.get_workers_by_manager(session_id)
    return workers


@router.post("/{session_id}/delegate", response_model=DelegateTaskResponse)
async def delegate_task(
    session_id: str = Path(..., description="Manager session ID"),
    request: DelegateTaskRequest = ...
):
    """
    Delegate a task from manager to worker.

    The manager sends a task to one of its workers.
    The worker executes the task based on its mode (autonomous or single).
    """
    # Verify manager session
    manager_session = session_manager.get_session_info(session_id)
    if not manager_session:
        raise HTTPException(status_code=404, detail=f"Manager session not found: {session_id}")

    if manager_session.role != SessionRole.MANAGER:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not a manager (role: {manager_session.role})"
        )

    # Verify worker session
    worker_session = session_manager.get_session_info(request.worker_id)
    if not worker_session:
        raise HTTPException(status_code=404, detail=f"Worker session not found: {request.worker_id}")

    if worker_session.manager_id != session_id:
        raise HTTPException(
            status_code=400,
            detail=f"Worker {request.worker_id} is not managed by this manager"
        )

    # Get worker process
    worker_process = session_manager.get_process(request.worker_id)
    if not worker_process:
        raise HTTPException(
            status_code=400,
            detail=f"Worker process not found (may be on different pod)"
        )

    if not worker_process.is_alive():
        raise HTTPException(
            status_code=400,
            detail=f"Worker session is not running (status: {worker_process.status})"
        )

    # Get manager's session logger for event logging
    manager_logger = get_session_logger(session_id, create_if_missing=True)
    delegation_id = str(uuid.uuid4())[:8]

    try:
        # Log delegation start
        if manager_logger:
            manager_logger.log_task_delegated(
                worker_id=request.worker_id,
                worker_name=worker_session.session_name,
                task_prompt=request.prompt,
                context=request.context
            )
            manager_logger.log_worker_started(
                worker_id=request.worker_id,
                worker_name=worker_session.session_name
            )

        # Mark worker as busy
        worker_process.is_busy = True
        worker_process.current_task = request.prompt[:100]
        worker_process.last_activity = datetime.now()

        # Execute task (use agent_controller for autonomous graph execution)
        result = await worker_process.execute(
            prompt=request.prompt,
            timeout=request.timeout or worker_process.timeout,
            skip_permissions=request.skip_permissions
        )
        output = result.get("output")
        success = result.get("success", False)

        # Update worker state
        worker_process.is_busy = False
        worker_process.last_output = output[:500] if output else None
        worker_process.last_activity = datetime.now()

        # Log completion
        if manager_logger:
            manager_logger.log_worker_completed(
                worker_id=request.worker_id,
                worker_name=worker_session.session_name,
                success=success,
                output_preview=output[:200] if output else None,
                duration_ms=result.get("duration_ms"),
                cost_usd=result.get("cost_usd")
            )

        return DelegateTaskResponse(
            success=success,
            manager_id=session_id,
            worker_id=request.worker_id,
            delegation_id=delegation_id,
            status="completed" if success else "error",
            output=output,
            error=result.get("error") or result.get("stop_reason") if not success else None
        )

    except Exception as e:
        # Update worker state on error
        worker_process.is_busy = False
        worker_process.last_activity = datetime.now()

        # Log error
        if manager_logger:
            manager_logger.log_worker_completed(
                worker_id=request.worker_id,
                worker_name=worker_session.session_name,
                success=False,
                output_preview=str(e)
            )

        logger.error(f"❌ Task delegation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/events", response_model=List[ManagerEvent])
async def get_manager_events(
    session_id: str = Path(..., description="Manager session ID"),
    limit: int = Query(50, description="Maximum number of events to return")
):
    """
    Get manager event log.

    Returns recent events for the manager including delegations,
    worker progress, and plan updates.
    """
    session = session_manager.get_session_info(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if session.role != SessionRole.MANAGER:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not a manager (role: {session.role})"
        )

    session_logger = get_session_logger(session_id, create_if_missing=False)
    if not session_logger:
        return []

    # Get manager events from logger
    raw_events = session_logger.get_manager_events(limit=limit)

    # Convert to ManagerEvent model
    events = []
    for raw in raw_events:
        metadata = raw.get("metadata", {})
        events.append(ManagerEvent(
            event_id=metadata.get("event_id", str(uuid.uuid4())[:8]),
            event_type=ManagerEventType(metadata.get("event_type", "status_check")),
            timestamp=datetime.fromisoformat(raw.get("timestamp")) if raw.get("timestamp") else datetime.now(),
            manager_id=session_id,
            worker_id=metadata.get("worker_id"),
            message=raw.get("message", ""),
            data=metadata.get("data")
        ))

    return events


@router.get("/{session_id}/dashboard", response_model=ManagerDashboard)
async def get_manager_dashboard(
    session_id: str = Path(..., description="Manager session ID")
):
    """
    Get manager dashboard data.

    Returns comprehensive dashboard including workers, events, and status.
    """
    session = session_manager.get_session_info(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if session.role != SessionRole.MANAGER:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not a manager (role: {session.role})"
        )

    # Get workers
    workers = session_manager.get_workers_by_manager(session_id)
    worker_statuses = []

    for worker in workers:
        worker_process = session_manager.get_process(worker.session_id)

        worker_status = WorkerStatus(
            worker_id=worker.session_id,
            worker_name=worker.session_name,
            status=worker.status,
            is_busy=worker_process.is_busy if worker_process else False,
            current_task=worker_process.current_task if worker_process else None,
            last_output=worker_process.last_output if worker_process else None,
            last_activity=worker_process.last_activity if worker_process else None
        )
        worker_statuses.append(worker_status)

    # Get events
    events_response = await get_manager_events(session_id, limit=20)

    # Count delegations
    active_delegations = sum(1 for w in worker_statuses if w.is_busy)
    completed_delegations = sum(
        1 for e in events_response
        if e.event_type in [ManagerEventType.WORKER_COMPLETED, ManagerEventType.WORKER_ERROR]
    )

    return ManagerDashboard(
        manager_id=session_id,
        manager_name=session.session_name,
        workers=worker_statuses,
        recent_events=events_response,
        active_delegations=active_delegations,
        completed_delegations=completed_delegations
    )
