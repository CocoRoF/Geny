"""
Tool Search & Execute Tools — agent-facing tools for dynamic tool discovery and execution.

These tools are the core of the "deferred tool" pattern inspired by
graph-tool-call. Instead of receiving all tool definitions in their
context window, agents receive only these search/execute tools and use
them to discover, inspect, and execute the specific tools they need.

Workflow:
    1. Agent receives a task
    2. Agent calls ``tool_search`` to find relevant tools
    3. Agent calls ``tool_schema`` to get the full parameter schema
    4. Agent calls ``tool_execute`` to run the discovered tool
    5. Agent processes the result and continues

Per-session filtering:
    When a session has ``allowed_tools`` configured, the ContextVar in
    ``service.tool_executor.context`` restricts which tools are visible
    and executable. This is set before each graph invocation.

This file is auto-loaded by MCPLoader (matches *_tools.py pattern).
"""

import asyncio
import json
from typing import Optional, List
from tools.base import BaseTool


def _get_allowed_tools() -> Optional[List[str]]:
    """Get per-session allowed tools from context, if set."""
    try:
        from service.tool_executor.context import get_session_allowed_tools
        return get_session_allowed_tools()
    except ImportError:
        return None


def _is_tool_allowed(tool_name: str) -> bool:
    """Check if a tool passes the per-session filter."""
    allowed = _get_allowed_tools()
    if allowed is None:
        return True  # No restriction
    return tool_name in allowed


def _filter_results(entries: list) -> list:
    """Filter a list of ToolEntry objects by per-session allowed_tools."""
    allowed = _get_allowed_tools()
    if allowed is None:
        return entries
    allowed_set = set(allowed)
    return [e for e in entries if e.name in allowed_set]


class ToolSearchTool(BaseTool):
    """Search for available tools by natural language query.

    Given a description of what you need to do, this tool searches the
    tool registry and returns the most relevant tools with their names
    and descriptions. Use this as the first step to discover which tools
    are available for a task.

    After finding a tool, use ``tool_schema`` to get its full parameter
    schema, then use ``tool_execute`` to run it.
    """

    name = "tool_search"
    description = (
        "Search for available tools by describing what you need. "
        "Returns matching tool names and descriptions ranked by relevance. "
        "Use this to discover which tools can help with your current task."
    )

    def run(self, query: str, top_k: int = 5) -> str:
        """Search for tools matching a natural language query.

        Args:
            query: What you need to do (e.g. "read a file", "search git history")
            top_k: Maximum number of results to return (default: 5)
        """
        from service.tool_registry import get_tool_registry
        registry = get_tool_registry()

        results = registry.search(query, top_k=top_k)
        results = _filter_results(results)

        if not results:
            # Show total available (filtered)
            allowed = _get_allowed_tools()
            total = len(allowed) if allowed else registry.tool_count
            return json.dumps({
                "matches": [],
                "message": f"No tools found matching '{query}'. Try broader search terms.",
                "total_available": total,
            }, indent=2)

        matches = []
        for entry in results:
            match = {
                "name": entry.name,
                "description": entry.description,
                "server": entry.server_name,
            }
            if entry.tags:
                match["tags"] = entry.tags
            matches.append(match)

        return json.dumps({
            "matches": matches,
            "result_count": len(matches),
            "hint": "Use tool_schema(tool_name) to get full parameter details, then tool_execute(tool_name, parameters) to run it.",
        }, indent=2)


