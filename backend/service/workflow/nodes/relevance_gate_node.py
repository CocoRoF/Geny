"""
Relevance Gate Node — chat/broadcast message filter.

Only activates when ``is_chat_message`` is True in state. For normal
(non-chat) messages, passes through immediately. When active, performs
a structured-output LLM call to decide relevance. Routes to "continue"
(relevant) or "skip" (not relevant → END).
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Callable, Dict, Optional

from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import RELEVANCE_GATE_I18N

logger = getLogger(__name__)


@register_node
class RelevanceGateNode(BaseNode):
    """Filter broadcast/chat messages by agent role relevance.

    Only activates when ``is_chat_message`` is True in state.
    For normal (non-chat) messages, passes through immediately.

    When active, performs a structured-output LLM call to decide
    if the broadcast message is relevant to this agent's role/persona.
    Routes to "continue" (relevant) or "skip" (not relevant → END).

    Uses Pydantic-validated structured output (``RelevanceOutput``)
    for reliable, deterministic YES/NO parsing — never relies on
    fragile substring matching.
    """

    node_type = "relevance_gate"
    label = "Relevance Gate"
    description = (
        "Chat/broadcast relevance filter. Uses a structured-output LLM call "
        "to determine if a broadcast message is relevant to this agent's "
        "role and persona. Non-chat messages pass through without any LLM call. "
        "Irrelevant messages route to 'skip' (→ END), relevant ones to 'continue'."
    )
    category = "logic"
    icon = "filter"
    color = "#8b5cf6"
    i18n = RELEVANCE_GATE_I18N
    state_usage = NodeStateUsage(
        reads=["is_chat_message", "input", "metadata"],
        writes=["relevance_skipped", "is_complete", "final_answer", "current_step"],
    )

    from service.workflow.nodes.structured_output import (
        RelevanceOutput, build_frontend_schema as _build_relevance_schema,
    )
    structured_output_schema = _build_relevance_schema(
        RelevanceOutput,
        description="LLM relevance gate result for chat/broadcast filtering.",
    )

    parameters = []

    output_ports = [
        OutputPort(
            id="continue",
            label="Continue",
            description="Message is relevant — proceed with normal execution",
        ),
        OutputPort(
            id="skip",
            label="Skip",
            description="Message is not relevant — skip to END",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        is_chat = state.get("is_chat_message", False)

        # Not a chat/broadcast message — pass through immediately
        if not is_chat:
            return {}

        # Chat mode — check relevance via structured-output LLM call
        from langchain_core.messages import HumanMessage
        from service.prompt.sections import AutonomousPrompts
        from service.workflow.nodes.structured_output import RelevanceOutput

        input_text = state.get("input", "")
        metadata = state.get("metadata", {})
        agent_name = metadata.get("agent_name", "Agent")
        agent_role = metadata.get("agent_role", "worker")

        try:
            prompt = AutonomousPrompts.check_relevance().format(
                agent_name=agent_name,
                role=agent_role,
                message=input_text,
            )
            messages = [HumanMessage(content=prompt)]

            parsed, _ = await context.resilient_structured_invoke(
                messages,
                "relevance_gate",
                RelevanceOutput,
                extra_instruction=(
                    "The 'relevant' field MUST be a boolean (true or false). "
                    "Respond true ONLY if this message clearly pertains to "
                    "your name, role, or expertise."
                ),
            )

            is_relevant = parsed.relevant
            reasoning = parsed.reasoning or ""

            logger.info(
                f"[{context.session_id}] relevance_gate: "
                f"message {'relevant' if is_relevant else 'NOT relevant'} "
                f"(agent={agent_name}, role={agent_role}"
                f"{', reason=' + reasoning[:80] if reasoning else ''})"
            )

            if not is_relevant:
                return {
                    "relevance_skipped": True,
                    "is_complete": True,
                    "final_answer": "",
                    "current_step": "relevance_skipped",
                }

            return {"relevance_skipped": False}

        except Exception as e:
            logger.warning(
                f"[{context.session_id}] relevance_gate: "
                f"structured parse failed: {e}, "
                f"falling back to string matching"
            )
            # Fallback: try simple LLM call with YES/NO parsing
            return await self._fallback_relevance_check(
                state, context, agent_name, agent_role, input_text,
            )

    async def _fallback_relevance_check(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        agent_name: str,
        agent_role: str,
        input_text: str,
    ) -> Dict[str, Any]:
        """Fallback relevance check using simple YES/NO string matching.

        Only called when structured output parsing fails.
        """
        from langchain_core.messages import HumanMessage

        try:
            fallback_prompt = (
                f"You are {agent_name} (role: {agent_role}).\n"
                f"Message: \"{input_text}\"\n\n"
                f"Is this message relevant to you? Reply ONLY: YES or NO"
            )
            messages = [HumanMessage(content=fallback_prompt)]
            response, _ = await context.resilient_invoke(
                messages, "relevance_gate_fallback"
            )
            response_text = response.content.strip().lower()

            # Check for explicit yes/no — handle both English and Korean
            is_relevant = (
                "yes" in response_text
                or "예" in response_text
                or "네" in response_text
            ) and "no" not in response_text[:5]

            logger.info(
                f"[{context.session_id}] relevance_gate (fallback): "
                f"message {'relevant' if is_relevant else 'NOT relevant'} "
                f"(raw: {response_text[:50]})"
            )

            if not is_relevant:
                return {
                    "relevance_skipped": True,
                    "is_complete": True,
                    "final_answer": "",
                    "current_step": "relevance_skipped",
                }

            return {"relevance_skipped": False}

        except Exception as e2:
            logger.warning(
                f"[{context.session_id}] relevance_gate: "
                f"fallback also failed: {e2}, defaulting to relevant"
            )
            # On total failure, assume relevant (don't block legitimate work)
            return {"relevance_skipped": False}

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        def _route(state: Dict[str, Any]) -> str:
            # Primary check: explicit relevance skip flag
            if state.get("relevance_skipped"):
                return "skip"
            # Safety check: if is_complete was set during relevance gate
            if state.get("is_complete") and state.get("current_step") == "relevance_skipped":
                return "skip"
            return "continue"
        return _route
