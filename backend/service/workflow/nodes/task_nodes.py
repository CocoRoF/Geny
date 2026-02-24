"""
Task Nodes — TODO management and synthesis nodes.

These cover the hard-path execution: creating TODO lists,
executing individual items, checking progress, and
producing the final synthesised answer.
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

logger = getLogger(__name__)

MAX_TODO_ITEMS = 20


# ============================================================================
# Create Todos
# ============================================================================


@register_node
class CreateTodosNode(BaseNode):
    """Break a complex task into a structured TODO list (hard path)."""

    node_type = "create_todos"
    label = "Create TODOs"
    description = "Break a complex task into a structured TODO list"
    category = "task"
    icon = "📝"
    color = "#ef4444"

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

        try:
            try:
                prompt = template.format(input=input_text)
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(messages, "create_todos")
            response_text = response.content.strip()

            # Parse JSON — handle markdown code block wrappers
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            try:
                todos_raw = json.loads(response_text.strip())
            except json.JSONDecodeError:
                logger.warning(f"[{context.session_id}] create_todos: JSON parse failed, fallback")
                todos_raw = [{"id": 1, "title": "Execute task", "description": input_text}]

            todos: List[TodoItem] = []
            for item in todos_raw:
                todos.append({
                    "id": item.get("id", len(todos) + 1),
                    "title": item.get("title", f"Task {len(todos) + 1}"),
                    "description": item.get("description", ""),
                    "status": TodoStatus.PENDING,
                    "result": None,
                })

            if len(todos) > max_todos:
                todos = todos[:max_todos]

            logger.info(f"[{context.session_id}] create_todos: {len(todos)} items")

            result: Dict[str, Any] = {
                "todos": todos,
                "current_todo_index": 0,
                "messages": [response],
                "last_output": response.content,
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
    """Execute a single TODO item from the plan (hard path)."""

    node_type = "execute_todo"
    label = "Execute TODO"
    description = "Execute a single TODO item with context from previous results"
    category = "task"
    icon = "🔨"
    color = "#ef4444"

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default=AutonomousPrompts.execute_todo(),
            description="Prompt for executing a TODO item.",
            group="prompt",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        current_index = state.get("current_todo_index", 0)
        todos = state.get("todos", [])

        try:
            if current_index >= len(todos):
                return {"current_step": "todos_complete"}

            input_text = state.get("input", "")
            todo = todos[current_index]
            template = config.get("prompt_template", AutonomousPrompts.execute_todo())

            # Budget-aware compaction
            budget = state.get("context_budget") or {}
            compact = budget.get("status") in ("block", "overflow")
            max_chars = 200 if compact else 500

            previous_results = ""
            for i, t in enumerate(todos):
                if i < current_index and t.get("result"):
                    truncated = t["result"][:max_chars]
                    previous_results += f"\n[{t['title']}]: {truncated}"
                    if len(t["result"]) > max_chars:
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
                "todos": [updated_todo],
                "current_todo_index": current_index + 1,
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
                    "todos": [failed],
                    "current_todo_index": current_index + 1,
                    "last_output": f"Error: {str(e)}",
                    "current_step": f"todo_{current_index + 1}_failed",
                }
            return {"error": str(e), "is_complete": True}


# ============================================================================
# Final Review
# ============================================================================


@register_node
class FinalReviewNode(BaseNode):
    """Final comprehensive review of all TODO results (hard path)."""

    node_type = "final_review"
    label = "Final Review"
    description = "Comprehensive review of all completed TODO results"
    category = "task"
    icon = "✅"
    color = "#ef4444"

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default=AutonomousPrompts.final_review(),
            description="Prompt for the final review of all work.",
            group="prompt",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        todos = state.get("todos", [])
        input_text = state.get("input", "")
        template = config.get("prompt_template", AutonomousPrompts.final_review())

        try:
            budget = state.get("context_budget") or {}
            compact = budget.get("status") in ("block", "overflow")
            max_chars = 500 if compact else 2000

            todo_results = ""
            for todo in todos:
                status = todo.get("status", TodoStatus.PENDING)
                result = todo.get("result", "No result")
                if result and len(result) > max_chars:
                    result = result[:max_chars] + "... (truncated)"
                todo_results += f"\n### {todo['title']} [{status}]\n{result}\n"

            try:
                prompt = template.format(input=input_text, todo_results=todo_results)
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(messages, "final_review")

            result: Dict[str, Any] = {
                "review_feedback": response.content,
                "messages": [response],
                "last_output": response.content,
                "current_step": "final_review_complete",
            }
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] final_review error: {e}")
            return {
                "review_feedback": f"Review failed: {str(e)}",
                "last_output": f"Review failed: {str(e)}",
                "current_step": "final_review_failed",
            }


# ============================================================================
# Final Answer
# ============================================================================


@register_node
class FinalAnswerNode(BaseNode):
    """Synthesize a final answer from TODO results and review (hard path)."""

    node_type = "final_answer"
    label = "Final Answer"
    description = "Synthesize the final comprehensive answer from all results"
    category = "task"
    icon = "🎯"
    color = "#ef4444"

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default=AutonomousPrompts.final_answer(),
            description="Prompt for synthesizing the final answer.",
            group="prompt",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        todos = state.get("todos", [])
        input_text = state.get("input", "")
        review_feedback = state.get("review_feedback", "")
        template = config.get("prompt_template", AutonomousPrompts.final_answer())

        try:
            budget = state.get("context_budget") or {}
            compact = budget.get("status") in ("block", "overflow")
            max_chars = 500 if compact else 2000

            todo_results = ""
            for todo in todos:
                status = todo.get("status", TodoStatus.PENDING)
                result = todo.get("result", "No result")
                if result and len(result) > max_chars:
                    result = result[:max_chars] + "... (truncated)"
                todo_results += f"\n### {todo['title']} [{status}]\n{result}\n"

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
                "final_answer": response.content,
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
                "final_answer": f"Task completed with errors.\n\nResults:\n{todo_results}",
                "last_output": f"Error in final_answer: {str(e)}",
                "error": str(e),
                "is_complete": True,
            }
