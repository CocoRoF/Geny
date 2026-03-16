"""
Direct Answer Node — single-shot answer for easy tasks.

Generates a direct answer without review. Best for simple tasks
that need no quality checking.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from service.workflow.nodes._helpers import safe_format
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import DIRECT_ANSWER_I18N

logger = getLogger(__name__)


@register_node
class DirectAnswerNode(BaseNode):
    """Generate a direct answer for easy tasks. Single-shot, no review.

    Generalised: Configurable output fields and completion behaviour.
    Can serve as a single-shot answer generator for any simple task.
    """

    node_type = "direct_answer"
    label = "Direct Answer"
    description = "Generates a single-shot direct answer without review. Best for easy tasks that need no quality checking. Writes the response to configurable output fields and can mark the workflow as complete."
    category = "model"
    icon = "zap"
    color = "#10b981"
    i18n = DIRECT_ANSWER_I18N
    state_usage = NodeStateUsage(
        reads=["input", "messages"],
        writes=["messages", "last_output", "current_step", "answer", "final_answer", "is_complete"],
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default="{input}",
            description="Prompt template. Use {field_name} for state substitution.",
            group="prompt",
        ),
        NodeParameter(
            name="output_fields",
            label="Output Fields (JSON)",
            type="json",
            default='["answer", "final_answer"]',
            description=(
                "State fields to store the response in. "
                'Example: ["answer", "final_answer", "summary"]'
            ),
            group="output",
        ),
        NodeParameter(
            name="mark_complete",
            label="Mark Complete",
            type="boolean",
            default=True,
            description="Set is_complete=True after execution.",
            group="output",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        template = config.get("prompt_template", "{input}")
        mark_complete = config.get("mark_complete", True)

        # Parse output fields
        of_raw = config.get("output_fields", '["answer", "final_answer"]')
        if isinstance(of_raw, str):
            try:
                output_fields = json.loads(of_raw)
            except (json.JSONDecodeError, TypeError):
                output_fields = ["answer", "final_answer"]
        else:
            output_fields = of_raw
        if not isinstance(output_fields, list):
            output_fields = ["answer", "final_answer"]

        prompt = safe_format(template, state)
        messages = [HumanMessage(content=prompt)]

        try:
            response, fallback = await context.resilient_invoke(
                messages, "direct_answer"
            )
            answer = response.content

            result: Dict[str, Any] = {
                "messages": [response],
                "last_output": answer,
                "current_step": "direct_answer_complete",
            }
            for f in output_fields:
                result[f] = answer
            if mark_complete:
                result["is_complete"] = True
            result.update(fallback)
            return result
        except Exception as e:
            logger.exception(f"[{context.session_id}] direct_answer error: {e}")
            return {"error": str(e), "is_complete": True}
