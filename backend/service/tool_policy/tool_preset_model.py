"""
Tool Preset Model — Pydantic model for tool preset definitions.

A ToolPreset defines a reusable selection of MCP servers and built-in tools
that can be assigned to sessions at creation time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class ToolPreset(BaseModel):
    """A named, reusable selection of MCP servers and tools.

    Analogous to WorkflowDefinition for graph presets, a ToolPreset
    captures which MCP servers and which individual tools should be
    available when a session uses this preset.

    Fields:
        id: Unique identifier (slug-safe, e.g. "coding-full").
        name: Human-readable display name.
        description: Optional longer description.
        allowed_servers: List of MCP server names to include (empty = none).
        allowed_tools: List of individual tool names to include (empty = none).
        is_template: If True, this preset is a built-in template (read-only).
        created_at: ISO timestamp of creation.
        updated_at: ISO timestamp of last update.
    """

    id: str = Field(..., description="Unique preset identifier")
    name: str = Field(..., description="Human-readable preset name")
    description: str = Field(default="", description="Optional description")

    allowed_servers: List[str] = Field(
        default_factory=list,
        description="MCP server names to include in this preset",
    )
    allowed_tools: List[str] = Field(
        default_factory=list,
        description="Built-in tool names to include in this preset",
    )

    is_template: bool = Field(
        default=False,
        description="Whether this is a built-in read-only template",
    )

    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now(timezone.utc).isoformat()


class ToolPresetSummary(BaseModel):
    """Lightweight summary for listing presets."""

    id: str
    name: str
    description: str = ""
    server_count: int = 0
    tool_count: int = 0
    is_template: bool = False
