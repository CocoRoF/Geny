"""
Session Logger

Per-session logging system for Geny Agent.
Each session gets its own log file in the logs/ directory.
Supports DB-backed storage (primary) with file fallback.
"""
import json
import time
from logging import getLogger
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List
from threading import Lock

from service.logging.tool_detail_formatter import format_tool_detail
from service.utils.utils import now_kst, format_kst

logger = getLogger(__name__)

# ── Module-level DB reference for standalone functions ─────────────────
_log_db_manager = None


def set_log_database(app_db) -> None:
    """Set the module-level DB manager for session logging.

    Called once at startup from main.py lifespan.
    Enables DB-backed reads in module-level functions like
    ``list_session_logs()`` and ``read_logs_from_file()``.
    """
    global _log_db_manager
    _log_db_manager = app_db
    logger.info("SessionLogger: DB backend enabled")


class LogLevel(str, Enum):
    """Log levels for session logging."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    COMMAND = "COMMAND"
    RESPONSE = "RESPONSE"
    # Preferred level for geny-executor stage transitions. Mirrors the
    # executor's Environment/Stage model; new writes use STAGE.
    STAGE = "STAGE"
    # Legacy alias kept so DB rows persisted under the old LangGraph-era
    # name still deserialize. Reads only — new writes should use STAGE.
    GRAPH = "GRAPH"
    TOOL_USE = "TOOL"           # Tool invocation events
    TOOL_RESULT = "TOOL_RES"    # Tool execution results
    STREAM_EVENT = "STREAM"     # Stream-json events
    ITERATION = "ITER"          # Autonomous execution iteration complete


# ── Stage order lookup ───────────────────────────────────────────
# Mirror of ``geny_executor.core.pipeline._DEFAULT_STAGE_NAMES``.
# The executor treats that table as private; duplicating it here is a
# deliberate trade-off (zero coordination with the executor package)
# guarded by ``test_stage_order_table_matches_executor_names`` so a
# rename upstream surfaces as a loud failing test rather than silent
# drift. Update in lockstep when the floor version changes.
#
# Updated for geny-executor 1.0+ (Sub-phase 9a 21-stage layout):
# the original 16 names + 5 new scaffold stages (tool_review,
# task_registry, hitl, summarize, persist) fill orders 11/13/15/19/20.
STAGE_ORDER: Dict[str, int] = {
    "input": 1, "context": 2, "system": 3, "guard": 4,
    "cache": 5, "api": 6, "token": 7, "think": 8,
    "parse": 9, "tool": 10, "tool_review": 11, "agent": 12,
    "task_registry": 13, "evaluate": 14, "hitl": 15, "loop": 16,
    "emit": 17, "memory": 18, "summarize": 19, "persist": 20,
    "yield": 21,
}


def stage_display_name(stage_name: Optional[str], stage_order: Optional[int]) -> Optional[str]:
    """Return ``s{NN}_{name}`` for a known stage, else the raw name."""
    if not stage_name:
        return None
    order = stage_order if stage_order is not None else STAGE_ORDER.get(stage_name)
    return f"s{order:02d}_{stage_name}" if order else stage_name


class LogEntry:
    """Represents a single log entry."""

    def __init__(
        self,
        level: LogLevel,
        message: str,
        timestamp: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.level = level
        self.message = message
        self.timestamp = timestamp or now_kst()
        self.metadata = metadata or {}

    def _level_str(self) -> str:
        """Get level as string, handling both enum and plain string."""
        return self.level.value if hasattr(self.level, 'value') else str(self.level)

    def to_dict(self) -> Dict[str, Any]:
        """Convert log entry to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self._level_str(),
            "message": self.message,
            "metadata": self.metadata
        }

    def to_line(self) -> str:
        """Convert log entry to formatted log line."""
        ts = format_kst(self.timestamp)
        meta_str = ""
        if self.metadata:
            meta_str = f" | {json.dumps(self.metadata, ensure_ascii=False)}"
        return f"[{ts}] [{self._level_str():8}] {self.message}{meta_str}\n"


