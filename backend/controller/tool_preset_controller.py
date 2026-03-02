"""
Tool Preset Controller

REST API endpoints for managing tool presets and querying available tools/MCP servers.

Tool Preset API:     /api/tool-presets
Available Tools API: /api/tools
"""
from logging import getLogger
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from service.tool_policy.tool_preset_model import ToolPreset, ToolPresetSummary
from service.tool_policy.tool_preset_store import get_tool_preset_store
from service.mcp_loader import get_global_mcp_config

logger = getLogger(__name__)

router = APIRouter(tags=["tool-presets"])


# ============================================================================
# Request/Response Models
# ============================================================================


class CreateToolPresetRequest(BaseModel):
    """Request to create a new tool preset."""
    name: str = Field(..., min_length=1, description="Preset name")
    description: str = Field(default="", description="Optional description")
    allowed_servers: List[str] = Field(default_factory=list, description="MCP server names")
    allowed_tools: List[str] = Field(default_factory=list, description="Built-in tool names")


class UpdateToolPresetRequest(BaseModel):
    """Request to update an existing tool preset."""
    name: Optional[str] = Field(default=None, description="New name")
    description: Optional[str] = Field(default=None, description="New description")
    allowed_servers: Optional[List[str]] = Field(default=None, description="New server list")
    allowed_tools: Optional[List[str]] = Field(default=None, description="New tool list")


class ToolPresetListResponse(BaseModel):
    """Response for listing all tool presets."""
    presets: List[ToolPreset]
    total: int


class AvailableServerInfo(BaseModel):
    """Information about an available MCP server."""
    name: str
    type: str = "unknown"  # stdio | http | sse
    description: str = ""


class AvailableToolInfo(BaseModel):
    """Information about an available built-in tool."""
    name: str
    description: str = ""


class AvailableToolsResponse(BaseModel):
    """Lists all available MCP servers and built-in tools."""
    servers: List[AvailableServerInfo]
    tools: List[AvailableToolInfo]


# ============================================================================
# Tool Preset CRUD API
# ============================================================================


@router.get("/api/tool-presets", response_model=ToolPresetListResponse)
async def list_tool_presets():
    """List all tool presets (templates + user-created)."""
    store = get_tool_preset_store()
    presets = store.list_all()
    return ToolPresetListResponse(presets=presets, total=len(presets))


@router.get("/api/tool-presets/templates")
async def list_tool_preset_templates():
    """List only built-in template presets."""
    store = get_tool_preset_store()
    templates = store.list_templates()
    return {"templates": templates, "total": len(templates)}


@router.post("/api/tool-presets", response_model=ToolPreset)
async def create_tool_preset(request: CreateToolPresetRequest):
    """Create a new tool preset."""
    import uuid

    store = get_tool_preset_store()
    preset_id = f"preset-{uuid.uuid4().hex[:8]}"

    preset = ToolPreset(
        id=preset_id,
        name=request.name,
        description=request.description,
        allowed_servers=request.allowed_servers,
        allowed_tools=request.allowed_tools,
        is_template=False,
    )
    store.save(preset)
    logger.info(f"✅ Tool preset created: {preset.name} ({preset.id})")
    return preset


