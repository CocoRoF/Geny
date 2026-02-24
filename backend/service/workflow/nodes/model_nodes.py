"""
Model Nodes — LLM invocation nodes for workflow graphs.

These nodes call the Claude CLI model with configurable prompts
and handle response parsing. They cover the full spectrum from
generic LLM calls to specialised operations like difficulty
classification or review.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Callable, Dict, List, Literal, Optional

from langchain_core.messages import HumanMessage

from service.langgraph.state import (
    CompletionSignal,
    Difficulty,
    ReviewResult,
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


# ============================================================================
# Generic LLM Call
# ============================================================================


@register_node
class LLMCallNode(BaseNode):
    """Generic LLM invocation with a configurable prompt template.

    The prompt template can reference state fields using ``{field}``
    placeholders that are substituted at runtime (e.g. ``{input}``).
    """

    node_type = "llm_call"
    label = "LLM Call"
    description = "Invoke the language model with a configurable prompt template"
    category = "model"
    icon = "🤖"
    color = "#8b5cf6"

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default="{input}",
            required=True,
            description=(
                "Prompt sent to the model. Use {field_name} for state variable substitution. "
                "Available fields: input, answer, review_feedback, last_output, etc."
            ),
            group="prompt",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="last_output",
            description="State field to store the model response in.",
            group="output",
        ),
        NodeParameter(
            name="set_complete",
            label="Mark Complete After",
            type="boolean",
            default=False,
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
        output_field = config.get("output_field", "last_output")
        set_complete = config.get("set_complete", False)

        # Substitute state fields into template
        try:
            prompt = template.format(**{
                k: (v if isinstance(v, str) else str(v) if v is not None else "")
                for k, v in state.items()
            })
        except KeyError:
            prompt = template  # fallback: use raw template

        messages = [HumanMessage(content=prompt)]
        response, fallback = await context.resilient_invoke(messages, "llm_call")

        result: Dict[str, Any] = {
            output_field: response.content,
            "messages": [response],
            "last_output": response.content,
            "current_step": "llm_call_complete",
        }
        if set_complete:
            result["is_complete"] = True
        result.update(fallback)
        return result


# ============================================================================
# Classify Difficulty
# ============================================================================


@register_node
class ClassifyDifficultyNode(BaseNode):
    """Classify task difficulty as easy / medium / hard.

    Conditional node — routes to one of four output ports.
    """

    node_type = "classify_difficulty"
    label = "Classify Difficulty"
    description = "Classify the input task difficulty (easy/medium/hard)"
    category = "model"
    icon = "🔀"
    color = "#3b82f6"

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Classification Prompt",
            type="prompt_template",
            default=AutonomousPrompts.classify_difficulty(),
            description="Prompt template for difficulty classification.",
            group="prompt",
        ),
    ]

    output_ports = [
        OutputPort(id="easy", label="Easy", description="Simple, direct tasks"),
        OutputPort(id="medium", label="Medium", description="Moderate complexity"),
        OutputPort(id="hard", label="Hard", description="Complex, multi-step tasks"),
        OutputPort(id="end", label="End", description="Error / early termination"),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_text = state.get("input", "")
        template = config.get("prompt_template", AutonomousPrompts.classify_difficulty())

        try:
            prompt = template.format(input=input_text)
        except (KeyError, IndexError):
            prompt = template

        messages = [HumanMessage(content=prompt)]

        try:
            response, fallback = await context.resilient_invoke(
                messages, "classify_difficulty"
            )
            response_text = response.content.strip().lower()

            if "easy" in response_text:
                difficulty = Difficulty.EASY
            elif "medium" in response_text:
                difficulty = Difficulty.MEDIUM
            elif "hard" in response_text:
                difficulty = Difficulty.HARD
            else:
                difficulty = Difficulty.MEDIUM

            logger.info(
                f"[{context.session_id}] classify_difficulty: {difficulty.value}"
            )

            result: Dict[str, Any] = {
                "difficulty": difficulty,
                "current_step": "difficulty_classified",
                "messages": [HumanMessage(content=input_text)],
                "last_output": response.content,
            }
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] classify_difficulty error: {e}")
            return {"error": str(e), "is_complete": True}

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        def _route(state: Dict[str, Any]) -> str:
            if state.get("error"):
                return "end"
            difficulty = state.get("difficulty")
            if difficulty == Difficulty.EASY:
                return "easy"
            elif difficulty == Difficulty.MEDIUM:
                return "medium"
            return "hard"
        return _route


# ============================================================================
# Direct Answer (Easy path)
# ============================================================================


@register_node
class DirectAnswerNode(BaseNode):
    """Generate a direct answer for easy tasks. Single-shot, no review."""

    node_type = "direct_answer"
    label = "Direct Answer"
    description = "Generate a direct answer for easy/simple tasks"
    category = "model"
    icon = "⚡"
    color = "#10b981"

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Prompt Template",
            type="prompt_template",
            default="{input}",
            description="Prompt template. {input} is the user request.",
            group="prompt",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_text = state.get("input", "")
        template = config.get("prompt_template", "{input}")

        try:
            prompt = template.format(input=input_text)
        except (KeyError, IndexError):
            prompt = input_text

        messages = [HumanMessage(content=prompt)]

        try:
            response, fallback = await context.resilient_invoke(
                messages, "direct_answer"
            )
            answer = response.content
            result: Dict[str, Any] = {
                "answer": answer,
                "final_answer": answer,
                "messages": [response],
                "last_output": answer,
                "current_step": "direct_answer_complete",
                "is_complete": True,
            }
            result.update(fallback)
            return result
        except Exception as e:
            logger.exception(f"[{context.session_id}] direct_answer error: {e}")
            return {"error": str(e), "is_complete": True}


# ============================================================================
# Answer (Medium path)
# ============================================================================


@register_node
class AnswerNode(BaseNode):
    """Generate an answer for medium-complexity tasks.

    Incorporates review feedback on retries.
    """

    node_type = "answer"
    label = "Answer"
    description = "Generate an answer with optional review feedback integration"
    category = "model"
    icon = "💬"
    color = "#f59e0b"

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
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_text = state.get("input", "")
        review_count = state.get("review_count", 0)
        previous_feedback = state.get("review_feedback")

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
                try:
                    prompt = template.format(input=input_text)
                except (KeyError, IndexError):
                    prompt = input_text

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(messages, "answer")
            answer = response.content

            result: Dict[str, Any] = {
                "answer": answer,
                "messages": [response],
                "last_output": answer,
                "current_step": "answer_generated",
            }
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] answer error: {e}")
            return {"error": str(e), "is_complete": True}


# ============================================================================
# Review (Medium path)
# ============================================================================


@register_node
class ReviewNode(BaseNode):
    """Review a generated answer and emit approved/rejected verdict.

    Conditional node — outputs to approved / retry / end.
    """

    node_type = "review"
    label = "Review"
    description = "Quality review of a generated answer"
    category = "model"
    icon = "📋"
    color = "#f59e0b"

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Review Prompt",
            type="prompt_template",
            default=AutonomousPrompts.review(),
            description="Prompt template for the quality review.",
            group="prompt",
        ),
        NodeParameter(
            name="max_retries",
            label="Max Review Retries",
            type="number",
            default=3,
            min=1,
            max=10,
            description="Force approval after this many retries.",
            group="behavior",
        ),
    ]

    output_ports = [
        OutputPort(id="approved", label="Approved", description="Answer passed review"),
        OutputPort(id="retry", label="Retry", description="Answer needs improvement"),
        OutputPort(id="end", label="End", description="Completed or error"),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        review_count = state.get("review_count", 0) + 1
        max_retries = int(config.get("max_retries", 3))

        try:
            input_text = state.get("input", "")
            answer = state.get("answer", "")
            template = config.get("prompt_template", AutonomousPrompts.review())

            try:
                prompt = template.format(question=input_text, answer=answer)
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(messages, "review")
            review_text = response.content

            review_result = ReviewResult.APPROVED
            feedback = ""

            if "VERDICT:" in review_text:
                lines = review_text.split("\n")
                for line in lines:
                    if line.startswith("VERDICT:"):
                        verdict = line.replace("VERDICT:", "").strip().lower()
                        if "rejected" in verdict:
                            review_result = ReviewResult.REJECTED
                    elif line.startswith("FEEDBACK:"):
                        feedback = line.replace("FEEDBACK:", "").strip()
                        idx = lines.index(line)
                        feedback = "\n".join([feedback] + lines[idx + 1:])
                        break
            else:
                feedback = review_text

            is_complete = False
            if review_result == ReviewResult.REJECTED and review_count >= max_retries:
                logger.warning(
                    f"[{context.session_id}] review: max retries ({max_retries}), forcing approval"
                )
                review_result = ReviewResult.APPROVED
                is_complete = True
            elif review_result == ReviewResult.APPROVED:
                is_complete = True

            result: Dict[str, Any] = {
                "review_result": review_result,
                "review_feedback": feedback,
                "review_count": review_count,
                "messages": [response],
                "last_output": review_text,
                "current_step": "review_complete",
            }
            if is_complete:
                result["final_answer"] = answer
                result["is_complete"] = True
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] review error: {e}")
            return {"error": str(e), "is_complete": True}

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        def _route(state: Dict[str, Any]) -> str:
            if state.get("is_complete") or state.get("error"):
                return "end"
            signal = state.get("completion_signal")
            if signal in (CompletionSignal.COMPLETE.value, CompletionSignal.BLOCKED.value):
                return "approved"
            review_result = state.get("review_result")
            if review_result == ReviewResult.APPROVED:
                return "approved"
            return "retry"
        return _route
