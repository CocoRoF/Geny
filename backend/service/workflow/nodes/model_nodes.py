"""
Model Nodes — LLM invocation nodes for workflow graphs.

These nodes call the Claude CLI model with configurable prompts
and handle response parsing. They cover the full spectrum from
generic LLM calls to specialised operations like difficulty
classification or review.

Generalisation design:
    Every model node exposes powerful parameters so that users
    can replicate most specialisations via configuration alone.
    Nodes with irreplaceable core logic (structured parsing,
    conditional routing) keep that logic internally while still
    making surrounding behaviour configurable.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage

from service.langgraph.state import (
    CompletionSignal,
    Difficulty,
)
from service.prompt.sections import AutonomousPrompts
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    get_node_registry,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import (
    LLM_CALL_I18N,
    CLASSIFY_I18N,
    DIRECT_ANSWER_I18N,
    ANSWER_I18N,
    REVIEW_I18N,
)

logger = getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================


def _safe_format(template: str, state: Dict[str, Any]) -> str:
    """Substitute state fields into a prompt template, safely."""
    try:
        return template.format(**{
            k: (v if isinstance(v, str) else str(v) if v is not None else "")
            for k, v in state.items()
        })
    except (KeyError, IndexError):
        return template


def _parse_categories(
    raw: Any,
    fallback: Optional[List[str]] = None,
) -> List[str]:
    """Parse categories from flexible user input.

    Accepts:
      - JSON array:       '["easy", "medium", "hard"]'
      - Single-quoted:    "['easy']"
      - Comma-separated:  'easy, medium, hard'
      - Single value:     'easy'
      - Python list:      ['easy', 'medium', 'hard']  (already parsed)

    Returns a list of lowercase stripped category strings,
    falling back to *fallback* when parsing yields nothing.
    """
    _fallback = fallback or ["easy", "medium", "hard"]

    if isinstance(raw, list):
        cats = [str(c).strip().lower() for c in raw if str(c).strip()]
        return cats if cats else _fallback

    if not isinstance(raw, str) or not raw.strip():
        return _fallback

    text = raw.strip()

    # Try JSON first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            cats = [str(c).strip().lower() for c in parsed if str(c).strip()]
            return cats if cats else _fallback
        if isinstance(parsed, dict):
            return _fallback  # JSON object is not a valid category list
    except (json.JSONDecodeError, TypeError):
        pass

    # Try single-quoted JSON  e.g.  ['easy', 'medium']
    if text.startswith("[") and text.endswith("]"):
        try:
            fixed = text.replace("'", '"')
            parsed = json.loads(fixed)
            if isinstance(parsed, list):
                cats = [str(c).strip().lower() for c in parsed if str(c).strip()]
                return cats if cats else _fallback
        except (json.JSONDecodeError, TypeError):
            pass

    # Comma-separated:  "easy, medium, hard"  or  "easy"
    parts = [p.strip().lower() for p in text.split(",") if p.strip()]
    return parts if parts else _fallback


# ============================================================================
# Generic LLM Call
# ============================================================================


@register_node
class LLMCallNode(BaseNode):
    """Generic LLM invocation with a configurable prompt template.

    This is the most powerful general-purpose model node. Through its
    parameters you can replicate the behaviour of most specialised model
    nodes (DirectAnswer, Answer, FinalReview, FinalAnswer, etc.).

    Key capabilities:
        - **Prompt Template** with ``{field}`` state substitution.
        - **Conditional Prompt** — switch to an alternative prompt when
          a state field meets a condition (enables retry/feedback loops).
        - **Multiple Output Mappings** — store the response in several
          state fields at once.
        - **Completion flag** — optionally mark the workflow as complete.
    """

    node_type = "llm_call"
    label = "LLM Call"
    description = "Universal LLM invocation node. Sends a configurable prompt template to the model with {field} state variable substitution. Supports conditional prompt switching, multiple output field mappings, and an optional completion flag. Can replicate most specialized model nodes through configuration alone."
    category = "model"
    icon = "bot"
    color = "#8b5cf6"
    i18n = LLM_CALL_I18N
    state_usage = NodeStateUsage(
        reads=["input", "messages"],
        writes=["messages", "last_output", "current_step"],
        config_dynamic_reads={"conditional_field": ""},
        config_dynamic_writes={"output_field": "last_output"},
    )

    parameters = [
        # ── Prompt ──
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
            name="conditional_field",
            label="Conditional Prompt Field",
            type="string",
            default="",
            description=(
                "State field to check for prompt switching. "
                "When set and the condition is met, the Alternative Prompt is used instead."
            ),
            group="prompt",
        ),
        NodeParameter(
            name="conditional_check",
            label="Conditional Check",
            type="select",
            default="truthy",
            description="How to evaluate the conditional field.",
            options=[
                {"label": "Truthy (non-empty / non-zero)", "value": "truthy"},
                {"label": "Falsy (empty / zero / None)", "value": "falsy"},
                {"label": "Greater than zero", "value": "gt_zero"},
            ],
            group="prompt",
        ),
        NodeParameter(
            name="alternative_prompt",
            label="Alternative Prompt",
            type="prompt_template",
            default="",
            description="Prompt used when the conditional field check passes.",
            group="prompt",
        ),
        # ── Output ──
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="last_output",
            description="Primary state field to store the model response in.",
            group="output",
        ),
        NodeParameter(
            name="output_mappings",
            label="Additional Output Mappings (JSON)",
            type="json",
            default="{}",
            description=(
                "Additional state fields to set from the response. "
                'Keys are field names, values are true to copy the response. '
                'Example: {"answer": true, "final_answer": true}'
            ),
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

        # ── Conditional prompt switching ──
        cond_field = config.get("conditional_field", "")
        alt_prompt = config.get("alternative_prompt", "")
        if cond_field and alt_prompt:
            cond_check = config.get("conditional_check", "truthy")
            field_val = state.get(cond_field)
            use_alt = False
            if cond_check == "truthy":
                use_alt = bool(field_val)
            elif cond_check == "falsy":
                use_alt = not bool(field_val)
            elif cond_check == "gt_zero":
                try:
                    use_alt = (int(field_val or 0) > 0)
                except (TypeError, ValueError):
                    use_alt = False
            if use_alt:
                template = alt_prompt

        prompt = _safe_format(template, state)
        messages = [HumanMessage(content=prompt)]
        response, fallback = await context.resilient_invoke(messages, "llm_call")

        result: Dict[str, Any] = {
            output_field: response.content,
            "messages": [response],
            "last_output": response.content,
            "current_step": "llm_call_complete",
        }

        # ── Additional output mappings ──
        raw_mappings = config.get("output_mappings", "{}")
        if isinstance(raw_mappings, str):
            try:
                mappings = json.loads(raw_mappings)
            except (json.JSONDecodeError, TypeError):
                mappings = {}
        else:
            mappings = raw_mappings
        if isinstance(mappings, dict):
            for field_name, flag in mappings.items():
                if flag:
                    result[field_name] = response.content

        if set_complete:
            result["is_complete"] = True
        result.update(fallback)
        return result


# ============================================================================
# Classify Difficulty
# ============================================================================


@register_node
class ClassifyNode(BaseNode):
    """General-purpose LLM classification with port-based routing.

    Conditional node — classifies input into configurable categories
    via LLM analysis, then routes execution directly through named
    output ports.  Each configured category becomes a port.

    Fully general: While the defaults use easy/medium/hard for
    backward compatibility, users can define arbitrary categories
    (e.g. low/medium/high/critical, positive/negative/neutral, etc.)
    and choose any state field to store the classification result.

    This node is self-routing — connect its output ports directly
    to downstream nodes.  No separate ConditionalRouter is needed.
    """

    node_type = "classify"
    label = "Classify"
    description = "General-purpose LLM classification node. Sends a configurable prompt to the model, parses the response into one of the configured categories, stores the result in a state field, and routes execution directly through the matching output port. Default categories are easy/medium/hard but fully customizable to any set of labels."
    category = "model"
    icon = "split"
    color = "#3b82f6"
    i18n = CLASSIFY_I18N
    state_usage = NodeStateUsage(
        reads=["input"],
        writes=["current_step", "messages", "last_output"],
        config_dynamic_writes={"output_field": "difficulty"},
    )

    from service.workflow.nodes.structured_output import (
        ClassifyOutput, build_frontend_schema,
    )
    structured_output_schema = build_frontend_schema(
        ClassifyOutput,
        description="LLM classification result with validated category routing.",
        dynamic_fields={
            "classification": "Must be one of the configured Categories (e.g. easy, medium, hard)",
        },
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Classification Prompt",
            type="prompt_template",
            default=AutonomousPrompts.classify_difficulty(),
            description=(
                "Prompt sent to the model for classification. "
                "Use {input} for the user request, {field_name} for other state fields. "
                "The model's response is parsed for category keywords."
            ),
            group="prompt",
        ),
        NodeParameter(
            name="categories",
            label="Categories (JSON)",
            type="json",
            default='["easy", "medium", "hard"]',
            description=(
                "List of category names the LLM should classify into. "
                "Each category becomes an output port. "
                'Example: ["low", "medium", "high", "critical"]'
            ),
            group="routing",            generates_ports=True,        ),
        NodeParameter(
            name="default_category",
            label="Default Category",
            type="string",
            default="medium",
            description="Category to use when the LLM response doesn't match any known category.",
            group="routing",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="difficulty",
            description="State field to store the classification result in.",
            group="output",
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
        output_field = config.get("output_field", "difficulty")

        # Parse categories (flexible: comma-separated, JSON array, etc.)
        categories = _parse_categories(
            config.get("categories", "easy, medium, hard")
        )

        default_cat = config.get("default_category", "medium")
        if default_cat not in categories:
            default_cat = categories[1] if len(categories) > 1 else categories[0]

        try:
            from service.workflow.nodes.structured_output import ClassifyOutput

            prompt = _safe_format(template, {**state, "input": input_text})
            messages = [HumanMessage(content=prompt)]

            # ── Structured output: schema-validated classification ──
            parsed, fallback = await context.resilient_structured_invoke(
                messages,
                "classify",
                ClassifyOutput,
                allowed_values={"classification": categories},
                coerce_field="classification",
                coerce_values=categories,
                coerce_default=default_cat,
                extra_instruction=(
                    f"The 'classification' field MUST be exactly one of: "
                    f"{', '.join(categories)}"
                ),
            )
            matched = parsed.classification

            # Backward-compat: also set Difficulty enum if field == "difficulty"
            if output_field == "difficulty":
                try:
                    difficulty_enum = Difficulty(matched)
                    store_value = difficulty_enum
                except ValueError:
                    store_value = matched
            else:
                store_value = matched

            logger.info(
                f"[{context.session_id}] classify: {matched} "
                f"(field={output_field}, confidence={parsed.confidence})"
            )

            result: Dict[str, Any] = {
                output_field: store_value,
                "current_step": "classified",
                "messages": [HumanMessage(content=input_text)],
                "last_output": matched,
            }
            result.update(fallback)
            return result

        except Exception as e:
            logger.exception(f"[{context.session_id}] classify error: {e}")
            return {"error": str(e), "is_complete": True}

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        output_field = config.get("output_field", "difficulty")
        categories = _parse_categories(
            config.get("categories", "easy, medium, hard")
        )

        default_cat = config.get("default_category", "medium")
        if default_cat not in categories:
            default_cat = categories[1] if len(categories) > 1 else categories[0]

        cat_set = {c.lower() for c in categories}

        def _route(state: Dict[str, Any]) -> str:
            if state.get("error"):
                return "end"
            value = state.get(output_field)
            if hasattr(value, "value"):  # Handle enums
                value = value.value
            if isinstance(value, str):
                value = value.strip().lower()
            if value in cat_set:
                return value
            return default_cat

        return _route

    def get_dynamic_output_ports(
        self, config: Dict[str, Any],
    ) -> Optional[List[OutputPort]]:
        """Generate output ports from configured categories."""
        categories = _parse_categories(
            config.get("categories", "easy, medium, hard")
        )
        ports = [
            OutputPort(id=cat, label=cat.capitalize(), description=f"Route for '{cat}'")
            for cat in categories
        ]
        ports.append(OutputPort(id="end", label="End", description="Error / early termination"))
        return ports


# Backward compatibility: old templates/workflows using "classify_difficulty"
# still resolve to the same ClassifyNode instance.
get_node_registry().register_alias("classify_difficulty", "classify")


# ============================================================================
# Direct Answer (Easy path)
# ============================================================================


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

        prompt = _safe_format(template, state)
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


# ============================================================================
# Answer (Medium path)
# ============================================================================


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
                prompt = _safe_format(template, state)

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


# ============================================================================
# Review (Medium path)
# ============================================================================


@register_node
class ReviewNode(BaseNode):
    """Review a generated answer and route by verdict.

    Conditional, self-routing node — like Classify, the user
    configures a list of **verdicts** (e.g. ``approved``, ``retry``)
    and each verdict becomes a named output port.  An extra ``end``
    port is always present for error / early-termination.

    The model is given the original question and the generated
    answer, then its response is parsed as structured JSON using
    ``resilient_structured_invoke`` with a ``ReviewOutput`` Pydantic
    schema.  The validated ``verdict`` field determines the output
    port.  After a configurable *max_retries* the first verdict in
    the list is force-selected (typically *approved*).

    Generalisation design mirrors ``ClassifyNode``:

    * ``verdicts`` parameter with ``generates_ports=True``
    * ``get_dynamic_output_ports()`` computes ports from config
    * ``get_routing_function()`` reads configurable ``output_field``
    * ``default_verdict`` fallback when no keyword matches
    * Pydantic validation + coercion ensures exact verdict matching
    """

    node_type = "review"
    label = "Review"
    description = (
        "Self-routing quality gate that reviews a generated answer via LLM "
        "and routes to a configurable set of verdict ports. "
        "Uses structured JSON output for reliable verdict + feedback parsing. "
        "Each configured verdict becomes an output port. "
        "Forces the first verdict after max retries to prevent infinite loops."
    )
    category = "model"
    icon = "clipboard-check"
    color = "#f59e0b"
    i18n = REVIEW_I18N
    state_usage = NodeStateUsage(
        reads=["input", "error", "is_complete", "completion_signal"],
        writes=["review_feedback", "messages", "last_output", "current_step",
                "final_answer", "is_complete"],
        config_dynamic_reads={
            "answer_field": "answer",
            "count_field": "review_count",
        },
        config_dynamic_writes={
            "output_field": "review_result",
            "count_field": "review_count",
        },
    )

    from service.workflow.nodes.structured_output import (
        ReviewOutput, build_frontend_schema as _build_schema,
    )
    structured_output_schema = _build_schema(
        ReviewOutput,
        description="LLM review result with validated verdict and feedback.",
        dynamic_fields={
            "verdict": "Must be one of the configured Verdicts (e.g. approved, retry)",
        },
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Review Prompt",
            type="prompt_template",
            default=AutonomousPrompts.review(),
            description=(
                "Prompt template for the quality review. "
                "Use {question} and {answer} for substitution."
            ),
            group="prompt",
        ),
        NodeParameter(
            name="verdicts",
            label="Verdicts (JSON)",
            type="json",
            default='["approved", "retry"]',
            description=(
                "List of verdict names the LLM may emit. "
                "Each verdict becomes an output port. "
                'Example: ["approved", "retry"] or ["pass", "minor_fix", "major_rewrite"]'
            ),
            group="routing",
            generates_ports=True,
        ),
        NodeParameter(
            name="default_verdict",
            label="Default Verdict",
            type="string",
            default="retry",
            description="Verdict to use when the model's response doesn't match any configured verdict.",
            group="routing",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="review_result",
            description="State field to store the matched verdict string.",
            group="output",
        ),
        NodeParameter(
            name="max_retries",
            label="Max Review Retries",
            type="number",
            default=3,
            min=1,
            max=10,
            description="Force the first verdict (typically 'approved') after this many review cycles.",
            group="behavior",
        ),
        NodeParameter(
            name="answer_field",
            label="Answer State Field",
            type="string",
            default="answer",
            description="State field containing the answer to review.",
            group="state_fields",
        ),
        NodeParameter(
            name="count_field",
            label="Review Count State Field",
            type="string",
            default="review_count",
            description="State field tracking the review cycle count.",
            group="state_fields",
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
        count_field = config.get("count_field", "review_count")
        review_count = state.get(count_field, 0) + 1
        max_retries = int(config.get("max_retries", 3))

        answer_field = config.get("answer_field", "answer")
        output_field = config.get("output_field", "review_result")

        verdicts = _parse_categories(
            config.get("verdicts", "approved, retry"),
            fallback=["approved", "retry"],
        )
        default_verdict = config.get("default_verdict", "retry")
        if default_verdict not in verdicts:
            default_verdict = verdicts[-1] if verdicts else "retry"

        # The first verdict is the "positive" one (forced on max retries)
        force_verdict = verdicts[0] if verdicts else "approved"

        try:
            from service.workflow.nodes.structured_output import ReviewOutput

            input_text = state.get("input", "")
            answer = state.get(answer_field, "")
            template = config.get("prompt_template", AutonomousPrompts.review())

            try:
                prompt = template.format(question=input_text, answer=answer)
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]

            # ── Structured output: schema-validated verdict + feedback ──
            parsed, fallback = await context.resilient_structured_invoke(
                messages,
                "review",
                ReviewOutput,
                allowed_values={"verdict": verdicts},
                coerce_field="verdict",
                coerce_values=verdicts,
                coerce_default=default_verdict,
                extra_instruction=(
                    f"The 'verdict' field MUST be exactly one of: "
                    f"{', '.join(verdicts)}. "
                    f"The 'feedback' field should contain detailed reasoning."
                ),
            )

            matched_verdict = parsed.verdict
            feedback = parsed.feedback or ""

            is_complete = False
            if matched_verdict != force_verdict and review_count >= max_retries:
                logger.warning(
                    f"[{context.session_id}] review: max retries ({max_retries}), "
                    f"forcing verdict '{force_verdict}'"
                )
                matched_verdict = force_verdict
                is_complete = True
            elif matched_verdict == force_verdict:
                is_complete = True

            logger.info(
                f"[{context.session_id}] review: verdict={matched_verdict} "
                f"(cycle {review_count}, field={output_field})"
            )

            result: Dict[str, Any] = {
                output_field: matched_verdict,
                "review_feedback": feedback,
                count_field: review_count,
                "messages": [HumanMessage(content=f"Review verdict: {matched_verdict}")],
                "last_output": f"VERDICT: {matched_verdict}\nFEEDBACK: {feedback}",
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
        output_field = config.get("output_field", "review_result")
        verdicts = _parse_categories(
            config.get("verdicts", "approved, retry"),
            fallback=["approved", "retry"],
        )
        default_verdict = config.get("default_verdict", "retry")
        if default_verdict not in verdicts:
            default_verdict = verdicts[-1] if verdicts else "retry"

        # First verdict is the "positive" one
        force_verdict = verdicts[0] if verdicts else "approved"
        verdict_set = {v.lower() for v in verdicts}

        def _route(state: Dict[str, Any]) -> str:
            if state.get("error"):
                return "end"
            if state.get("is_complete"):
                # is_complete with matching force_verdict → route to force_verdict port
                value = state.get(output_field)
                if hasattr(value, "value"):
                    value = value.value
                if isinstance(value, str):
                    value = value.strip().lower()
                if value in verdict_set:
                    return value
                return force_verdict
            signal = state.get("completion_signal")
            if signal in (CompletionSignal.COMPLETE.value, CompletionSignal.BLOCKED.value):
                return force_verdict
            value = state.get(output_field)
            if hasattr(value, "value"):
                value = value.value
            if isinstance(value, str):
                value = value.strip().lower()
            if value in verdict_set:
                return value
            return default_verdict
        return _route

    def get_dynamic_output_ports(
        self, config: Dict[str, Any],
    ) -> Optional[List[OutputPort]]:
        """Generate output ports from configured verdicts."""
        verdicts = _parse_categories(
            config.get("verdicts", "approved, retry"),
            fallback=["approved", "retry"],
        )
        ports = [
            OutputPort(id=v, label=v.capitalize(), description=f"Route for '{v}'")
            for v in verdicts
        ]
        ports.append(OutputPort(id="end", label="End", description="Error / early termination"))
        return ports