class ToolSchemaTool(BaseTool):
    """Get the full schema for a specific tool.

    After discovering a tool via ``tool_search``, use this to retrieve its
    complete parameter schema including required fields, types, and
    descriptions. This gives you everything needed to call the tool via
    ``tool_execute``.
    """

    name = "tool_schema"
    description = (
        "Get the full parameter schema for a specific tool by name. "
        "Returns the complete definition needed to call the tool correctly, "
        "including all parameters, their types, and which are required."
    )

    def run(self, tool_name: str) -> str:
        """Get the full schema for a tool.

        Args:
            tool_name: Exact name of the tool (from tool_search results)
        """
        # Check per-session filter
        if not _is_tool_allowed(tool_name):
            return json.dumps({
                "error": f"Tool '{tool_name}' is not available in this session.",
                "hint": "Use tool_search(query) to find available tools.",
            }, indent=2)

        from service.tool_registry import get_tool_registry
        registry = get_tool_registry()

        schema = registry.get_tool_schema(tool_name)

        if schema is None:
            # Try fuzzy match (within allowed tools)
            all_tools = registry.list_all_tools()
            allowed = _get_allowed_tools()
            if allowed is not None:
                all_tools = [t for t in all_tools if t in set(allowed)]

            suggestions = [
                t for t in all_tools
                if tool_name.lower() in t.lower() or t.lower() in tool_name.lower()
            ]

            result = {
                "error": f"Tool '{tool_name}' not found.",
            }
            if suggestions:
                result["did_you_mean"] = suggestions[:5]
            else:
                result["hint"] = "Use tool_search(query) to find available tools."

            return json.dumps(result, indent=2)

        return json.dumps(schema, indent=2)


class BrowseToolCategoriesTool(BaseTool):
    """Browse all available tools organized by category/server.

    Use this to get an overview of what tool categories are available
    without searching for a specific capability. Helpful when you want
    to understand the full scope of available tools.
    """

    name = "tool_browse"
    description = (
        "Browse all available tools organized by server/category. "
        "Returns a tree of tool groups with tool counts. "
        "Use this to explore what types of tools are available."
    )

    def run(self) -> str:
        """Browse tool categories."""
        from service.tool_registry import get_tool_registry
        registry = get_tool_registry()

        categories = registry.browse_categories()

        # Apply per-session filtering
        allowed = _get_allowed_tools()
        if allowed is not None and "servers" in categories:
            allowed_set = set(allowed)
            filtered_servers = {}
            total = 0
            for server_name, server_info in categories["servers"].items():
                if isinstance(server_info, dict) and "tools" in server_info:
                    filtered_tools = [
                        t for t in server_info["tools"]
                        if t in allowed_set
                    ]
                    if filtered_tools:
                        filtered_servers[server_name] = {
                            "tools": filtered_tools,
                            "tool_count": len(filtered_tools),
                        }
                        total += len(filtered_tools)
            categories = {
                "servers": filtered_servers,
                "total_tools": total,
            }

        return json.dumps(categories, indent=2)


class ToolWorkflowTool(BaseTool):
    """Get the recommended workflow chain for a tool.

    Some tools are typically called in sequence (e.g. list_orders ->
    get_order -> cancel_order -> process_refund). This tool reveals
    the typical execution flow for a given tool.
    """

    name = "tool_workflow"
    description = (
        "Get the recommended execution sequence for a tool. "
        "Shows which tools typically precede or follow the given tool. "
        "Useful for understanding multi-step workflows."
    )

    def run(self, tool_name: str) -> str:
        """Get the workflow chain for a tool.

        Args:
            tool_name: Name of the tool to get the workflow for
        """
        if not _is_tool_allowed(tool_name):
            return json.dumps({
                "error": f"Tool '{tool_name}' is not available in this session.",
            }, indent=2)

        from service.tool_registry import get_tool_registry
        registry = get_tool_registry()

        workflow = registry.get_workflow(tool_name)

        if not workflow:
            return json.dumps({
                "tool": tool_name,
                "workflow": [],
                "message": "No workflow chain detected for this tool.",
            }, indent=2)

        # Filter workflow steps by allowed tools
        allowed = _get_allowed_tools()
        if allowed is not None:
            allowed_set = set(allowed)
            workflow = [t for t in workflow if t in allowed_set]

        return json.dumps({
            "tool": tool_name,
            "workflow": workflow,
            "step_count": len(workflow),
        }, indent=2)


