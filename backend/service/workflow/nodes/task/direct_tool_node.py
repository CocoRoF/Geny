"""
Direct Tool Node — single-shot tool execution for tool_direct tasks.

When the task's essence IS a tool operation (e.g. git push, npm install),
this node executes it in a single LLM call without plan decomposition.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import DIRECT_TOOL_I18N

logger = getLogger(__name__)

_DEFAULT_PROMPT = (
    "You are a tool execution agent. Your ONLY job is to "
    "execute the requested operation using the available tools.\n\n"
    "Rules:\n"
    "- Execute the tool operation directly and immediately\n"
    "- Do NOT explain what you will do — just do it\n"
    "- Do NOT create plans or break down into steps\n"
    "- Do NOT ask clarifying questions\n"
    "- Report the result concisely after execution\n\n"
    "Task:\n{input}"
)


@register_node
class DirectToolNode(BaseNode):
    """Execute a tool-direct task in a single LLM call.

    For tasks where the essence IS a tool operation (e.g. git push,
    npm install, file deletion), this node instructs the LLM to
    execute the operation directly without plan decomposition.
    Marks the workflow as complete after execution.
    """

    node_type = "direct_tool"
    label = "Direct Tool"
    description = (
        "Single-shot tool execution node. For tasks where the essence IS "
        "a tool operation, executes it in one LLM call without planning. "
        "Marks workflow complete after execution."
    )
    category = "task"
    icon = "terminal"
    color = "#10b981"
    i18n = DIRECT_TOOL_I18N
    state_usage = NodeStateUsage(
        reads=["input"],
        writes=[
            "messages", "last_output", "current_step",
            "is_complete",
        ],
        config_dynamic_writes={"output_field": "final_answer"},
    )

    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Tool Execution Prompt",
            type="prompt_template",
            default=_DEFAULT_PROMPT,
            description="Prompt instructing the LLM to execute the tool directly.",
            group="prompt",
        ),
        NodeParameter(
            name="output_field",
            label="Output State Field",
            type="string",
            default="final_answer",
            description="State field to store the execution result.",
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
        output_field = config.get("output_field", "final_answer")
        template = config.get("prompt_template", _DEFAULT_PROMPT)

        try:
            try:
                prompt = template.format(input=input_text)
            except (KeyError, IndexError):
                prompt = template

            messages = [HumanMessage(content=prompt)]
            response, fallback = await context.resilient_invoke(
                messages, "direct_tool"
            )

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
            logger.exception(
                f"[{context.session_id}] direct_tool error: {e}"
            )
            return {
                output_field: f"Tool execution failed: {e}",
                "last_output": f"Error in direct_tool: {e}",
                "error": str(e),
                "is_complete": True,
            }
