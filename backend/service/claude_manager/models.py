"""
Data models for Geny Agent

Data model definitions for Claude Code session management.
"""
from enum import Enum
from typing import Optional, Dict, Any, List, Union, Literal
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# Legacy session_type values seen in persisted session records. The current
# canonical value is "sub" (Sub-Worker); older runs wrote "bound" (PR 18+)
# or "cli" (pre-PR 18). Normalize on input so the rest of the codebase only
# has to reason about the current enum.
_LEGACY_SESSION_TYPES = {"bound": "sub", "cli": "sub"}


def _normalize_session_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return _LEGACY_SESSION_TYPES.get(value, value)


class SessionStatus(str, Enum):
    """Claude session status."""
    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPED = "stopped"
    ERROR = "error"


class SessionRole(str, Enum):
    """Session role type defining the agent's purpose and behavior."""
    WORKER = "worker"          # Default developer/worker — executes tasks
    DEVELOPER = "developer"    # Alias for worker — implementation focus
    RESEARCHER = "researcher"  # Research & Ideation — discovers info, generates ideas
    PLANNER = "planner"        # Plan Architect — creates detailed plans and designs
    VTUBER = "vtuber"          # VTuber persona — conversational front-end agent


# =============================================================================
# MCP (Model Context Protocol) Configuration Models
# =============================================================================

class MCPServerStdio(BaseModel):
    """
    STDIO transport MCP server configuration.

    For MCP servers running as local processes (e.g., npx, python scripts).
    """
    type: Literal["stdio"] = "stdio"
    command: str = Field(..., description="Command to execute (e.g., 'npx', 'python')")
    args: List[str] = Field(default_factory=list, description="Command arguments")
    env: Optional[Dict[str, str]] = Field(default=None, description="Environment variables")


class MCPServerHTTP(BaseModel):
    """
    HTTP transport MCP server configuration.

    For remote HTTP-based MCP servers (e.g., Notion, GitHub).
    """
    type: Literal["http"] = "http"
    url: str = Field(..., description="MCP server URL (e.g., 'https://mcp.notion.com/mcp')")
    headers: Optional[Dict[str, str]] = Field(default=None, description="Authentication headers")


class MCPServerSSE(BaseModel):
    """
    SSE transport MCP server configuration (deprecated, use HTTP instead).
    """
    type: Literal["sse"] = "sse"
    url: str = Field(..., description="SSE server URL")
    headers: Optional[Dict[str, str]] = Field(default=None, description="Authentication headers")


# MCP server configuration Union type
MCPServerConfig = Union[MCPServerStdio, MCPServerHTTP, MCPServerSSE]


class MCPConfig(BaseModel):
    """
    MCP server configuration collection.

    Manages multiple MCP servers by name.
    This configuration is generated as the session's .mcp.json file.

    Example:
        {
            "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"},
            "filesystem": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]}
        }
    """
    servers: Dict[str, MCPServerConfig] = Field(
        default_factory=dict,
        description="MCP server configurations (name -> config)"
    )

    def to_mcp_json(self) -> Dict[str, Any]:
        """
        Convert to .mcp.json file format.

        Returns:
            Dictionary in .mcp.json format recognized by Claude Code.
        """
        mcp_servers = {}
        for name, config in self.servers.items():
            if isinstance(config, MCPServerStdio):
                server_config = {
                    "command": config.command,
                    "args": config.args,
                }
                if config.env:
                    server_config["env"] = config.env
            elif isinstance(config, (MCPServerHTTP, MCPServerSSE)):
                server_config = {
                    "type": config.type,
                    "url": config.url,
                }
                if config.headers:
                    server_config["headers"] = config.headers
            else:
                continue
            mcp_servers[name] = server_config

        return {"mcpServers": mcp_servers}


# =============================================================================
# Session Management Models
# =============================================================================

