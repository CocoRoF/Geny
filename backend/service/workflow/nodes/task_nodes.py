"""
Task Nodes — TODO management and synthesis nodes.

These cover the hard-path execution: creating TODO lists,
executing individual items, checking progress, and
producing the final synthesised answer.

Generalisation design:
    Every task node now has configurable state-field names
    (list field, index field, output field, etc.) so the same
    TODO-management pattern can be re-used with custom state
    schemas, not just the built-in ``todos`` / ``current_todo_index``.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage

from service.langgraph.state import (
    CompletionSignal,
    TodoItem,
    TodoStatus,
)
from service.prompt.sections import AutonomousPrompts
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)
from service.workflow.nodes.i18n import (
    CREATE_TODOS_I18N,
    EXECUTE_TODO_I18N,
    FINAL_REVIEW_I18N,
    FINAL_ANSWER_I18N,
)

logger = getLogger(__name__)

MAX_TODO_ITEMS = 20


# ============================================================================
# Helpers
# ============================================================================


def _safe_format(template: str, mapping: Dict[str, Any]) -> str:
    """Substitute placeholders, safely."""
    try:
        return template.format(**{
            k: (v if isinstance(v, str) else str(v) if v is not None else "")
            for k, v in mapping.items()
        })
    except (KeyError, IndexError):
        return template


def _format_list_items(
    items: List[Dict[str, Any]],
    max_chars: int,
) -> str:
    """Format a list of items (e.g. todos) into readable markdown."""
    text = ""
    for item in items:
        status = item.get("status", "pending")
        result = item.get("result", "No result")
        if result and len(result) > max_chars:
            result = result[:max_chars] + "... (truncated)"
        text += f"\n### {item.get('title', 'Item')} [{status}]\n{result}\n"
    return text


# ============================================================================
# Create Todos
# ============================================================================


@register_node
class CreateTodosNode(BaseNode):
    """Break a complex task into a structured TODO list (hard path).

    Generalised: Configurable output field names, max items, and
    JSON parsing behaviour.
    """

    node_type = "create_todos"
    label = "Create TODOs"
    description = "Breaks a complex task into a structured JSON TODO list via LLM. Parses the response as JSON (handling markdown code block wrappers), converts items to TodoItem format with id/title/description/status/result, and caps the count to prevent runaway execution."
    category = "task"
    icon = "📝"
    color = "#ef4444"
    i18n = CREATE_TODOS_I18N

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default=AutonomousPrompts.create_todos(),
            description="Prompt template for generating the TODO list.",
            group="prompt",
        ),
        NodeParameter(
            name="max_todos",
            label="Max TODO Items",
            type="number",
            default=20,
            min=1,
            max=50,
            description="Maximum number of TODO items to prevent runaway execution.",
            group="behavior",
        ),
        NodeParameter(
            name="output_list_field",
            label="Output List Field",
            type="string",
            default="todos",
            description="State field to store the generated list in.",
            group="state_fields",
        ),
        NodeParameter(
            name="output_index_field",
            label="Output Index Field",
            type="string",
            default="current_todo_index",
            description="State field for the current index (reset to 0).",
            group="state_fields",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_text = state.get("input", "")
        template = config.get("prompt_template", AutonomousPrompts.create_todos())
        max_todos = int(config.get("max_todos", MAX_TODO_ITEMS))
        list_field = config.get("output_list_field", "todos")
        index_field = config.get("output_index_field", "current_todo_index")

        try:
            from service.workflow.nodes.structured_output import CreateTodosOutput

            prompt = _safe_format(template, {**state, "input": input_text})
            messages = [HumanMessage(content=prompt)]

            # ── Structured output: schema-validated TODO list ──
            parsed, fallback = await context.resilient_structured_invoke(
                messages,
                "create_todos",
                CreateTodosOutput,
                extra_instruction=(
                    "Each TODO item MUST have 'id' (integer), 'title' (string), "
                    "and 'description' (string). Return between 1 and "
                    f"{max_todos} items."
                ),
            )

            todos: List[TodoItem] = []
            for item in parsed.todos:
                todos.append({
                    "id": item.id,
                    "title": item.title,
                    "description": item.description,
                    "status": TodoStatus.PENDING,
                    "result": None,
                })

            if len(todos) > max_todos:
                todos = todos[:max_todos]

            if not todos:
                logger.warning(
                    f"[{context.session_id}] create_todos: structured output "
                    f"returned empty list, using single-item fallback"
                )
                todos = [{
                    "id": 1,
                    "title": "Execute task",
                    "description": input_text,
                    "status": TodoStatus.PENDING,
                    "result": None,
                }]

            logger.info(f"[{context.session_id}] create_todos: {len(todos)} items")

            result: Dict[str, Any] = {
                list_field: todos,
                index_field: 0,
                "messages": [HumanMessage(content=f"Created {len(todos)} TODO items")],
                "last_output": json.dumps([
                    {"id": t["id"], "title": t["title"]} for t in todos
                ]),
                "current_step": "todos_created",
            }
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] create_todos error: {e}")
            return {"error": str(e), "is_complete": True}


# ============================================================================
# Execute Todo
# ============================================================================


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
    icon = "🔨"
    color = "#ef4444"
    i18n = EXECUTE_TODO_I18N

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


# ============================================================================
# Final Review
# ============================================================================


@register_node
class FinalReviewNode(BaseNode):
    """Final comprehensive review of all list item results.

    Generalised: Configurable list field, output field, and
    per-item character limits.
    """

    node_type = "final_review"
    label = "Final Review"
    description = "Comprehensive review of all completed list item results. Presents every item's title, status, and result text to the LLM with budget-aware character truncation. Stores the review output for use by the final answer synthesis."
    category = "task"
    icon = "✅"
    color = "#ef4444"
    i18n = FINAL_REVIEW_I18N

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
            description="State field to store the review output.",
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
        output_field = config.get("output_field", "review_feedback")
        todos = state.get(list_field, [])
        input_text = state.get("input", "")
        template = config.get("prompt_template", AutonomousPrompts.final_review())

        max_chars = int(config.get("max_item_chars", 2000))
        compact_chars = int(config.get("compact_item_chars", 500))

        try:
            budget = state.get("context_budget") or {}
            compact = budget.get("status") in ("block", "overflow")
            effective_chars = compact_chars if compact else max_chars

            todo_results = _format_list_items(todos, effective_chars)

            try:
                prompt = template.format(input=input_text, todo_results=todo_results)
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(messages, "final_review")

            result: Dict[str, Any] = {
                output_field: response.content,
                "messages": [response],
                "last_output": response.content,
                "current_step": "final_review_complete",
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


# ============================================================================
# Final Answer
# ============================================================================


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
    icon = "🎯"
    color = "#ef4444"
    i18n = FINAL_ANSWER_I18N

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

            todo_results = _format_list_items(todos, effective_chars)

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
