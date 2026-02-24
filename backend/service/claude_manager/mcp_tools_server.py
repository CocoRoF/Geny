"""
LangChain Tools to MCP Server Wrapper

Wraps LangChain's BaseTool as MCP server for use in Claude Code sessions.

Usage:
    1. Define LangChain tools
    2. Wrap with MCPToolsServer
    3. Run server or connect to Claude Control session

Example:
    ```python
    from langchain_core.tools import tool
    from service.claude_manager.mcp_tools_server import MCPToolsServer

    @tool
    def search_web(query: str) -> str:
        '''Search the web for information'''
        return f"Results for: {query}"

    @tool
    def calculate(expression: str) -> str:
        '''Calculate a math expression'''
        return str(eval(expression))

    # Run as MCP server
    server = MCPToolsServer(
        name="custom-tools",
        tools=[search_web, calculate]
    )
    server.run(transport="stdio")
    ```
"""
import asyncio
import json
from logging import getLogger
from typing import List, Optional, Dict, Any, Callable, Union
from pathlib import Path

logger = getLogger(__name__)

# Check if MCP SDK is installed
try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning("MCP SDK not installed. Install with: pip install mcp")

# Check if LangChain is installed
try:
    from langchain_core.tools import BaseTool, StructuredTool
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logger.warning("LangChain not installed. Install with: pip install langchain-core")


