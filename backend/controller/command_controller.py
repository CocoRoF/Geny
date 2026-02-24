"""
Central Command Controller

Provides batch command capability for multiple sessions
and session monitoring endpoints.
"""
import asyncio
from logging import getLogger
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from service.claude_manager.session_manager import get_session_manager
from service.claude_manager.models import SessionStatus, ExecuteResponse
from service.logging.session_logger import (
    get_session_logger,
    list_session_logs,
    remove_session_logger,
    read_logs_from_file,
    get_log_file_path,
    LogLevel
)

logger = getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/command", tags=["command"])


# ========== Request/Response Models ==========

class BatchCommandRequest(BaseModel):
    """Request for batch command execution across multiple sessions."""
    session_ids: List[str] = Field(
        ...,
        description="List of session IDs to execute command on"
    )
    prompt: str = Field(
        ...,
        description="Prompt to send to all sessions"
    )
    timeout: Optional[float] = Field(
        default=600.0,
        description="Execution timeout per session (seconds)"
    )
    skip_permissions: Optional[bool] = Field(
        default=True,
        description="Skip permission prompts"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="Additional system prompt"
    )
    max_turns: Optional[int] = Field(
        default=None,
        description="Maximum turns per session"
    )
    parallel: Optional[bool] = Field(
        default=True,
        description="Execute in parallel (True) or sequential (False)"
    )


class BatchCommandResult(BaseModel):
    """Result of a single command execution in a batch."""
    session_id: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


class BatchCommandResponse(BaseModel):
    """Response for batch command execution."""
    total_sessions: int
    successful: int
    failed: int
    results: List[BatchCommandResult]
    total_duration_ms: int


class SessionMonitorInfo(BaseModel):
    """Session monitoring information."""
    session_id: str
    session_name: Optional[str] = None
    status: SessionStatus
    created_at: datetime
    pid: Optional[int] = None
    model: Optional[str] = None
    pod_name: Optional[str] = None
    pod_ip: Optional[str] = None
    log_file: Optional[str] = None
    recent_logs: Optional[List[Dict[str, Any]]] = None


class SessionLogEntry(BaseModel):
    """A single log entry."""
    timestamp: str
    level: str
    message: str
    metadata: Optional[Dict[str, Any]] = None


class SessionLogsResponse(BaseModel):
    """Response for session logs."""
    session_id: str
    log_file: Optional[str] = None
    entries: List[SessionLogEntry]
    total_entries: int


# ========== Batch Command Endpoints ==========

@router.post("/batch", response_model=BatchCommandResponse)
async def execute_batch_command(request: BatchCommandRequest):
    """
    Execute a command across multiple sessions.

    Supports both parallel and sequential execution modes.
    Returns aggregated results from all sessions.
    """
    session_manager = get_session_manager()
    start_time = datetime.now()
    results: List[BatchCommandResult] = []

    async def execute_single(session_id: str) -> BatchCommandResult:
        """Execute command on a single session."""
        # Get session logger
        session_logger = get_session_logger(session_id, create_if_missing=False)

        try:
            process = session_manager.get_process(session_id)
            if not process:
                error_msg = f"Session not found: {session_id}"
                if session_logger:
                    session_logger.error(error_msg)
                return BatchCommandResult(
                    session_id=session_id,
                    success=False,
                    error=error_msg
                )

            if not process.is_alive():
                error_msg = f"Session is not running (status: {process.status})"
                if session_logger:
                    session_logger.error(error_msg)
                return BatchCommandResult(
                    session_id=session_id,
                    success=False,
                    error=error_msg
                )

            # Log the command
            if session_logger:
                session_logger.log_command(
                    prompt=request.prompt,
                    timeout=request.timeout,
                    system_prompt=request.system_prompt,
                    max_turns=request.max_turns
                )

            # Execute command
            result = await process.execute(
                prompt=request.prompt,
                timeout=request.timeout or 600.0,
                skip_permissions=request.skip_permissions,
                system_prompt=request.system_prompt,
                max_turns=request.max_turns
            )

            # Log the response
            if session_logger:
                session_logger.log_response(
                    success=result.get("success", False),
                    output=result.get("output"),
                    error=result.get("error"),
                    duration_ms=result.get("duration_ms"),
                    cost_usd=result.get("cost_usd")
                )

            return BatchCommandResult(
                session_id=session_id,
                success=result.get("success", False),
                output=result.get("output"),
                error=result.get("error"),
                duration_ms=result.get("duration_ms")
            )

        except Exception as e:
            error_msg = str(e)
            if session_logger:
                session_logger.error(f"Execution error: {error_msg}")
            logger.error(f"Batch execution error for session {session_id}: {e}", exc_info=True)
            return BatchCommandResult(
                session_id=session_id,
                success=False,
                error=error_msg
            )

    # Execute commands
    if request.parallel:
        # Parallel execution
        tasks = [execute_single(sid) for sid in request.session_ids]
        results = await asyncio.gather(*tasks)
    else:
        # Sequential execution
        for session_id in request.session_ids:
            result = await execute_single(session_id)
            results.append(result)

    # Calculate statistics
    total_duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    logger.info(f"Batch command completed: {successful}/{len(results)} successful")

    return BatchCommandResponse(
        total_sessions=len(request.session_ids),
        successful=successful,
        failed=failed,
        results=results,
        total_duration_ms=total_duration_ms
    )


