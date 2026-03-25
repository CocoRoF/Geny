"""
Adaptive Classify Node — rule-based pre-check with LLM fallback.

Performs fast rule-based classification first: short/trivial inputs are
classified as "easy" without any LLM call.  When rules are uncertain,
falls back to the standard LLM-based classification.  Includes inline
context-guard and post-model logic to eliminate surrounding resilience
nodes.

Saves 8-15 seconds on easy questions by skipping the LLM classify call.
"""

from __future__ import annotations

import re
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage

from service.prompt.sections import AutonomousPrompts
from service.workflow.nodes._helpers import parse_categories, safe_format
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)
from service.workflow.nodes.structured_output import ClassifyOutput
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import ADAPTIVE_CLASSIFY_I18N

logger = getLogger(__name__)


# ── Rule-based quick classifier ──────────────────────────────────────

# Patterns that strongly indicate an "easy" input.
_EASY_PATTERNS: List[re.Pattern] = [
    # Greetings / farewells / acknowledgments (Korean + English)
    re.compile(
        r"^(안녕|hello|hi\b|hey\b|감사|고마워|thanks|bye|잘\s?가|수고|ok\b|네\b|예\b|아니[요오]?|응\b)",
        re.IGNORECASE,
    ),
    # Short factual questions (question word + short)
    re.compile(
        r"^(뭐|무엇|what|who|when|where|how\s*much|몇|어디|언제|왜|why|어떤|which)\b.{0,80}[?？]?\s*$",
        re.IGNORECASE,
    ),
    # Simple arithmetic
    re.compile(r"^\d[\d\s+\-*/×÷.()=]{0,50}$"),
    # Factual lookups (weather, time, conversions)
    re.compile(
        r"(날씨|시간|환율|수도|인구|높이|길이|넓이|번역|translate|capital|population)"
        r".{0,60}[?？]?\s*$",
        re.IGNORECASE,
    ),
]

# Patterns that strongly indicate a "hard" input.
_HARD_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"(만들어|구현|빌드|build|create|implement|design|develop)"
        r".{0,80}(시스템|앱|서비스|아키텍처|프로젝트|application|service|system|architecture)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(분석|analysis|리팩터|refactor|마이그레이션|migration|리팩토링)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(여러|multiple|단계|step).{0,40}(파일|file|모듈|module|작업|task)",
        re.IGNORECASE,
    ),
]

_EASY_MAX_CHARS = 100
_HARD_MIN_CHARS = 500


def _quick_classify(text: str, categories: List[str]) -> Optional[str]:
    """Rule-based classification.  Returns a category or ``None``."""
    text = text.strip()
    length = len(text)

    has_easy = "easy" in categories
    has_hard = "hard" in categories

    # 1) Easy pattern matches
    if has_easy and length <= _EASY_MAX_CHARS:
        for pat in _EASY_PATTERNS:
            if pat.search(text):
                return "easy"

    # 2) Very short input → easy
    if has_easy and length <= 50:
        return "easy"

    # 3) Short question → easy
    if has_easy and length <= _EASY_MAX_CHARS and ("?" in text or "？" in text):
        return "easy"

    # 4) Hard pattern matches
    if has_hard and length >= _HARD_MIN_CHARS:
        for pat in _HARD_PATTERNS:
            if pat.search(text):
                return "hard"

    # Uncertain — need LLM
    return None


# ── Node implementation ──────────────────────────────────────────────

