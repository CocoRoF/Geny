"""
Session Memory Manager — unified facade.

Combines long-term and short-term memory into a single interface
per session, analogous to OpenClaw's MemorySearchManager.

Each session gets its own SessionMemoryManager tied to its storage_path.
The manager owns:
  - LongTermMemory  (memory/*.md files)
  - ShortTermMemory (transcripts/session.jsonl)

It handles:
  - Unified search across both stores
  - Memory injection for prompts (build context string)
  - Memory flush before compaction (save durable facts)
  - Statistics
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from logging import getLogger
from typing import Any, Dict, List, Optional

from service.memory.long_term import LongTermMemory
from service.memory.short_term import ShortTermMemory
from service.memory.types import (
    MemoryEntry,
    MemorySearchResult,
    MemorySource,
    MemoryStats,
)

logger = getLogger(__name__)

KST = timezone(timedelta(hours=9))

# Maximum characters injected from memory into context.
DEFAULT_MAX_INJECT_CHARS = 8_000


class SessionMemoryManager:
    """Per-session memory facade.

    Usage::

        mgr = SessionMemoryManager(storage_path="/tmp/sessions/abc123")
        mgr.initialize()

        # Record conversation
        mgr.record_message("user", "Fix the login bug")
        mgr.record_message("assistant", "I'll look into auth.py...")

        # Save durable knowledge
        mgr.remember("The login bug was caused by expired JWT tokens.")

        # Search across all memory
        results = mgr.search("JWT token")

        # Build injection block for system prompt
        context = mgr.build_memory_context(query="JWT")
    """

    def __init__(
        self,
        storage_path: str,
        max_inject_chars: int = DEFAULT_MAX_INJECT_CHARS,
    ):
        """
        Args:
            storage_path: Session's root storage directory.
            max_inject_chars: Budget for memory injection into context.
        """
        self._storage_path = storage_path
        self._max_inject_chars = max_inject_chars

        self._ltm = LongTermMemory(storage_path)
        self._stm = ShortTermMemory(storage_path)

        self._initialized = False

    @property
    def long_term(self) -> LongTermMemory:
        return self._ltm

    @property
    def short_term(self) -> ShortTermMemory:
        return self._stm

    @property
    def storage_path(self) -> str:
        return self._storage_path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Set up directory structure for both memory stores."""
        self._ltm.ensure_directory()
        self._stm.ensure_directory()
        self._initialized = True
        logger.info("SessionMemoryManager initialized at %s", self._storage_path)

    # ------------------------------------------------------------------
    # Write operations (convenience wrappers)
    # ------------------------------------------------------------------

    def record_message(
        self,
        role: str,
        content: str,
        **metadata: Any,
    ) -> None:
        """Record a conversation message to short-term memory.

        Args:
            role: "user" | "assistant" | "system"
            content: Message content.
            **metadata: Extra metadata fields.
        """
        self._stm.add_message(role, content, metadata=metadata if metadata else None)

    def record_event(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Record a non-message event (tool call, state change, etc.)."""
        self._stm.add_event(event, data)

    def remember(self, text: str, *, heading: Optional[str] = None) -> None:
        """Write durable knowledge to long-term memory.

        This appends to MEMORY.md. For dated entries use remember_dated().

        Args:
            text: The knowledge to persist.
            heading: Optional markdown heading.
        """
        self._ltm.append(text, heading=heading)

    def remember_dated(self, text: str) -> None:
        """Write knowledge to a dated long-term memory file."""
        self._ltm.write_dated(text)

    def remember_topic(self, topic: str, text: str) -> None:
        """Write knowledge to a topic-specific long-term memory file."""
        self._ltm.write_topic(topic, text)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        sources: Optional[List[MemorySource]] = None,
    ) -> List[MemorySearchResult]:
        """Search across all memory stores.

        Results from long-term memory are weighted higher (1.2x)
        than short-term memory.

        Args:
            query: Search string.
            max_results: Maximum total results.
            sources: Filter to specific sources. None = all.
        """
        results: list[MemorySearchResult] = []

        if sources is None or MemorySource.LONG_TERM in sources:
            ltm_results = self._ltm.search(query, max_results=max_results)
            for r in ltm_results:
                r.score *= 1.2  # Long-term memory relevance boost
            results.extend(ltm_results)

        if sources is None or MemorySource.SHORT_TERM in sources:
            stm_results = self._stm.search(query, max_results=max_results)
            results.extend(stm_results)

        # Sort by combined score, deduplicate if needed
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:max_results]

    # ------------------------------------------------------------------
    # Context injection
    # ------------------------------------------------------------------

    def build_memory_context(
        self,
        query: Optional[str] = None,
        *,
        include_summary: bool = True,
        include_recent: int = 0,
        max_chars: Optional[int] = None,
    ) -> Optional[str]:
        """Build a memory context block for system prompt injection.

        This is called before each agent turn to inject relevant
        memory into the conversation context.

        Args:
            query: Optional query to search for relevant memories.
            include_summary: Include session summary if available.
            include_recent: Number of recent messages to include (0 = none).
            max_chars: Character budget (default: self._max_inject_chars).

        Returns:
            Formatted memory context string, or None if nothing to inject.
        """
        budget = max_chars or self._max_inject_chars
        parts: list[str] = []
        total_chars = 0

        # 1. Session summary (if available)
        if include_summary:
            summary = self._stm.get_summary()
            if summary and (total_chars + len(summary)) <= budget:
                parts.append(f"<session-summary>\n{summary}\n</session-summary>")
                total_chars += len(summary)

        # 2. Long-term memory: main MEMORY.md
        main_mem = self._ltm.load_main()
        if main_mem and (total_chars + main_mem.char_count) <= budget:
            parts.append(
                f"<long-term-memory source=\"{main_mem.filename}\">\n"
                f"{main_mem.content}\n"
                f"</long-term-memory>"
            )
            total_chars += main_mem.char_count

        # 3. Query-based memory retrieval
        if query:
            search_results = self.search(query, max_results=5)
            for result in search_results:
                chunk = (
                    f"<memory-recall source=\"{result.entry.filename}\" "
                    f"score=\"{result.score:.2f}\">\n"
                    f"{result.snippet}\n"
                    f"</memory-recall>"
                )
                if (total_chars + len(chunk)) > budget:
                    break
                parts.append(chunk)
                total_chars += len(chunk)

        # 4. Recent transcript messages
        if include_recent > 0:
            recent = self._stm.get_recent(n=include_recent)
            for entry in recent:
                if (total_chars + entry.char_count) > budget:
                    break
                parts.append(
                    f"<recent-message>\n{entry.content}\n</recent-message>"
                )
                total_chars += entry.char_count

        if not parts:
            return None

        header = "## Recalled Memory\n"
        body = "\n\n".join(parts)
        return f"{header}\n{body}"

    # ------------------------------------------------------------------
    # Memory flush (pre-compaction)
    # ------------------------------------------------------------------

    def flush_to_long_term(
        self,
        content: str,
        *,
        heading: str = "Session Memory Flush",
    ) -> None:
        """Flush important information from short-term to long-term memory.

        Called before context compaction to preserve durable facts.

        Args:
            content: Text to persist.
            heading: Section heading in MEMORY.md.
        """
        self._ltm.append(content, heading=heading)
        logger.info(
            "Memory flush: %d chars saved to long-term memory", len(content)
        )

    def auto_flush(self, recent_n: int = 30) -> Optional[str]:
        """Generate a summary of recent conversation for long-term storage.

        This is a simplified version of OpenClaw's memory flush.
        The caller should invoke this before compaction.

        Args:
            recent_n: Number of recent messages to summarize.

        Returns:
            The flushed text, or None if nothing to flush.
        """
        recent = self._stm.get_recent(n=recent_n)
        if not recent:
            return None

        # Build a condensed transcript
        lines: list[str] = []
        for entry in recent:
            lines.append(entry.content)

        transcript = "\n".join(lines)
        if len(transcript) < 100:
            return None  # Too short to bother

        # Save to dated file
        self._ltm.write_dated(
            f"## Auto-flushed Session Transcript\n\n{transcript}"
        )

        logger.info(
            "auto_flush: saved %d messages (%d chars) to long-term",
            len(recent), len(transcript),
        )
        return transcript

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> MemoryStats:
        """Compute memory statistics."""
        ltm_entries = self._ltm.load_all()
        stm_entries = self._stm.load_all()

        ltm_chars = sum(e.char_count for e in ltm_entries)
        stm_chars = sum(e.char_count for e in stm_entries)

        all_timestamps = [
            e.timestamp for e in ltm_entries + stm_entries
            if e.timestamp is not None
        ]
        last_write = max(all_timestamps) if all_timestamps else None

        return MemoryStats(
            long_term_entries=len(ltm_entries),
            short_term_entries=len(stm_entries),
            long_term_chars=ltm_chars,
            short_term_chars=stm_chars,
            total_files=len(ltm_entries),
            last_write=last_write,
        )
