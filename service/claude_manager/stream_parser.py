"""
Claude CLI Stream JSON Parser

Parses --output-format stream-json output from Claude CLI.
Provides structured events for tool usage, assistant messages, and results.
"""
import json
from logging import getLogger
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any, Callable

logger = getLogger(__name__)


class StreamEventType(str, Enum):
    """Types of events from Claude CLI stream-json output."""
    SYSTEM_INIT = "system_init"           # Initial system info (tools, model, etc.)
    ASSISTANT_MESSAGE = "assistant"       # Assistant text message
    TOOL_USE = "tool_use"                 # Tool invocation
    TOOL_RESULT = "tool_result"           # Tool execution result
    CONTENT_BLOCK_START = "content_start" # Content block started
    CONTENT_BLOCK_DELTA = "content_delta" # Content block delta (streaming text)
    CONTENT_BLOCK_STOP = "content_stop"   # Content block finished
    RESULT = "result"                     # Final execution result
    ERROR = "error"                       # Error event
    UNKNOWN = "unknown"                   # Unknown event type


@dataclass
class StreamEvent:
    """Parsed event from Claude CLI stream-json output."""
    event_type: StreamEventType
    timestamp: datetime
    raw_data: Dict[str, Any]

    # Common fields
    session_id: Optional[str] = None

    # System init fields
    tools: Optional[List[str]] = None
    mcp_servers: Optional[List[str]] = None
    model: Optional[str] = None

    # Assistant message fields
    message_id: Optional[str] = None
    text: Optional[str] = None
    stop_reason: Optional[str] = None

    # Tool use fields
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_use_id: Optional[str] = None

    # Tool result fields
    tool_output: Optional[str] = None
    is_error: Optional[bool] = None

    # Result fields
    duration_ms: Optional[int] = None
    total_cost_usd: Optional[float] = None
    num_turns: Optional[int] = None
    result_text: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


@dataclass
class ExecutionSummary:
    """Summary of a Claude execution from stream events."""
    session_id: Optional[str] = None
    model: Optional[str] = None
    available_tools: List[str] = field(default_factory=list)
    mcp_servers: List[str] = field(default_factory=list)

    # Execution tracking
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    assistant_messages: List[str] = field(default_factory=list)
    final_output: str = ""

    # Result info
    success: bool = False
    is_error: bool = False
    error_message: Optional[str] = None
    duration_ms: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    usage: Optional[Dict[str, Any]] = None
    stop_reason: Optional[str] = None


