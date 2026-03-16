"""
LLM Call Node — generic LLM invocation with configurable prompt template.

This is the most powerful general-purpose model node. Through its
parameters you can replicate the behaviour of most specialised model
nodes (DirectAnswer, Answer, FinalReview, FinalAnswer, etc.).
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from service.workflow.nodes._helpers import safe_format
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import LLM_CALL_I18N

logger = getLogger(__name__)


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

        prompt = safe_format(template, state)
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
