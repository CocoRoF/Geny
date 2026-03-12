#!/usr/bin/env python3
"""
Auto-generated MCP Server for tools/
This file is auto-generated. Do not edit manually.
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Import tools
from tools.example_tool import TOOLS as example_tool_TOOLS

# Create MCP server
mcp = FastMCP("builtin-tools")

# Collect all tools
all_tools = []
all_tools.extend(example_tool_TOOLS)

# Register each tool to MCP
for tool_obj in all_tools:
    name = getattr(tool_obj, 'name', None)
    if not name and hasattr(tool_obj, '__name__'):
        name = tool_obj.__name__
    if not name:
        continue

    description = getattr(tool_obj, 'description', '') or getattr(tool_obj, '__doc__', '') or f"Tool: {name}"

    # Find run or arun method
    if hasattr(tool_obj, 'arun'):
        func = tool_obj.arun
    elif hasattr(tool_obj, 'run'):
        func = tool_obj.run
    elif callable(tool_obj):
        func = tool_obj
    else:
        continue

    # Register as MCP tool
    wrapper = mcp.tool()(func)
    wrapper.__name__ = name
    wrapper.__doc__ = description

if __name__ == "__main__":
    mcp.run(transport="stdio")
