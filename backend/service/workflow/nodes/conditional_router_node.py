"""
Conditional Router Node — generic state-field routing.

Reads a configurable state field and maps its value to one of
the output ports. Useful for building custom branching workflows.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import CONDITIONAL_ROUTER_I18N

logger = getLogger(__name__)


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
