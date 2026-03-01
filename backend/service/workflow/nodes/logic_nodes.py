"""
Logic Nodes — routing, gating, and progress-checking nodes.

These nodes perform pure state-based decisions without
invoking the LLM model. They implement the graph's control flow.

Generalisation design:
    Every logic node exposes configurable field names and
    thresholds so that the same control-flow pattern can be
    re-used across different workflow topologies without
    hard-coding to specific state field names like ``todos``.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from service.langgraph.state import (
    CompletionSignal,
    TodoStatus,
)
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import (
    CONDITIONAL_ROUTER_I18N,
    ITERATION_GATE_I18N,
    CHECK_PROGRESS_I18N,
    STATE_SETTER_I18N,
)

logger = getLogger(__name__)


# ============================================================================
# Conditional Router — generic state-field routing
# ============================================================================


@register_node
class ConditionalRouterNode(BaseNode):
    """Route execution based on a state field value.

    Reads a configurable state field and maps its value to
    one of the output ports. Useful for building custom branching.

    Already maximally generalised — no structural changes needed.
    """

    node_type = "conditional_router"
    label = "Conditional Router"
    description = "Pure state-based routing node. Reads a specified state field and maps its value to output ports via a configurable JSON route map. Handles enums, strings, and other types with automatic normalization. Essential for building branching workflows where routing decisions are separated from node execution."
    category = "logic"
    icon = "git-branch"
    color = "#6366f1"
    i18n = CONDITIONAL_ROUTER_I18N
    state_usage = NodeStateUsage(
        reads=[],
        writes=["current_step"],
        config_dynamic_reads={"routing_field": "difficulty"},
    )

    parameters = [
        NodeParameter(
            name="routing_field",
            label="Routing State Field",
            type="string",
            default="difficulty",
            required=True,
            description="Name of the state field to read for routing decisions.",
            group="routing",
        ),
        NodeParameter(
            name="route_map",
            label="Route Mapping (JSON)",
            type="json",
            default='{"easy": "easy", "medium": "medium", "hard": "hard"}',
            required=True,
            description=(
                'JSON object mapping field values to output port IDs. '
                'Example: {"value1": "port_a", "value2": "port_b"}'
            ),
            group="routing",
            generates_ports=True,
        ),
        NodeParameter(
            name="default_port",
            label="Default Port",
            type="string",
            default="default",
            description="Port to use when the field value doesn't match any route.",
            group="routing",
        ),
    ]

    # Output ports are dynamic — determined by route_map at build time.
    output_ports = [
        OutputPort(id="default", label="Default", description="Fallback route"),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Pure routing — no state changes needed.
        return {"current_step": "routed"}

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        routing_field = config.get("routing_field", "difficulty")
        default_port = config.get("default_port", "default")

        route_map_raw = config.get("route_map", "{}")
        if isinstance(route_map_raw, str):
            try:
                route_map = json.loads(route_map_raw)
            except (json.JSONDecodeError, TypeError):
                route_map = {}
        else:
            route_map = route_map_raw

        def _route(state: Dict[str, Any]) -> str:
            value = state.get(routing_field)
            if hasattr(value, "value"):  # Handle enums
                value = value.value
            if isinstance(value, str):
                value = value.strip().lower()
            return route_map.get(str(value), default_port) if value is not None else default_port

        return _route

    def get_dynamic_output_ports(self, config: Dict[str, Any]) -> Optional[List[OutputPort]]:
        """Compute output ports from the route_map config."""
        route_map_raw = config.get("route_map", "{}")
        if isinstance(route_map_raw, str):
            try:
                route_map = json.loads(route_map_raw)
            except (json.JSONDecodeError, TypeError):
                return None
        else:
            route_map = route_map_raw

        ports = []
        seen = set()
        for _val, port_id in route_map.items():
            if port_id not in seen:
                ports.append(OutputPort(id=port_id, label=port_id.capitalize()))
                seen.add(port_id)

        default_port = config.get("default_port", "default")
        if default_port not in seen:
            ports.append(OutputPort(id=default_port, label="Default"))

        return ports or None


# ============================================================================
# Iteration Gate — loop-prevention node
# ============================================================================


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
            if state.get("is_complete") or state.get("error"):
                return "stop"
            return "continue"
        return _route


# ============================================================================
# Check Progress — list completion checker (generalised)
# ============================================================================


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


# ============================================================================
# State Setter — manipulate state fields
# ============================================================================


@register_node
class StateSetterNode(BaseNode):
    """Set specific state fields to configured values.

    Useful for initialising state or resetting counters.

    Already maximally generalised — no structural changes needed.
    """

    node_type = "state_setter"
    label = "State Setter"
    description = "Directly manipulates state fields by setting them to configured JSON values. Useful for initializing state, resetting counters, setting flags, or injecting static configuration into the workflow at specific points."
    category = "logic"
    icon = "pen-line"
    color = "#6366f1"
    i18n = STATE_SETTER_I18N
    state_usage = NodeStateUsage(
        reads=[],
        writes=[],  # dynamic from config
    )

    parameters = [
        NodeParameter(
            name="state_updates",
            label="State Updates (JSON)",
            type="json",
            default='{}',
            required=True,
            description='JSON object of state field updates. Example: {"is_complete": true, "review_count": 0}',
            group="general",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw = config.get("state_updates", "{}")
        if isinstance(raw, str):
            try:
                updates = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                updates = {}
        else:
            updates = raw

        if isinstance(updates, dict):
            return updates
        return {}
