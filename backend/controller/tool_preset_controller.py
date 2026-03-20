"""
Tool Preset Controller — REST API for managing tool presets.

Provides CRUD operations for tool presets, plus a catalog endpoint
that returns all available tools (built-in + custom + MCP servers).
"""

from __future__ import annotations

from logging import getLogger
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from service.tool_preset.models import ToolPresetDefinition
from service.tool_preset.store import get_tool_preset_store

logger = getLogger(__name__)

router = APIRouter(prefix="/api/tool-presets", tags=["tool-presets"])


# ════════════════════════════════════════════════════════════════════════════
# Request / Response Models
# ════════════════════════════════════════════════════════════════════════════


class CreateToolPresetRequest(BaseModel):
    """Request to create a new tool preset."""
    name: str = Field(..., description="Preset name")
    description: str = Field(default="", description="Preset description")
    icon: Optional[str] = Field(default=None, description="Icon emoji")
    custom_tools: List[str] = Field(default_factory=list, description="Custom tool names")
    mcp_servers: List[str] = Field(default_factory=list, description="External MCP server names")


class UpdateToolPresetRequest(BaseModel):
    """Request to update an existing tool preset."""
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    custom_tools: Optional[List[str]] = None
    mcp_servers: Optional[List[str]] = None


class ClonePresetRequest(BaseModel):
    """Request to clone a preset."""
    new_name: str = Field(..., description="Name for the cloned preset")


class ToolPresetListResponse(BaseModel):
    """Response containing a list of presets."""
    presets: List[ToolPresetDefinition]
    total: int


# ════════════════════════════════════════════════════════════════════════════
# Endpoints
# ════════════════════════════════════════════════════════════════════════════


@router.get("/", response_model=ToolPresetListResponse)
async def list_presets():
    """List all tool presets (templates + user-created)."""
    store = get_tool_preset_store()
    presets = store.list_all()
    return ToolPresetListResponse(presets=presets, total=len(presets))


@router.get("/templates", response_model=ToolPresetListResponse)
async def list_templates():
    """List template presets only."""
    store = get_tool_preset_store()
    presets = store.list_templates()
    return ToolPresetListResponse(presets=presets, total=len(presets))


@router.post("/", response_model=ToolPresetDefinition, status_code=201)
async def create_preset(req: CreateToolPresetRequest):
    """Create a new user tool preset."""
    store = get_tool_preset_store()

    preset = ToolPresetDefinition(
        name=req.name,
        description=req.description,
        icon=req.icon,
        custom_tools=req.custom_tools,
        mcp_servers=req.mcp_servers,
        is_template=False,
    )
    store.save(preset)
    return preset


@router.get("/{preset_id}", response_model=ToolPresetDefinition)
async def get_preset(preset_id: str):
    """Get a specific tool preset by ID."""
    store = get_tool_preset_store()
    preset = store.load(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")
    return preset


@router.put("/{preset_id}", response_model=ToolPresetDefinition)
async def update_preset(preset_id: str, req: UpdateToolPresetRequest):
    """Update an existing tool preset. Templates cannot be modified."""
    store = get_tool_preset_store()
    preset = store.load(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")
    if preset.is_template:
        raise HTTPException(status_code=403, detail="Cannot modify template presets. Clone it first.")

    if req.name is not None:
        preset.name = req.name
    if req.description is not None:
        preset.description = req.description
    if req.icon is not None:
        preset.icon = req.icon
    if req.custom_tools is not None:
        preset.custom_tools = req.custom_tools
    if req.mcp_servers is not None:
        preset.mcp_servers = req.mcp_servers

    store.save(preset)
    return preset


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str):
    """Delete a tool preset. Templates cannot be deleted."""
    store = get_tool_preset_store()
    preset = store.load(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")
    if preset.is_template:
        raise HTTPException(status_code=403, detail="Cannot delete template presets.")

    store.delete(preset_id)
    return {"success": True, "deleted": preset_id}


@router.post("/{preset_id}/clone", response_model=ToolPresetDefinition, status_code=201)
async def clone_preset(preset_id: str, req: ClonePresetRequest):
    """Clone a preset (template or user) with a new name."""
    store = get_tool_preset_store()
    cloned = store.clone(preset_id, req.new_name)
    if not cloned:
        raise HTTPException(status_code=404, detail=f"Source preset not found: {preset_id}")
    return cloned