@router.get("/api/tool-presets/{preset_id}", response_model=ToolPreset)
async def get_tool_preset(
    preset_id: str = Path(..., description="Tool preset ID"),
):
    """Get a specific tool preset by ID."""
    store = get_tool_preset_store()
    preset = store.load(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Tool preset not found: {preset_id}")
    return preset


@router.put("/api/tool-presets/{preset_id}", response_model=ToolPreset)
async def update_tool_preset(
    request: UpdateToolPresetRequest,
    preset_id: str = Path(..., description="Tool preset ID"),
):
    """Update an existing tool preset. Templates cannot be modified."""
    store = get_tool_preset_store()
    preset = store.load(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Tool preset not found: {preset_id}")
    if preset.is_template:
        raise HTTPException(status_code=400, detail="Cannot modify a built-in template. Clone it first.")

    if request.name is not None:
        preset.name = request.name
    if request.description is not None:
        preset.description = request.description
    if request.allowed_servers is not None:
        preset.allowed_servers = request.allowed_servers
    if request.allowed_tools is not None:
        preset.allowed_tools = request.allowed_tools

    store.save(preset)
    logger.info(f"✅ Tool preset updated: {preset.name} ({preset.id})")
    return preset


@router.delete("/api/tool-presets/{preset_id}")
async def delete_tool_preset(
    preset_id: str = Path(..., description="Tool preset ID"),
):
    """Delete a tool preset. Templates cannot be deleted."""
    store = get_tool_preset_store()
    preset = store.load(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Tool preset not found: {preset_id}")
    if preset.is_template:
        raise HTTPException(status_code=400, detail="Cannot delete a built-in template.")

    store.delete(preset_id)
    logger.info(f"✅ Tool preset deleted: {preset_id}")
    return {"success": True, "preset_id": preset_id}


@router.post("/api/tool-presets/{preset_id}/clone", response_model=ToolPreset)
async def clone_tool_preset(
    preset_id: str = Path(..., description="Tool preset ID to clone"),
):
    """Clone a tool preset (including templates)."""
    store = get_tool_preset_store()
    cloned = store.clone(preset_id)
    if not cloned:
        raise HTTPException(status_code=404, detail=f"Tool preset not found: {preset_id}")
    logger.info(f"✅ Tool preset cloned: {cloned.name} ({cloned.id})")
    return cloned


# ============================================================================
# Available Tools & Servers API
# ============================================================================


@router.get("/api/tools/available", response_model=AvailableToolsResponse)
async def list_available_tools():
    """List all currently available MCP servers and built-in tools.

    This endpoint inspects the global MCP config to enumerate what
    servers and tools are loaded and available for use in presets.
    """
    mcp_config = get_global_mcp_config()

    servers: List[AvailableServerInfo] = []
    tools: List[AvailableToolInfo] = []

    if mcp_config and mcp_config.servers:
        for name, server_cfg in mcp_config.servers.items():
            server_type = "unknown"
            # Determine type from class name
            cls_name = type(server_cfg).__name__.lower()
            if "stdio" in cls_name:
                server_type = "stdio"
            elif "http" in cls_name:
                server_type = "http"
            elif "sse" in cls_name:
                server_type = "sse"

            servers.append(AvailableServerInfo(
                name=name,
                type=server_type,
                description=f"MCP server ({server_type})",
            ))

    # Load built-in tools from tools/ directory
    try:
        from service.mcp_loader import MCPLoader
        loader = MCPLoader()
        loader._load_tools()
        for tool_obj in loader.tools:
            tool_name = getattr(tool_obj, 'name', None)
            if not tool_name and hasattr(tool_obj, '__name__'):
                tool_name = tool_obj.__name__
            if not tool_name:
                continue
            tool_desc = (
                getattr(tool_obj, 'description', '')
                or getattr(tool_obj, '__doc__', '')
                or f"Tool: {tool_name}"
            )
            tools.append(AvailableToolInfo(
                name=tool_name,
                description=tool_desc[:200],
            ))
    except Exception as e:
        logger.warning(f"Failed to enumerate built-in tools: {e}")

    return AvailableToolsResponse(servers=servers, tools=tools)


# ============================================================================
# Session Tools Query API
# ============================================================================


@router.get("/api/tools/session/{session_id}")
async def get_session_tools(
    session_id: str = Path(..., description="Session ID"),
):
    """Get the tools and MCP servers active for a specific session.

    Returns which tool preset was used, which servers are active,
    and which tools are available.
    """
    from service.langgraph import get_agent_session_manager

    manager = get_agent_session_manager()
    agent = manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Get MCP config from the agent's process
    active_servers: List[str] = []
    if agent.process and hasattr(agent.process, '_mcp_config'):
        mcp = agent.process._mcp_config
        if mcp and hasattr(mcp, 'servers') and mcp.servers:
            active_servers = list(mcp.servers.keys())

    # Get tool_preset_id from session metadata
    tool_preset_id = getattr(agent, '_tool_preset_id', None)
    tool_preset_name = None

    if tool_preset_id:
        store = get_tool_preset_store()
        preset = store.load(tool_preset_id)
        if preset:
            tool_preset_name = preset.name

    return {
        "session_id": session_id,
        "tool_preset_id": tool_preset_id,
        "tool_preset_name": tool_preset_name,
        "active_servers": active_servers,
    }
