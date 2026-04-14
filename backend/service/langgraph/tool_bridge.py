"""Tool Bridge — adapts Geny's BaseTool instances to geny-executor's Tool interface.

Bridges the gap between Geny's tool system (BaseTool with run(**kwargs))
and geny-executor's tool system (Tool ABC with async execute(input, context)).

Usage::

    from service.langgraph.tool_bridge import build_geny_tool_registry

    registry = build_geny_tool_registry(tool_loader, ["web_search", "file_read"])
    pipeline = GenyPresets.worker_full(api_key, memory_manager, tools=registry)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_geny_tool_registry(
    tool_loader: Any,
    allowed_tool_names: List[str],
) -> Any:
    """Build a geny-executor ToolRegistry from Geny's ToolLoader.

    Args:
        tool_loader: Geny's ToolLoader instance (has get_tool(name) method).
        allowed_tool_names: List of tool names to include.

    Returns:
        geny-executor ToolRegistry populated with adapted tools.
    """
    from geny_executor.tools.registry import ToolRegistry
    from geny_executor.tools.base import Tool, ToolResult

    registry = ToolRegistry()

    for tool_name in allowed_tool_names:
        try:
            geny_tool = tool_loader.get_tool(tool_name)
            if geny_tool is None:
                continue

            adapted = _GenyToolAdapter(geny_tool)
            registry.register(adapted)

        except Exception as exc:
            logger.debug("tool_bridge: failed to adapt '%s': %s", tool_name, exc)

    logger.info(
        "tool_bridge: built registry with %d tools (from %d requested)",
        len(registry),
        len(allowed_tool_names),
    )
    return registry


class _GenyToolAdapter:
    """Adapts a Geny BaseTool to geny-executor's Tool interface.

    Implements all methods required by geny-executor's Tool ABC:
    - name, description, input_schema (properties)
    - execute(input, context) -> ToolResult
    - to_api_format() -> dict (Anthropic API tool definition)
    """

    def __init__(self, geny_tool: Any):
        self._tool = geny_tool
        self._name = getattr(geny_tool, "name", "unknown_tool")
        self._description = getattr(geny_tool, "description", "")
        self._parameters = getattr(geny_tool, "parameters", None) or {
            "type": "object",
            "properties": {},
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> Dict[str, Any]:
        return self._parameters

    def to_api_format(self) -> Dict[str, Any]:
        """Convert to Anthropic API tools parameter format.

        Required by ToolRegistry.to_api_format() which is called
        by s03_system stage to build the API request tools list.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    async def execute(
        self, input: Dict[str, Any], context: Any = None
    ) -> Any:
        """Execute the Geny tool and wrap result as ToolResult.

        Automatically injects session_id from ToolContext into the input
        dict if the tool expects it (many Geny built-in tools require it).
        """
        from geny_executor.tools.base import ToolResult

        # Auto-inject session_id from Pipeline ToolContext
        if context and hasattr(context, "session_id") and context.session_id:
            input.setdefault("session_id", context.session_id)

        try:
            # Try async first (arun), fall back to sync (run)
            if hasattr(self._tool, "arun"):
                result = await self._tool.arun(**input)
            elif hasattr(self._tool, "run"):
                run_fn = self._tool.run
                if asyncio.iscoroutinefunction(run_fn):
                    result = await run_fn(**input)
                else:
                    result = await asyncio.to_thread(lambda: run_fn(**input))
            else:
                return ToolResult(
                    content=f"Tool '{self._name}' has no run/arun method",
                    is_error=True,
                )

            # Normalize result to string
            if not isinstance(result, str):
                import json
                try:
                    result = json.dumps(result, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    result = str(result)

            return ToolResult(content=result)

        except Exception as exc:
            logger.warning("tool_bridge: '%s' execution failed: %s", self._name, exc, exc_info=True)
            return ToolResult(
                content=f"Error executing {self._name}: {exc}",
                is_error=True,
            )
