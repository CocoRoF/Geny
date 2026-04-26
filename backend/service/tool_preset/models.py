"""
Tool Preset Data Models.

Defines the serializable data structure that describes which tools
and MCP servers are available in a session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class ToolPresetDefinition(BaseModel):
    """A tool preset — defines which tools a session can use.

    Built-in tools (geny_tools) are ALWAYS available regardless of preset.
    This preset controls:
    - Which custom Python tools are enabled
    - Which external MCP servers are included

    Attributes:
        id: Unique identifier (UUID or "template-xxx").
        name: Human-readable name (e.g. "Web Research").
        description: What this preset is for.
        icon: Optional emoji/icon for UI.
        custom_tools: List of custom tool names to include.
                      ["*"] means all custom tools.
                      [] means none.
        mcp_servers: List of external MCP server names to include.
                     ["*"] means all. [] means none.
        is_template: If True, this is a built-in template (read-only, clone to edit).
        template_name: Machine name for templates (e.g. "web-research").
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Preset"
    description: str = ""
    icon: Optional[str] = None

    custom_tools: List[str] = Field(
        default_factory=list,
        description="Custom tool names to include. ['*'] = all, [] = none.",
    )
    mcp_servers: List[str] = Field(
        default_factory=list,
        description="External MCP server names to include. ['*'] = all, [] = none.",
    )

    # PR-F.5.1 — per-preset framework built-in selection. Existing
    # behaviour ("framework built-ins always on, no filtering") is
    # preserved by the default ``built_in_mode='inherit'`` — old
    # preset records on disk parse cleanly because every new field has
    # a default. The manifest builder (PR-F.5.2) only consults these
    # fields when ``built_in_mode != 'inherit'``.
    built_in_mode: str = Field(
        "inherit",
        description=(
            "How built_in_tools / built_in_deny apply: "
            "'inherit' = ignore both, executor uses every BUILT_IN_TOOL_CLASS; "
            "'allowlist' = manifest.tools.built_in = built_in_tools (deny ignored); "
            "'blocklist' = every BUILT_IN_TOOL_CLASS minus built_in_deny."
        ),
    )
    built_in_tools: List[str] = Field(
        default_factory=list,
        description=(
            "Allow-listed framework built-in tool names — "
            "consulted when built_in_mode='allowlist'."
        ),
    )
    built_in_deny: List[str] = Field(
        default_factory=list,
        description=(
            "Deny-listed framework built-in tool names — "
            "consulted when built_in_mode='blocklist'."
        ),
    )

    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    is_template: bool = False
    template_name: Optional[str] = None

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp."""
        self.updated_at = datetime.now(timezone.utc).isoformat()
