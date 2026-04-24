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

from service.execution.agent_executor import (
    execute_command,
    AgentNotFoundError,
    AgentNotAliveError,
    AlreadyExecutingError,
)
from service.logging.session_logger import (
    get_session_logger,
    list_session_logs,
    remove_session_logger,
    read_logs_from_file,
    get_log_file_path,
    count_logs_for_session,
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
    start_time = datetime.now()
    results: List[BatchCommandResult] = []

    async def execute_single(session_id: str) -> BatchCommandResult:
        """Execute command on a single session via the geny-executor Pipeline."""
        session_logger = get_session_logger(session_id, create_if_missing=False)
        try:
            if session_logger:
                session_logger.log_command(
                    prompt=request.prompt,
                    timeout=request.timeout,
                    system_prompt=request.system_prompt,
                    max_turns=request.max_turns,
                )

            result = await execute_command(
                session_id,
                request.prompt,
                timeout=request.timeout,
                system_prompt=request.system_prompt,
                max_turns=request.max_turns,
            )

            if session_logger:
                session_logger.log_response(
                    success=result.success,
                    output=result.output,
                    error=result.error,
                    duration_ms=result.duration_ms,
                    cost_usd=result.cost_usd,
                )

            return BatchCommandResult(
                session_id=session_id,
                success=result.success,
                output=result.output,
                error=result.error,
                duration_ms=result.duration_ms,
            )

        except AgentNotFoundError:
            error_msg = f"Session not found: {session_id}"
            if session_logger:
                session_logger.error(error_msg)
            return BatchCommandResult(session_id=session_id, success=False, error=error_msg)
        except AgentNotAliveError as e:
            error_msg = f"Session is not running: {e}"
            if session_logger:
                session_logger.error(error_msg)
            return BatchCommandResult(session_id=session_id, success=False, error=error_msg)
        except AlreadyExecutingError as e:
            error_msg = f"Session is already executing: {e}"
            if session_logger:
                session_logger.error(error_msg)
            return BatchCommandResult(session_id=session_id, success=False, error=error_msg)
        except Exception as e:
            error_msg = str(e)
            if session_logger:
                session_logger.error(f"Execution error: {error_msg}")
            logger.error(f"Batch execution error for session {session_id}: {e}", exc_info=True)
            return BatchCommandResult(session_id=session_id, success=False, error=error_msg)

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
    level: Optional[str] = Query(None, description="Filter by log level. Single level (e.g. 'INFO') or comma-separated (e.g. 'INFO,COMMAND,RESPONSE')"),
    offset: int = Query(0, ge=0, description="Number of entries to skip (for pagination)"),
):
    """
    Get log entries for a specific session.

    Reads logs from persistent log files. Logs are preserved even after session deletion.
    Supports filtering by a single level or multiple comma-separated levels.
    Supports pagination via offset and limit. Returns newest entries first.
    """
    # Parse level filter — supports single level or comma-separated set
    level_filter = None
    if level:
        raw_levels = [lv.strip().upper() for lv in level.split(",") if lv.strip()]
        parsed = set()
        for lv in raw_levels:
            try:
                parsed.add(LogLevel(lv))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid log level: {lv}")
        if len(parsed) == 1:
            level_filter = parsed.pop()          # single LogLevel
        elif parsed:
            level_filter = parsed                 # set[LogLevel]

    # Get total count for pagination
    total = count_logs_for_session(session_id, level=level_filter)

    # Always read from DB/file first (covers full history including pre-restore logs).
    # Fall back to active session logger cache only when DB/file returns nothing.
    entries = read_logs_from_file(
        session_id, limit=limit, level=level_filter,
        offset=offset, newest_first=True,
    )

    if not entries:
        # DB/file had nothing — try active session logger's in-memory cache
        session_logger = get_session_logger(session_id, create_if_missing=False)
        if session_logger:
            entries = session_logger.get_logs(
                limit=limit, level=level_filter,
                offset=offset, newest_first=True,
            )

    # Resolve file path (informational — may be None if logs are DB-only)
    log_file_path = get_log_file_path(session_id)

    if not entries and not log_file_path and total == 0:
        raise HTTPException(status_code=404, detail=f"No logs found for session: {session_id}")

    return SessionLogsResponse(
        session_id=session_id,
        log_file=log_file_path,
        entries=[SessionLogEntry(**e) for e in entries],
        total_entries=total
    )


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
    """Get the prompt templates directory path."""
    return Path(__file__).parent.parent / "prompts" / "templates"


def get_prompts_list() -> list:
    """
    Get list of available prompt templates (sync version for SSR).

    Returns a list of dicts with name, filename, and description.
    Reads from prompts/templates/ directory (specialization prompts).
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

    Reads .md files from the prompts/templates directory.
    These are specialization prompts (e.g. developer-frontend,
    researcher-market-analysis) that augment the base role prompt.
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