class ToolExecuteTool(BaseTool):
    """Execute a discovered tool by name with given parameters.

    This is the execution proxy — after discovering a tool via ``tool_search``
    and getting its schema via ``tool_schema``, use this tool to actually
    run it. The tool is executed server-side through the ToolExecutor engine.

    Example workflow:
        1. tool_search("read a file") → finds "read_file"
        2. tool_schema("read_file") → gets {path: string (required)}
        3. tool_execute("read_file", {"path": "src/main.py"}) → file contents
    """

    name = "tool_execute"
    description = (
        "Execute a tool by name with the given parameters. "
        "Use this after discovering a tool with tool_search and getting "
        "its schema with tool_schema. The tool runs server-side and "
        "returns its output directly."
    )

    def run(self, tool_name: str, parameters: Optional[dict] = None) -> str:
        """Execute a tool.

        Args:
            tool_name: Name of the tool to execute (from tool_search results)
            parameters: Tool input parameters as a dictionary (from tool_schema)
        """
        # Check per-session filter
        if not _is_tool_allowed(tool_name):
            return json.dumps({
                "error": f"Tool '{tool_name}' is not available in this session.",
                "hint": "Use tool_search(query) to find available tools.",
            }, indent=2)

        # Prevent recursive execution of discovery tools
        discovery_tools = {"tool_search", "tool_schema", "tool_browse", "tool_workflow", "tool_execute"}
        if tool_name in discovery_tools:
            return json.dumps({
                "error": f"Cannot execute discovery tool '{tool_name}' through tool_execute. Call it directly.",
            }, indent=2)

        from service.tool_executor import get_tool_executor
        executor = get_tool_executor()

        if not executor.is_tool_executable(tool_name):
            return json.dumps({
                "error": f"Tool '{tool_name}' is not available for execution.",
                "hint": "Use tool_search(query) to find available tools.",
            }, indent=2)

        # Execute (async → sync bridge for BaseTool.run())
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                # We're inside an async context (LangGraph) — use thread pool
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        executor.execute(tool_name, parameters or {}),
                    ).result(timeout=120)
            else:
                result = asyncio.run(
                    executor.execute(tool_name, parameters or {})
                )
        except Exception as e:
            return json.dumps({
                "error": f"Execution failed: {e}",
                "isError": True,
            }, indent=2)

        if result.get("isError"):
            return json.dumps({
                "error": result.get("error", "Unknown error"),
                "isError": True,
            }, indent=2)

        return result.get("result", "")

    async def arun(self, tool_name: str, parameters: Optional[dict] = None) -> str:
        """Async execution of a tool.

        Args:
            tool_name: Name of the tool to execute
            parameters: Tool input parameters
        """
        # Check per-session filter
        if not _is_tool_allowed(tool_name):
            return json.dumps({
                "error": f"Tool '{tool_name}' is not available in this session.",
                "hint": "Use tool_search(query) to find available tools.",
            }, indent=2)

        # Prevent recursive execution of discovery tools
        discovery_tools = {"tool_search", "tool_schema", "tool_browse", "tool_workflow", "tool_execute"}
        if tool_name in discovery_tools:
            return json.dumps({
                "error": f"Cannot execute discovery tool '{tool_name}' through tool_execute. Call it directly.",
            }, indent=2)

        from service.tool_executor import get_tool_executor
        executor = get_tool_executor()

        if not executor.is_tool_executable(tool_name):
            return json.dumps({
                "error": f"Tool '{tool_name}' is not available for execution.",
                "hint": "Use tool_search(query) to find available tools.",
            }, indent=2)

        result = await executor.execute(tool_name, parameters or {})

        if result.get("isError"):
            return json.dumps({
                "error": result.get("error", "Unknown error"),
                "isError": True,
            }, indent=2)

        return result.get("result", "")


# =============================================================================
# Export list — MCPLoader auto-collects these
# =============================================================================

TOOLS = [
    ToolSearchTool(),
    ToolSchemaTool(),
    BrowseToolCategoriesTool(),
    ToolWorkflowTool(),
    ToolExecuteTool(),
]