@router.post("/broadcast")
async def broadcast_command(
    prompt: str = Query(..., description="Prompt to broadcast"),
    timeout: float = Query(600.0, description="Timeout per session"),
    skip_permissions: bool = Query(True, description="Skip permission prompts"),
    status_filter: Optional[SessionStatus] = Query(None, description="Only send to sessions with this status")
):
    """
    Broadcast a command to all active sessions.

    Optionally filter by session status.
    """
    session_manager = get_session_manager()
    sessions = session_manager.list_sessions()

    # Filter by status if specified
    if status_filter:
        sessions = [s for s in sessions if s.status == status_filter]
    else:
        # Default: only running sessions
        sessions = [s for s in sessions if s.status == SessionStatus.RUNNING]

    if not sessions:
        return {
            "message": "No active sessions to broadcast to",
            "sessions_count": 0
        }

    session_ids = [s.session_id for s in sessions]

    # Create batch request
    batch_request = BatchCommandRequest(
        session_ids=session_ids,
        prompt=prompt,
        timeout=timeout,
        skip_permissions=skip_permissions,
        parallel=True
    )

    return await execute_batch_command(batch_request)


# ========== Session Monitoring Endpoints ==========

@router.get("/monitor", response_model=List[SessionMonitorInfo])
async def get_all_sessions_monitor():
    """
    Get monitoring information for all sessions.

    Includes session status, recent logs, and log file paths.
    """
    session_manager = get_session_manager()
    sessions = session_manager.list_sessions()

    monitor_info = []
    for session in sessions:
        # Get session logger
        session_logger = get_session_logger(session.session_id, create_if_missing=False)

        log_file = None
        recent_logs = None
        if session_logger:
            log_file = session_logger.get_log_file_path()
            recent_logs = session_logger.get_logs(limit=10)

        monitor_info.append(SessionMonitorInfo(
            session_id=session.session_id,
            session_name=session.session_name,
            status=session.status,
            created_at=session.created_at,
            pid=session.pid,
            model=session.model,
            pod_name=session.pod_name,
            pod_ip=session.pod_ip,
            log_file=log_file,
            recent_logs=recent_logs
        ))

    return monitor_info


@router.get("/monitor/{session_id}", response_model=SessionMonitorInfo)
async def get_session_monitor(session_id: str):
    """
    Get detailed monitoring information for a specific session.
    """
    session_manager = get_session_manager()
    session = session_manager.get_session_info(session_id)

    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Get session logger
    session_logger = get_session_logger(session_id, create_if_missing=False)

    log_file = None
    recent_logs = None
    if session_logger:
        log_file = session_logger.get_log_file_path()
        recent_logs = session_logger.get_logs(limit=50)

    return SessionMonitorInfo(
        session_id=session.session_id,
        session_name=session.session_name,
        status=session.status,
        created_at=session.created_at,
        pid=session.pid,
        model=session.model,
        pod_name=session.pod_name,
        pod_ip=session.pod_ip,
        log_file=log_file,
        recent_logs=recent_logs
    )


# ========== Session Logs Endpoints ==========

@router.get("/logs", response_model=List[Dict[str, Any]])
async def list_all_session_logs():
    """
    List all available session log files.

    Returns metadata about each log file.
    """
    return list_session_logs()


