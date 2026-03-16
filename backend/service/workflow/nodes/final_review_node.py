"""
Final Review Node — comprehensive review of all list item results.

Uses structured output to produce a reliable, actionable quality
assessment. The Pydantic-validated FinalReviewOutput includes
overall quality, a completion summary, issues found, and
recommendations.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from service.prompt.sections import AutonomousPrompts
from service.workflow.nodes._helpers import format_list_items
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import FINAL_REVIEW_I18N

logger = getLogger(__name__)


@register_node
class FinalReviewNode(BaseNode):
    """Final comprehensive review of all list item results.

    Uses structured output to produce a reliable, actionable quality
    assessment. The Pydantic-validated FinalReviewOutput includes
    overall quality, a completion summary, issues found, and
    recommendations — all of which are formatted into a rich string
    for downstream consumption by FinalAnswerNode.

    Generalised: Configurable list field, output field, quality levels,
    and per-item character limits.
    """

    node_type = "final_review"
    label = "Final Review"
    description = "Comprehensive review of all completed list item results using Pydantic-validated structured output. Evaluates overall quality, summarizes accomplishments, identifies issues, and provides actionable recommendations. Stores structured review for use by the final answer synthesis."
    category = "task"
    icon = "badge-check"
    color = "#ef4444"
    i18n = FINAL_REVIEW_I18N
    state_usage = NodeStateUsage(
        reads=["input", "context_budget"],
        writes=["messages", "last_output", "current_step", "metadata"],
        config_dynamic_reads={"list_field": "todos"},
        config_dynamic_writes={"output_field": "review_feedback"},
    )

    from service.workflow.nodes.structured_output import (
        FinalReviewOutput, build_frontend_schema as _build_schema,
    )
    structured_output_schema = _build_schema(
        FinalReviewOutput,
        description="Structured quality assessment of all completed work.",
        dynamic_fields={
            "overall_quality": "Must be one of the configured Quality Levels (e.g. excellent, good, needs_improvement, poor)",
        },
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default=AutonomousPrompts.final_review(),
            description="Prompt for the final review of all work.",
            group="prompt",
        ),
        NodeParameter(
            name="list_field",
            label="List State Field",
            type="string",
            default="todos",
            description="State field containing the list to review.",
            group="state_fields",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="review_feedback",
            description="State field to store the formatted review output.",
            group="output",
        ),
        NodeParameter(
            name="quality_levels",
            label="Quality Levels (JSON)",
            type="json",
            default='["excellent", "good", "needs_improvement", "poor"]',
            description=(
                "Allowed values for the overall_quality assessment. "
                'Example: ["excellent", "good", "needs_improvement", "poor"]'
            ),
            group="behavior",
        ),
        NodeParameter(
            name="max_item_chars",
            label="Max Chars per Item",
            type="number",
            default=2000,
            min=100,
            max=50000,
            description="Maximum characters per list item result in the prompt.",
            group="behavior",
        ),
        NodeParameter(
            name="compact_item_chars",
            label="Compact Chars per Item",
            type="number",
            default=500,
            min=100,
            max=10000,
            description="Maximum characters per item when context budget is tight.",
            group="behavior",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        list_field = config.get("list_field", "todos")
        output_field = config.get("output_field", "review_feedback")
        todos = state.get(list_field, [])
        input_text = state.get("input", "")
        template = config.get("prompt_template", AutonomousPrompts.final_review())

        max_chars = int(config.get("max_item_chars", 2000))
        compact_chars = int(config.get("compact_item_chars", 500))

        # Parse quality levels
        ql_raw = config.get("quality_levels", '["excellent", "good", "needs_improvement", "poor"]')
        if isinstance(ql_raw, str):
            try:
                quality_levels = json.loads(ql_raw)
            except (json.JSONDecodeError, TypeError):
                quality_levels = ["excellent", "good", "needs_improvement", "poor"]
        else:
            quality_levels = ql_raw
        if not isinstance(quality_levels, list) or not quality_levels:
            quality_levels = ["excellent", "good", "needs_improvement", "poor"]

        try:
            from service.workflow.nodes.structured_output import FinalReviewOutput

            budget = state.get("context_budget") or {}
            compact = budget.get("status") in ("block", "overflow")
            effective_chars = compact_chars if compact else max_chars

            todo_results = format_list_items(todos, effective_chars)

            try:
                prompt = template.format(input=input_text, todo_results=todo_results)
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]

            # ── Structured output: schema-validated review ──
            parsed, fallback = await context.resilient_structured_invoke(
                messages,
                "final_review",
                FinalReviewOutput,
                allowed_values={"overall_quality": quality_levels},
                coerce_field="overall_quality",
                coerce_values=quality_levels,
                coerce_default=quality_levels[1] if len(quality_levels) > 1 else quality_levels[0],
                extra_instruction=(
                    f"The 'overall_quality' field MUST be exactly one of: "
                    f"{', '.join(quality_levels)}. "
                    f"The 'completed_summary' field should describe what was accomplished. "
                    f"Include any issues in the 'issues_found' array. "
                    f"Provide actionable 'recommendations' for the final answer."
                ),
            )

            # Format structured review into a rich, downstream-compatible string
            formatted_review = (
                f"## Quality Assessment: {parsed.overall_quality.upper()}\n\n"
                f"### Summary\n{parsed.completed_summary}\n"
            )
            if parsed.issues_found:
                formatted_review += "\n### Issues Found\n"
                for issue in parsed.issues_found:
                    formatted_review += f"- {issue}\n"
            if parsed.recommendations:
                formatted_review += f"\n### Recommendations\n{parsed.recommendations}\n"

            logger.info(
                f"[{context.session_id}] final_review: "
                f"quality={parsed.overall_quality}, "
                f"issues={len(parsed.issues_found or [])}"
            )

            result: Dict[str, Any] = {
                output_field: formatted_review,
                "messages": [HumanMessage(content=formatted_review[:2000])],
                "last_output": formatted_review,
                "current_step": "final_review_complete",
                "metadata": {
                    **state.get("metadata", {}),
                    "review_quality": parsed.overall_quality,
                    "review_issues_count": len(parsed.issues_found or []),
                },
            }
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] final_review error: {e}")
            return {
                output_field: f"Review failed: {str(e)}",
                "last_output": f"Review failed: {str(e)}",
                "current_step": "final_review_failed",
            }
