"""
Logic Nodes — routing, gating, and progress-checking nodes.

These nodes perform pure state-based decisions without
invoking the LLM model. They implement the graph's control flow.
"""

from __future__ import annotations

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

logger = getLogger(__name__)


# ============================================================================
# Conditional Router — generic state-field routing
# ============================================================================


@register_node
class ConditionalRouterNode(BaseNode):
    """Route execution based on a state field value.

    Reads a configurable state field and maps its value to
    one of the output ports. Useful for building custom branching.
    """

    node_type = "conditional_router"
    label = "Conditional Router"
    description = "Route based on a state field value"
    category = "logic"
    icon = "🔀"
    color = "#6366f1"

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
    # The executor will read the config to build the edge map.
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
            import json
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

    def get_dynamic_output_ports(self, config: Dict[str, Any]) -> List[OutputPort]:
        """Compute output ports from the route_map config."""
        route_map_raw = config.get("route_map", "{}")
        if isinstance(route_map_raw, str):
            import json
            try:
                route_map = json.loads(route_map_raw)
            except (json.JSONDecodeError, TypeError):
                return [OutputPort(id="default", label="Default")]
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

        return ports


# ============================================================================
# Iteration Gate — loop-prevention node
# ============================================================================


@register_node
class IterationGateNode(BaseNode):
    """Check iteration limit, context budget, and completion signals.

    Gates loop continuation: sets ``is_complete=True`` when any
    limit is exceeded. Conditional output: continue / stop.
    """

    node_type = "iteration_gate"
    label = "Iteration Gate"
    description = "Prevent infinite loops by checking iteration limits and context budget"
    category = "logic"
    icon = "🚧"
    color = "#6366f1"

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

        stop_reason = None

        # Check 1: iteration limit
        if iteration >= max_iterations:
            stop_reason = f"Iteration limit ({iteration}/{max_iterations})"

        # Check 2: context budget
        if not stop_reason:
            budget = state.get("context_budget") or {}
            if budget.get("status") in ("block", "overflow"):
                stop_reason = f"Context budget {budget['status']}"

        # Check 3: completion signal
        if not stop_reason:
            signal = state.get("completion_signal")
            if signal in (
                CompletionSignal.COMPLETE.value,
                CompletionSignal.BLOCKED.value,
                CompletionSignal.ERROR.value,
            ):
                stop_reason = f"Completion signal: {signal}"

        updates: Dict[str, Any] = {}
        if stop_reason:
            logger.warning(f"[{context.session_id}] iteration_gate: STOP — {stop_reason}")
            updates["is_complete"] = True

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
# Check Progress — TODO completion checker
# ============================================================================


@register_node
class CheckProgressNode(BaseNode):
    """Check TODO list completion progress (hard path).

    Pure state-checking node. Conditional output: continue / complete.
    """

    node_type = "check_progress"
    label = "Check Progress"
    description = "Check TODO list completion progress"
    category = "logic"
    icon = "📊"
    color = "#6366f1"

    output_ports = [
        OutputPort(id="continue", label="Continue", description="More TODOs remaining"),
        OutputPort(id="complete", label="Complete", description="All TODOs done"),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        current_index = state.get("current_todo_index", 0)
        todos = state.get("todos", [])
        completed = sum(1 for t in todos if t.get("status") == TodoStatus.COMPLETED)
        failed = sum(1 for t in todos if t.get("status") == TodoStatus.FAILED)

        logger.info(
            f"[{context.session_id}] check_progress: "
            f"{completed} done, {failed} failed, {current_index}/{len(todos)}"
        )

        return {
            "current_step": "progress_checked",
            "metadata": {
                **state.get("metadata", {}),
                "completed_todos": completed,
                "failed_todos": failed,
                "total_todos": len(todos),
            },
        }

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        def _route(state: Dict[str, Any]) -> str:
            if state.get("is_complete") or state.get("error"):
                return "complete"
            signal = state.get("completion_signal")
            if signal in (CompletionSignal.COMPLETE.value, CompletionSignal.BLOCKED.value):
                return "complete"
            current_index = state.get("current_todo_index", 0)
            todos = state.get("todos", [])
            if current_index >= len(todos):
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
    """

    node_type = "state_setter"
    label = "State Setter"
    description = "Set state fields to specific values"
    category = "logic"
    icon = "✏️"
    color = "#6366f1"

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
        import json

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
