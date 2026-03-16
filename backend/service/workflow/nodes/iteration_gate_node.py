"""
Iteration Gate Node — loop-prevention guard.

Gates loop continuation: sets ``is_complete=True`` when any limit
is exceeded (iteration count, context budget, completion signals,
or a custom stop field). Conditional output: continue / stop.
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
from service.workflow.nodes.i18n import ITERATION_GATE_I18N

logger = getLogger(__name__)


@register_node
class IterationGateNode(BaseNode):
    """Check iteration limit, context budget, and completion signals.

    Gates loop continuation: sets ``is_complete=True`` when any
    limit is exceeded. Conditional output: continue / stop.

    Generalised: Each check can be individually toggled, and a
    custom state field can serve as an additional stop condition.
    """

    node_type = "iteration_gate"
    label = "Iteration Gate"
    description = "Loop prevention guard that checks multiple stop conditions: iteration count vs limit, context window budget status, completion signals, and an optional custom state field. When any limit is exceeded, sets is_complete=True and routes to the 'stop' port. Place before loop-back edges to prevent infinite execution."
    category = "logic"
    icon = "fence"
    color = "#6366f1"
    i18n = ITERATION_GATE_I18N
    state_usage = NodeStateUsage(
        reads=["iteration", "max_iterations", "is_complete", "error",
               "completion_signal", "context_budget"],
        writes=["is_complete", "metadata"],
        config_dynamic_reads={"custom_stop_field": ""},
    )

    parameters = [
        NodeParameter(
            name="max_iterations_override",
            label="Max Iterations Override",
            type="number",
            default=0,
            min=0,
            max=500,
            description="Override the global max iterations. 0 = use default.",
            group="behavior",
        ),
        NodeParameter(
            name="check_iteration",
            label="Check Iteration Limit",
            type="boolean",
            default=True,
            description="Enable checking against the iteration counter.",
            group="checks",
        ),
        NodeParameter(
            name="check_budget",
            label="Check Context Budget",
            type="boolean",
            default=True,
            description="Enable checking context window budget status.",
            group="checks",
        ),
        NodeParameter(
            name="check_completion",
            label="Check Completion Signals",
            type="boolean",
            default=True,
            description="Enable checking for structured completion signals.",
            group="checks",
        ),
        NodeParameter(
            name="custom_stop_field",
            label="Custom Stop Field",
            type="string",
            default="",
            description=(
                "Additional state field to check. "
                "If truthy, the gate will stop. Leave empty to disable."
            ),
            group="checks",
        ),
    ]

    output_ports = [
        OutputPort(id="continue", label="Continue", description="Loop can proceed"),
        OutputPort(id="stop", label="Stop", description="Limit exceeded, exit loop"),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        iteration = state.get("iteration", 0)
        max_iter_override = int(config.get("max_iterations_override", 0))
        max_iterations = max_iter_override if max_iter_override > 0 else state.get("max_iterations", 50)

        check_iteration = config.get("check_iteration", True)
        check_budget = config.get("check_budget", True)
        check_completion = config.get("check_completion", True)
        custom_stop_field = config.get("custom_stop_field", "")

        stop_reason = None

        # Check 1: iteration limit
        if check_iteration and not stop_reason:
            if iteration >= max_iterations:
                stop_reason = f"Iteration limit ({iteration}/{max_iterations})"

        # Check 2: context budget
        if check_budget and not stop_reason:
            budget = state.get("context_budget") or {}
            if budget.get("status") in ("block", "overflow"):
                stop_reason = f"Context budget {budget['status']}"

        # Check 3: completion signal
        if check_completion and not stop_reason:
            signal = state.get("completion_signal")
            if signal in (
                CompletionSignal.COMPLETE.value,
                CompletionSignal.BLOCKED.value,
                CompletionSignal.ERROR.value,
            ):
                stop_reason = f"Completion signal: {signal}"

        # Check 4: custom stop field
        if custom_stop_field and not stop_reason:
            if state.get(custom_stop_field):
                stop_reason = f"Custom stop: {custom_stop_field}={state[custom_stop_field]}"

        updates: Dict[str, Any] = {}
        if stop_reason:
            logger.warning(f"[{context.session_id}] iteration_gate: STOP — {stop_reason}")
            updates["is_complete"] = True
            updates["gate_stop_reason"] = stop_reason
            updates["metadata"] = {
                **state.get("metadata", {}),
                "gate_stop_reason": stop_reason,
                "stopped_at_iteration": iteration,
            }
        else:
            # Clear any previous stop reason when continuing
            updates["gate_stop_reason"] = None

        return updates

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        def _route(state: Dict[str, Any]) -> str:
            if state.get("gate_stop_reason"):
                return "stop"
            if state.get("error"):
                return "stop"
            if state.get("is_complete"):
                return "stop"
            return "continue"
        return _route
