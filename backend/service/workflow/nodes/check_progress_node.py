"""
Check Progress Node — list completion checker.

Compares the current index against a configurable list field's length
and counts completed/failed items. Routes to 'continue' when items
remain or 'complete' when all items are processed.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Callable, Dict, Optional

from service.langgraph.state import CompletionSignal
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import CHECK_PROGRESS_I18N

logger = getLogger(__name__)


@register_node
class CheckProgressNode(BaseNode):
    """Check list completion progress.

    Originally TODO-specific, now generalised to work with any
    state list field and index field. Conditional: continue / complete.
    """

    node_type = "check_progress"
    label = "Check Progress"
    description = "Checks completion progress of a configurable list field. Compares the current index against the list length and counts completed/failed items. Routes to 'continue' when items remain or 'complete' when all items are processed. Also respects completion signals and error flags."
    category = "logic"
    icon = "bar-chart"
    color = "#6366f1"
    i18n = CHECK_PROGRESS_I18N
    state_usage = NodeStateUsage(
        reads=["is_complete", "error", "completion_signal"],
        writes=["current_step", "metadata"],
        config_dynamic_reads={
            "list_field": "todos",
            "index_field": "current_todo_index",
        },
    )

    parameters = [
        NodeParameter(
            name="list_field",
            label="List State Field",
            type="string",
            default="todos",
            description="State field containing the list to check progress on.",
            group="state_fields",
        ),
        NodeParameter(
            name="index_field",
            label="Index State Field",
            type="string",
            default="current_todo_index",
            description="State field tracking the current index in the list.",
            group="state_fields",
        ),
        NodeParameter(
            name="completed_status",
            label="Completed Status Value",
            type="string",
            default="completed",
            description="Status value that counts an item as completed.",
            group="behavior",
        ),
        NodeParameter(
            name="failed_status",
            label="Failed Status Value",
            type="string",
            default="failed",
            description="Status value that counts an item as failed.",
            group="behavior",
        ),
    ]

    output_ports = [
        OutputPort(id="continue", label="Continue", description="More items remaining"),
        OutputPort(id="complete", label="Complete", description="All items done"),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        list_field = config.get("list_field", "todos")
        index_field = config.get("index_field", "current_todo_index")
        completed_status = config.get("completed_status", "completed")
        failed_status = config.get("failed_status", "failed")

        current_index = state.get(index_field, 0)
        items = state.get(list_field, [])
        completed = sum(1 for t in items if t.get("status") == completed_status)
        failed = sum(1 for t in items if t.get("status") == failed_status)

        total = len(items)
        progress_ratio = current_index / total if total > 0 else 0.0

        logger.info(
            f"[{context.session_id}] check_progress: "
            f"{completed} done, {failed} failed, "
            f"{current_index}/{total} ({progress_ratio:.0%})"
        )

        return {
            "current_step": "progress_checked",
            "metadata": {
                **state.get("metadata", {}),
                "completed_items": completed,
                "failed_items": failed,
                "total_items": total,
                "progress_ratio": round(progress_ratio, 3),
            },
        }

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        list_field = config.get("list_field", "todos")
        index_field = config.get("index_field", "current_todo_index")

        def _route(state: Dict[str, Any]) -> str:
            if state.get("is_complete") or state.get("error"):
                return "complete"
            signal = state.get("completion_signal")
            if signal in (CompletionSignal.COMPLETE.value, CompletionSignal.BLOCKED.value):
                return "complete"
            current_index = state.get(index_field, 0)
            items = state.get(list_field, [])
            if current_index >= len(items):
                return "complete"
            return "continue"
        return _route
