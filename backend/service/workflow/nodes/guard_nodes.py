"""
Guard & Post-Model Nodes — resilience infrastructure nodes.

Context guard checks context window budget.
Post-model handles completion signal detection,
iteration increment, and transcript recording.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

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
    description = "Check context window budget and token usage"
    category = "resilience"
    icon = "🛡️"
    color = "#6b7280"

    parameters = [
        NodeParameter(
            name="position_label",
            label="Position Label",
            type="string",
            default="general",
            description="Descriptive label for logging (e.g. 'classify', 'execute').",
            group="general",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        position = config.get("position_label", "general")
        messages = state.get("messages", [])

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
    """

    node_type = "post_model"
    label = "Post Model"
    description = "Post-processing: iteration increment, signal detection, transcript recording"
    category = "resilience"
    icon = "📌"
    color = "#6b7280"

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
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        iteration = state.get("iteration", 0) + 1
        detect = config.get("detect_completion", True)
        record = config.get("record_transcript", True)

        updates: Dict[str, Any] = {
            "iteration": iteration,
            "current_step": "post_model",
        }

        last_output = state.get("last_output", "") or ""

        # 1. Completion signal detection
        if detect and last_output:
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
