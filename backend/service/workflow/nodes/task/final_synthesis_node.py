"""
Final Synthesis Node — merged final-review + final-answer in one LLM call.

Replaces the 6-node chain (guard_fr → fin_rev → post_fr → guard_fa →
fin_ans → post_fa) with a single node that reviews completed work and
synthesises the final answer in one prompt.  Saves one LLM call and
four resilience nodes on the hard path.

Budget-aware: truncates per-item results when context is tight.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from service.workflow.nodes._helpers import format_list_items, safe_format
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import FINAL_SYNTHESIS_I18N

logger = getLogger(__name__)

_DEFAULT_PROMPT = (
    "You have completed a complex task through multiple steps.\n\n"
    "Original Request:\n{input}\n\n"
    "Completed Work:\n{todo_results}\n\n"
    "Provide your final comprehensive response:\n"
    "1. Briefly review the quality of completed work — note any gaps "
    "or issues.\n"
    "2. Synthesize all work into a polished, coherent answer that fully "
    "addresses the original request.\n\n"
    "Focus on the synthesized answer. The internal review is for your "
    "own quality assurance and should not dominate the response."
)


@register_node
class FinalSynthesisNode(BaseNode):
    """Review and synthesise completed work in a single LLM call.

    Combines the responsibilities of ``FinalReviewNode`` and
    ``FinalAnswerNode``: the prompt asks the model to self-review the
    completed items and produce the final polished answer.  This
    eliminates one full LLM round-trip on the hard path (typically
    10-20 seconds).

    Reusable: works with any list-of-items state field, configurable
    output field, and budget-aware truncation.
    """

    node_type = "final_synthesis"
    label = "Final Synthesis"
    description = (
        "Merged final-review + final-answer node. Reviews all completed "
        "list item results and synthesizes them into a polished final "
        "answer in a single LLM call. Budget-aware truncation prevents "
        "context overflow. Marks the workflow as complete."
    )
    category = "task"
    icon = "sparkles"
    color = "#ef4444"
    i18n = FINAL_SYNTHESIS_I18N
    state_usage = NodeStateUsage(
        reads=["input", "context_budget", "iteration"],
        writes=[
            "messages", "last_output", "current_step",
            "is_complete", "iteration",
        ],
        config_dynamic_reads={
            "list_field": "todos",
            "combined_result_field": "batch_execution_result",
        },
        config_dynamic_writes={"output_field": "final_answer"},
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Synthesis Prompt",
            type="prompt_template",
            default=_DEFAULT_PROMPT,
            description=(
                "Prompt for reviewing and synthesising the final answer. "
                "Use {input} for the original request and {todo_results} "
                "for completed work."
            ),
            group="prompt",
        ),
        NodeParameter(
            name="list_field",
            label="List State Field",
            type="string",
            default="todos",
            description="State field containing the list of completed items.",
            group="state_fields",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="final_answer",
            description="State field to store the synthesised answer.",
            group="output",
        ),
        NodeParameter(
            name="combined_result_field",
            label="Combined Result Field",
            type="string",
            default="",
            description=(
                "Optional state field containing a shared combined result. "
                "When set, that content is used once instead of expanding each item result."
            ),
            group="state_fields",
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
        NodeParameter(
            name="skip_threshold",
            label="Skip Threshold",
            type="number",
            default=0,
            min=0,
            max=20,
            description=(
                "When the number of completed TODOs is <= this value "
                "and all are completed, skip the synthesis LLM call and "
                "return the last result directly. 0 = always synthesize."
            ),
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
        output_field = config.get("output_field", "final_answer")
        template = config.get("prompt_template", _DEFAULT_PROMPT)
        combined_result_field = config.get("combined_result_field", "")

        todos = state.get(list_field, [])
        input_text = state.get("input", "")

        # --- skip_threshold optimisation ---
        skip_threshold = int(config.get("skip_threshold", 0))
        if skip_threshold > 0 and 0 < len(todos) <= skip_threshold:
            all_done = all(
                (t.get("status") in ("completed", "COMPLETED"))
                for t in todos
            )
            if all_done:
                last = ""
                if combined_result_field:
                    last = state.get(combined_result_field, "") or ""
                if not last:
                    last = state.get("last_output", "") or todos[-1].get("result", "")
                logger.info(
                    "[%s] skip_threshold=%d, %d todos all completed — skipping LLM",
                    context.session_id, skip_threshold, len(todos),
                )
                return {
                    output_field: last,
                    "last_output": last,
                    "current_step": "complete",
                    "is_complete": True,
                    "iteration": state.get("iteration", 0) + 1,
                }

        max_chars = int(config.get("max_item_chars", 2000))
        compact_chars = int(config.get("compact_item_chars", 500))

        try:
            # Budget-aware truncation
            budget = state.get("context_budget") or {}
            compact = budget.get("status") in ("block", "overflow")
            effective_chars = compact_chars if compact else max_chars

            combined_result = None
            if combined_result_field:
                combined_result = state.get(combined_result_field)

            if combined_result:
                combined_text = str(combined_result)
                if len(combined_text) > effective_chars:
                    combined_text = combined_text[:effective_chars] + "... (truncated)"
                todo_results = combined_text
            else:
                todo_results = format_list_items(todos, effective_chars)

            try:
                prompt = template.format(
                    input=input_text,
                    todo_results=todo_results,
                )
            except (KeyError, IndexError):
                prompt = safe_format(template, {
                    "input": input_text,
                    "todo_results": todo_results,
                })

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(
                messages, "final_synthesis"
            )

            result: Dict[str, Any] = {
                output_field: response.content,
                "messages": [response],
                "last_output": response.content,
                "current_step": "complete",
                "is_complete": True,
                "iteration": state.get("iteration", 0) + 1,
            }
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(
                f"[{context.session_id}] final_synthesis error: {e}"
            )
            # Emergency fallback: concatenate raw results
            raw = ""
            for t in todos:
                if t.get("result"):
                    raw += f"{t['title']}: {t['result']}\n"
            return {
                output_field: (
                    f"Task completed with errors.\n\nResults:\n{raw}"
                ),
                "last_output": f"Error in final_synthesis: {e}",
                "error": str(e),
                "is_complete": True,
            }
