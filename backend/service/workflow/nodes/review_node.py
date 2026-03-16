"""
Review Node — self-routing quality gate with structured verdict parsing.

Conditional, self-routing node — like Classify, the user configures a
list of **verdicts** (e.g. ``approved``, ``retry``) and each verdict
becomes a named output port. The model reviews an answer and produces
a structured JSON verdict + feedback.
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage

from service.langgraph.state import CompletionSignal
from service.prompt.sections import AutonomousPrompts
from service.workflow.nodes._helpers import parse_categories, safe_format
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import REVIEW_I18N

logger = getLogger(__name__)


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

        verdicts = parse_categories(
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
        verdicts = parse_categories(
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
        verdicts = parse_categories(
            config.get("verdicts", "approved, retry"),
            fallback=["approved", "retry"],
        )
        ports = [
            OutputPort(id=v, label=v.capitalize(), description=f"Route for '{v}'")
            for v in verdicts
        ]
        ports.append(OutputPort(id="end", label="End", description="Error / early termination"))
        return ports
