"""
Memory Nodes — memory injection and transcript recording.

Handle interaction with the session memory manager
for loading relevant context and recording conversation.

Generalisation design:
    Both nodes expose configurable field names and behaviour
    toggles so they can serve any memory-related pattern.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List

from service.langgraph.state import MemoryRef
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
)
from service.workflow.workflow_state import NodeStateUsage
from service.workflow.nodes.i18n import (
    MEMORY_INJECT_I18N,
    TRANSCRIPT_RECORD_I18N,
)

logger = getLogger(__name__)


# ============================================================================
# Memory Inject
# ============================================================================


@register_node
class MemoryInjectNode(BaseNode):
    """Load relevant memory context into state at graph start.

    Searches the SessionMemoryManager for memories related to the
    input text and writes MemoryRef entries to state.

    Generalised: Configurable search source field, record toggle,
    and result limits.
    """

    node_type = "memory_inject"
    label = "Memory Inject"
    description = "Loads relevant memories from the session memory manager at workflow start. Searches for memories related to the input text and injects MemoryRef entries into state for traceability. Also optionally records the user input to the short-term transcript. Place at graph start for context-aware execution."
    category = "memory"
    icon = "brain"
    color = "#ec4899"
    i18n = MEMORY_INJECT_I18N
    state_usage = NodeStateUsage(
        reads=[],
        writes=["memory_refs"],
        config_dynamic_reads={"search_field": "input"},
    )

    parameters = [
        NodeParameter(
            name="max_results",
            label="Max Memory Results",
            type="number",
            default=5,
            min=1,
            max=20,
            description="Maximum number of memory chunks to load.",
            group="behavior",
        ),
        NodeParameter(
            name="search_chars",
            label="Search Input Length",
            type="number",
            default=500,
            min=50,
            max=5000,
            description="Character limit of input text used for memory search.",
            group="behavior",
        ),
        NodeParameter(
            name="search_field",
            label="Search Source Field",
            type="string",
            default="input",
            description="State field whose value is used as the memory search query.",
            group="state_fields",
        ),
        NodeParameter(
            name="record_input",
            label="Record Input to Transcript",
            type="boolean",
            default=True,
            description="Record the search text to the short-term transcript.",
            group="behavior",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not context.memory_manager:
            logger.debug(f"[{context.session_id}] memory_inject: no memory manager")
            return {}

        try:
            search_field = config.get("search_field", "input")
            input_text = state.get(search_field, "") or ""
            max_results = int(config.get("max_results", 5))
            search_chars = int(config.get("search_chars", 500))
            record_input = config.get("record_input", True)

            # Record user input to transcript
            if record_input:
                try:
                    context.memory_manager.record_message("user", input_text[:5000])
                except Exception:
                    logger.debug(f"[{context.session_id}] memory_inject: transcript record failed")

            # Search for relevant memories
            results = context.memory_manager.search(
                input_text[:search_chars], max_results=max_results
            )

            refs: List[MemoryRef] = []
            for r in results:
                refs.append({
                    "filename": r.entry.filename or "unknown",
                    "source": r.entry.source.value,
                    "char_count": r.entry.char_count,
                    "injected_at_turn": 0,
                })

            if refs:
                logger.info(
                    f"[{context.session_id}] memory_inject: "
                    f"loaded {len(refs)} refs "
                    f"({sum(r['char_count'] for r in refs)} chars)"
                )

            return {"memory_refs": refs} if refs else {}

        except Exception as e:
            logger.warning(f"[{context.session_id}] memory_inject failed: {e}")
            return {}


# ============================================================================
# Transcript Record
# ============================================================================


@register_node
class TranscriptRecordNode(BaseNode):
    """Record a state field's content to short-term memory transcript.

    Generalised: Configurable source field and message role.
    """

    node_type = "transcript_record"
    label = "Transcript Record"
    description = "Records a state field's content to the short-term memory transcript with a configurable message role (assistant/user/system). Use for explicit transcript control when the built-in recording in PostModel is insufficient."
    category = "memory"
    icon = "file-text"
    color = "#ec4899"
    i18n = TRANSCRIPT_RECORD_I18N
    state_usage = NodeStateUsage(
        reads=[],
        writes=[],  # writes to external memory, not state
        config_dynamic_reads={"source_field": "last_output"},
    )

    parameters = [
        NodeParameter(
            name="max_length",
            label="Max Content Length",
            type="number",
            default=5000,
            min=100,
            max=50000,
            description="Maximum characters to record from the output.",
            group="behavior",
        ),
        NodeParameter(
            name="source_field",
            label="Source State Field",
            type="string",
            default="last_output",
            description="State field whose content is recorded to the transcript.",
            group="state_fields",
        ),
        NodeParameter(
            name="role",
            label="Message Role",
            type="select",
            default="assistant",
            description="Role label for the transcript entry.",
            options=[
                {"label": "Assistant", "value": "assistant"},
                {"label": "User", "value": "user"},
                {"label": "System", "value": "system"},
            ],
            group="behavior",
        ),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not context.memory_manager:
            return {}

        source_field = config.get("source_field", "last_output")
        content = state.get(source_field, "") or ""
        max_length = int(config.get("max_length", 5000))
        role = config.get("role", "assistant")

        if content:
            try:
                context.memory_manager.record_message(role, content[:max_length])
            except Exception:
                logger.debug(f"[{context.session_id}] transcript_record: failed")

        return {}
