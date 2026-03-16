"""
Final Answer Node — synthesize a final answer from list item results.

Combines all completed list item results and review feedback into
a coherent final response with budget-aware truncation. Marks the
workflow as complete upon success.
"""

from __future__ import annotations

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
from service.workflow.nodes.i18n import FINAL_ANSWER_I18N

logger = getLogger(__name__)


@register_node
class FinalAnswerNode(BaseNode):
    """Synthesize a final answer from list item results and review feedback.

    Generalised: Configurable list field, feedback field, output field,
    and per-item character limits.
    """

    node_type = "final_answer"
    label = "Final Answer"
    description = "Synthesizes the final comprehensive answer from all list item results and review feedback. Combines completed work into a coherent response with budget-aware truncation. Marks the workflow as complete upon success."
    category = "task"
    icon = "target"
    color = "#ef4444"
    i18n = FINAL_ANSWER_I18N
    state_usage = NodeStateUsage(
        reads=["input", "context_budget"],
        writes=["messages", "last_output", "current_step", "is_complete"],
        config_dynamic_reads={
            "list_field": "todos",
            "feedback_field": "review_feedback",
        },
        config_dynamic_writes={"output_field": "final_answer"},
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default=AutonomousPrompts.final_answer(),
            description="Prompt for synthesizing the final answer.",
            group="prompt",
        ),
        NodeParameter(
            name="list_field",
            label="List State Field",
            type="string",
            default="todos",
            description="State field containing the list of results.",
            group="state_fields",
        ),
        NodeParameter(
            name="feedback_field",
            label="Feedback State Field",
            type="string",
            default="review_feedback",
            description="State field containing review feedback to incorporate.",
            group="state_fields",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="final_answer",
            description="State field to store the synthesized answer.",
            group="output",
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
        feedback_field = config.get("feedback_field", "review_feedback")
        output_field = config.get("output_field", "final_answer")

        todos = state.get(list_field, [])
        input_text = state.get("input", "")
        review_feedback = state.get(feedback_field, "") or ""
        template = config.get("prompt_template", AutonomousPrompts.final_answer())

        max_chars = int(config.get("max_item_chars", 2000))
        compact_chars = int(config.get("compact_item_chars", 500))

        try:
            budget = state.get("context_budget") or {}
            compact = budget.get("status") in ("block", "overflow")
            effective_chars = compact_chars if compact else max_chars

            todo_results = format_list_items(todos, effective_chars)

            review_text = review_feedback
            if review_text and len(review_text) > 2000:
                review_text = review_text[:2000] + "... (truncated)"

            try:
                prompt = template.format(
                    input=input_text,
                    todo_results=todo_results,
                    review_feedback=review_text,
                )
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(messages, "final_answer")

            result: Dict[str, Any] = {
                output_field: response.content,
                "messages": [response],
                "last_output": response.content,
                "current_step": "complete",
                "is_complete": True,
            }
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] final_answer error: {e}")
            todo_results = ""
            for t in todos:
                if t.get("result"):
                    todo_results += f"{t['title']}: {t['result']}\n"
            return {
                output_field: f"Task completed with errors.\n\nResults:\n{todo_results}",
                "last_output": f"Error in final_answer: {str(e)}",
                "error": str(e),
                "is_complete": True,
            }
