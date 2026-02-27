"""
Guard & Post-Model Nodes — resilience infrastructure nodes.

Context guard checks context window budget.
Post-model handles completion signal detection,
iteration increment, and transcript recording.

Generalisation design:
    Both nodes expose configurable field names and feature
    toggles so they can be placed flexibly within any workflow.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List, Optional

from service.langgraph.state import (
    CompletionSignal,
    ContextBudget,
)
from service.langgraph.resilience_nodes import detect_completion_signal
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.nodes.i18n import (
    CONTEXT_GUARD_I18N,
    POST_MODEL_I18N,
)

logger = getLogger(__name__)


# ============================================================================
# Context Guard
# ============================================================================


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
    icon = "🛡️"
    color = "#6b7280"
    i18n = CONTEXT_GUARD_I18N

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


# ============================================================================
# Post Model
# ============================================================================


@register_node
class PostModelNode(BaseNode):
    """Post-model processing node.

    Performs three sequential concerns:
    1. Global iteration increment
    2. Completion signal detection from last_output
    3. Transcript recording to short-term memory

    Generalised: Configurable counter field, source field
    for signal detection, and individual feature toggles.
    """

    node_type = "post_model"
    label = "Post Model"
    description = "Post-processing node placed after every model call. Performs three sequential concerns: (1) increments the configurable iteration counter, (2) optionally detects structured completion signals from the output, and (3) optionally records the output to the short-term memory transcript. Essential resilience infrastructure for any model-calling workflow."
    category = "resilience"
    icon = "📌"
    color = "#6b7280"
    i18n = POST_MODEL_I18N

    parameters = [
        NodeParameter(
            name="detect_completion",
            label="Detect Completion Signals",
            type="boolean",
            default=True,
            description="Parse structured completion signals from the output.",
            group="behavior",
        ),
        NodeParameter(
            name="record_transcript",
            label="Record Transcript",
            type="boolean",
            default=True,
            description="Record the output to short-term memory.",
            group="behavior",
        ),
        NodeParameter(
            name="increment_field",
            label="Iteration Counter Field",
            type="string",
            default="iteration",
            description="State field to increment as the iteration counter.",
            group="state_fields",
        ),
        NodeParameter(
            name="source_field",
            label="Source State Field",
            type="string",
            default="last_output",
            description="State field to read for signal detection and transcript recording.",
            group="state_fields",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        increment_field = config.get("increment_field", "iteration")
        source_field = config.get("source_field", "last_output")
        iteration = state.get(increment_field, 0) + 1
        detect = config.get("detect_completion", True)
        record = config.get("record_transcript", True)

        updates: Dict[str, Any] = {
            increment_field: iteration,
            "current_step": "post_model",
        }

        last_output = state.get(source_field, "") or ""

        # 1. Completion signal detection
        #    Always reset completion_signal to prevent stale signals
        #    from a previous iteration leaking across loop boundaries.
        if detect and not last_output:
            # No output → explicitly clear any stale signal
            updates["completion_signal"] = CompletionSignal.NONE.value
            updates["completion_detail"] = None
        elif detect and last_output:
            signal, detail = detect_completion_signal(last_output)
            updates["completion_signal"] = signal.value
            updates["completion_detail"] = detail

            if signal in (
                CompletionSignal.COMPLETE,
                CompletionSignal.BLOCKED,
                CompletionSignal.ERROR,
            ):
                logger.info(
                    f"[{context.session_id}] post_model: "
                    f"signal={signal.value}"
                    + (f", detail={detail}" if detail else "")
                )

        # 2. Transcript recording
        if record and context.memory_manager and last_output:
            try:
                context.memory_manager.record_message("assistant", last_output[:5000])
            except Exception:
                logger.debug(f"[{context.session_id}] post_model: transcript record failed")

        return updates
