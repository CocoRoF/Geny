"""
ToolExecutor — proxy execution engine for MCP and built-in tools.

Provides server-side tool execution so agents in tool_search_mode
can discover tools and then execute them through the tool_execute proxy
without needing direct MCP server access.
"""

from service.tool_executor.executor import (
    ToolExecutor,
    get_tool_executor,
    reset_tool_executor,
)

__all__ = [
    "ToolExecutor",
    "get_tool_executor",
    "reset_tool_executor",
]
