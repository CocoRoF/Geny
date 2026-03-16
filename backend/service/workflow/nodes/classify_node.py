"""
Classify Node — general-purpose LLM classification with port-based routing.

Conditional node that classifies input into configurable categories
via LLM analysis, then routes execution directly through named
output ports.  Each configured category becomes a port.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage

from service.langgraph.state import Difficulty
from service.prompt.sections import AutonomousPrompts
from service.workflow.nodes._helpers import safe_format, parse_categories
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    get_node_registry,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import CLASSIFY_I18N

logger = getLogger(__name__)


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
            group="routing",
            generates_ports=True,
        ),
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
        categories = parse_categories(
            config.get("categories", "easy, medium, hard")
        )

        default_cat = config.get("default_category", "medium")
        if default_cat not in categories:
            default_cat = categories[1] if len(categories) > 1 else categories[0]

        try:
            from service.workflow.nodes.structured_output import ClassifyOutput

            prompt = safe_format(template, {**state, "input": input_text})
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
                "messages": [],
                "last_output": matched,
            }
            result.update(fallback)
            return result

        except Exception as e:
            # Classify failure should NOT terminate the graph.
            # Fall back to default category and continue execution.
            logger.warning(
                f"[{context.session_id}] classify: structured parse failed, "
                f"falling back to default='{default_cat}'. Error: {e}"
            )

            # Store default as Difficulty enum if output_field == "difficulty"
            if output_field == "difficulty":
                try:
                    store_value = Difficulty(default_cat)
                except ValueError:
                    store_value = default_cat
            else:
                store_value = default_cat

            return {
                output_field: store_value,
                "current_step": "classified",
                "messages": [],
                "last_output": default_cat,
            }

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        output_field = config.get("output_field", "difficulty")
        categories = parse_categories(
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
        categories = parse_categories(
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
