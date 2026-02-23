"""
Session Logger

Per-session logging system for Claude Control.
Each session gets its own log file in the logs/ directory.
"""
import json
from logging import getLogger
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List
from threading import Lock

from service.utils.utils import now_kst, format_kst

logger = getLogger(__name__)


class LogLevel(str, Enum):
    """Log levels for session logging."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    COMMAND = "COMMAND"
    RESPONSE = "RESPONSE"
    MANAGER_EVENT = "MANAGER"   # Manager-specific events for hierarchical management
    GRAPH = "GRAPH"             # LangGraph state transitions and node executions
    TOOL_USE = "TOOL"           # Tool invocation events
    TOOL_RESULT = "TOOL_RES"    # Tool execution results
    STREAM_EVENT = "STREAM"     # Stream-json events
    ITERATION = "ITER"          # Autonomous execution iteration complete


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert log entry to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "message": self.message,
            "metadata": self.metadata
        }

    def to_line(self) -> str:
        """Convert log entry to formatted log line."""
        ts = format_kst(self.timestamp)
        meta_str = ""
        if self.metadata:
            meta_str = f" | {json.dumps(self.metadata, ensure_ascii=False)}"
        return f"[{ts}] [{self.level.value:8}] {self.message}{meta_str}\n"


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
        self._max_cache_size = 1000  # Keep last 1000 entries in memory

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
        """Write a log entry to file and cache."""
        with self._lock:
            # Write to file
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(entry.to_line())

            # Add to cache
            self._log_cache.append(entry)

            # Trim cache if too large
            if len(self._log_cache) > self._max_cache_size:
                self._log_cache = self._log_cache[-self._max_cache_size:]

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
        max_turns: Optional[int] = None
    ):
        """
        Log a command sent to Claude.

        Args:
            prompt: The prompt/command sent to Claude
            timeout: Command timeout
            system_prompt: Custom system prompt
            max_turns: Maximum turns for execution
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
            "preview": preview
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
        num_turns: Optional[int] = None
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
            "num_turns": num_turns
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

        message = f"🔧 {tool_name}: {detail}"
        self.log(LogLevel.TOOL_USE, message, metadata)

    def _format_tool_detail(self, tool_name: str, tool_input: Optional[Dict]) -> str:
        """
        Format tool input into a concise, informative detail string.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input dictionary

        Returns:
            Formatted detail string for display
        """
        if not tool_input:
            return "(no input)"

        try:
            name_lower = tool_name.lower()

            # Bash/shell commands
            if name_lower in ("bash", "shell", "execute"):
                command = tool_input.get("command", tool_input.get("cmd", ""))
                if command:
                    # Clean up and truncate
                    command = command.strip().replace("\n", " ")
                    if len(command) > 100:
                        return f"`{command[:100]}...`"
                    return f"`{command}`"

            # Read file operations
            elif name_lower in ("read", "readfile", "read_file", "view"):
                file_path = tool_input.get("file_path", tool_input.get("path", tool_input.get("file", "")))
                start_line = tool_input.get("start_line", tool_input.get("offset", ""))
                end_line = tool_input.get("end_line", tool_input.get("limit", ""))
                if file_path:
                    # Get just filename for brevity
                    filename = file_path.replace("\\", "/").split("/")[-1]
                    if start_line and end_line:
                        return f"{filename} (L{start_line}-{end_line})"
                    elif start_line:
                        return f"{filename} (from L{start_line})"
                    return filename

            # Write file operations
            elif name_lower in ("write", "writefile", "write_file", "edit", "edit_file"):
                file_path = tool_input.get("file_path", tool_input.get("path", tool_input.get("file", "")))
                content = tool_input.get("content", tool_input.get("text", ""))
                if file_path:
                    filename = file_path.replace("\\", "/").split("/")[-1]
                    if content:
                        lines = content.count("\n") + 1
                        chars = len(content)
                        return f"{filename} (+{lines} lines, {chars} chars)"
                    return filename

            # Glob/search/list operations
            elif name_lower in ("glob", "search", "find", "list", "ls", "listdir"):
                pattern = tool_input.get("pattern", tool_input.get("query", tool_input.get("path", "")))
                if pattern:
                    if len(pattern) > 60:
                        return f"`{pattern[:60]}...`"
                    return f"`{pattern}`"

            # Grep operations
            elif name_lower in ("grep", "ripgrep", "rg"):
                pattern = tool_input.get("pattern", tool_input.get("query", tool_input.get("regex", "")))
                path = tool_input.get("path", tool_input.get("directory", ""))
                if pattern:
                    pat = f"`{pattern[:40]}`" if len(pattern) > 40 else f"`{pattern}`"
                    if path:
                        dir_name = path.replace("\\", "/").split("/")[-1]
                        return f"{pat} in {dir_name}"
                    return pat

            # Web fetch
            elif name_lower in ("fetch", "web", "http", "curl"):
                url = tool_input.get("url", tool_input.get("uri", ""))
                if url:
                    if len(url) > 60:
                        return f"{url[:60]}..."
                    return url

            # MCP tool calls (mcp__server__tool format)
            elif tool_name.startswith("mcp__") or "__" in tool_name:
                # Try to extract most relevant parameter
                for key in ["query", "path", "file_path", "command", "url", "content", "message", "prompt"]:
                    if key in tool_input:
                        value = str(tool_input[key]).strip().replace("\n", " ")
                        if len(value) > 80:
                            return f"{key}=`{value[:80]}...`"
                        return f"{key}=`{value}`"

            # Default: show first meaningful parameter
            for key, value in tool_input.items():
                if key.startswith("_"):
                    continue
                value_str = str(value).strip().replace("\n", " ")
                if len(value_str) > 80:
                    return f"{key}=`{value_str[:80]}...`"
                return f"{key}=`{value_str}`"

            return "(empty input)"

        except Exception as e:
            return f"(parse error)"

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
        is_truncated = result_length > 500
        result_preview = result[:500] + "..." if result and is_truncated else result

        metadata = {
            "type": "tool_result",
            "tool_name": tool_name,
            "tool_id": tool_id,
            "is_error": is_error,
            "result_preview": result_preview,
            "result_length": result_length,
            "duration_ms": duration_ms
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

    # ========== Manager Event Logging ==========

    def log_manager_event(
        self,
        event_type: str,
        message: str,
        worker_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ):
        """
        Log a manager-specific event for hierarchical management.

        Args:
            event_type: Type of manager event (e.g., task_delegated, worker_completed)
            message: Human-readable event description
            worker_id: Worker session ID (if applicable)
            data: Additional event data
        """
        import uuid
        event_id = str(uuid.uuid4())[:8]

        metadata = {
            "event_id": event_id,
            "event_type": event_type,
            "worker_id": worker_id,
            "data": data
        }
        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v is not None}

        self.log(LogLevel.MANAGER_EVENT, message, metadata)
        return event_id

    def log_task_delegated(
        self,
        worker_id: str,
        worker_name: Optional[str],
        task_prompt: str,
        context: Optional[str] = None
    ) -> str:
        """Log when manager delegates a task to worker."""
        task_preview = task_prompt[:100] + "..." if len(task_prompt) > 100 else task_prompt
        message = f"Delegated task to {worker_name or worker_id[:8]}: {task_preview}"
        return self.log_manager_event(
            event_type="task_delegated",
            message=message,
            worker_id=worker_id,
            data={
                "worker_name": worker_name,
                "task_preview": task_preview,
                "task_length": len(task_prompt),
                "context": context
            }
        )

    def log_worker_started(self, worker_id: str, worker_name: Optional[str]):
        """Log when a worker starts executing."""
        message = f"Worker {worker_name or worker_id[:8]} started execution"
        return self.log_manager_event(
            event_type="worker_started",
            message=message,
            worker_id=worker_id,
            data={"worker_name": worker_name}
        )

    def log_worker_progress(
        self,
        worker_id: str,
        worker_name: Optional[str],
        progress: str,
        iteration: Optional[int] = None
    ):
        """Log worker progress update."""
        message = f"Worker {worker_name or worker_id[:8]}: {progress}"
        return self.log_manager_event(
            event_type="worker_progress",
            message=message,
            worker_id=worker_id,
            data={
                "worker_name": worker_name,
                "progress": progress,
                "iteration": iteration
            }
        )

    def log_worker_completed(
        self,
        worker_id: str,
        worker_name: Optional[str],
        success: bool,
        output_preview: Optional[str] = None,
        duration_ms: Optional[int] = None,
        cost_usd: Optional[float] = None
    ):
        """Log when a worker completes execution."""
        status = "completed successfully" if success else "failed"
        message = f"Worker {worker_name or worker_id[:8]} {status}"
        return self.log_manager_event(
            event_type="worker_completed" if success else "worker_error",
            message=message,
            worker_id=worker_id,
            data={
                "worker_name": worker_name,
                "success": success,
                "output_preview": output_preview,
                "duration_ms": duration_ms,
                "cost_usd": cost_usd
            }
        )

    def log_plan_update(self, plan_summary: str, action: str = "updated"):
        """Log when manager updates its plan/todo list."""
        message = f"Plan {action}: {plan_summary}"
        return self.log_manager_event(
            event_type="plan_updated",
            message=message,
            data={"plan_summary": plan_summary, "action": action}
        )

    def log_user_interaction(self, user_message: str, manager_response: Optional[str] = None):
        """Log user interaction with manager."""
        message = f"User: {user_message[:100]}..."
        return self.log_manager_event(
            event_type="user_message",
            message=message,
            data={
                "user_message_preview": user_message[:200] if len(user_message) > 200 else user_message,
                "has_response": manager_response is not None
            }
        )

    def get_manager_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get manager event log entries.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of manager event entries
        """
        return self.get_logs(limit=limit, level=LogLevel.MANAGER_EVENT)

    # ========== LangGraph Event Logging ==========

    def log_graph_event(
        self,
        event_type: str,
        message: str,
        node_name: Optional[str] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Log a LangGraph execution event.

        Args:
            event_type: Type of graph event (e.g., execution_start, node_enter, state_update)
            message: Human-readable event description
            node_name: Current node name (if applicable)
            state_snapshot: Snapshot of current AgentState (if applicable)
            data: Additional event data

        Returns:
            Event ID for tracking
        """
        import uuid
        event_id = str(uuid.uuid4())[:8]

        metadata = {
            "event_id": event_id,
            "event_type": event_type,
            "node_name": node_name,
            "state_snapshot": state_snapshot,
            "data": data
        }
        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v is not None}

        self.log(LogLevel.GRAPH, message, metadata)
        return event_id

    def log_graph_execution_start(
        self,
        input_text: str,
        thread_id: Optional[str] = None,
        max_iterations: Optional[int] = None,
        execution_mode: str = "invoke"
    ) -> str:
        """Log when graph execution starts."""
        input_preview = input_text[:100] + "..." if len(input_text) > 100 else input_text
        message = f"GRAPH START [{execution_mode.upper()}]: {input_preview}"
        return self.log_graph_event(
            event_type="execution_start",
            message=message,
            data={
                "input_preview": input_preview,
                "input_length": len(input_text),
                "thread_id": thread_id,
                "max_iterations": max_iterations,
                "execution_mode": execution_mode
            }
        )

    def log_graph_node_enter(
        self,
        node_name: str,
        iteration: int = 0,
        state_summary: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log when entering a graph node."""
        message = f"NODE ENTER: {node_name} (iteration {iteration})"
        return self.log_graph_event(
            event_type="node_enter",
            message=message,
            node_name=node_name,
            state_snapshot=state_summary,
            data={"iteration": iteration}
        )

    def log_graph_node_exit(
        self,
        node_name: str,
        iteration: int = 0,
        output_preview: Optional[str] = None,
        duration_ms: Optional[int] = None,
        state_changes: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log when exiting a graph node."""
        message = f"NODE EXIT: {node_name} (iteration {iteration})"
        if duration_ms:
            message += f" [{duration_ms}ms]"
        return self.log_graph_event(
            event_type="node_exit",
            message=message,
            node_name=node_name,
            data={
                "iteration": iteration,
                "output_preview": output_preview[:200] if output_preview and len(output_preview) > 200 else output_preview,
                "output_length": len(output_preview) if output_preview else 0,
                "duration_ms": duration_ms,
                "state_changes": state_changes
            }
        )

    def log_graph_state_update(
        self,
        update_type: str,
        changes: Dict[str, Any],
        iteration: int = 0
    ) -> str:
        """Log when graph state is updated."""
        message = f"STATE UPDATE: {update_type} (iteration {iteration})"
        return self.log_graph_event(
            event_type="state_update",
            message=message,
            data={
                "update_type": update_type,
                "iteration": iteration,
                "changes": changes
            }
        )

    def log_graph_edge_decision(
        self,
        from_node: str,
        decision: str,
        reason: Optional[str] = None,
        iteration: int = 0
    ) -> str:
        """Log conditional edge decision."""
        message = f"EDGE DECISION: {from_node} -> {decision}"
        if reason:
            message += f" ({reason})"
        return self.log_graph_event(
            event_type="edge_decision",
            message=message,
            node_name=from_node,
            data={
                "from_node": from_node,
                "decision": decision,
                "reason": reason,
                "iteration": iteration
            }
        )

    def log_graph_execution_complete(
        self,
        success: bool,
        total_iterations: int,
        final_output: Optional[str] = None,
        total_duration_ms: Optional[int] = None,
        stop_reason: Optional[str] = None
    ) -> str:
        """Log when graph execution completes."""
        status = "SUCCESS" if success else "FAILED"
        message = f"GRAPH COMPLETE [{status}]: {total_iterations} iterations"
        if stop_reason:
            message += f" ({stop_reason})"

        output_preview = None
        if final_output:
            output_preview = final_output[:200] + "..." if len(final_output) > 200 else final_output

        return self.log_graph_event(
            event_type="execution_complete",
            message=message,
            data={
                "success": success,
                "total_iterations": total_iterations,
                "final_output_preview": output_preview,
                "final_output_length": len(final_output) if final_output else 0,
                "total_duration_ms": total_duration_ms,
                "stop_reason": stop_reason
            }
        )

    def log_graph_error(
        self,
        error_message: str,
        node_name: Optional[str] = None,
        iteration: int = 0,
        error_type: Optional[str] = None
    ) -> str:
        """Log graph execution error."""
        message = f"GRAPH ERROR"
        if node_name:
            message += f" in {node_name}"
        message += f": {error_message}"

        return self.log_graph_event(
            event_type="error",
            message=message,
            node_name=node_name,
            data={
                "error_message": error_message,
                "error_type": error_type,
                "iteration": iteration
            }
        )

    def get_graph_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get LangGraph event log entries.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of graph event entries
        """
        return self.get_logs(limit=limit, level=LogLevel.GRAPH)

    def get_logs(
        self,
        limit: int = 100,
        level: Optional[LogLevel] = None,
        from_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get log entries.

        Args:
            limit: Maximum number of entries to return
            level: Filter by log level
            from_cache: If True, read from cache; if False, read from file

        Returns:
            List of log entries as dictionaries
        """
        if from_cache:
            with self._lock:
                entries = self._log_cache[-limit:]
                if level:
                    entries = [e for e in entries if e.level == level]
                return [e.to_dict() for e in entries]
        else:
            # Read from file
            return self._read_logs_from_file(limit, level)

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

    Returns:
        List of log file info dictionaries
    """
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
    level: Optional[LogLevel] = None
) -> List[Dict[str, Any]]:
    """
    Read log entries directly from a log file.

    This function reads logs from disk without requiring an active session logger.
    Useful for reading historical logs from deleted sessions.

    Args:
        session_id: Session ID (used to find the log file)
        limit: Maximum number of entries to return
        level: Filter by log level

    Returns:
        List of log entries as dictionaries
    """
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
                            if level and log_level != level.value:
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
