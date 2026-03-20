"""
Internal Tool Controller — executes Python tools in the main process.

This endpoint is called ONLY by the Proxy MCP server subprocess.
It receives tool execution requests and runs them directly in the
FastAPI process where singletons (AgentSessionManager, ChatStore, etc.)
are properly initialized.

Security: These endpoints should only be accessible from localhost.
The ``/internal/`` prefix is not exposed through the public API.
"""

from __future__ import annotations

import asyncio
from logging import getLogger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = getLogger(__name__)

router = APIRouter(prefix="/internal/tools", tags=["internal-tools"])


# ════════════════════════════════════════════════════════════════════════════
# Request / Response Models
# ════════════════════════════════════════════════════════════════════════════


class ToolExecuteRequest(BaseModel):
    """Request from Proxy MCP server to execute a tool."""
    tool_name: str = Field(..., description="Name of the tool to execute")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    session_id: str = Field(default="", description="Session ID for context")


class ToolExecuteResponse(BaseModel):
    """Response with tool execution result."""
    result: Optional[str] = None
    error: Optional[str] = None


class ToolSchemaInfo(BaseModel):
    """Schema information for a single tool."""
    name: str
    description: str
    parameters: Optional[Dict[str, Any]] = None
    category: Optional[str] = None
    group: Optional[str] = None


# ════════════════════════════════════════════════════════════════════════════
# Endpoints
# ════════════════════════════════════════════════════════════════════════════


@router.post("/execute", response_model=ToolExecuteResponse)
async def execute_tool(req: ToolExecuteRequest, request: Request):
    """Execute a Python tool in the main process.

    Called by the Proxy MCP server when Claude CLI invokes a tool.
    The tool runs in the same process as FastAPI, so all singletons
    (AgentSessionManager, ChatStore, etc.) are properly accessible.
    """
    from service.tool_loader import get_tool_loader

    tool_loader = get_tool_loader()
    tool = tool_loader.get_tool(req.tool_name)

    if not tool:
        logger.warning(f"Unknown tool requested: {req.tool_name}")
        return ToolExecuteResponse(error=f"Unknown tool: {req.tool_name}")

    try:
        # Try async execution first, fall back to sync
        if hasattr(tool, "arun") and asyncio.iscoroutinefunction(tool.arun):
            result = await tool.arun(**req.args)
        elif hasattr(tool, "run"):
            run_fn = tool.run
            if asyncio.iscoroutinefunction(run_fn):
                result = await run_fn(**req.args)
            else:
                result = run_fn(**req.args)
        else:
            return ToolExecuteResponse(error=f"Tool {req.tool_name} has no run method")

        return ToolExecuteResponse(result=str(result) if result is not None else "")

    except Exception as e:
        logger.error(f"Tool execution error [{req.tool_name}]: {e}", exc_info=True)
        return ToolExecuteResponse(error=str(e))


@router.get("/schemas", response_model=List[ToolSchemaInfo])
async def get_tool_schemas(
    request: Request,
    names: Optional[str] = None,
):
    """Return schemas for available tools.

    Args:
        names: Optional comma-separated list of tool names to filter.
               If omitted, returns all tools.
    """
    from service.tool_loader import get_tool_loader

    tool_loader = get_tool_loader()
    all_tools = tool_loader.get_all_tools()

    if names:
        allowed = set(n.strip() for n in names.split(",") if n.strip())
        all_tools = {k: v for k, v in all_tools.items() if k in allowed}

    result = []
    for name, tool_obj in all_tools.items():
        result.append(ToolSchemaInfo(
            name=name,
            description=getattr(tool_obj, "description", "") or "",
            parameters=getattr(tool_obj, "parameters", None),
            category=tool_loader.get_tool_category(name),
            group=tool_loader.get_tool_source(name),
        ))

    return result