class StreamParser:
    """
    Parser for Claude CLI --output-format stream-json output.

    Parses JSON lines and emits structured events.
    Supports callbacks for real-time event handling.
    """

    def __init__(
        self,
        on_event: Optional[Callable[[StreamEvent], None]] = None,
        session_id: Optional[str] = None
    ):
        """
        Initialize stream parser.

        Args:
            on_event: Callback function called for each parsed event.
            session_id: Session ID for logging context.
        """
        self.on_event = on_event
        self.session_id = session_id
        self.summary = ExecutionSummary()
        self._current_tool_use: Optional[Dict[str, Any]] = None

    def parse_line(self, line: str) -> Optional[StreamEvent]:
        """
        Parse a single JSON line from stream output.

        Args:
            line: Raw JSON line from Claude CLI.

        Returns:
            Parsed StreamEvent or None if line is empty/invalid.
        """
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning(f"[{self.session_id}] Failed to parse stream line: {e}")
            return None

        event = self._parse_event(data)

        if event:
            self._update_summary(event)
            if self.on_event:
                try:
                    self.on_event(event)
                except Exception as e:
                    logger.warning(f"[{self.session_id}] Event callback error: {e}")

        return event

    def _parse_event(self, data: Dict[str, Any]) -> Optional[StreamEvent]:
        """Parse JSON data into a StreamEvent."""
        event_type_str = data.get("type", "unknown")
        subtype = data.get("subtype")
        timestamp = datetime.now()

        # Determine event type
        if event_type_str == "system" and subtype == "init":
            return self._parse_system_init(data, timestamp)
        elif event_type_str == "assistant":
            return self._parse_assistant_message(data, timestamp)
        elif event_type_str == "content_block_start":
            return self._parse_content_block_start(data, timestamp)
        elif event_type_str == "content_block_delta":
            return self._parse_content_block_delta(data, timestamp)
        elif event_type_str == "content_block_stop":
            return self._parse_content_block_stop(data, timestamp)
        elif event_type_str == "result":
            return self._parse_result(data, timestamp)
        else:
            return StreamEvent(
                event_type=StreamEventType.UNKNOWN,
                timestamp=timestamp,
                raw_data=data
            )

    def _parse_system_init(self, data: Dict, timestamp: datetime) -> StreamEvent:
        """Parse system init event."""
        return StreamEvent(
            event_type=StreamEventType.SYSTEM_INIT,
            timestamp=timestamp,
            raw_data=data,
            session_id=data.get("session_id"),
            tools=data.get("tools", []),
            mcp_servers=data.get("mcp_servers", []),
            model=data.get("model")
        )

    def _parse_assistant_message(self, data: Dict, timestamp: datetime) -> StreamEvent:
        """Parse assistant message event (may contain tool_use or text)."""
        message = data.get("message", {})
        content = message.get("content", [])

        # Extract text and tool_use from content blocks
        text_parts = []
        tool_uses = []

        for block in content:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_uses.append({
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input", {})
                })

        text = "\n".join(text_parts) if text_parts else None

        event = StreamEvent(
            event_type=StreamEventType.ASSISTANT_MESSAGE,
            timestamp=timestamp,
            raw_data=data,
            session_id=data.get("session_id"),
            message_id=message.get("id"),
            text=text,
            stop_reason=message.get("stop_reason")
        )

        # Store tool uses for later processing
        if tool_uses:
            event.tool_name = tool_uses[0].get("name") if len(tool_uses) == 1 else None
            event.tool_input = tool_uses[0].get("input") if len(tool_uses) == 1 else None
            event.tool_use_id = tool_uses[0].get("id") if len(tool_uses) == 1 else None

            # For multiple tool uses, store in raw_data
            if len(tool_uses) > 1:
                event.raw_data["_parsed_tool_uses"] = tool_uses

        return event

    def _parse_content_block_start(self, data: Dict, timestamp: datetime) -> StreamEvent:
        """Parse content block start (for streaming)."""
        content_block = data.get("content_block", {})
        block_type = content_block.get("type")

        event = StreamEvent(
            event_type=StreamEventType.CONTENT_BLOCK_START,
            timestamp=timestamp,
            raw_data=data,
            session_id=data.get("session_id")
        )

        if block_type == "tool_use":
            event.event_type = StreamEventType.TOOL_USE
            event.tool_name = content_block.get("name")
            event.tool_use_id = content_block.get("id")
            self._current_tool_use = {
                "id": content_block.get("id"),
                "name": content_block.get("name"),
                "input": {}
            }

        return event

    def _parse_content_block_delta(self, data: Dict, timestamp: datetime) -> StreamEvent:
        """Parse content block delta (streaming text or tool input)."""
        delta = data.get("delta", {})
        delta_type = delta.get("type")

        event = StreamEvent(
            event_type=StreamEventType.CONTENT_BLOCK_DELTA,
            timestamp=timestamp,
            raw_data=data
        )

        if delta_type == "text_delta":
            event.text = delta.get("text", "")
        elif delta_type == "input_json_delta" and self._current_tool_use:
            # Note: Full input will be in content_block_stop or final message
            pass

        return event

    def _parse_content_block_stop(self, data: Dict, timestamp: datetime) -> StreamEvent:
        """Parse content block stop."""
        event = StreamEvent(
            event_type=StreamEventType.CONTENT_BLOCK_STOP,
            timestamp=timestamp,
            raw_data=data
        )

        if self._current_tool_use:
            event.event_type = StreamEventType.TOOL_USE
            event.tool_name = self._current_tool_use.get("name")
            event.tool_use_id = self._current_tool_use.get("id")
            self._current_tool_use = None

        return event

    def _parse_result(self, data: Dict, timestamp: datetime) -> StreamEvent:
        """Parse final result event."""
        return StreamEvent(
            event_type=StreamEventType.RESULT,
            timestamp=timestamp,
            raw_data=data,
            session_id=data.get("session_id"),
            duration_ms=data.get("duration_ms"),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            num_turns=data.get("num_turns"),
            result_text=data.get("result"),
            usage=data.get("usage"),
            is_error=data.get("is_error", False),
            stop_reason=data.get("stop_reason")
        )

    def _update_summary(self, event: StreamEvent):
        """Update execution summary from event."""
        if event.event_type == StreamEventType.SYSTEM_INIT:
            self.summary.session_id = event.session_id
            self.summary.model = event.model
            self.summary.available_tools = event.tools or []
            self.summary.mcp_servers = event.mcp_servers or []

        elif event.event_type == StreamEventType.ASSISTANT_MESSAGE:
            if event.text:
                self.summary.assistant_messages.append(event.text)

            # Track tool uses from assistant message
            if event.tool_name:
                self.summary.tool_calls.append({
                    "id": event.tool_use_id,
                    "name": event.tool_name,
                    "input": event.tool_input,
                    "timestamp": event.timestamp.isoformat()
                })

            # Handle multiple tool uses
            parsed_tools = event.raw_data.get("_parsed_tool_uses", [])
            for tool in parsed_tools[1:]:  # Skip first, already added above
                self.summary.tool_calls.append({
                    "id": tool.get("id"),
                    "name": tool.get("name"),
                    "input": tool.get("input"),
                    "timestamp": event.timestamp.isoformat()
                })

        elif event.event_type == StreamEventType.TOOL_USE:
            if event.tool_name:
                self.summary.tool_calls.append({
                    "id": event.tool_use_id,
                    "name": event.tool_name,
                    "input": event.tool_input,
                    "timestamp": event.timestamp.isoformat()
                })

        elif event.event_type == StreamEventType.RESULT:
            self.summary.success = not event.is_error
            self.summary.is_error = event.is_error or False
            self.summary.duration_ms = event.duration_ms or 0
            self.summary.total_cost_usd = event.total_cost_usd or 0.0
            self.summary.num_turns = event.num_turns or 0
            self.summary.final_output = event.result_text or ""
            self.summary.usage = event.usage
            self.summary.stop_reason = event.stop_reason

            if event.is_error and event.result_text:
                self.summary.error_message = event.result_text

    def get_summary(self) -> ExecutionSummary:
        """Get the current execution summary."""
        return self.summary

    def reset(self):
        """Reset parser state for a new execution."""
        self.summary = ExecutionSummary()
        self._current_tool_use = None