class CreateSessionRequest(BaseModel):
    """
    Session creation request.

    Creates a new session to run Claude Code.
    Each session has its own independent working directory (storage).
    """
    session_name: Optional[str] = Field(
        default=None,
        description="Session name (for identification)"
    )
    working_dir: Optional[str] = Field(
        default=None,
        description="Working directory (if None, uses {temp_dir}/{session_id} as storage/work directory)"
    )
    env_vars: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional environment variables"
    )
    model: Optional[str] = Field(
        default=None,
        description="Claude model to use (e.g., claude-sonnet-4-20250514)"
    )
    max_turns: Optional[int] = Field(
        default=50,
        description="Maximum conversation turns per invocation"
    )
    timeout: Optional[float] = Field(
        default=1800.0,
        description="Default execution timeout per iteration (seconds)"
    )

    # Graph execution settings
    max_iterations: Optional[int] = Field(
        default=50,
        description="Maximum graph iterations (prevents infinite loops)"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="Additional system prompt (appended to default prompt)"
    )
    allowed_tools: Optional[List[str]] = Field(
        default=None,
        description="List of allowed tools (None allows all tools)"
    )

    # Workflow / Graph settings
    workflow_id: Optional[str] = Field(
        default=None,
        description="Workflow (graph) ID to use for this session."
    )
    graph_name: Optional[str] = Field(
        default=None,
        description="Human-readable name of the graph/workflow used by this session."
    )

    # MCP server settings
    mcp_config: Optional[MCPConfig] = Field(
        default=None,
        description="MCP server configuration - MCP tools to use in session"
    )

    # Role settings
    role: Optional[SessionRole] = Field(
        default=SessionRole.WORKER,
        description="Session role: 'worker', 'developer', 'researcher', or 'planner'"
    )

    # Tool preset settings
    tool_preset_id: Optional[str] = Field(
        default=None,
        description="Tool preset ID — determines which Python tools and MCP servers are available. "
                    "If None, the default preset for the session role is used."
    )

    # Dual-agent pairing (VTuber ↔ Sub-Worker)
    linked_session_id: Optional[str] = Field(
        default=None,
        description="Linked session ID for VTuber ↔ Sub-Worker pairing"
    )
    session_type: Optional[str] = Field(
        default=None,
        description="Session type: 'vtuber' (persona layer), 'sub' (Worker bound to a VTuber), "
                    "or 'solo' / None (standalone Worker)"
    )

    @field_validator("session_type", mode="before")
    @classmethod
    def _normalize_session_type_request(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_session_type(v)

    # VTuber-specific: overrides for the Sub-Worker session
    sub_worker_system_prompt: Optional[str] = Field(
        default=None,
        description="System prompt override for the Sub-Worker (VTuber role only)"
    )
    sub_worker_model: Optional[str] = Field(
        default=None,
        description="Model override for the Sub-Worker (VTuber role only)"
    )
    sub_worker_env_id: Optional[str] = Field(
        default=None,
        description="Explicit env_id for the Sub-Worker (VTuber role only). "
                    "When None, resolve_env_id(role=WORKER) picks the default worker env."
    )

    # Cycle 20260422_6 PR3 — name separation
    character_display_name: Optional[str] = Field(
        default=None,
        description=(
            "In-character display name for VTuber sessions. When set, the "
            "VTuber persona is told 'Your character name is X.' When unset, "
            "the persona stays anonymous and (per the first-encounter "
            "overlay) will ask the user how to be addressed. This is "
            "intentionally separate from `session_name`, which is treated "
            "as an internal handle and never exposed as the persona's "
            "name. Ignored by non-VTuber roles."
        ),
    )


class SessionInfo(BaseModel):
    """
    Session information response.

    Contains current state and metadata of the session.
    """
    session_id: str
    session_name: Optional[str] = None
    status: SessionStatus
    created_at: datetime
    pid: Optional[int] = None
    error_message: Optional[str] = None

    # Claude-related information
    model: Optional[str] = None

    # Session execution settings (preserved from creation)
    max_turns: Optional[int] = Field(
        default=100,
        description="Maximum conversation turns per execution"
    )
    timeout: Optional[float] = Field(
        default=1800.0,
        description="Execution timeout per iteration (seconds)"
    )
    max_iterations: Optional[int] = Field(
        default=100,
        description="Maximum graph iterations"
    )

    # Session storage path
    storage_path: Optional[str] = Field(
        default=None,
        description="Session-specific storage path"
    )

    # Pod information for multi-pod routing
    pod_name: Optional[str] = Field(
        default=None,
        description="Pod name where session is running"
    )
    pod_ip: Optional[str] = Field(
        default=None,
        description="Pod IP where session is running"
    )

    # Role settings
    role: Optional[SessionRole] = Field(
        default=SessionRole.WORKER,
        description="Session role: 'worker', 'developer', 'researcher', or 'planner'"
    )

    # Workflow / Graph settings
    workflow_id: Optional[str] = Field(
        default=None,
        description="Workflow (graph) ID used by this session"
    )
    graph_name: Optional[str] = Field(
        default=None,
        description="Human-readable name of the graph/workflow used by this session"
    )

    # Tool preset
    tool_preset_id: Optional[str] = Field(
        default=None,
        description="Tool preset ID that determines available tools for this session"
    )

    # System prompt
    system_prompt: Optional[str] = Field(
        default=None,
        description="System prompt applied to every execution in this session"
    )

    # Cost tracking
    total_cost: Optional[float] = Field(
        default=0.0,
        description="Cumulative API usage cost (USD) across all executions"
    )

    # Dual-agent pairing (VTuber ↔ Sub-Worker)
    linked_session_id: Optional[str] = Field(
        default=None,
        description="Linked session ID for VTuber ↔ Sub-Worker pairing"
    )
    session_type: Optional[str] = Field(
        default=None,
        description="Session type: 'vtuber' (persona layer), 'sub' (Worker bound to a VTuber), "
                    "or 'solo' / None (standalone Worker)"
    )

    @field_validator("session_type", mode="before")
    @classmethod
    def _normalize_session_type_info(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_session_type(v)

    # VTuber chat room
    chat_room_id: Optional[str] = Field(
        default=None,
        description="Chat room ID auto-created for VTuber sessions"
    )

    # Environment / memory — surfaced read-only for operator visibility.
    # Populated by AgentSession.get_session_info from the values captured
    # at session creation; see CreateAgentRequest for the write path.
    env_id: Optional[str] = Field(
        default=None,
        description="EnvironmentManifest id bound at session creation, or None for legacy preset path"
    )
    memory_config: Optional[dict] = Field(
        default=None,
        description="Per-session MemoryProvider override config, or None when the process default is used"
    )

    # Tamagotchi creature state — surfaced only for sessions that have
    # a state_provider wired (classic / non-Tamagotchi sessions keep
    # this ``None``). Populated by the agent controller after calling
    # ``AgentSession.load_creature_state_snapshot()``; the base
    # ``get_session_info`` stays sync to keep its many existing
    # callers unaffected. See cycle 20260422_5 (X7).
    creature_state: Optional[dict] = Field(
        default=None,
        description=(
            "Snapshot of the session's CreatureState (mood / bond / vitals / "
            "progression) when a state_provider is attached; None for sessions "
            "without Tamagotchi integration."
        ),
    )


class ExecuteRequest(BaseModel):
    """
    Claude execution request.

    Sends a prompt to Claude and executes it in the session.
    The session's graph drives the execution flow.
    """
    prompt: str = Field(
        ...,
        description="Prompt to send to Claude"
    )
    timeout: Optional[float] = Field(
        default=None,
        description="Execution timeout (seconds) - None uses session default (21600s / 6h)"
    )
    skip_permissions: Optional[bool] = Field(
        default=True,
        description="Skip permission prompts"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="Additional system prompt for this execution"
    )
    max_turns: Optional[int] = Field(
        default=None,
        description="Maximum turns for this execution (None uses session setting)"
    )


class ToolCallInfo(BaseModel):
    """Information about a single tool call."""
    id: Optional[str] = Field(default=None, description="Unique tool call ID")
    name: str = Field(description="Tool name")
    input: Optional[Dict[str, Any]] = Field(default=None, description="Tool input parameters")
    timestamp: Optional[str] = Field(default=None, description="When the tool was called")


class ExecuteResponse(BaseModel):
    """Claude execution response."""
    success: bool
    session_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    cost_usd: Optional[float] = Field(
        default=None,
        description="API usage cost (USD)"
    )
    duration_ms: Optional[int] = Field(
        default=None,
        description="Execution time (milliseconds)"
    )
    # Tool usage tracking
    tool_calls: Optional[List[ToolCallInfo]] = Field(
        default=None,
        description="List of tools called during execution"
    )
    num_turns: Optional[int] = Field(
        default=None,
        description="Number of conversation turns"
    )
    model: Optional[str] = Field(
        default=None,
        description="Model used for execution"
    )
    stop_reason: Optional[str] = Field(
        default=None,
        description="Reason for stopping (end_turn, max_tokens, tool_use, etc.)"
    )
    # Auto-continue fields
    should_continue: bool = Field(
        default=False,
        description="Whether the task should continue (detected from [CONTINUE: ...] pattern)"
    )
    continue_hint: Optional[str] = Field(
        default=None,
        description="Hint about next step (extracted from [CONTINUE: ...] pattern)"
    )
    # Execution tracking fields
    is_task_complete: bool = Field(
        default=False,
        description="Whether the task is complete (detected from [TASK_COMPLETE] pattern)"
    )
    iteration_count: Optional[int] = Field(
        default=None,
        description="Current iteration count"
    )
    total_iterations: Optional[int] = Field(
        default=None,
        description="Total iterations completed"
    )
    original_request: Optional[str] = Field(
        default=None,
        description="Original user request (for tracking)"
    )


class StorageFile(BaseModel):
    """Storage file information."""
    name: str
    path: str
    is_dir: bool
    size: Optional[int] = None
    modified_at: Optional[datetime] = None


class StorageListResponse(BaseModel):
    """Storage file list response."""
    session_id: str
    storage_path: str
    files: List[StorageFile]


class StorageFileContent(BaseModel):
    """Storage file content response."""
    session_id: str
    file_path: str
    content: str
    size: int
    encoding: str = "utf-8"
