"""
Resilience graph nodes — context guard, model fallback, memory injection.

These nodes run inside the LangGraph StateGraph and read/write the
enhanced AgentState / AutonomousState fields, keeping all resilience
concerns state-based and observable.

Nodes:
    context_guard_node   — check context budget, auto-compact if needed
    memory_inject_node   — load relevant memory into state (pre-LLM)
    transcript_record_node — persist turn to short-term memory (post-LLM)
    completion_detect_node — parse structured signals from output
"""

from __future__ import annotations

import re
from logging import getLogger
from typing import Any, Dict, Optional

from service.langgraph.state import (
    CompletionSignal,
    ContextBudget,
    MemoryRef,
)

logger = getLogger(__name__)


# ============================================================================
# Completion detection (works on raw output text)
# ============================================================================

# Pre-compiled patterns for hot-path performance.
_RE_TASK_COMPLETE = re.compile(r"\[TASK_COMPLETE\]")
_RE_BLOCKED = re.compile(r"\[BLOCKED:\s*(.+?)\]")
_RE_ERROR = re.compile(r"\[ERROR:\s*(.+?)\]")
_RE_CONTINUE = re.compile(r"\[CONTINUE:\s*(.+?)\]")

# Legacy fallback patterns.
_LEGACY_COMPLETE = [
    "작업이 완료되었습니다",
    "task completed",
    "완료되었습니다",
]


def detect_completion_signal(output: str) -> tuple[CompletionSignal, Optional[str]]:
    """Parse structured completion signals from agent output.

    Returns:
        (signal, detail) — detail is the text inside brackets, if any.
    """
    if not output:
        return CompletionSignal.NONE, None

    if _RE_TASK_COMPLETE.search(output):
        return CompletionSignal.COMPLETE, None

    m = _RE_BLOCKED.search(output)
    if m:
        return CompletionSignal.BLOCKED, m.group(1).strip()

    m = _RE_ERROR.search(output)
    if m:
        return CompletionSignal.ERROR, m.group(1).strip()

    m = _RE_CONTINUE.search(output)
    if m:
        return CompletionSignal.CONTINUE, m.group(1).strip()

    # Legacy fallback
    output_lower = output.lower()
    for pattern in _LEGACY_COMPLETE:
        if pattern in output_lower:
            return CompletionSignal.COMPLETE, "legacy_signal"

    return CompletionSignal.NONE, None


# ============================================================================
# Context guard node
# ============================================================================

def make_context_guard_node(
    model: Optional[str] = None,
    warn_ratio: float = 0.75,
    block_ratio: float = 0.90,
    auto_compact_keep: int = 20,
):
    """Factory for a context-guard graph node.

    Usage inside graph builder::

        graph_builder.add_node(
            "context_guard",
            make_context_guard_node(model="claude-sonnet-4-20250514"),
        )

    The node reads ``state["messages"]`` and writes ``state["context_budget"]``.
    If the budget is BLOCK level, it trims older messages in-place.
    """
    from service.langgraph.context_guard import ContextWindowGuard

    guard = ContextWindowGuard(
        model=model,
        warn_ratio=warn_ratio,
        block_ratio=block_ratio,
        auto_compact_keep_count=auto_compact_keep,
    )

    async def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        """Check context budget and compact if necessary."""
        messages = state.get("messages", [])

        # Convert LangChain messages to dicts for the guard
        msg_dicts = []
        for msg in messages:
            if hasattr(msg, "content"):
                msg_dicts.append({
                    "role": getattr(msg, "type", "unknown"),
                    "content": msg.content,
                })
            elif isinstance(msg, dict):
                msg_dicts.append(msg)

        result = guard.check(msg_dicts)

        budget: ContextBudget = {
            "estimated_tokens": result.estimated_tokens,
            "context_limit": result.context_limit,
            "usage_ratio": result.usage_ratio,
            "status": result.status.value,
            "compaction_count": (
                state.get("context_budget", {}).get("compaction_count", 0)
            ),
        }

        updates: Dict[str, Any] = {"context_budget": budget}

        # If over block threshold, compact messages
        if result.should_block and len(messages) > auto_compact_keep + 2:
            logger.warning(
                "Context guard: BLOCK at %.1f%% — compacting to %d messages",
                result.usage_ratio * 100,
                auto_compact_keep,
            )
            # Keep system messages + most recent N
            # We signal that compaction is needed rather than mutating
            # the message list directly, because the messages field
            # uses an additive reducer. The session handles actual truncation.
            budget["compaction_count"] = budget.get("compaction_count", 0) + 1
            updates["context_budget"] = budget
            updates["metadata"] = {
                **state.get("metadata", {}),
                "_compaction_requested": True,
                "_keep_recent_count": auto_compact_keep,
            }

        return updates

    return _node