@router.get("/logs/{session_id}", response_model=SessionLogsResponse)
async def get_session_logs(
    session_id: str,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of log entries"),
    level: Optional[str] = Query(None, description="Filter by log level (DEBUG, INFO, WARNING, ERROR, COMMAND, RESPONSE)")
):
    """
    Get log entries for a specific session.

    Reads logs from persistent log files. Logs are preserved even after session deletion.
    Supports filtering by log level.
    """
    # Parse level filter
    level_filter = None
    if level:
        try:
            level_filter = LogLevel(level.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid log level: {level}")

    # First check if log file exists
    log_file_path = get_log_file_path(session_id)

    if not log_file_path:
        raise HTTPException(status_code=404, detail=f"No logs found for session: {session_id}")

    # Try to get from active session logger first (faster, uses cache)
    session_logger = get_session_logger(session_id, create_if_missing=False)

    if session_logger:
        entries = session_logger.get_logs(limit=limit, level=level_filter)
    else:
        # Read directly from file (for historical/deleted sessions)
        entries = read_logs_from_file(session_id, limit=limit, level=level_filter)

    return SessionLogsResponse(
        session_id=session_id,
        log_file=log_file_path,
        entries=[SessionLogEntry(**e) for e in entries],
        total_entries=len(entries)
    )


# ========== Summary Statistics Endpoints ==========

@router.get("/stats")
async def get_command_stats():
    """
    Get overall command execution statistics.
    """
    session_manager = get_session_manager()
    sessions = session_manager.list_sessions()

    stats = {
        "total_sessions": len(sessions),
        "sessions_by_status": {
            "running": sum(1 for s in sessions if s.status == SessionStatus.RUNNING),
            "stopped": sum(1 for s in sessions if s.status == SessionStatus.STOPPED),
            "starting": sum(1 for s in sessions if s.status == SessionStatus.STARTING),
            "error": sum(1 for s in sessions if s.status == SessionStatus.ERROR)
        },
        "log_files": list_session_logs()
    }

    return stats


# ========== Prompts Management Endpoints ==========

class PromptInfo(BaseModel):
    """Information about an available prompt template."""
    name: str = Field(..., description="Prompt name (filename without extension)")
    filename: str = Field(..., description="Prompt filename")
    description: Optional[str] = Field(None, description="First line of the prompt (as description)")


class PromptListResponse(BaseModel):
    """Response containing list of available prompts."""
    prompts: List[PromptInfo]
    total: int


class PromptContentResponse(BaseModel):
    """Response containing full prompt content."""
    name: str
    filename: str
    content: str


def get_prompts_dir() -> Path:
    """Get the prompts directory path."""
    return Path(__file__).parent.parent / "prompts"


def get_prompts_list() -> list:
    """
    Get list of available prompt templates (sync version for SSR).

    Returns a list of dicts with name, filename, and description.
    """
    prompts_dir = get_prompts_dir()
    prompts = []

    if prompts_dir.exists():
        for file_path in sorted(prompts_dir.glob("*.md")):
            if file_path.name.lower() == "readme.md":
                continue

            name = file_path.stem
            description = None

            # Read first non-empty line as description
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            description = line[:100]
                            break
                        elif line.startswith("# "):
                            description = line[2:].strip()
                            break
            except Exception:
                pass

            prompts.append({
                "name": name,
                "filename": file_path.name,
                "description": description
            })

    return prompts


@router.get("/prompts", response_model=PromptListResponse)
async def list_prompts():
    """
    List all available prompt templates.

    Reads .md files from the prompts directory.
    """
    prompts_dir = get_prompts_dir()
    prompts = []

    if prompts_dir.exists():
        for file_path in sorted(prompts_dir.glob("*.md")):
            if file_path.name.lower() == "readme.md":
                continue

            name = file_path.stem
            description = None

            # Read first non-empty line as description
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            description = line[:100]  # Limit description length
                            break
                        elif line.startswith("# "):
                            description = line[2:].strip()
                            break
            except Exception as e:
                logger.warning(f"Failed to read prompt file {file_path}: {e}")

            prompts.append(PromptInfo(
                name=name,
                filename=file_path.name,
                description=description
            ))

    return PromptListResponse(prompts=prompts, total=len(prompts))


@router.get("/prompts/{prompt_name}", response_model=PromptContentResponse)
async def get_prompt(prompt_name: str):
    """
    Get the full content of a specific prompt template.
    """
    prompts_dir = get_prompts_dir()
    file_path = prompts_dir / f"{prompt_name}.md"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_name}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return PromptContentResponse(
            name=prompt_name,
            filename=file_path.name,
            content=content
        )
    except Exception as e:
        logger.error(f"Failed to read prompt {prompt_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read prompt: {e}")
