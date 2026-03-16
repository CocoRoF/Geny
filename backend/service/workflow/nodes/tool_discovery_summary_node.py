"""
Tool Discovery Summary Node — inject discovered tool summaries into agent context.

When placed before a model call in tool_search_mode, this node
prepends a summary of all previously discovered tools and their
schemas to help the agent remember what tools are available
without re-searching.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict

from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.nodes.i18n import TOOL_DISCOVERY_SUMMARY_I18N
from service.workflow.workflow_state import NodeStateUsage

logger = getLogger(__name__)


@register_node
class ToolDiscoverySummaryNode(BaseNode):
    """Injects a summary of discovered tools into messages for agent context.

    When placed before a model call in tool_search_mode, this node
    prepends a summary of all previously discovered tools and their
    schemas to help the agent remember what tools are available
    without re-searching.

    No-op when tool_search_mode is not active or no tools discovered.
    """

    node_type = "tool_discovery_summary"
    label = "Tool Discovery Summary"
    description = (
        "Injects discovered tool summaries into agent context. "
        "Helps the agent remember previously discovered tools "
        "without re-searching. No-op when tool_search_mode is off."
    )
    category = "resilience"
    icon = "list"
    color = "#8b5cf6"
    i18n = TOOL_DISCOVERY_SUMMARY_I18N
    state_usage = NodeStateUsage(
        reads=["tool_search_mode", "discovered_tools"],
        writes=["memory_context"],
    )

    parameters = [
        NodeParameter(
            name="max_tools_in_summary",
            label="Max Tools in Summary",
            type="number",
            default=20,
            min=1,
            max=100,
            description="Maximum number of discovered tools to include in the summary.",
            group="behavior",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not state.get("tool_search_mode", False):
            return {}

        discovered = state.get("discovered_tools", {})
        if not discovered:
            return {}

        max_tools = int(config.get("max_tools_in_summary", 20))

        # Build a concise summary of discovered tools
        lines = ["## Previously Discovered Tools"]
        for i, (name, tool) in enumerate(discovered.items()):
            if i >= max_tools:
                lines.append(f"... and {len(discovered) - max_tools} more")
                break
            desc = tool.get("description", "")
            has_schema = bool(tool.get("parameters"))
            schema_note = " (schema loaded)" if has_schema else " (use tool_schema to get params)"
            lines.append(f"- **{name}**: {desc}{schema_note}")

        summary = "\n".join(lines)

        # Merge with existing memory context
        existing_context = state.get("memory_context", "") or ""
        if existing_context:
            combined = f"{existing_context}\n\n{summary}"
        else:
            combined = summary

        return {"memory_context": combined}
