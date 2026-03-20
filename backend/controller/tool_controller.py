"""
Tool Controller — REST API for the tool catalog.

Provides read-only endpoints to browse all available tools
(built-in Python tools, custom Python tools, external MCP servers).
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from service.tool_loader import get_tool_loader
from service.mcp_loader import get_global_mcp_config

logger = getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


# ════════════════════════════════════════════════════════════════════════════
# Response Models
# ════════════════════════════════════════════════════════════════════════════


class ToolInfo(BaseModel):
    """Metadata for a single Python tool."""
    name: str
    description: str = ""
    category: str = ""         # "built_in" or "custom"
    group: Optional[str] = None  # source file stem (e.g. "browser_tools")
    parameters: Optional[Dict[str, Any]] = None


class MCPServerInfo(BaseModel):
    """Metadata for an external MCP server."""
    name: str
    type: str  # "stdio", "http", "sse"


class ToolCatalogResponse(BaseModel):
    """Full tool catalog."""
    built_in: List[ToolInfo] = Field(default_factory=list)
    custom: List[ToolInfo] = Field(default_factory=list)
    mcp_servers: List[MCPServerInfo] = Field(default_factory=list)
    total_python_tools: int = 0
    total_mcp_servers: int = 0


# ════════════════════════════════════════════════════════════════════════════
# Endpoints
# ════════════════════════════════════════════════════════════════════════════


@router.get("/catalog", response_model=ToolCatalogResponse)
async def get_catalog():
    """Return the full tool catalog (built-in + custom + MCP servers)."""
    loader = get_tool_loader()

    built_in_tools = _tools_to_info(loader.builtin_tools, "built_in", loader)
    custom_tools = _tools_to_info(loader.custom_tools, "custom", loader)
    mcp_servers = _get_mcp_server_info()

    return ToolCatalogResponse(
        built_in=built_in_tools,
        custom=custom_tools,
        mcp_servers=mcp_servers,
        total_python_tools=len(built_in_tools) + len(custom_tools),
        total_mcp_servers=len(mcp_servers),
    )


@router.get("/catalog/built-in", response_model=List[ToolInfo])
async def get_builtin_tools():
    """Return all built-in Python tools."""
    loader = get_tool_loader()
    return _tools_to_info(loader.builtin_tools, "built_in", loader)


@router.get("/catalog/custom", response_model=List[ToolInfo])
async def get_custom_tools():
    """Return all custom Python tools."""
    loader = get_tool_loader()
    return _tools_to_info(loader.custom_tools, "custom", loader)


@router.get("/catalog/mcp-servers", response_model=List[MCPServerInfo])
async def get_mcp_servers():
    """Return all external MCP servers."""
    return _get_mcp_server_info()


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════


def _tools_to_info(
    tools_dict: Dict[str, Any], category: str, loader: Any
) -> List[ToolInfo]:
    """Convert tool dict to ToolInfo list."""
    result = []
    for name, tool_obj in tools_dict.items():
        result.append(
            ToolInfo(
                name=name,
                description=getattr(tool_obj, "description", "") or "",
                category=category,
                group=loader.get_tool_source(name),
                parameters=getattr(tool_obj, "parameters", None),
            )
        )
    return result


def _get_mcp_server_info() -> List[MCPServerInfo]:
    """Get info for all external MCP servers."""
    config = get_global_mcp_config()
    if not config or not config.servers:
        return []

    result = []
    for name, server in config.servers.items():
        if name.startswith("_"):
            continue
        server_type = type(server).__name__.replace("MCPServer", "").lower()
        result.append(MCPServerInfo(name=name, type=server_type))
    return result
