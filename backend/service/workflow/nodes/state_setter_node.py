"""
State Setter Node — directly manipulate state fields.

Sets specific state fields to configured JSON values. Useful for
initialising state, resetting counters, setting flags, or injecting
static configuration into the workflow.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Dict

from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import STATE_SETTER_I18N

logger = getLogger(__name__)


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
