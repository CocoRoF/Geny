"""
Tool Discovery Post Node — extract tool discovery results from agent output.

Placed after model calls in tool_search_mode workflows. Scans the
agent's output for tool_search/tool_schema results and updates
``discovered_tools`` in state.
"""

from __future__ import annotations

import json
import re
from logging import getLogger
from typing import Any, Dict, List

from service.langgraph.state import DiscoveredTool
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.nodes.i18n import TOOL_DISCOVERY_POST_I18N
from service.workflow.workflow_state import NodeStateUsage

logger = getLogger(__name__)

# Regex patterns for detecting tool discovery in agent output
_RE_TOOL_RESULT = re.compile(
    r"tool[_\s](?:search|schema|browse|workflow)",
    re.IGNORECASE,
)


def _find_json_objects(text: str) -> List[str]:
    """Extract top-level JSON object strings from text using balanced-brace scanning."""
    objects: List[str] = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            start = i
            in_string = False
            escape_next = False
            while i < len(text):
                ch = text[i]
                if escape_next:
                    escape_next = False
                elif ch == '\\' and in_string:
                    escape_next = True
                elif ch == '"' and not escape_next:
                    in_string = not in_string
                elif not in_string:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            objects.append(text[start:i + 1])
                            break
                i += 1
        i += 1
    return objects


def _extract_discovered_tools(
    output: str,
    iteration: int,
) -> Dict[str, DiscoveredTool]:
    """Extract tool discovery information from agent output.

    Parses the output for tool_search results (tool names + descriptions)
    and tool_schema results (full parameter schemas). Returns a dict of
    tool_name → DiscoveredTool entries to merge into state.
    """
    discovered: Dict[str, DiscoveredTool] = {}

    if not output:
        return discovered

    # Find JSON blocks using balanced-brace scanner (handles nesting)
    json_blocks = _find_json_objects(output)

    for block in json_blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue

        # Pattern 1: tool_schema result — has "name" and "parameters"
        if isinstance(data, dict) and "name" in data and "parameters" in data:
            name = data["name"]
            discovered[name] = DiscoveredTool(
                name=name,
                description=data.get("description", ""),
                server_name=data.get("server_name", "unknown"),
                parameters=data.get("parameters", {}),
                discovered_at_turn=iteration,
            )

        # Pattern 2: tool_search result — has "results" list
        if isinstance(data, dict) and "results" in data:
            results = data["results"]
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict) and "name" in item:
                        name = item["name"]
                        if name not in discovered:
                            discovered[name] = DiscoveredTool(
                                name=name,
                                description=item.get("description", ""),
                                server_name=item.get("server_name", "unknown"),
                                parameters={},
                                discovered_at_turn=iteration,
                            )

    # Pattern 3: Look for tool names mentioned after "tool_search" calls
    # Match lines like: "- **tool_name**: description"
    tool_lines = re.findall(
        r'[-*]\s*\*?\*?(\w+)\*?\*?\s*[-:]\s*(.+?)(?:\n|$)',
        output,
    )
    for name, desc in tool_lines:
        # Only add if it looks like a tool name (lowercase, underscores)
        if re.match(r'^[a-z][a-z0-9_]+$', name) and name not in discovered:
            discovered[name] = DiscoveredTool(
                name=name,
                description=desc.strip(),
                server_name="unknown",
                parameters={},
                discovered_at_turn=iteration,
            )

    return discovered


@register_node
class ToolDiscoveryPostNode(BaseNode):
    """Post-processing node that extracts tool discovery results from agent output.

    Placed after model calls in tool_search_mode workflows. Scans the
    agent's output for tool_search/tool_schema results and updates
    ``discovered_tools`` in state.

    When tool_search_mode is not active, this node is a no-op.
    """

    node_type = "tool_discovery_post"
    label = "Tool Discovery Post"
    description = (
        "Extracts tool discovery results from agent output in tool_search_mode. "
        "Parses tool_search and tool_schema results, updating the discovered_tools "
        "state dict for cross-turn tool tracking. No-op when tool_search_mode is off."
    )
    category = "resilience"
    icon = "search"
    color = "#8b5cf6"
    i18n = TOOL_DISCOVERY_POST_I18N
    state_usage = NodeStateUsage(
        reads=["tool_search_mode", "discovered_tools", "last_output", "iteration"],
        writes=["discovered_tools"],
    )

    parameters = [
        NodeParameter(
            name="source_field",
            label="Source State Field",
            type="string",
            default="last_output",
            description="State field containing the agent output to scan for tool discovery.",
            group="state_fields",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        # No-op when tool_search_mode is not active
        if not state.get("tool_search_mode", False):
            return {}

        source_field = config.get("source_field", "last_output")
        output = state.get(source_field, "") or ""
        iteration = state.get("iteration", 0)

        if not output:
            return {}

        # Quick check: does the output mention tool discovery at all?
        if not _RE_TOOL_RESULT.search(output):
            return {}

        # Extract discovered tools
        new_tools = _extract_discovered_tools(output, iteration)

        if not new_tools:
            return {}

        # Merge with existing discoveries
        existing = state.get("discovered_tools", {})
        # Only log genuinely new tools
        genuinely_new = [n for n in new_tools if n not in existing]
        if genuinely_new:
            logger.info(
                f"[{context.session_id}] tool_discovery_post: "
                f"discovered {len(genuinely_new)} new tool(s): "
                f"{', '.join(genuinely_new)}"
            )

        return {"discovered_tools": new_tools}
