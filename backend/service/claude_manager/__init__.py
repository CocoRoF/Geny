"""
Claude Manager Package

NOTE: This package is being dissolved (cycle 20260424_2). After PR-4
the Claude-CLI subprocess layer (ClaudeProcess / SessionManager /
StreamParser / cli_discovery / constants) has been deleted. Only the
domain models, session store, generic platform utilities, and file-
storage helpers remain — PR-5 will relocate them to ``service/sessions/``
and ``service/utils/`` and remove this package entirely.

Modules still present:
    - models: Session / MCP / storage data models
    - session_store: Session metadata persistence (Postgres + JSON)
    - platform_utils: DEFAULT_STORAGE_ROOT + IS_{WINDOWS,MACOS,LINUX}
    - storage_utils: list_storage_files / read_storage_file / gitignore
"""
from service.claude_manager.models import (
    SessionStatus,
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
from service.claude_manager.platform_utils import (
    IS_WINDOWS,
    IS_MACOS,
    IS_LINUX,
    DEFAULT_STORAGE_ROOT,
)
from service.claude_manager.storage_utils import (
    DEFAULT_IGNORE_PATTERNS,
    list_storage_files,
    read_storage_file,
)

__all__ = [
    # Session / MCP / storage models
    'SessionStatus',
    'SessionInfo',
    'CreateSessionRequest',
    'ExecuteRequest',
    'ExecuteResponse',
    'StorageFile',
    'StorageListResponse',
    'StorageFileContent',
    'ToolCallInfo',
    'MCPConfig',
    'MCPServerStdio',
    'MCPServerHTTP',
    'MCPServerSSE',
    # Platform
    'IS_WINDOWS',
    'IS_MACOS',
    'IS_LINUX',
    'DEFAULT_STORAGE_ROOT',
    # Storage utilities
    'DEFAULT_IGNORE_PATTERNS',
    'list_storage_files',
    'read_storage_file',
]
