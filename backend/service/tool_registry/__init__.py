"""
Tool Registry — graph-based tool indexing and retrieval for Geny agents.

Wraps graph-tool-call's ToolGraph to register all MCP and built-in tools
at startup, then provides search/browse/schema APIs that agents use
instead of receiving the full tool list.

Public API:
    get_tool_registry() → ToolRegistry singleton
    ToolRegistry.register_mcp_tools(server_name, tools)
    ToolRegistry.register_builtin_tools(tools)
    ToolRegistry.search(query, top_k) → list[ToolEntry]
    ToolRegistry.get_tool_schema(tool_name) → dict | None
    ToolRegistry.browse_categories() → dict
    ToolRegistry.list_all_tools() → list[str]
"""

from service.tool_registry.registry import ToolRegistry, ToolEntry, get_tool_registry

__all__ = [
    "ToolRegistry",
    "ToolEntry",
    "get_tool_registry",
]
