"""
Session domain package.

Session metadata models + persistent session store. Moved here from
``service/claude_manager/`` in cycle 20260424_2 PR-5 after the Claude
CLI subprocess layer was removed.

Modules:
    - models: Session / MCP / storage data models (Pydantic)
    - store: SessionStore persistence (Postgres + JSON fallback)
"""
from service.sessions.models import (
    SessionStatus,
    SessionRole,
    SessionInfo,
    CreateSessionRequest,
    ExecuteRequest,
    ExecuteResponse,
    StorageFile,
    StorageListResponse,
    StorageFileContent,
    ToolCallInfo,
    # MCP config models
    MCPConfig,
    MCPServerStdio,
    MCPServerHTTP,
    MCPServerSSE,
)
from service.sessions.store import SessionStore, get_session_store

__all__ = [
    # Session models
    'SessionStatus',
    'SessionRole',
    'SessionInfo',
    'CreateSessionRequest',
    'ExecuteRequest',
    'ExecuteResponse',
    'ToolCallInfo',
    # Storage models
    'StorageFile',
    'StorageListResponse',
    'StorageFileContent',
    # MCP models
    'MCPConfig',
    'MCPServerStdio',
    'MCPServerHTTP',
    'MCPServerSSE',
    # Store
    'SessionStore',
    'get_session_store',
]
