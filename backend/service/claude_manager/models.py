"""
Data models for Geny Agent

Data model definitions for Claude Code session management.
"""
from enum import Enum
from typing import Optional, Dict, Any, List, Union, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class SessionStatus(str, Enum):
    """Claude session status."""
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class SessionRole(str, Enum):
    """Session role type for hierarchical management."""
    MANAGER = "manager"  # Manager session - can delegate to workers
    WORKER = "worker"    # Worker session - managed by a manager


class ManagerEventType(str, Enum):
    """Event types for manager activity logging."""
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    TASK_DELEGATED = "task_delegated"
    WORKER_STARTED = "worker_started"
    WORKER_PROGRESS = "worker_progress"
    WORKER_COMPLETED = "worker_completed"
    WORKER_ERROR = "worker_error"
    USER_MESSAGE = "user_message"
    MANAGER_RESPONSE = "manager_response"
    STATUS_CHECK = "status_check"


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
        default=100,
        description="Maximum conversation turns per invocation"
    )
    timeout: Optional[float] = Field(
        default=1800.0,
        description="Default execution timeout per iteration (seconds)"
    )

    # Graph execution settings
    max_iterations: Optional[int] = Field(
        default=100,
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

    # Role settings for hierarchical management
    role: Optional[SessionRole] = Field(
        default=SessionRole.WORKER,
        description="Session role: 'manager' or 'worker'"
    )
    manager_id: Optional[str] = Field(
        default=None,
        description="Manager session ID (required for worker role)"
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

    # Role settings for hierarchical management
    role: Optional[SessionRole] = Field(
        default=SessionRole.WORKER,
        description="Session role: 'manager' or 'worker'"
    )
    manager_id: Optional[str] = Field(
        default=None,
        description="Manager session ID (for worker role)"
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
        description="Execution timeout (seconds) - None uses session default (1800s)"
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
    # Auto-continue fields for self-manager mode
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


# =============================================================================
# Manager/Worker Hierarchical Management Models
# =============================================================================

class ManagerEvent(BaseModel):
    """
    Event log entry for manager activities.

    Used to track delegations, worker progress, and plan changes.
    """
    event_id: str = Field(description="Unique event identifier")
    event_type: ManagerEventType = Field(description="Type of event")
    timestamp: datetime = Field(description="When the event occurred")
    manager_id: str = Field(description="Manager session ID")
    worker_id: Optional[str] = Field(default=None, description="Worker session ID (if applicable)")
    message: str = Field(description="Human-readable event description")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Additional event data")


class DelegateTaskRequest(BaseModel):
    """
    Request to delegate a task from manager to worker.
    """
    worker_id: str = Field(description="Worker session ID to delegate to")
    prompt: str = Field(description="Task prompt to send to worker")
    timeout: Optional[float] = Field(
        default=None,
        description="Execution timeout (uses session default if not specified)"
    )
    skip_permissions: Optional[bool] = Field(
        default=True,
        description="Skip permission prompts"
    )
    context: Optional[str] = Field(
        default=None,
        description="Additional context from manager's plan"
    )


class DelegateTaskResponse(BaseModel):
    """
    Response from delegating a task to worker.
    """
    success: bool
    manager_id: str
    worker_id: str
    delegation_id: str = Field(description="Unique ID for this delegation")
    status: str = Field(description="Delegation status: 'started', 'completed', 'error'")
    output: Optional[str] = Field(default=None, description="Worker output (if completed synchronously)")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class WorkerStatus(BaseModel):
    """
    Status information for a worker session under a manager.
    """
    worker_id: str
    worker_name: Optional[str] = None
    status: SessionStatus
    is_busy: bool = Field(default=False, description="Whether worker is currently executing")
    current_task: Optional[str] = Field(default=None, description="Current task description")
    last_output: Optional[str] = Field(default=None, description="Last execution output")
    last_activity: Optional[datetime] = Field(default=None, description="Last activity timestamp")


class ManagerDashboard(BaseModel):
    """
    Dashboard data for a manager session.

    Shows workers, events, and overall status.
    """
    manager_id: str
    manager_name: Optional[str] = None
    workers: List[WorkerStatus] = Field(default_factory=list)
    recent_events: List[ManagerEvent] = Field(default_factory=list)
    active_delegations: int = Field(default=0)
    completed_delegations: int = Field(default=0)
    plan_summary: Optional[str] = Field(default=None, description="Current plan/todo summary")
