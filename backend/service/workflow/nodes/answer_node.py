"""
Answer Node — answer generation with optional review feedback integration.

Works in any review-retry loop: on the first pass uses the primary
prompt; on retry, automatically switches to the retry template with
feedback context. Budget-aware prompt compaction when context window is tight.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from service.prompt.sections import AutonomousPrompts
from service.workflow.nodes._helpers import safe_format
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import ANSWER_I18N

logger = getLogger(__name__)


@register_node
class AnswerNode(BaseNode):
    """Generate an answer with optional review feedback integration.

    Generalised: Configurable feedback/count fields and output
    targets. Works in any review-retry loop, not just the medium path.
    """

    node_type = "answer"
    label = "Answer"
    description = "Generates an answer with optional review feedback integration for iterative improvement. On the first pass, uses the primary prompt; on retry, automatically switches to the retry template with feedback context. Budget-aware prompt compaction when context window is tight."
    category = "model"
    i18n = ANSWER_I18N
    icon = "message-circle"
    color = "#f59e0b"
    state_usage = NodeStateUsage(
        reads=["input", "context_budget"],
        writes=["messages", "last_output", "current_step", "answer"],
        config_dynamic_reads={
            "feedback_field": "review_feedback",
            "count_field": "review_count",
        },
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default="{input}",
            description="Prompt for the initial answer.",
            group="prompt",
        ),
        NodeParameter(
            name="retry_template",
            label="Retry Prompt Template",
            type="prompt_template",
            default=AutonomousPrompts.retry_with_feedback(),
            description="Prompt template when retrying after review rejection.",
            group="prompt",
        ),
        NodeParameter(
            name="feedback_field",
            label="Feedback State Field",
            type="string",
            default="review_feedback",
            description="State field containing review feedback.",
            group="state_fields",
        ),
        NodeParameter(
            name="count_field",
            label="Review Count State Field",
            type="string",
            default="review_count",
            description="State field tracking the number of review cycles.",
            group="state_fields",
        ),
        NodeParameter(
            name="output_fields",
            label="Output Fields (JSON)",
            type="json",
            default='["answer"]',
            description="State fields to store the response in.",
            group="output",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_text = state.get("input", "")
        feedback_field = config.get("feedback_field", "review_feedback")
        count_field = config.get("count_field", "review_count")
        review_count = state.get(count_field, 0)
        previous_feedback = state.get(feedback_field)

        # Parse output fields
        of_raw = config.get("output_fields", '["answer"]')
        if isinstance(of_raw, str):
            try:
                output_fields = json.loads(of_raw)
            except (json.JSONDecodeError, TypeError):
                output_fields = ["answer"]
        else:
            output_fields = of_raw
        if not isinstance(output_fields, list):
            output_fields = ["answer"]

        try:
            if previous_feedback and review_count > 0:
                budget = state.get("context_budget") or {}
                if budget.get("status") in ("block", "overflow"):
                    previous_feedback = previous_feedback[:500] + "... (truncated)"

                retry_template = config.get(
                    "retry_template", AutonomousPrompts.retry_with_feedback()
                )
                try:
                    prompt = retry_template.format(
                        previous_feedback=previous_feedback,
                        input_text=input_text,
                    )
                except (KeyError, IndexError):
                    prompt = input_text
            else:
                template = config.get("prompt_template", "{input}")
                prompt = safe_format(template, state)

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(messages, "answer")
            answer = response.content

            result: Dict[str, Any] = {
                "messages": [response],
                "last_output": answer,
                "current_step": "answer_generated",
            }
            for f in output_fields:
                result[f] = answer
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] answer error: {e}")
            return {"error": str(e), "is_complete": True}
