"""
Transcript Record Node — record a state field to short-term memory.

Records a configurable state field's content to the short-term memory
transcript with a configurable message role (assistant/user/system).
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict

from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import TRANSCRIPT_RECORD_I18N

logger = getLogger(__name__)


@register_node
class TranscriptRecordNode(BaseNode):
    """Record a state field's content to short-term memory transcript.

    Generalised: Configurable source field and message role.
    """

    node_type = "transcript_record"
    label = "Transcript Record"
    description = "Records a state field's content to the short-term memory transcript with a configurable message role (assistant/user/system). Use for explicit transcript control when the built-in recording in PostModel is insufficient."
    category = "memory"
    icon = "file-text"
    color = "#ec4899"
    i18n = TRANSCRIPT_RECORD_I18N
    state_usage = NodeStateUsage(
        reads=[],
        writes=[],  # writes to external memory, not state
        config_dynamic_reads={"source_field": "last_output"},
    )

    parameters = [
        NodeParameter(
            name="max_length",
            label="Max Content Length",
            type="number",
            default=5000,
            min=100,
            max=50000,
            description="Maximum characters to record from the output.",
            group="behavior",
        ),
        NodeParameter(
            name="source_field",
            label="Source State Field",
            type="string",
            default="last_output",
            description="State field whose content is recorded to the transcript.",
            group="state_fields",
        ),
        NodeParameter(
            name="role",
            label="Message Role",
            type="select",
            default="assistant",
            description="Role label for the transcript entry.",
            options=[
                {"label": "Assistant", "value": "assistant"},
                {"label": "User", "value": "user"},
                {"label": "System", "value": "system"},
            ],
            group="behavior",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not context.memory_manager:
            return {}

        source_field = config.get("source_field", "last_output")
        content = state.get(source_field, "") or ""
        max_length = int(config.get("max_length", 5000))
        role = config.get("role", "assistant")

        if content:
            try:
                context.memory_manager.record_message(role, content[:max_length])
            except Exception:
                logger.debug(f"[{context.session_id}] transcript_record: failed")

        return {}
