"""
Execute TODO Node — execute a single TODO item from the plan.

Builds a prompt with the item's title, description, and budget-aware
context from previously completed items. Marks the item as completed
(or failed on error) and advances the index.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from service.langgraph.state import TodoItem, TodoStatus
from service.prompt.sections import AutonomousPrompts
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import EXECUTE_TODO_I18N

logger = getLogger(__name__)


@register_node
class ExecuteTodoNode(BaseNode):
    """Execute a single TODO item from the plan (hard path).

    Generalised: Configurable list/index fields and context-length
    limits for previous results.
    """

    node_type = "execute_todo"
    label = "Execute TODO"
    description = "Executes a single TODO item from the plan. Builds a prompt with the item's title, description, and budget-aware context from previously completed items. Marks the item as completed (or failed on error) and advances the index. Designed to run in a loop with CheckProgress."
    category = "task"
    icon = "hammer"
    color = "#ef4444"
    i18n = EXECUTE_TODO_I18N
    state_usage = NodeStateUsage(
        reads=["input", "context_budget"],
        writes=["messages", "last_output", "current_step"],
        config_dynamic_reads={
            "list_field": "todos",
            "index_field": "current_todo_index",
        },
        config_dynamic_writes={
            "list_field": "todos",
            "index_field": "current_todo_index",
        },
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default=AutonomousPrompts.execute_todo(),
            description="Prompt for executing a TODO item.",
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
            name="max_context_chars",
            label="Max Context Chars",
            type="number",
            default=500,
            min=50,
            max=10000,
            description="Max characters per previous result in the context window.",
            group="behavior",
        ),
        NodeParameter(
            name="compact_context_chars",
            label="Compact Context Chars",
            type="number",
            default=200,
            min=50,
            max=5000,
            description="Max characters per previous result when context budget is tight.",
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
        index_field = config.get("index_field", "current_todo_index")
        current_index = state.get(index_field, 0)
        todos = state.get(list_field, [])

        try:
            if current_index >= len(todos):
                return {"current_step": "todos_complete"}

            input_text = state.get("input", "")
            todo = todos[current_index]
            template = config.get("prompt_template", AutonomousPrompts.execute_todo())

            # Budget-aware compaction
            max_chars = int(config.get("max_context_chars", 500))
            compact_chars = int(config.get("compact_context_chars", 200))
            budget = state.get("context_budget") or {}
            compact = budget.get("status") in ("block", "overflow")
            effective_chars = compact_chars if compact else max_chars

            previous_results = ""
            for i, t in enumerate(todos):
                if i < current_index and t.get("result"):
                    truncated = t["result"][:effective_chars]
                    previous_results += f"\n[{t['title']}]: {truncated}"
                    if len(t["result"]) > effective_chars:
                        previous_results += "..."
                    previous_results += "\n"
            if not previous_results:
                previous_results = "(No previous items completed)"

            try:
                prompt = template.format(
                    goal=input_text,
                    title=todo["title"],
                    description=todo["description"],
                    previous_results=previous_results,
                )
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(messages, "execute_todo")
            result_text = response.content

            updated_todo: TodoItem = {
                **todo,
                "status": TodoStatus.COMPLETED,
                "result": result_text,
            }

            node_result: Dict[str, Any] = {
                list_field: [updated_todo],
                index_field: current_index + 1,
                "messages": [response],
                "last_output": result_text,
                "current_step": f"todo_{current_index + 1}_complete",
            }
            node_result.update(fallback)
            return node_result

        except Exception as e:
            logger.exception(f"[{context.session_id}] execute_todo error: {e}")
            if current_index < len(todos):
                failed: TodoItem = {
                    **todos[current_index],
                    "status": TodoStatus.FAILED,
                    "result": f"Error: {str(e)}",
                }
                return {
                    list_field: [failed],
                    index_field: current_index + 1,
                    "last_output": f"Error: {str(e)}",
                    "current_step": f"todo_{current_index + 1}_failed",
                }
            return {"error": str(e), "is_complete": True}
