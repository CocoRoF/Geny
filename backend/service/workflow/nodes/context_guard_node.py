"""
Context Guard Node — context window budget checker.

Estimates token usage from accumulated messages and writes the budget
status to state. Downstream nodes can read this to compact prompts
or skip calls.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict

from service.langgraph.state import ContextBudget
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import CONTEXT_GUARD_I18N

logger = getLogger(__name__)


@register_node
class ContextGuardNode(BaseNode):
    """Check context window budget before a model call.

    Estimates token usage from accumulated messages and writes
    the budget status to state. Downstream nodes can read
    this to compact prompts or skip calls.
    """

    node_type = "context_guard"
    label = "Context Guard"
    description = "Checks context window token budget before model calls. Estimates token usage from accumulated messages and writes budget status (safe/warning/block/overflow) to state. Downstream model nodes read this to compact prompts when budget is tight. Place before every model-calling node for resilience."
    category = "resilience"
    icon = "shield-check"
    color = "#6b7280"
    i18n = CONTEXT_GUARD_I18N
    state_usage = NodeStateUsage(
        reads=["context_budget"],
        writes=["context_budget"],
        config_dynamic_reads={"messages_field": "messages"},
    )

    parameters = [
        NodeParameter(
            name="position_label",
            label="Position Label",
            type="string",
            default="general",
            description="Descriptive label for logging (e.g. 'classify', 'execute').",
            group="general",
        ),
        NodeParameter(
            name="messages_field",
            label="Messages State Field",
            type="string",
            default="messages",
            description="State field containing the message list to measure.",
            group="state_fields",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        position = config.get("position_label", "general")
        messages_field = config.get("messages_field", "messages")
        messages = state.get(messages_field, [])

        if not context.context_guard:
            return {}

        # Convert messages to dicts for the guard
        msg_dicts = []
        for msg in messages:
            if hasattr(msg, "content"):
                msg_dicts.append({
                    "role": getattr(msg, "type", "unknown"),
                    "content": msg.content,
                })
            elif isinstance(msg, dict):
                msg_dicts.append(msg)

        result = context.context_guard.check(msg_dicts)

        prev_budget = state.get("context_budget") or {}
        budget: ContextBudget = {
            "estimated_tokens": result.estimated_tokens,
            "context_limit": result.context_limit,
            "usage_ratio": result.usage_ratio,
            "status": result.status.value,
            "compaction_count": prev_budget.get("compaction_count", 0),
        }

        if result.should_block:
            logger.warning(
                f"[{context.session_id}] guard_{position}: "
                f"BLOCK at {result.usage_ratio:.0%} "
                f"({result.estimated_tokens}/{result.context_limit})"
            )
            budget["compaction_count"] = budget["compaction_count"] + 1

        return {"context_budget": budget}