# ============================================================================
# Memory injection node
# ============================================================================

def make_memory_inject_node(storage_path: str, max_inject_chars: int = 8_000):
    """Factory for a memory-injection graph node.

    Loads relevant long-term and short-term memory into state before
    the LLM call. Results are stored in ``state["memory_refs"]``.

    Usage::

        graph_builder.add_node(
            "memory_inject",
            make_memory_inject_node("/tmp/sessions/abc"),
        )
    """
    from service.memory.manager import SessionMemoryManager

    mgr = SessionMemoryManager(storage_path, max_inject_chars=max_inject_chars)
    mgr.initialize()

    async def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        """Inject memory references into state."""
        iteration = state.get("iteration", 0)

        # Only inject on first turn or every 10 turns to save tokens
        existing_refs = state.get("memory_refs", [])
        if existing_refs and iteration % 10 != 0:
            return {}  # No update needed

        # Extract query from last user message
        query = None
        messages = state.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "human":
                query = msg.content[:500]
                break
            elif isinstance(msg, dict) and msg.get("role") == "user":
                query = msg.get("content", "")[:500]
                break

        if not query:
            # If no specific query, load whatever is in MEMORY.md
            main_mem = mgr.long_term.load_main()
            if main_mem:
                ref: MemoryRef = {
                    "filename": main_mem.filename or "MEMORY.md",
                    "source": "long_term",
                    "char_count": main_mem.char_count,
                    "injected_at_turn": iteration,
                }
                return {"memory_refs": [ref]}
            return {}

        # Search and build refs
        results = mgr.search(query, max_results=5)
        refs: list[MemoryRef] = []
        for r in results:
            refs.append({
                "filename": r.entry.filename or "unknown",
                "source": r.entry.source.value,
                "char_count": r.entry.char_count,
                "injected_at_turn": iteration,
            })

        if refs:
            logger.debug(
                "Memory inject: loaded %d refs (%d chars total)",
                len(refs),
                sum(r["char_count"] for r in refs),
            )

        return {"memory_refs": refs} if refs else {}

    return _node


# ============================================================================
# Transcript recording node
# ============================================================================

def make_transcript_record_node(storage_path: str):
    """Factory for a post-LLM transcript recording node.

    Persists each assistant response to the JSONL transcript.

    Usage::

        graph_builder.add_node(
            "transcript_record",
            make_transcript_record_node("/tmp/sessions/abc"),
        )
    """
    from service.memory.short_term import ShortTermMemory

    stm = ShortTermMemory(storage_path)
    stm.ensure_directory()

    async def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        """Record the latest assistant message to transcript."""
        last_output = state.get("last_output", "")
        if not last_output:
            return {}

        stm.add_message("assistant", last_output)

        # Also record user input if this is the first turn
        iteration = state.get("iteration", 0)
        if iteration <= 1:
            messages = state.get("messages", [])
            for msg in messages:
                if hasattr(msg, "type") and msg.type == "human":
                    stm.add_message("user", msg.content)
                    break

        return {}  # No state mutation

    return _node


# ============================================================================
# Completion detection node
# ============================================================================

async def completion_detect_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Parse structured completion signals from the last output.

    Writes ``completion_signal`` and ``completion_detail`` to state,
    which the edge function then reads to decide continue vs end.
    """
    last_output = state.get("last_output", "")
    signal, detail = detect_completion_signal(last_output)

    updates: Dict[str, Any] = {
        "completion_signal": signal.value,
        "completion_detail": detail,
    }

    # If signal says complete/blocked/error, mark is_complete
    if signal in (
        CompletionSignal.COMPLETE,
        CompletionSignal.BLOCKED,
        CompletionSignal.ERROR,
    ):
        updates["is_complete"] = True

    return updates
