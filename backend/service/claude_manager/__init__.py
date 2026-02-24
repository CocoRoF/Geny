"""
Claude Manager Package

Core modules for Claude Code session management

Modules:
    - models: Data models for sessions and MCP configuration
    - session_manager: Session lifecycle management
    - process_manager: Claude process execution (ClaudeProcess class)
    - constants: Configuration constants and environment variable keys
    - platform_utils: Cross-platform utilities
    - cli_discovery: Claude CLI discovery utilities
    - storage_utils: Storage and gitignore filtering utilities
    - stream_parser: Claude CLI stream-json output parser
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
from service.claude_manager.session_manager import SessionManager, get_session_manager
from service.claude_manager.process_manager import ClaudeProcess
from service.claude_manager.constants import CLAUDE_DEFAULT_TIMEOUT, CLAUDE_ENV_KEYS
from service.claude_manager.platform_utils import (
    IS_WINDOWS,
    DEFAULT_STORAGE_ROOT,
)
from service.claude_manager.cli_discovery import (
    ClaudeNodeConfig,
    find_claude_node_config,
)
from service.claude_manager.storage_utils import (
    DEFAULT_IGNORE_PATTERNS,
    list_storage_files,
    read_storage_file,
)
from service.claude_manager.stream_parser import (
    StreamParser,
    StreamEvent,
    StreamEventType,
    ExecutionSummary,
)

__all__ = [
    # Models
    'SessionStatus',
    'SessionInfo',
    'CreateSessionRequest',
    'ExecuteRequest',
    'ExecuteResponse',
    'StorageFile',
    'StorageListResponse',
    'StorageFileContent',
    'ToolCallInfo',
    # MCP Models
    'MCPConfig',
    'MCPServerStdio',
    'MCPServerHTTP',
    'MCPServerSSE',
    # Managers
    'SessionManager',
    'get_session_manager',
    'ClaudeProcess',
    # Constants
    'CLAUDE_DEFAULT_TIMEOUT',
    'CLAUDE_ENV_KEYS',
    # Platform utilities
    'IS_WINDOWS',
    'DEFAULT_STORAGE_ROOT',
    # CLI Discovery
    'ClaudeNodeConfig',
    'find_claude_node_config',
    # Storage utilities
    'DEFAULT_IGNORE_PATTERNS',
    'list_storage_files',
    'read_storage_file',
    # Stream Parser
    'StreamParser',
    'StreamEvent',
    'StreamEventType',
    'ExecutionSummary',
]
