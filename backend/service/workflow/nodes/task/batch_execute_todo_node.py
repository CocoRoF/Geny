"""
Batch Execute TODO Node — execute all pending TODOs in a single LLM call.

For HARD-path tasks where the scope is predictable and TODOs are <=5,
this node batches all pending items into one prompt instead of executing
them individually in a loop.  This reduces LLM calls from N to 1.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage

from service.langgraph.state import TodoItem, TodoStatus
from service.workflow.nodes._helpers import safe_format
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import BATCH_EXECUTE_TODO_I18N

logger = getLogger(__name__)

_DEFAULT_PROMPT = (
    "You are executing a multi-step task plan. "
    "Complete ALL of the following TODO items in order.\n\n"
    "Overall Goal:\n{input}\n\n"
    "TODO Items:\n{todo_list}\n\n"
    "Execute each item thoroughly. For each item, clearly indicate:\n"
    "- Which TODO you are working on\n"
    "- The complete result/implementation\n"
    "Complete ALL items before finishing."
)


def _format_pending_todos(todos: List[dict]) -> str:
    """Format pending TODO items into a numbered list for the prompt."""
    lines: List[str] = []
    for t in todos:
        if t.get("status") in (TodoStatus.PENDING, "pending"):
            lines.append(
                f"[{t.get('id', '?')}] {t.get('title', 'Untitled')}\n"
                f"    Description: {t.get('description', 'No description')}"
            )
    return "\n\n".join(lines) if lines else "(No pending items)"


@register_node
class BatchExecuteTodoNode(BaseNode):
    """Execute all pending TODO items in a single LLM call.

    Unlike ``ExecuteTodoNode`` which runs one item per LLM call in a
    loop, this node batches all pending items into a single prompt.
    Best for HARD-path tasks with <=5 predictable, independent TODOs.
    """

    node_type = "batch_execute_todo"
    label = "Batch Execute TODOs"
    description = (
        "Executes all pending TODO items in a single LLM call. "
        "Reduces N individual LLM calls to 1. Best for HARD-path tasks "
        "with a small number of predictable, independent TODO items."
    )
    category = "task"
    icon = "layers"
    color = "#8b5cf6"
    i18n = BATCH_EXECUTE_TODO_I18N
    state_usage = NodeStateUsage(
        reads=["input"],
        writes=[
            "messages", "last_output", "current_step",
        ],
        config_dynamic_reads={"list_field": "todos"},
        config_dynamic_writes={
            "list_field": "todos",
            "index_field": "current_todo_index",
            "batch_result_field": "batch_execution_result",
            "output_field": "final_answer",
        },
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Batch Prompt",
            type="prompt_template",
            default=_DEFAULT_PROMPT,
            description=(
                "Prompt for batch executing TODO items. "
                "Use {input} for the goal and {todo_list} for formatted items."
            ),
            group="prompt",
        ),
        NodeParameter(
            name="list_field",
            label="List State Field",
            type="string",
            default="todos",
            description="State field containing the TODO list.",
            group="state_fields",
        ),
        NodeParameter(
            name="index_field",
            label="Index State Field",
            type="string",
            default="current_todo_index",
            description="State field tracking the current TODO index.",
            group="state_fields",
        ),
        NodeParameter(
            name="batch_result_field",
            label="Batch Result Field",
            type="string",
            default="batch_execution_result",
            description="State field to store the shared combined batch result.",
            group="state_fields",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="",
            description="Optional state field to store the combined response as the final output.",
            group="output",
        ),
        NodeParameter(
            name="set_complete",
            label="Mark Complete After",
            type="boolean",
            default=False,
            description="Set is_complete=True after successful batch execution.",
            group="output",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        list_field = config.get("list_field", "todos")
        index_field = config.get("index_field", "current_todo_index")
        batch_result_field = config.get(
            "batch_result_field", "batch_execution_result"
        )
        template = config.get("prompt_template", _DEFAULT_PROMPT)
        output_field = config.get("output_field", "")
        set_complete = config.get("set_complete", False)

        todos = state.get(list_field, [])
        input_text = state.get("input", "")

        pending = [t for t in todos if t.get("status") in (TodoStatus.PENDING, "pending")]

        if not pending:
            return {"current_step": "todos_complete"}

        try:
            todo_list_text = _format_pending_todos(todos)

            try:
                prompt = template.format(
                    input=input_text,
                    todo_list=todo_list_text,
                )
            except (KeyError, IndexError):
                prompt = safe_format(template, {
                    "input": input_text,
                    "todo_list": todo_list_text,
                })

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(
                messages, "batch_execute_todo"
            )
            response_text = response.content

            # Mark all pending TODOs as completed
            updated: List[TodoItem] = []
            for t in pending:
                per_item_result = response_text
                if len(pending) > 1:
                    per_item_result = (
                        "Completed in shared batch execution. "
                        f"See '{batch_result_field}' for the combined result."
                    )
                updated.append({
                    **t,
                    "status": TodoStatus.COMPLETED,
                    "result": per_item_result,
                })

            result: Dict[str, Any] = {
                list_field: updated,
                index_field: len(todos),
                batch_result_field: response_text,
                "messages": [response],
                "last_output": response_text,
                "current_step": "batch_execute_complete",
            }
            if output_field:
                result[output_field] = response_text
            if set_complete:
                result["is_complete"] = True
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(
                f"[{context.session_id}] batch_execute_todo error: {e}"
            )
            # Mark all pending as failed
            failed: List[TodoItem] = []
            for t in pending:
                failed.append({
                    **t,
                    "status": TodoStatus.FAILED,
                    "result": f"Error: {e}",
                })
            return {
                list_field: failed,
                index_field: len(todos),
                "last_output": f"Batch execution error: {e}",
                "error": str(e),
                "current_step": "batch_execute_failed",
            }
