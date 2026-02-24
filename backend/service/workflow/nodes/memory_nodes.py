"""
Memory Nodes — memory injection and transcript recording.

Handle interaction with the session memory manager
for loading relevant context and recording conversation.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List, Optional

from service.langgraph.state import MemoryRef
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    register_node,
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
    """

    node_type = "memory_inject"
    label = "Memory Inject"
    description = "Load relevant memory context into the graph state"
    category = "memory"
    icon = "🧠"
    color = "#ec4899"

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
            input_text = state.get("input", "")
            max_results = int(config.get("max_results", 5))
            search_chars = int(config.get("search_chars", 500))

            # Record user input to transcript
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
    """Record the latest model output to short-term memory transcript."""

    node_type = "transcript_record"
    label = "Transcript Record"
    description = "Record the latest output to memory transcript"
    category = "memory"
    icon = "📝"
    color = "#ec4899"

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
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not context.memory_manager:
            return {}

        last_output = state.get("last_output", "") or ""
        max_length = int(config.get("max_length", 5000))

        if last_output:
            try:
                context.memory_manager.record_message(
                    "assistant", last_output[:max_length]
                )
            except Exception:
                logger.debug(f"[{context.session_id}] transcript_record: failed")

        return {}