class MCPToolsServer:
    """
    Wrap LangChain tools as MCP server

    Converts tools defined with LangChain's BaseTool or @tool decorator
    to MCP server for use in Claude Code.

    Attributes:
        name: MCP server name
        tools: LangChain tools list
        mcp: FastMCP instance
    """

    def __init__(
        self,
        name: str = "langchain-tools",
        tools: Optional[List[Any]] = None,
        description: Optional[str] = None
    ):
        """
        Args:
            name: MCP server name
            tools: LangChain BaseTool list
            description: Server description
        """
        if not MCP_AVAILABLE:
            raise ImportError(
                "MCP SDK is not installed. "
                "Install with 'pip install mcp'."
            )

        self.name = name
        self._tools: List[Any] = []
        self._description = description or f"LangChain tools wrapped as MCP server: {name}"

        # Create FastMCP instance
        self.mcp = FastMCP(name)

        # Register tools
        if tools:
            for tool in tools:
                self.add_tool(tool)

    def add_tool(self, tool: Any) -> None:
        """
        Add LangChain tool

        Args:
            tool: LangChain BaseTool or function defined with @tool decorator
        """
        if not LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LangChain is not installed. "
                "Install with 'pip install langchain-core'."
            )

        self._tools.append(tool)
        self._register_mcp_tool(tool)

    def _register_mcp_tool(self, tool: Any) -> None:
        """
        Register LangChain tool as MCP tool

        Args:
            tool: LangChain tool
        """
        # Extract tool name and description
        if hasattr(tool, 'name'):
            tool_name = tool.name
        elif hasattr(tool, '__name__'):
            tool_name = tool.__name__
        else:
            tool_name = str(tool)

        if hasattr(tool, 'description'):
            tool_description = tool.description
        elif hasattr(tool, '__doc__') and tool.__doc__:
            tool_description = tool.__doc__
        else:
            tool_description = f"LangChain tool: {tool_name}"

        # Create tool function
        async def mcp_tool_wrapper(**kwargs) -> str:
            """MCP tool wrapper"""
            try:
                # Execute LangChain tool
                if hasattr(tool, 'ainvoke'):
                    result = await tool.ainvoke(kwargs)
                elif hasattr(tool, 'invoke'):
                    result = tool.invoke(kwargs)
                elif hasattr(tool, 'run'):
                    result = tool.run(**kwargs) if kwargs else tool.run()
                elif callable(tool):
                    result = tool(**kwargs)
                else:
                    result = str(tool)

                # Convert result to string
                if isinstance(result, str):
                    return result
                elif isinstance(result, (dict, list)):
                    return json.dumps(result, ensure_ascii=False, indent=2)
                else:
                    return str(result)

            except Exception as e:
                logger.error(f"Tool execution error ({tool_name}): {e}")
                return f"Error: {str(e)}"

        # Set function metadata
        mcp_tool_wrapper.__name__ = tool_name
        mcp_tool_wrapper.__doc__ = tool_description

        # Register as MCP tool
        self.mcp.tool()(mcp_tool_wrapper)
        logger.info(f"Registered MCP tool: {tool_name}")

    def add_function(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> None:
        """
        Add regular Python function as MCP tool

        Args:
            func: Python function
            name: Tool name (default: function name)
            description: Tool description (default: docstring)
        """
        tool_name = name or func.__name__
        tool_description = description or func.__doc__ or f"Function: {tool_name}"

        # Set function metadata
        wrapper = func
        wrapper.__name__ = tool_name
        wrapper.__doc__ = tool_description

        # Register as MCP tool
        self.mcp.tool()(wrapper)
        logger.info(f"Registered MCP function: {tool_name}")

    def run(self, transport: str = "stdio", host: str = "0.0.0.0", port: int = 8080) -> None:
        """
        Run MCP server

        Args:
            transport: Transport type ("stdio" or "http")
            host: HTTP server host (when transport="http")
            port: HTTP server port (when transport="http")
        """
        logger.info(f"Starting MCP server '{self.name}' with {len(self._tools)} tools")
        logger.info(f"Transport: {transport}")

        if transport == "http":
            self.mcp.run(transport="http", host=host, port=port)
        else:
            self.mcp.run(transport="stdio")

    def get_tool_list(self) -> List[Dict[str, str]]:
        """
        Return list of registered tools

        Returns:
            List of tool information
        """
        tools = []
        for tool in self._tools:
            if hasattr(tool, 'name'):
                name = tool.name
            elif hasattr(tool, '__name__'):
                name = tool.__name__
            else:
                name = str(tool)

            if hasattr(tool, 'description'):
                desc = tool.description
            elif hasattr(tool, '__doc__'):
                desc = tool.__doc__ or ""
            else:
                desc = ""

            tools.append({"name": name, "description": desc})

        return tools


def create_mcp_server_script(
    tools_module_path: str,
    tool_names: List[str],
    server_name: str = "custom-tools",
    output_path: Optional[str] = None
) -> str:
    """
    Create script to run LangChain tools as MCP server

    Args:
        tools_module_path: Module path where tools are defined
        tool_names: List of tool names to use
        server_name: MCP server name
        output_path: Output script path (returns string if None)

    Returns:
        Generated script content
    """
    script = f'''#!/usr/bin/env python3
"""
Auto-generated MCP Server Script
Server Name: {server_name}
Tools: {", ".join(tool_names)}
"""
import sys
sys.path.insert(0, ".")

from {tools_module_path} import {", ".join(tool_names)}
from service.claude_manager.mcp_tools_server import MCPToolsServer

if __name__ == "__main__":
    server = MCPToolsServer(
        name="{server_name}",
        tools=[{", ".join(tool_names)}]
    )
    server.run(transport="stdio")
'''

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(script)
        logger.info(f"MCP server script created: {output_path}")

    return script


# =============================================================================
# Convenience functions: Create commonly used MCP server configs
# =============================================================================

def create_filesystem_mcp_config(paths: List[str]) -> Dict[str, Any]:
    """
    Create filesystem MCP server config

    Args:
        paths: List of paths to allow access

    Returns:
        MCP server config dictionary
    """
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"] + paths
    }


def create_github_mcp_config() -> Dict[str, Any]:
    """
    Create GitHub MCP server config

    Returns:
        MCP server config dictionary
    """
    return {
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/"
    }


def create_postgres_mcp_config(dsn: str) -> Dict[str, Any]:
    """
    Create PostgreSQL MCP server config

    Args:
        dsn: PostgreSQL connection string

    Returns:
        MCP server config dictionary
    """
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@bytebase/dbhub", "--dsn", dsn]
    }


def create_custom_mcp_config(
    server_type: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    url: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Create custom MCP server config

    Args:
        server_type: Server type ("stdio", "http", "sse")
        command: Execution command (for stdio)
        args: Command arguments (for stdio)
        url: Server URL (for http/sse)
        env: Environment variables
        headers: HTTP headers

    Returns:
        MCP server config dictionary
    """
    config: Dict[str, Any] = {"type": server_type}

    if server_type == "stdio":
        if command:
            config["command"] = command
        if args:
            config["args"] = args
        if env:
            config["env"] = env
    else:  # http or sse
        if url:
            config["url"] = url
        if headers:
            config["headers"] = headers

    return config
