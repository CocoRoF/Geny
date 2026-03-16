"""
ToolExecutor — proxy execution engine for all tools.

Central service that can execute any registered tool on behalf of an agent.
Handles two categories:

1. **Built-in tools** (from tools/ folder):
   Called directly via their Python ``run()``/``arun()`` methods.

2. **MCP server tools** (from mcp/ folder configs):
   Called via JSON-RPC over stdio using MCPStdioClient.

The executor is initialized at startup alongside the ToolRegistry.
Agents in tool_search_mode call ``tool_execute(tool_name, parameters)``
which routes through this executor.

Per-session filtering is handled externally (via ContextVar in
tool_search_tools.py) — the executor itself executes any tool it knows.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from logging import getLogger
from typing import Any, Dict, List, Optional

from service.tool_executor.mcp_client import MCPStdioClient

logger = getLogger(__name__)


class ToolExecutor:
    """Proxy execution engine for MCP and built-in tools.

    Provides:
        - register_builtin_tools(): Register Python tool objects for direct execution.
        - register_mcp_server(): Register an MCP server config for lazy connection.
        - execute(): Execute a tool by name with given parameters.
        - list_executable_tools(): List all tools that can be executed.
        - shutdown(): Close all MCP client connections.
    """

    def __init__(self) -> None:
        # Built-in tools: name → tool object (has .run()/.arun())
        self._builtin_tools: Dict[str, Any] = {}

        # MCP clients: server_name → MCPStdioClient (lazy-connected)
        self._mcp_clients: Dict[str, MCPStdioClient] = {}

        # Tool → server mapping: tool_name → server_name
        self._tool_server_map: Dict[str, str] = {}

        # MCP server tool schemas (populated on first connect)
        self._mcp_tool_schemas: Dict[str, Dict[str, Any]] = {}

        self._initialized = False

    # ====================================================================
    # Registration
    # ====================================================================

    def register_builtin_tools(self, tools: List[Any]) -> int:
        """Register built-in Python tools for direct execution.

        Args:
            tools: List of tool objects from tools/ folder (BaseTool, ToolWrapper, etc.)

        Returns:
            Number of tools registered.
        """
        count = 0
        for tool_obj in tools:
            name = getattr(tool_obj, "name", None)
            if not name and hasattr(tool_obj, "__name__"):
                name = tool_obj.__name__
            if not name:
                continue

            self._builtin_tools[name] = tool_obj
            self._tool_server_map[name] = "_builtin_tools"
            count += 1

        logger.info(f"ToolExecutor: registered {count} built-in tools")
        return count

    def register_mcp_server(
        self,
        server_name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Register an MCP server for lazy connection.

        The actual connection is established on first tool call
        to minimize startup overhead.

        Args:
            server_name: MCP server name (e.g. "filesystem", "github").
            command: Server command (e.g. "npx", "python").
            args: Command arguments.
            env: Environment variables.
        """
        client = MCPStdioClient(
            server_name=server_name,
            command=command,
            args=args,
            env=env,
        )
        self._mcp_clients[server_name] = client
        logger.info(
            f"ToolExecutor: registered MCP server '{server_name}' "
            f"(lazy connect)"
        )

    def register_mcp_server_tools(
        self,
        server_name: str,
        tools: List[Dict[str, Any]],
    ) -> int:
        """Pre-register MCP tool names from ToolRegistry data.

        Called during startup when we know the tool names from the registry
        but haven't connected to the MCP server yet. This lets us map
        tool names to servers without establishing connections.

        Args:
            server_name: MCP server name.
            tools: List of tool dicts with 'name' key.

        Returns:
            Number of tools mapped.
        """
        count = 0
        for tool_def in tools:
            name = tool_def.get("name", "")
            if name:
                self._tool_server_map[name] = server_name
                self._mcp_tool_schemas[name] = tool_def
                count += 1
        return count

    def finalize(self) -> None:
        """Mark registration complete."""
        self._initialized = True
        total = len(self._tool_server_map)
        builtin_count = len(self._builtin_tools)
        mcp_count = total - builtin_count
        logger.info(
            f"ToolExecutor: finalized — {total} tools "
            f"({builtin_count} built-in, {mcp_count} MCP across "
            f"{len(self._mcp_clients)} servers)"
        )

    # ====================================================================
    # Execution
    # ====================================================================

    async def execute(
        self,
        tool_name: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a tool by name.

        Routes to built-in Python execution or MCP server call
        based on the tool's registration source.

        Args:
            tool_name: Name of the tool to execute.
            parameters: Tool input parameters.

        Returns:
            Dict with 'result' on success or 'error' on failure.
        """
        params = parameters or {}

        # Check if tool is registered
        server = self._tool_server_map.get(tool_name)
        if not server:
            return {
                "error": f"Tool '{tool_name}' is not registered in the executor.",
                "isError": True,
                "hint": "Use tool_search to find available tools first.",
            }

        # Route: built-in tool → direct Python call
        if server == "_builtin_tools" and tool_name in self._builtin_tools:
            return await self._execute_builtin(tool_name, params)

        # Route: MCP server tool → JSON-RPC call
        if server in self._mcp_clients:
            return await self._execute_mcp(server, tool_name, params)

        return {
            "error": (
                f"Tool '{tool_name}' is mapped to server '{server}' "
                f"but no executor is available for it."
            ),
            "isError": True,
        }

    async def _execute_builtin(
        self,
        tool_name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a built-in Python tool."""
        tool_obj = self._builtin_tools[tool_name]

        try:
            # Prefer arun() for async execution
            if hasattr(tool_obj, "arun"):
                func = tool_obj.arun
                if inspect.iscoroutinefunction(func):
                    result = await func(**params)
                else:
                    result = func(**params)
            elif hasattr(tool_obj, "run"):
                func = tool_obj.run
                if inspect.iscoroutinefunction(func):
                    result = await func(**params)
                else:
                    # Run sync function in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: func(**params))
            elif callable(tool_obj):
                if inspect.iscoroutinefunction(tool_obj):
                    result = await tool_obj(**params)
                else:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, lambda: tool_obj(**params)
                    )
            else:
                return {
                    "error": f"Tool '{tool_name}' is not callable.",
                    "isError": True,
                }

            # Normalize result to string
            if isinstance(result, str):
                return {"result": result, "isError": False}
            elif isinstance(result, dict):
                return {"result": json.dumps(result, indent=2), "isError": False}
            else:
                return {"result": str(result), "isError": False}

        except TypeError as e:
            return {
                "error": (
                    f"Parameter error calling '{tool_name}': {e}. "
                    f"Use tool_schema('{tool_name}') to check required parameters."
                ),
                "isError": True,
            }
        except Exception as e:
            logger.warning(f"ToolExecutor: builtin '{tool_name}' failed: {e}")
            return {
                "error": f"Tool '{tool_name}' execution failed: {e}",
                "isError": True,
            }

    async def _execute_mcp(
        self,
        server_name: str,
        tool_name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a tool on an MCP server."""
        client = self._mcp_clients[server_name]

        try:
            # Ensure connected (lazy connect)
            if not client.is_connected:
                connected = await client.connect()
                if not connected:
                    return {
                        "error": (
                            f"Cannot connect to MCP server '{server_name}'. "
                            f"The server may not be available."
                        ),
                        "isError": True,
                    }

            # Call tool
            result = await client.call_tool(tool_name, params)

            # Normalize MCP result
            if result.get("isError"):
                return {
                    "error": result.get("error", "Unknown MCP error"),
                    "isError": True,
                }

            # Extract text from content blocks
            content = result.get("content", [])
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        else:
                            text_parts.append(json.dumps(block))
                    else:
                        text_parts.append(str(block))
                return {"result": "\n".join(text_parts), "isError": False}

            return {"result": json.dumps(result, indent=2), "isError": False}

        except Exception as e:
            logger.warning(
                f"ToolExecutor: MCP '{server_name}/{tool_name}' failed: {e}"
            )
            return {
                "error": f"MCP tool '{tool_name}' execution failed: {e}",
                "isError": True,
            }

    # ====================================================================
    # Query
    # ====================================================================

    def is_tool_executable(self, tool_name: str) -> bool:
        """Check if a tool is registered for execution."""
        return tool_name in self._tool_server_map

    def get_tool_server(self, tool_name: str) -> Optional[str]:
        """Get the server name for a tool."""
        return self._tool_server_map.get(tool_name)

    def list_executable_tools(self) -> List[str]:
        """List all tool names that can be executed."""
        return sorted(self._tool_server_map.keys())

    def get_stats(self) -> Dict[str, Any]:
        """Return executor statistics."""
        connected_servers = [
            name for name, client in self._mcp_clients.items()
            if client.is_connected
        ]
        return {
            "total_tools": len(self._tool_server_map),
            "builtin_tools": len(self._builtin_tools),
            "mcp_servers": len(self._mcp_clients),
            "connected_servers": connected_servers,
            "initialized": self._initialized,
        }

    # ====================================================================
    # Lifecycle
    # ====================================================================

    async def shutdown(self) -> None:
        """Disconnect all MCP clients and clean up."""
        for name, client in self._mcp_clients.items():
            if client.is_connected:
                logger.info(f"ToolExecutor: disconnecting MCP server '{name}'")
                await client.disconnect()
        self._mcp_clients.clear()
        self._builtin_tools.clear()
        self._tool_server_map.clear()
        self._initialized = False
        logger.info("ToolExecutor: shutdown complete")


# ========================================================================
# Singleton
# ========================================================================

_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get the singleton ToolExecutor instance."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor


def reset_tool_executor() -> None:
    """Reset the singleton (for testing)."""
    global _tool_executor
    _tool_executor = None
