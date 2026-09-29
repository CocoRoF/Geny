"""PersistingLLMSummaryCompactor — Memory v2 PR 8.

Wraps the executor's :class:`LLMSummaryCompactor` so that every
successful compaction also gets persisted via
:meth:`SessionMemoryManager.record_compaction` (PR 8). Plan §2.2:
the executor by itself emits ``memory.compaction.summarized`` and
walks on; without this wrapper the next session has no way to see
what that compaction summarised.

The wrapper observes ``state.messages`` before and after
``super().compact(state)`` so we don't need to peer inside the
compactor's prompt or its event payload — whatever
``LLMSummaryCompactor`` writes as ``state.messages[0].content`` is
the canonical summary to persist.

Edge cases:

  * Compaction skipped (history too short) — ``state.messages``
    unchanged, no persist call.
  * LLM call failed and fell back to placeholder — placeholder
    text *is* the new summary, so we persist it; operators want
    to see the placeholder showed up.
  * ``record_compaction`` itself fails — best-effort, swallowed,
    pipeline continues.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from geny_executor.core.state import PipelineState
from geny_executor.stages.s02_context.artifact.default.compactors import (
    SUMMARY_PREFIX,
    LLMSummaryCompactor,
)

logger = logging.getLogger(__name__)


class PersistingLLMSummaryCompactor(LLMSummaryCompactor):
    """:class:`LLMSummaryCompactor` plus a one-shot
    ``record_compaction`` call after a successful compaction.
    """

    # This wrapper writes its own compaction snapshot via
    # ``SessionMemoryManager.record_compaction`` below. Tell the executor's
    # shared ``run_compaction`` helper (2.5.0) NOT to also persist through
    # the attached provider — otherwise both the proactive (Stage 2) and
    # the new guard-recovery (Stage 4) paths would record the same snapshot
    # twice.
    persists_own_compaction = True

    def __init__(
        self,
        *args: Any,
        memory_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._memory_manager = memory_manager

    @property
    def name(self) -> str:
        return "persisting_llm_summary"

    async def compact(self, state: PipelineState) -> None:
        before = list(state.messages)
        old_count = len(before)
        await super().compact(state)
        new_count = len(state.messages)
        # Compaction is a no-op when history is short — bail early. Compared
        # by the head message, not the length: the compacted history also
        # carries the request being worked on, so a small compaction can
        # come out no shorter than it went in.
        if not state.messages or (before and state.messages[0] is before[0]):
            return

        if self._memory_manager is None:
            return
        # The executor's LLMSummaryCompactor (and its placeholder
        # super) writes the canonical summary into
        # state.messages[0].content. Extract verbatim so the audit
        # copy mirrors what the LLM actually saw.
        try:
            summary_msg = state.messages[0]
            summary_text = summary_msg.get("content", "")
            if isinstance(summary_text, list):
                # Defensive — multi-block content shouldn't happen
                # for the compaction summary, but extract text just
                # in case.
                summary_text = "\n".join(
                    b.get("text", "")
                    for b in summary_text
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            if isinstance(summary_text, str) and summary_text.startswith(SUMMARY_PREFIX):
                summary_text = summary_text[len(SUMMARY_PREFIX):]
            # The messages that are gone: everything but what was kept.
            kept = {id(m) for m in state.messages}
            replaced = sum(1 for m in before if id(m) not in kept) or max(0, old_count - new_count)
            # ``record_compaction`` is a SYNC chain (CompactionArchiver)
            # that reaches ``run_coro_sync`` for its vault note write.
            # ``compact`` runs ON the main event loop, so calling it inline
            # would make ``run_coro_sync`` block the loop on a worker future
            # that contends for a memory lock — the same deadlock class that
            # froze the backend. Run it off the loop. See ``sync_async_bridge``.
            from service.memory.sync_async_bridge import offload_blocking
            await offload_blocking(
                lambda: self._memory_manager.record_compaction(
                    str(summary_text),
                    replaced_count=int(replaced),
                    strategy=self.name,
                )
            )
        except Exception:
            logger.debug(
                "PersistingLLMSummaryCompactor: record_compaction failed",
                exc_info=True,
            )


__all__ = ["PersistingLLMSummaryCompactor"]