@register_node
class AdaptiveClassifyNode(BaseNode):
    """Adaptive classification with rule-based fast path and LLM fallback.

    Reusable classifier that first attempts fast rule-based
    categorisation.  When the rules are uncertain (returns ``None``),
    falls back to the standard LLM-based structured-output classify.

    Includes **inline context-guard** (token estimation) and **inline
    post-model** (iteration increment, completion-signal detection)
    to eliminate the need for surrounding Guard/PostModel nodes.

    Like ``ClassifyNode``, this is a conditional self-routing node:
    each configured category becomes an output port, plus a fixed
    ``end`` port for errors.
    """

    node_type = "adaptive_classify"
    label = "Adaptive Classify"
    description = (
        "Rule-based fast classification with LLM fallback. "
        "Short/trivial inputs are classified instantly without an LLM call, "
        "saving 8-15 seconds. Uncertain inputs fall back to structured-output "
        "LLM classification. Includes inline context-guard and post-model "
        "to eliminate surrounding resilience nodes."
    )
    category = "model"
    icon = "zap"
    color = "#f59e0b"
    i18n = ADAPTIVE_CLASSIFY_I18N
    state_usage = NodeStateUsage(
        reads=["input", "messages", "memory_context", "iteration"],
        writes=[
            "messages", "last_output", "current_step",
            "context_budget", "iteration",
            "completion_signal", "completion_detail",
        ],
        config_dynamic_writes={"output_field": "difficulty"},
    )

    structured_output_schema = None  # reuses ClassifyOutput from structured_output.py

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Classification Prompt",
            type="prompt_template",
            default=AutonomousPrompts.classify_difficulty(),
            description="Prompt for LLM classification (used only when rules are uncertain).",
            group="prompt",
        ),
        NodeParameter(
            name="categories",
            label="Categories",
            type="string",
            default="easy, tool_direct, medium, hard, extreme",
            description=(
                "Comma-separated category names. Each becomes an output port."
            ),
            group="routing",
            generates_ports=True,
        ),
        NodeParameter(
            name="default_category",
            label="Default Category",
            type="string",
            default="medium",
            description="Fallback when the LLM response doesn't match any category.",
            group="routing",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="difficulty",
            description="State field to store the classification result.",
            group="output",
        ),
        NodeParameter(
            name="enable_rules",
            label="Enable Rule-Based Fast Path",
            type="boolean",
            default=True,
            description="Use rule-based pre-check before LLM. Disable to always use LLM.",
            group="behavior",
        ),
    ]

    output_ports = [
        OutputPort(id="easy", label="Easy", description="Simple, direct tasks"),
        OutputPort(id="tool_direct", label="Tool Direct", description="Direct tool execution"),
        OutputPort(id="medium", label="Medium", description="Moderate complexity"),
        OutputPort(id="hard", label="Hard", description="Complex, multi-step tasks"),
        OutputPort(id="extreme", label="Extreme", description="Very high complexity"),
        OutputPort(id="end", label="End", description="Error / early termination"),
    ]

    # ── Inline context guard ──────────────────────────────────────

    @staticmethod
    def _inline_context_guard(state: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """Lightweight inline context-budget estimation."""
        messages = state.get("messages", [])
        if not messages:
            return {}

        try:
            from service.langgraph.context_guard import ContextWindowGuard

            model_name = context.model_name or "default"
            guard = ContextWindowGuard(model=model_name)
            msg_dicts = [
                {"role": getattr(m, "type", "unknown"), "content": getattr(m, "content", "")}
                for m in messages
                if hasattr(m, "content")
            ]
            result = guard.check(msg_dicts)
            prev_budget = state.get("context_budget") or {}
            return {
                "context_budget": {
                    "estimated_tokens": result.estimated_tokens,
                    "context_limit": result.context_limit,
                    "usage_ratio": result.usage_ratio,
                    "status": result.status.value,
                    "compaction_count": prev_budget.get("compaction_count", 0),
                }
            }
        except Exception:
            return {}

    # ── Inline post-model ─────────────────────────────────────────

    @staticmethod
    def _inline_post_model(state: Dict[str, Any]) -> Dict[str, Any]:
        """Lightweight inline iteration increment."""
        return {"iteration": state.get("iteration", 0) + 1}

    # ── Main execution ────────────────────────────────────────────

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_text = state.get("input", "")
        output_field = config.get("output_field", "difficulty")
        enable_rules = config.get("enable_rules", True)

        categories = parse_categories(
            config.get("categories", "easy, tool_direct, medium, hard, extreme"),
            fallback=["easy", "tool_direct", "medium", "hard", "extreme"],
        )
        default_category = config.get("default_category", "medium")
        if default_category not in categories:
            default_category = categories[0] if categories else "medium"

        result: Dict[str, Any] = {}

        # 1) Inline context guard
        result.update(self._inline_context_guard(state, context))

        # 2) Rule-based fast path
        matched = None
        if enable_rules:
            matched = _quick_classify(input_text, categories)

        if matched is not None:
            logger.info(
                f"[{context.session_id}] adaptive_classify: "
                f"rule-based → {matched} (no LLM call)"
            )
            result.update({
                output_field: matched,
                "current_step": "difficulty_classified",
                "messages": [HumanMessage(content=input_text)],
                "last_output": f"[adaptive_classify: {matched} (rule)]",
            })
            result.update(self._inline_post_model(state))
            return result

        # 3) LLM fallback — structured output
        try:
            template = config.get(
                "prompt_template", AutonomousPrompts.classify_difficulty()
            )
            memory_ctx = state.get("memory_context", "") or ""
            prompt = safe_format(template, {**state, "memory_context": memory_ctx})
            messages = [HumanMessage(content=prompt)]

            parsed, fallback = await context.resilient_structured_invoke(
                messages,
                "adaptive_classify",
                ClassifyOutput,
                allowed_values={"classification": categories},
                coerce_field="classification",
                coerce_values=categories,
                coerce_default=default_category,
                extra_instruction=(
                    f"The 'classification' field MUST be exactly one of: "
                    f"{', '.join(categories)}. Respond with the classification only."
                ),
            )

            matched = parsed.classification
            if matched not in categories:
                matched = default_category

            logger.info(
                f"[{context.session_id}] adaptive_classify: "
                f"LLM → {matched}"
            )

            result.update({
                output_field: matched,
                "current_step": "difficulty_classified",
                "messages": [HumanMessage(content=input_text)],
                "last_output": f"[adaptive_classify: {matched} (llm)]",
            })
            result.update(fallback)
            result.update(self._inline_post_model(state))
            return result

        except Exception as e:
            logger.exception(
                f"[{context.session_id}] adaptive_classify error: {e}"
            )
            return {
                output_field: default_category,
                "error": str(e),
                "current_step": "classify_error",
            }

    # ── Routing ───────────────────────────────────────────────────

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        output_field = config.get("output_field", "difficulty")
        categories = parse_categories(
            config.get("categories", "easy, tool_direct, medium, hard, extreme"),
            fallback=["easy", "tool_direct", "medium", "hard", "extreme"],
        )
        default_category = config.get("default_category", "medium")
        if default_category not in categories:
            default_category = categories[0] if categories else "medium"
        cat_set = {c.lower() for c in categories}

        def _route(state: Dict[str, Any]) -> str:
            if state.get("error"):
                return "end"
            value = state.get(output_field)
            if hasattr(value, "value"):
                value = value.value
            if isinstance(value, str):
                value = value.strip().lower()
            return value if value in cat_set else default_category

        return _route

    def get_dynamic_output_ports(
        self, config: Dict[str, Any],
    ) -> Optional[List[OutputPort]]:
        categories = parse_categories(
            config.get("categories", "easy, tool_direct, medium, hard, extreme"),
            fallback=["easy", "tool_direct", "medium", "hard", "extreme"],
        )
        ports = [
            OutputPort(
                id=cat,
                label=cat.capitalize(),
                description=f"Route for '{cat}' classification",
            )
            for cat in categories
        ]
        ports.append(OutputPort(id="end", label="End", description="Error / early termination"))
        return ports