class SessionLogger:
    """
    Per-session logger.

    Each session has its own log file stored in logs/ directory.
    Log files are named: {session_id}.log

    Features:
    - Timestamps for each log entry
    - Command logging (user commands to Claude)
    - Response logging (Claude's responses)
    - Error logging
    - JSON metadata support
    """

    def __init__(
        self,
        session_id: str,
        session_name: Optional[str] = None,
        logs_dir: Optional[str] = None
    ):
        self.session_id = session_id
        self.session_name = session_name or session_id

        # Determine logs directory
        if logs_dir:
            self._logs_dir = Path(logs_dir)
        else:
            # Default to logs/ directory in project root
            self._logs_dir = Path(__file__).parent.parent.parent / "logs"

        # Ensure logs directory exists
        self._logs_dir.mkdir(parents=True, exist_ok=True)

        # Log file path
        self._log_file = self._logs_dir / f"{session_id}.log"

        # Thread safety
        self._lock = Lock()

        # In-memory log cache (for quick retrieval)
        self._log_cache: List[LogEntry] = []
        self._max_cache_size = 300  # Keep last 300 entries in memory
        self._write_count: int = 0   # Monotonically increasing write counter (cursor basis)

        # Activity tracking — monotonic timestamp of last cache write
        self._last_write_at: float = 0.0

        # Last entry tracking — for tool execution detection
        self._last_entry_level: Optional[str] = None
        self._last_tool_name: Optional[str] = None

        # Write session start entry
        self._write_header()

    def _write_header(self):
        """Write session header to log file."""
        header = (
            f"{'=' * 80}\n"
            f"Session ID: {self.session_id}\n"
            f"Session Name: {self.session_name}\n"
            f"Started: {format_kst(now_kst())}\n"
            f"{'=' * 80}\n\n"
        )
        with self._lock:
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(header)

    def _write_entry(self, entry: LogEntry):
        """Write a log entry to file, cache, and DB."""
        with self._lock:
            # Write to file
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(entry.to_line())

            # Add to cache
            self._log_cache.append(entry)
            self._write_count += 1
            self._last_write_at = time.monotonic()

            # Track last entry level + tool name
            self._last_entry_level = entry.level.value
            if entry.level == LogLevel.TOOL_USE:
                self._last_tool_name = entry.metadata.get("tool_name") if entry.metadata else None
            elif entry.level == LogLevel.TOOL_RESULT:
                self._last_tool_name = entry.metadata.get("tool_name") if entry.metadata else None

            # Trim cache if too large
            if len(self._log_cache) > self._max_cache_size:
                self._log_cache = self._log_cache[-self._max_cache_size:]

        # Write to DB (outside lock to avoid blocking)
        self._write_entry_to_db(entry)

    def _write_entry_to_db(self, entry: LogEntry):
        """Write a single log entry to the database (best-effort)."""
        global _log_db_manager
        if _log_db_manager is None:
            return
        try:
            from service.database.session_log_db_helper import db_insert_log_entry
            db_insert_log_entry(
                _log_db_manager,
                session_id=self.session_id,
                level=entry.level.value,
                message=entry.message,
                metadata=entry.metadata,
                log_timestamp=entry.timestamp.isoformat() if entry.timestamp else "",
            )
        except Exception as e:
            logger.debug(f"SessionLogger: DB write failed (non-critical): {e}")

    def log(
        self,
        level: LogLevel,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Write a log entry.

        Args:
            level: Log level
            message: Log message
            metadata: Optional metadata dictionary
        """
        entry = LogEntry(level=level, message=message, metadata=metadata)
        self._write_entry(entry)

    def debug(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log a debug message."""
        self.log(LogLevel.DEBUG, message, metadata)

    def info(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log an info message."""
        self.log(LogLevel.INFO, message, metadata)

    def warning(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log a warning message."""
        self.log(LogLevel.WARNING, message, metadata)

    def error(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log an error message."""
        self.log(LogLevel.ERROR, message, metadata)

    def log_command(
        self,
        prompt: str,
        timeout: Optional[float] = None,
        system_prompt: Optional[str] = None,
        max_turns: Optional[int] = None,
        env_id: Optional[str] = None,
        role: Optional[str] = None,
    ):
        """
        Log a command sent to Claude.

        Args:
            prompt: The prompt/command sent to Claude
            timeout: Command timeout
            system_prompt: Custom system prompt
            max_turns: Maximum turns for execution
            env_id: Environment id the session runs on (e.g.
                ``template-worker-env``). Lets log readers tell
                which environment produced the turn without a
                cross-reference to the session store.
            role: Session role string (``worker`` / ``vtuber`` /
                ``sub`` / etc.). Pairs with ``env_id`` for quick
                disambiguation on the LogsTab feed.
        """
        # Store full message for log file, but add preview info for frontend
        is_truncated = len(prompt) > 200
        preview = prompt[:200] + "..." if is_truncated else prompt

        metadata = {
            "type": "command",
            "timeout": timeout,
            "system_prompt_preview": system_prompt[:100] + "..." if system_prompt and len(system_prompt) > 100 else system_prompt,
            "system_prompt_length": len(system_prompt) if system_prompt else None,
            "max_turns": max_turns,
            "prompt_length": len(prompt),
            "is_truncated": is_truncated,
            "preview": preview,
            "env_id": env_id,
            "role": role,
        }
        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v is not None}

        # Full message in log file
        self.log(LogLevel.COMMAND, f"PROMPT: {prompt}", metadata)

    def log_response(
        self,
        success: bool,
        output: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
        cost_usd: Optional[float] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        num_turns: Optional[int] = None,
        env_id: Optional[str] = None,
        role: Optional[str] = None,
    ):
        """
        Log a response from Claude.

        Args:
            success: Whether execution was successful
            output: Claude's output
            error: Error message if failed
            duration_ms: Execution duration in milliseconds
            cost_usd: API cost in USD
            tool_calls: List of tool calls made during execution
            num_turns: Number of conversation turns
            env_id: Environment id the session runs on — mirrors
                ``log_command`` so every per-turn entry carries the
                same context.
            role: Session role string.
        """
        # Store full message for log file
        output_length = len(output) if output else 0
        is_truncated = output_length > 200
        preview = output[:200] + "..." if output and is_truncated else output

        metadata = {
            "type": "response",
            "success": success,
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
            "output_length": output_length,
            "is_truncated": is_truncated,
            "preview": preview if success else None,
            "tool_call_count": len(tool_calls) if tool_calls else 0,
            "num_turns": num_turns,
            "env_id": env_id,
            "role": role,
        }
        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v is not None}

        if success:
            # Full message in log file
            message = f"SUCCESS: {output}"
        else:
            message = f"FAILED: {error}"

        self.log(LogLevel.RESPONSE, message, metadata)

        # Log individual tool calls
        if tool_calls:
            for tool_call in tool_calls:
                self.log_tool_use(
                    tool_name=tool_call.get("name", "unknown"),
                    tool_input=tool_call.get("input"),
                    tool_id=tool_call.get("id")
                )

    def log_iteration_complete(
        self,
        iteration: int,
        success: bool,
        output: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
        cost_usd: Optional[float] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        is_complete: bool = False,
        stop_reason: Optional[str] = None
    ):
        """
        Log completion of an autonomous execution iteration.

        Args:
            iteration: Iteration number (1-based)
            success: Whether this iteration succeeded
            output: Claude's output for this iteration
            error: Error message if failed
            duration_ms: Duration of this iteration
            cost_usd: Cost of this iteration
            tool_calls: Tool calls made during this iteration
            is_complete: Whether the task is fully complete
            stop_reason: Reason for stopping (if applicable)
        """
        output_length = len(output) if output else 0
        is_truncated = output_length > 500
        preview = output[:500] + "..." if output and is_truncated else output

        # Build metadata
        metadata = {
            "type": "iteration_complete",
            "iteration": iteration,
            "success": success,
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
            "output_length": output_length,
            "is_truncated": is_truncated,
            "tool_call_count": len(tool_calls) if tool_calls else 0,
            "is_complete": is_complete,
            "stop_reason": stop_reason,
            "preview": preview if success else None,
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}

        # Build message
        status = "✅" if success else "❌"
        complete_marker = " [COMPLETE]" if is_complete else ""
        cost_str = f", ${cost_usd:.4f}" if cost_usd else ""
        duration_str = f" ({duration_ms}ms)" if duration_ms else ""
        tool_str = f", {len(tool_calls)} tools" if tool_calls else ""

        header = f"{status} Execution #{iteration}{complete_marker}{duration_str}{cost_str}{tool_str}"

        if success and output:
            # Include output preview in message
            message = f"{header}\n{preview}"
        elif error:
            message = f"{header}\nError: {error}"
        else:
            message = header

        self.log(LogLevel.ITERATION, message, metadata)

    def log_tool_use(
        self,
        tool_name: str,
        tool_input: Optional[Dict[str, Any]] = None,
        tool_id: Optional[str] = None
    ):
        """
        Log a tool invocation event with detailed context.

        Args:
            tool_name: Name of the tool being called
            tool_input: Input parameters to the tool
            tool_id: Unique ID for this tool use
        """
        # Format tool detail for readability
        detail = self._format_tool_detail(tool_name, tool_input)

        # Full input for metadata
        input_str = json.dumps(tool_input, ensure_ascii=False) if tool_input else "{}"
        is_truncated = len(input_str) > 500
        input_preview = input_str[:500] + "..." if is_truncated else input_str

        metadata = {
            "type": "tool_use",
            "tool_name": tool_name,
            "tool_id": tool_id,
            "detail": detail,
            "input_preview": input_preview,
            "input_length": len(input_str),
            "is_truncated": is_truncated
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}

        # Extract structured file change data for IDE-like display
        file_changes = self._extract_file_changes(tool_name, tool_input)
        if file_changes:
            metadata["file_changes"] = file_changes

        # Extract command data for terminal-like display
        command_data = self._extract_command_data(tool_name, tool_input)
        if command_data:
            metadata["command_data"] = command_data

        # Extract file read data for code viewer
        file_read = self._extract_file_read_data(tool_name, tool_input)
        if file_read:
            metadata["file_read"] = file_read

        message = f"🔧 {tool_name}: {detail}"
        self.log(LogLevel.TOOL_USE, message, metadata)

    def _extract_file_changes(self, tool_name: str, tool_input: Optional[Dict]) -> Optional[Dict[str, Any]]:
        """
        Extract structured file change data for IDE-like diff display.

        Returns a dict with file_path, operation, changes (hunks), and summary
        if the tool is a file modification tool, otherwise None.
        """
        if not tool_input:
            return None

        MAX_CONTENT_SIZE = 50000  # 50KB max per content field

        try:
            name_lower = tool_name.lower()

            # Write / create file: entire content is new
            if name_lower in ("write", "writefile", "write_file", "create_file", "create"):
                file_path = tool_input.get("file_path", tool_input.get("path", tool_input.get("file", "")))
                content = tool_input.get("content", tool_input.get("text", ""))
                if file_path and content:
                    content_truncated = content[:MAX_CONTENT_SIZE] if len(content) > MAX_CONTENT_SIZE else content
                    lines_added = content.count("\n") + 1
                    return {
                        "file_path": file_path,
                        "operation": "create" if name_lower in ("create_file", "create") else "write",
                        "changes": [{"new_str": content_truncated}],
                        "lines_added": lines_added,
                        "lines_removed": 0,
                        "is_content_truncated": len(content) > MAX_CONTENT_SIZE,
                    }

            # Edit / patch file: old_str -> new_str replacement
            elif name_lower in ("edit", "edit_file", "patch", "replace", "str_replace_editor"):
                file_path = tool_input.get("file_path", tool_input.get("path", tool_input.get("file", "")))
                old_str = tool_input.get("old_str", tool_input.get("old_string", tool_input.get("search", "")))
                new_str = tool_input.get("new_str", tool_input.get("new_string", tool_input.get("replace", "")))
                if file_path and (old_str or new_str):
                    old_truncated = old_str[:MAX_CONTENT_SIZE] if old_str and len(old_str) > MAX_CONTENT_SIZE else old_str
                    new_truncated = new_str[:MAX_CONTENT_SIZE] if new_str and len(new_str) > MAX_CONTENT_SIZE else new_str
                    lines_removed = old_str.count("\n") + 1 if old_str else 0
                    lines_added = new_str.count("\n") + 1 if new_str else 0
                    return {
                        "file_path": file_path,
                        "operation": "edit",
                        "changes": [{"old_str": old_truncated or "", "new_str": new_truncated or ""}],
                        "lines_added": lines_added,
                        "lines_removed": lines_removed,
                        "is_content_truncated": (
                            (old_str and len(old_str) > MAX_CONTENT_SIZE) or
                            (new_str and len(new_str) > MAX_CONTENT_SIZE)
                        ),
                    }

            # Multi-edit: multiple hunks
            elif name_lower in ("multi_edit", "multiedit"):
                file_path = tool_input.get("file_path", tool_input.get("path", ""))
                edits = tool_input.get("edits", tool_input.get("changes", []))
                if file_path and edits and isinstance(edits, list):
                    changes = []
                    total_added = 0
                    total_removed = 0
                    for edit in edits[:20]:  # Limit to 20 hunks
                        old_s = edit.get("old_str", edit.get("old_string", ""))
                        new_s = edit.get("new_str", edit.get("new_string", ""))
                        changes.append({
                            "old_str": old_s[:MAX_CONTENT_SIZE] if old_s else "",
                            "new_str": new_s[:MAX_CONTENT_SIZE] if new_s else "",
                        })
                        total_removed += old_s.count("\n") + 1 if old_s else 0
                        total_added += new_s.count("\n") + 1 if new_s else 0
                    return {
                        "file_path": file_path,
                        "operation": "multi_edit",
                        "changes": changes,
                        "lines_added": total_added,
                        "lines_removed": total_removed,
                        "total_edits": len(edits),
                    }

        except Exception as e:
            logger.debug(f"Failed to extract file changes: {e}")

        return None

    def _extract_command_data(self, tool_name: str, tool_input: Optional[Dict]) -> Optional[Dict[str, Any]]:
        """Extract structured command/shell data for terminal-like display."""
        if not tool_input:
            return None

        try:
            name_lower = tool_name.lower()
            if name_lower in ("bash", "shell", "execute", "terminal", "run"):
                command = tool_input.get("command", tool_input.get("cmd", ""))
                if command:
                    return {
                        "command": command[:10000],  # Max 10KB
                        "working_dir": tool_input.get("working_dir", tool_input.get("cwd", "")),
                    }
        except Exception:
            pass
        return None

    def _extract_file_read_data(self, tool_name: str, tool_input: Optional[Dict]) -> Optional[Dict[str, Any]]:
        """Extract structured file read data for code viewer display."""
        if not tool_input:
            return None

        try:
            name_lower = tool_name.lower()
            if name_lower in ("read", "readfile", "read_file", "view", "cat"):
                file_path = tool_input.get("file_path", tool_input.get("path", tool_input.get("file", "")))
                if file_path:
                    return {
                        "file_path": file_path,
                        "start_line": tool_input.get("start_line", tool_input.get("offset")),
                        "end_line": tool_input.get("end_line", tool_input.get("limit")),
                    }
        except Exception:
            pass
        return None

    def _format_tool_detail(self, tool_name: str, tool_input: Optional[Dict]) -> str:
        """Delegate to :func:`service.logging.tool_detail_formatter.format_tool_detail`."""
        return format_tool_detail(tool_name, tool_input)

    def log_tool_result(
        self,
        tool_name: str,
        tool_id: Optional[str] = None,
        result: Optional[str] = None,
        is_error: bool = False,
        duration_ms: Optional[int] = None
    ):
        """
        Log a tool execution result.

        Args:
            tool_name: Name of the tool
            tool_id: Unique ID for this tool use
            result: Tool execution result
            is_error: Whether the tool execution failed
            duration_ms: Tool execution time
        """
        result_length = len(result) if result else 0

        # For file-related tools, keep more result content for IDE display
        name_lower = tool_name.lower()
        is_file_tool = name_lower in (
            "read", "readfile", "read_file", "view", "cat",
            "bash", "shell", "execute", "terminal", "run",
        )
        max_preview = 5000 if is_file_tool else 500
        is_truncated = result_length > max_preview
        result_preview = result[:max_preview] + "..." if result and is_truncated else result

        metadata = {
            "type": "tool_result",
            "tool_name": tool_name,
            "tool_id": tool_id,
            "is_error": is_error,
            "result_preview": result_preview,
            "result_length": result_length,
            "duration_ms": duration_ms,
            "is_truncated": is_truncated,
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}

        status = "ERROR" if is_error else "OK"
        message = f"TOOL_RESULT [{status}]: {tool_name}"
        self.log(LogLevel.TOOL_RESULT, message, metadata)

    def log_stream_event(
        self,
        event_type: str,
        data: Dict[str, Any]
    ):
        """
        Log a stream-json event from Claude CLI.

        Args:
            event_type: Type of stream event (system_init, tool_use, result, etc.)
            data: Event data
        """
        # Extract key information based on event type
        preview = ""
        if event_type == "system_init":
            tools = data.get("tools", [])
            model = data.get("model", "unknown")
            preview = f"Model: {model}, Tools: {len(tools)}"
        elif event_type == "tool_use":
            tool_name = data.get("tool_name", "unknown")
            preview = f"Tool: {tool_name}"
        elif event_type == "result":
            duration = data.get("duration_ms", 0)
            cost = data.get("total_cost_usd", 0)
            preview = f"Duration: {duration}ms, Cost: ${cost:.6f}"

        metadata = {
            "type": "stream_event",
            "event_type": event_type,
            "preview": preview,
            "data": data
        }

        message = f"STREAM [{event_type}]: {preview}"
        self.log(LogLevel.STREAM_EVENT, message, metadata)

    def log_session_event(self, event: str, details: Optional[Dict[str, Any]] = None):
        """
        Log a session lifecycle event.

        Args:
            event: Event type (e.g., "created", "stopped", "error")
            details: Event details
        """
        metadata = {"event": event}
        if details:
            metadata.update(details)
        self.log(LogLevel.INFO, f"SESSION EVENT: {event}", metadata)

    def log_delegation_event(self, event: str, details: Dict[str, Any]) -> None:
        """Log a delegation protocol event.

        `event` is one of "delegation.sent" / "delegation.received".
        `details` must carry both session ids (`from_session_id`,
        `to_session_id`), the delegation `tag`, and optionally
        `task_id` + `from_role` / `to_role`.
        """
        metadata = {"event": event}
        metadata.update({k: v for k, v in details.items() if v is not None})
        tag = details.get("tag") or ""
        other_id = (
            details.get("to_session_id") if event == "delegation.sent"
            else details.get("from_session_id")
        )
        other_short = (other_id[:8] + "…") if isinstance(other_id, str) and len(other_id) > 8 else other_id
        direction = "→" if event == "delegation.sent" else "←"
        message = f"DELEGATION {direction} {tag} {other_short or ''}".strip()
        self.log(LogLevel.INFO, message, metadata)

    # ========== Stage Event Logging (geny-executor Environment model) ==========

    def log_stage_event(
        self,
        event_type: str,
        message: str,
        stage_name: Optional[str] = None,
        stage_order: Optional[int] = None,
        stage_display_name: Optional[str] = None,
        iteration: Optional[int] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Log a geny-executor stage lifecycle event.

        ``stage_name`` is the canonical short name (``"yield"``,
        ``"tool"``, …). ``stage_order`` is the 1-21 position from
        :data:`STAGE_ORDER`; callers pass it explicitly so a new
        unrecognised stage still logs (with ``stage_order=None``).
        ``node_name`` is mirrored into metadata for back-compat with
        frontend code that still reads legacy GRAPH rows.

        Returns:
            Event ID for tracking.
        """
        import uuid
        event_id = str(uuid.uuid4())[:8]

        metadata = {
            "event_id": event_id,
            "event_type": event_type,
            "stage_name": stage_name,
            "stage_order": stage_order,
            "stage_display_name": stage_display_name,
            "iteration": iteration,
            # Legacy mirror — old DB rows and older frontend code read node_name.
            "node_name": stage_name,
            "state_snapshot": state_snapshot,
            "data": data,
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}

        self.log(LogLevel.STAGE, message, metadata)
        return event_id

    def log_stage_enter(
        self,
        stage_name: str,
        *,
        stage_order: Optional[int] = None,
        iteration: int = 0,
        state_summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        display = stage_display_name(stage_name, stage_order)
        iter_suffix = f" (iter {iteration})" if iteration else ""
        message = f"→ {display}{iter_suffix}"
        return self.log_stage_event(
            event_type="stage_enter",
            message=message,
            stage_name=stage_name,
            stage_order=stage_order,
            stage_display_name=display,
            iteration=iteration,
            state_snapshot=state_summary,
        )

    def log_stage_exit(
        self,
        stage_name: str,
        *,
        stage_order: Optional[int] = None,
        iteration: int = 0,
        output_preview: Optional[str] = None,
        duration_ms: Optional[int] = None,
        state_changes: Optional[Dict[str, Any]] = None,
    ) -> str:
        display = stage_display_name(stage_name, stage_order)
        iter_suffix = f" (iter {iteration})" if iteration else ""
        message = f"✓ {display}{iter_suffix}"
        if duration_ms:
            message += f" [{duration_ms}ms]"
        return self.log_stage_event(
            event_type="stage_exit",
            message=message,
            stage_name=stage_name,
            stage_order=stage_order,
            stage_display_name=display,
            iteration=iteration,
            data={
                "iteration": iteration,
                "output_preview": output_preview[:200] if output_preview and len(output_preview) > 200 else output_preview,
                "output_length": len(output_preview) if output_preview else 0,
                "duration_ms": duration_ms,
                "state_changes": state_changes,
            },
        )

    def log_stage_bypass(
        self,
        stage_name: str,
        *,
        stage_order: Optional[int] = None,
        iteration: int = 0,
        reason: Optional[str] = None,
    ) -> str:
        """Log a stage that was registered but skipped (empty slot or conditional bypass)."""
        display = stage_display_name(stage_name, stage_order)
        message = f"⊘ {display} (skipped)"
        return self.log_stage_event(
            event_type="stage_bypass",
            message=message,
            stage_name=stage_name,
            stage_order=stage_order,
            stage_display_name=display,
            iteration=iteration,
            data={"reason": reason} if reason else None,
        )

    def log_stage_error(
        self,
        stage_name: str,
        error: str,
        *,
        stage_order: Optional[int] = None,
        iteration: int = 0,
    ) -> str:
        """Log a stage that raised. Recovery may still follow."""
        display = stage_display_name(stage_name, stage_order)
        short = (error or "")[:200]
        message = f"✗ {display}: {short}"
        return self.log_stage_event(
            event_type="stage_error",
            message=message,
            stage_name=stage_name,
            stage_order=stage_order,
            stage_display_name=display,
            iteration=iteration,
            data={"error": error},
        )

    def log_stage_execution_start(
        self,
        input_text: str,
        thread_id: Optional[str] = None,
        max_iterations: Optional[int] = None,
        execution_mode: str = "invoke",
    ) -> str:
        """Log when a pipeline starts. Mirrors old ``log_graph_execution_start``."""
        input_preview = input_text[:100] + "..." if len(input_text) > 100 else input_text
        message = f"PIPELINE START [{execution_mode.upper()}]: {input_preview}"
        return self.log_stage_event(
            event_type="execution_start",
            message=message,
            data={
                "input_preview": input_preview,
                "input_length": len(input_text),
                "thread_id": thread_id,
                "max_iterations": max_iterations,
                "execution_mode": execution_mode,
            },
        )

    def log_stage_execution_complete(
        self,
        success: bool,
        total_iterations: int,
        final_output: Optional[str] = None,
        total_duration_ms: Optional[int] = None,
        stop_reason: Optional[str] = None,
    ) -> str:
        """Log when a pipeline finishes."""
        status = "SUCCESS" if success else "FAILED"
        message = f"PIPELINE COMPLETE [{status}]: {total_iterations} iterations"
        if stop_reason:
            message += f" ({stop_reason})"

        output_preview = None
        if final_output:
            output_preview = final_output[:200] + "..." if len(final_output) > 200 else final_output

        return self.log_stage_event(
            event_type="execution_complete",
            message=message,
            data={
                "success": success,
                "total_iterations": total_iterations,
                "final_output_preview": output_preview,
                "final_output_length": len(final_output) if final_output else 0,
                "total_duration_ms": total_duration_ms,
                "stop_reason": stop_reason,
            },
        )

    # ── Legacy ``log_graph_*`` wrappers ──────────────────────────────
    # Kept so any external caller / call site not yet migrated keeps
    # working. They route to the new STAGE-level emit; the frontend
    # renders legacy GRAPH rows with the same Stage visual.

    def log_graph_event(
        self,
        event_type: str,
        message: str,
        node_name: Optional[str] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """DEPRECATED — use :meth:`log_stage_event`.

        ``node_name`` is treated as ``stage_name``. Emits at LogLevel.STAGE.
        """
        return self.log_stage_event(
            event_type=event_type,
            message=message,
            stage_name=node_name,
            stage_order=STAGE_ORDER.get(node_name) if node_name else None,
            stage_display_name=stage_display_name(node_name, STAGE_ORDER.get(node_name) if node_name else None),
            state_snapshot=state_snapshot,
            data=data,
        )

    def log_graph_execution_start(self, *args, **kwargs) -> str:
        """DEPRECATED — use :meth:`log_stage_execution_start`."""
        return self.log_stage_execution_start(*args, **kwargs)

    def log_graph_node_enter(
        self,
        node_name: str,
        iteration: int = 0,
        state_summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        """DEPRECATED — use :meth:`log_stage_enter`."""
        return self.log_stage_enter(
            stage_name=node_name,
            stage_order=STAGE_ORDER.get(node_name),
            iteration=iteration,
            state_summary=state_summary,
        )

    def log_graph_node_exit(
        self,
        node_name: str,
        iteration: int = 0,
        output_preview: Optional[str] = None,
        duration_ms: Optional[int] = None,
        state_changes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """DEPRECATED — use :meth:`log_stage_exit`."""
        return self.log_stage_exit(
            stage_name=node_name,
            stage_order=STAGE_ORDER.get(node_name),
            iteration=iteration,
            output_preview=output_preview,
            duration_ms=duration_ms,
            state_changes=state_changes,
        )

    def log_graph_state_update(
        self,
        update_type: str,
        changes: Dict[str, Any],
        iteration: int = 0,
    ) -> str:
        """DEPRECATED — use :meth:`log_stage_event`."""
        message = f"STATE UPDATE: {update_type} (iteration {iteration})"
        return self.log_stage_event(
            event_type="state_update",
            message=message,
            iteration=iteration,
            data={"update_type": update_type, "iteration": iteration, "changes": changes},
        )

    def log_graph_edge_decision(
        self,
        from_node: str,
        decision: str,
        reason: Optional[str] = None,
        iteration: int = 0,
    ) -> str:
        """DEPRECATED — use :meth:`log_stage_event`."""
        message = f"EDGE DECISION: {from_node} -> {decision}"
        if reason:
            message += f" ({reason})"
        return self.log_stage_event(
            event_type="edge_decision",
            message=message,
            stage_name=from_node,
            stage_order=STAGE_ORDER.get(from_node),
            iteration=iteration,
            data={"from_node": from_node, "decision": decision, "reason": reason, "iteration": iteration},
        )

    def log_graph_execution_complete(self, *args, **kwargs) -> str:
        """DEPRECATED — use :meth:`log_stage_execution_complete`."""
        return self.log_stage_execution_complete(*args, **kwargs)

    def log_graph_error(
        self,
        error_message: str,
        node_name: Optional[str] = None,
        iteration: int = 0,
        error_type: Optional[str] = None,
    ) -> str:
        """DEPRECATED — use :meth:`log_stage_error`."""
        return self.log_stage_error(
            stage_name=node_name or "unknown",
            error=error_message,
            stage_order=STAGE_ORDER.get(node_name) if node_name else None,
            iteration=iteration,
        )

    def get_stage_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get stage lifecycle log entries (new STAGE level)."""
        return self.get_logs(limit=limit, level=LogLevel.STAGE)

    def get_graph_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """DEPRECATED — use :meth:`get_stage_events`.

        Still returns only legacy GRAPH-level rows for callers that
        explicitly want to inspect pre-migration logs.
        """
        return self.get_logs(limit=limit, level=LogLevel.GRAPH)

    # ── Public API for cache-based streaming (used by SSE endpoint) ──

    def get_cache_length(self) -> int:
        """Return monotonic write count (used as cursor for SSE streaming).

        This returns a cursor value that only increases, even when the
        underlying cache is trimmed.  Use ``get_cache_entries_since()``
        with the value returned here.
        """
        with self._lock:
            return self._write_count

    def get_last_write_at(self) -> float:
        """Return monotonic timestamp of last cache write (0 if never written)."""
        return self._last_write_at

    def get_last_entry_info(self) -> dict:
        """Return level and tool name of the most recent log entry."""
        return {
            "level": self._last_entry_level,
            "tool_name": self._last_tool_name,
        }

    def extract_file_changes_from_cache(self, since_cursor: int = 0) -> list:
        """Extract file change entries from cached TOOL logs.

        *since_cursor* is a monotonic write-count cursor (from
        ``get_cache_length``).  Entries written after that point are
        scanned for file-change metadata.
        """
        with self._lock:
            new_writes = self._write_count - since_cursor
            if new_writes <= 0:
                entries = []
            else:
                available = min(new_writes, len(self._log_cache))
                entries = self._log_cache[-available:]
        result = []
        for entry in entries:
            if entry.level != LogLevel.TOOL_USE:
                continue
            meta = entry.metadata or {}
            fc = meta.get("file_changes")
            if not fc:
                continue
            result.append({
                "file_path": fc.get("file_path", ""),
                "operation": fc.get("operation", "write"),
                "lines_added": fc.get("lines_added", 0),
                "lines_removed": fc.get("lines_removed", 0),
                "changes": fc.get("changes", []),
                "is_content_truncated": fc.get("is_content_truncated", False),
                "total_edits": fc.get("total_edits"),
            })
        return result

    def get_cache_entries_since(self, cursor: int) -> "tuple[list[LogEntry], int]":
        """Return new cache entries after *cursor* and the updated cursor.

        Args:
            cursor: Previous write count (as returned by ``get_cache_length``
                    or a prior call to this method).

        Returns:
            (new_entries, new_cursor) – list of LogEntry objects + updated cursor.
        """
        with self._lock:
            new_writes = self._write_count - cursor
            if new_writes > 0:
                # Return at most as many entries as still exist in cache
                available = min(new_writes, len(self._log_cache))
                return list(self._log_cache[-available:]), self._write_count
            return [], cursor

    def get_logs(
        self,
        limit: int = 100,
        level: Optional["LogLevel | set[LogLevel]"] = None,
        from_cache: bool = True,
        offset: int = 0,
        newest_first: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get log entries.

        Priority: cache → DB → file.

        Args:
            limit: Maximum number of entries to return
            level: Filter by a single LogLevel or a set of LogLevels
            from_cache: If True, read from cache; if False, try DB then file
            offset: Number of entries to skip (for pagination)
            newest_first: If True, return newest entries first

        Returns:
            List of log entries as dictionaries
        """
        if from_cache:
            with self._lock:
                all_entries = list(self._log_cache)
                if level:
                    if isinstance(level, set):
                        all_entries = [e for e in all_entries if e.level in level]
                    else:
                        all_entries = [e for e in all_entries if e.level == level]
                if newest_first:
                    all_entries = list(reversed(all_entries))
                entries = all_entries[offset:offset + limit]
                return [e.to_dict() for e in entries]
        else:
            # Try DB first
            db_entries = self._read_logs_from_db(limit, level, offset, newest_first)
            if db_entries is not None:
                return db_entries
            # Fallback to file
            return self._read_logs_from_file(limit, level)

    def count_logs(
        self,
        level: Optional["LogLevel | set[LogLevel]"] = None,
        from_cache: bool = True,
    ) -> int:
        """
        Count total log entries (for pagination).

        Args:
            level: Filter by a single LogLevel or a set of LogLevels
            from_cache: If True, count from cache; if False, try DB

        Returns:
            Total count of matching entries
        """
        if from_cache:
            with self._lock:
                if not level:
                    return len(self._log_cache)
                if isinstance(level, set):
                    return sum(1 for e in self._log_cache if e.level in level)
                return sum(1 for e in self._log_cache if e.level == level)
        else:
            global _log_db_manager
            if _log_db_manager is not None:
                try:
                    from service.database.session_log_db_helper import db_count_session_logs
                    level_filter: Optional[set] = None
                    if level:
                        if isinstance(level, set):
                            level_filter = {lv.value for lv in level}
                        else:
                            level_filter = {level.value}
                    result = db_count_session_logs(
                        _log_db_manager,
                        session_id=self.session_id,
                        level_filter=level_filter,
                    )
                    if result is not None:
                        return result
                except Exception:
                    pass
            # Fallback to cache
            return self.count_logs(level=level, from_cache=True)

    def _read_logs_from_db(
        self,
        limit: int = 100,
        level: Optional["LogLevel | set[LogLevel]"] = None,
        offset: int = 0,
        newest_first: bool = True,
    ) -> Optional[List[Dict[str, Any]]]:
        """Read log entries from DB. Returns None if DB unavailable."""
        global _log_db_manager
        if _log_db_manager is None:
            return None
        try:
            from service.database.session_log_db_helper import db_get_session_logs

            level_filter: Optional[set] = None
            if level:
                if isinstance(level, set):
                    level_filter = {lv.value for lv in level}
                else:
                    level_filter = {level.value}

            return db_get_session_logs(
                _log_db_manager,
                session_id=self.session_id,
                limit=limit,
                level_filter=level_filter,
                offset=offset,
                newest_first=newest_first,
            )
        except Exception as e:
            logger.debug(f"SessionLogger: DB read failed, falling back to file: {e}")
            return None

    def _read_logs_from_file(
        self,
        limit: int = 100,
        level: Optional[LogLevel] = None
    ) -> List[Dict[str, Any]]:
        """Read log entries from file."""
        entries = []
        try:
            with self._lock:
                if not self._log_file.exists():
                    return []

                with open(self._log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                for line in lines[-limit * 2:]:  # Read more lines to account for filtering
                    if line.startswith('[') and '] [' in line:
                        try:
                            # Parse log line
                            # Format: [timestamp] [LEVEL   ] message | metadata
                            parts = line.split('] [', 1)
                            if len(parts) >= 2:
                                ts_str = parts[0][1:]
                                rest = parts[1]
                                level_end = rest.find(']')
                                if level_end > 0:
                                    log_level = rest[:level_end].strip()
                                    message_part = rest[level_end + 2:].strip()

                                    # Check level filter
                                    if level and log_level != level.value:
                                        continue

                                    # Parse metadata if present
                                    metadata = {}
                                    if ' | ' in message_part:
                                        msg, meta_str = message_part.rsplit(' | ', 1)
                                        try:
                                            metadata = json.loads(meta_str)
                                        except json.JSONDecodeError:
                                            pass
                                    else:
                                        msg = message_part.rstrip('\n')

                                    entries.append({
                                        "timestamp": ts_str,
                                        "level": log_level,
                                        "message": msg,
                                        "metadata": metadata
                                    })
                        except Exception:
                            continue

                return entries[-limit:]
        except Exception as e:
            logger.error(f"Failed to read logs from file: {e}")
            return []

    def get_log_file_path(self) -> str:
        """Get the path to this session's log file."""
        return str(self._log_file)

    def close(self):
        """Close the logger and write session end marker."""
        footer = (
            f"\n{'=' * 80}\n"
            f"Session Ended: {format_kst(now_kst())}\n"
            f"{'=' * 80}\n"
        )
        with self._lock:
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(footer)


# Session logger registry
_session_loggers: Dict[str, SessionLogger] = {}
_registry_lock = Lock()


def get_session_logger(
    session_id: str,
    session_name: Optional[str] = None,
    create_if_missing: bool = True
) -> Optional[SessionLogger]:
    """
    Get or create a session logger.

    Args:
        session_id: Session ID
        session_name: Session name (used only when creating)
        create_if_missing: If True, create logger if it doesn't exist

    Returns:
        SessionLogger instance or None
    """
    with _registry_lock:
        if session_id in _session_loggers:
            return _session_loggers[session_id]

        if create_if_missing:
            logger_instance = SessionLogger(session_id, session_name)
            _session_loggers[session_id] = logger_instance
            return logger_instance

        return None


def remove_session_logger(session_id: str, delete_file: bool = False):
    """
    Remove session logger from memory.

    By default, log files are preserved for historical reference.
    Only removes from memory registry, not from disk.

    Args:
        session_id: Session ID
        delete_file: If True, also delete the log file (default: False)
    """
    with _registry_lock:
        if session_id in _session_loggers:
            session_logger = _session_loggers[session_id]
            session_logger.close()

            # Optionally delete the file (default: keep it)
            if delete_file:
                try:
                    log_path = Path(session_logger.get_log_file_path())
                    if log_path.exists():
                        log_path.unlink()
                        logger.info(f"Deleted log file: {log_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete log file: {e}")

            del _session_loggers[session_id]


def list_session_logs() -> List[Dict[str, Any]]:
    """
    List all available session log files.

    Tries DB first, falls back to file-system scan.

    Returns:
        List of log file info dictionaries
    """
    global _log_db_manager

    # Try DB first
    if _log_db_manager is not None:
        try:
            from service.database.session_log_db_helper import db_list_session_log_summaries
            db_results = db_list_session_log_summaries(_log_db_manager)
            if db_results is not None and len(db_results) > 0:
                return db_results
        except Exception as e:
            logger.debug(f"list_session_logs: DB read failed, falling back to files: {e}")

    # Fallback to file-system scan
    logs_dir = Path(__file__).parent.parent.parent / "logs"
    if not logs_dir.exists():
        return []

    log_files = []
    for log_file in logs_dir.glob("*.log"):
        stat = log_file.stat()
        log_files.append({
            "session_id": log_file.stem,
            "file_name": log_file.name,
            "file_path": str(log_file),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })

    # Sort by modification time (newest first)
    log_files.sort(key=lambda x: x["modified_at"], reverse=True)
    return log_files


def read_logs_from_file(
    session_id: str,
    limit: int = 100,
    level: Optional["LogLevel | set[LogLevel]"] = None,
    offset: int = 0,
    newest_first: bool = True,
) -> List[Dict[str, Any]]:
    """
    Read log entries for a session.

    Tries DB first, falls back to file-based reading.

    This function reads logs without requiring an active session logger.
    Useful for reading historical logs from deleted sessions.

    Args:
        session_id: Session ID (used to find the log file)
        limit: Maximum number of entries to return
        level: Filter by a single LogLevel or a set of LogLevels
        offset: Number of entries to skip (for pagination)
        newest_first: If True, return newest entries first

    Returns:
        List of log entries as dictionaries
    """
    global _log_db_manager

    # Try DB first
    if _log_db_manager is not None:
        try:
            from service.database.session_log_db_helper import db_get_session_logs, db_session_has_logs

            if db_session_has_logs(_log_db_manager, session_id):
                level_filter: Optional[set] = None
                if level:
                    if isinstance(level, set):
                        level_filter = {lv.value for lv in level}
                    else:
                        level_filter = {level.value}

                db_entries = db_get_session_logs(
                    _log_db_manager,
                    session_id=session_id,
                    limit=limit,
                    level_filter=level_filter,
                    offset=offset,
                    newest_first=newest_first,
                )
                if db_entries is not None:
                    return db_entries
        except Exception as e:
            logger.debug(f"read_logs_from_file: DB read failed, falling back to file: {e}")

    # Fallback to file-based reading
    # Build a set of allowed level value strings for fast checking
    allowed_values: Optional[set] = None
    if level:
        if isinstance(level, set):
            allowed_values = {lv.value for lv in level}
        else:
            allowed_values = {level.value}

    logs_dir = Path(__file__).parent.parent.parent / "logs"
    log_file = logs_dir / f"{session_id}.log"

    if not log_file.exists():
        return []

    entries = []
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            if line.startswith('[') and '] [' in line:
                try:
                    # Parse log line
                    # Format: [timestamp] [LEVEL   ] message | metadata
                    parts = line.split('] [', 1)
                    if len(parts) >= 2:
                        ts_str = parts[0][1:]
                        rest = parts[1]
                        level_end = rest.find(']')
                        if level_end > 0:
                            log_level = rest[:level_end].strip()

                            # Check level filter
                            if allowed_values and log_level not in allowed_values:
                                continue

                            message_part = rest[level_end + 2:].strip()

                            # Parse metadata if present
                            metadata = {}
                            if ' | ' in message_part:
                                msg, meta_str = message_part.rsplit(' | ', 1)
                                try:
                                    metadata = json.loads(meta_str)
                                except json.JSONDecodeError:
                                    pass
                            else:
                                msg = message_part.rstrip('\n')

                            entries.append({
                                "timestamp": ts_str,
                                "level": log_level,
                                "message": msg,
                                "metadata": metadata
                            })
                except Exception:
                    continue

        return entries[-limit:]
    except Exception as e:
        logger.error(f"Failed to read logs from file {log_file}: {e}")
        return []


def get_log_file_path(session_id: str) -> Optional[str]:
    """
    Get the log file path for a session.

    Args:
        session_id: Session ID

    Returns:
        Path to log file if exists, None otherwise
    """
    logs_dir = Path(__file__).parent.parent.parent / "logs"
    log_file = logs_dir / f"{session_id}.log"
    return str(log_file) if log_file.exists() else None


def count_logs_for_session(
    session_id: str,
    level: Optional["LogLevel | set[LogLevel]"] = None,
) -> int:
    """
    Count total log entries for a session (for pagination).

    Tries DB first (full history), then falls back to active session logger cache.

    Args:
        session_id: Session ID
        level: Filter by a single LogLevel or a set of LogLevels

    Returns:
        Total count of matching entries
    """
    # Try DB first — it has the complete history
    global _log_db_manager
    if _log_db_manager is not None:
        try:
            from service.database.session_log_db_helper import db_count_session_logs
            level_filter: Optional[set] = None
            if level:
                if isinstance(level, set):
                    level_filter = {lv.value for lv in level}
                else:
                    level_filter = {level.value}
            result = db_count_session_logs(
                _log_db_manager,
                session_id=session_id,
                level_filter=level_filter,
            )
            if result is not None:
                return result
        except Exception:
            pass

    # Fallback to active logger cache
    session_logger = get_session_logger(session_id, create_if_missing=False)
    if session_logger:
        return session_logger.count_logs(level=level, from_cache=True)

    return 0
