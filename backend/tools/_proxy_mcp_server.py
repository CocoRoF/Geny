#!/usr/bin/env python3
"""
Proxy MCP Server — thin proxy between Claude CLI and the FastAPI main process.

This script runs as a stdio MCP server subprocess spawned by Claude CLI.
It does NOT execute tools itself. Instead, it:

1. Imports tool modules to extract schemas (function signatures)
2. Registers proxy functions with FastMCP that delegate execution
   to the main FastAPI process via HTTP POST

This solves the fundamental problem: tools like geny_tools need access
to singletons (AgentSessionManager, ChatStore) that only exist in the
main process.

Usage (spawned by Claude CLI via .mcp.json):
    python tools/_proxy_mcp_server.py <backend_url> <session_id> [tool1,tool2,...]

Arguments:
    backend_url:  Base URL of the FastAPI server (e.g. http://localhost:8000)
    session_id:   Session ID for context passing
    allowed_tools: Optional comma-separated list of tool names to register.
                   If omitted, all tools are registered.
"""

import sys
import functools
import asyncio
from pathlib import Path

# ── Add project root to path ──
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)


# ── Parse CLI arguments ──
if len(sys.argv) < 3:
    print(
        "Usage: python _proxy_mcp_server.py <backend_url> <session_id> [allowed_tools]",
        file=sys.stderr,
    )
    sys.exit(1)

BACKEND_URL = sys.argv[1]
SESSION_ID = sys.argv[2]
ALLOWED_TOOLS = (
    set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[3] else None
)

# ── Create MCP server ──
mcp = FastMCP("python-tools")


def _register_proxy_tool(tool_obj, mcp_server, backend_url, session_id):
    """Register a tool as a proxy that delegates execution to the main process.

    The tool's schema (name, description, parameters) comes from the original
    tool object. The actual execution is forwarded via HTTP POST.
    """
    name = getattr(tool_obj, "name", None)
    if not name:
        return

    description = getattr(tool_obj, "description", "") or f"Tool: {name}"

    # Get the original run function to preserve its signature.
    # FastMCP uses inspect.signature() on the registered function to
    # generate the input_schema. @functools.wraps copies __wrapped__,
    # __annotations__, etc. so the schema is accurate.
    if hasattr(tool_obj, "run") and callable(tool_obj.run):
        source_fn = tool_obj.run
    elif callable(tool_obj):
        source_fn = tool_obj
    else:
        return

    @functools.wraps(source_fn)
    async def proxy_fn(*args, **kwargs):
        """Proxy: forwards tool call to main FastAPI process via HTTP."""
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                resp = await client.post(
                    f"{backend_url}/internal/tools/execute",
                    json={
                        "tool_name": name,
                        "args": kwargs,
                        "session_id": session_id,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("error"):
                    return f"Error: {data['error']}"
                return data.get("result", "")

            except httpx.ConnectError:
                return f"Error: Cannot connect to backend at {backend_url}"
            except Exception as e:
                return f"Error executing {name}: {e}"

    # Override the function name and docstring for MCP registration
    proxy_fn.__name__ = name
    proxy_fn.__qualname__ = name

    # Build the docstring with Args section for proper schema generation
    source_doc = source_fn.__doc__ or ""
    args_section = ""
    if "Args:" in source_doc:
        args_idx = source_doc.index("Args:")
        args_section = source_doc[args_idx:]
    proxy_fn.__doc__ = (
        f"{description}\n\n{args_section}" if args_section else description
    )

    mcp_server.tool(name=name, description=description)(proxy_fn)


# ── Load tool modules for schema extraction ──
# We import the tool modules only to get their TOOLS lists.
# The actual execution happens in the main process.

_all_tools = []

# Built-in tools
try:
    from tools.built_in.geny_tools import TOOLS as builtin_geny
    _all_tools.extend(builtin_geny)
except ImportError as e:
    print(f"Warning: Could not load built-in geny_tools: {e}", file=sys.stderr)

# Custom tools
_custom_modules = [
    ("tools.custom.browser_tools", "TOOLS"),
    ("tools.custom.web_search_tools", "TOOLS"),
    ("tools.custom.web_fetch_tools", "TOOLS"),
]

for module_path, attr in _custom_modules:
    try:
        import importlib
        mod = importlib.import_module(module_path)
        tools_list = getattr(mod, attr, [])
        _all_tools.extend(tools_list)
    except ImportError as e:
        print(f"Warning: Could not load {module_path}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Error loading {module_path}: {e}", file=sys.stderr)

# ── Register proxy functions ──
_registered_count = 0
for tool_obj in _all_tools:
    tool_name = getattr(tool_obj, "name", "")
    if ALLOWED_TOOLS and tool_name not in ALLOWED_TOOLS:
        continue
    _register_proxy_tool(tool_obj, mcp, BACKEND_URL, SESSION_ID)
    _registered_count += 1

print(
    f"Proxy MCP server: {_registered_count} tools registered "
    f"(session={SESSION_ID})",
    file=sys.stderr,
)

# ── Run ──
if __name__ == "__main__":
    mcp.run(transport="stdio")
