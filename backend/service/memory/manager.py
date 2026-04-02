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
from service.memory.vector_memory import VectorMemoryManager
from service.memory.structured_writer import StructuredMemoryWriter
from service.memory.index import MemoryIndexManager
from service.memory.types import (
    MemoryEntry,
    MemorySearchResult,
    MemorySource,
    MemoryStats,
)

logger = getLogger(__name__)

# Use configured timezone from GENY_TIMEZONE env var
from service.utils.utils import _configured_tz as _get_tz

# Maximum characters injected from memory into context.
DEFAULT_MAX_INJECT_CHARS = 8_000

# Maximum chars for truncated fields in LTM entries.
_LTM_INPUT_PREVIEW = 300
_LTM_OUTPUT_PREVIEW = 800
_LTM_TODO_RESULT_PREVIEW = 400


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
        self._vmm = VectorMemoryManager(storage_path)

        # Structured memory layer (Obsidian-like)
        self._index_manager: Optional[MemoryIndexManager] = None
        self._structured_writer: Optional[StructuredMemoryWriter] = None

        self._initialized = False
        self._db_manager = None
        self._session_id: Optional[str] = None

    def set_database(self, db_manager, session_id: str) -> None:
        """Enable DB-backed persistence for LTM and STM.

        Args:
            db_manager: AppDatabaseManager instance.
            session_id: Session ID for DB queries.
        """
        self._db_manager = db_manager
        self._session_id = session_id
        self._ltm.set_database(db_manager, session_id)
        self._stm.set_database(db_manager, session_id)
        # Propagate DB to structured writer if already initialized
        if self._structured_writer is not None:
            self._structured_writer.set_database(db_manager, session_id)
        logger.info("SessionMemoryManager: DB backend enabled for session %s", session_id)

    @property
    def long_term(self) -> LongTermMemory:
        return self._ltm

    @property
    def short_term(self) -> ShortTermMemory:
        return self._stm

    @property
    def vector_memory(self) -> VectorMemoryManager:
        return self._vmm

    @property
    def index_manager(self) -> Optional[MemoryIndexManager]:
        return self._index_manager

    @property
    def structured_writer(self) -> Optional[StructuredMemoryWriter]:
        return self._structured_writer

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

        # Initialize structured memory layer
        memory_dir = self._ltm.memory_dir
        self._index_manager = MemoryIndexManager(str(memory_dir))
        self._structured_writer = StructuredMemoryWriter(
            str(memory_dir), self._index_manager
        )
        # Propagate DB if already set
        if self._db_manager is not None and self._session_id is not None:
            self._structured_writer.set_database(self._db_manager, self._session_id)

        # Run migration for legacy files (idempotent)
        try:
            from service.memory.migrator import MemoryMigrator
            migrator = MemoryMigrator(str(memory_dir), self._session_id or "")
            if migrator.needs_migration():
                report = migrator.migrate()
                logger.info(
                    "Memory migration: %s",
                    report.summary if report else "no changes",
                )
        except Exception:
            logger.debug("Memory migration failed (non-critical)", exc_info=True)

        self._initialized = True
        logger.info("SessionMemoryManager initialized at %s", self._storage_path)

    async def initialize_vector_memory(self) -> bool:
        """Initialise the FAISS vector memory layer (async).

        Called separately from :meth:`initialize` because it requires
        async I/O for config loading and initial indexing.

        Returns:
            ``True`` if vector memory was enabled and initialised.
        """
        try:
            ok = await self._vmm.initialize()
            if ok:
                # Index existing memory files on first load
                await self._vmm.index_memory_files()
            return ok
        except Exception:
            logger.warning(
                "initialize_vector_memory failed (non-critical)",
                exc_info=True,
            )
            return False

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
    # Structured memory operations (Obsidian-like)
    # ------------------------------------------------------------------

    def write_note(
        self,
        title: str,
        content: str,
        *,
        category: str = "topics",
        tags: Optional[List[str]] = None,
        importance: str = "medium",
        source: str = "system",
        links_to: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Write a structured memory note with frontmatter.

        Returns the filename of the created note, or None on failure.
        """
        if self._structured_writer is None:
            # Fallback to legacy write
            self._ltm.write_topic(title, content)
            return None
        return self._structured_writer.write_note(
            title=title,
            content=content,
            category=category,
            tags=tags,
            importance=importance,
            source=source,
            links=links_to,
        )

    def update_note(
        self,
        filename: str,
        *,
        body: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
    ) -> bool:
        """Update an existing structured memory note.

        Returns True if updated successfully.
        """
        if self._structured_writer is None:
            return False
        return self._structured_writer.update_note(
            filename, content=body, tags=tags, importance=importance,
        )

    def delete_note(self, filename: str) -> bool:
        """Delete a structured memory note.

        Returns True if deleted successfully.
        """
        if self._structured_writer is None:
            return False
        return self._structured_writer.delete_note(filename)

    def read_note(self, filename: str) -> Optional[Dict[str, Any]]:
        """Read a structured memory note and return its metadata + body.

        Returns dict with keys: metadata, body, filename. None if not found.
        """
        if self._structured_writer is None:
            return None
        return self._structured_writer.read_note(filename)

    def list_notes(
        self,
        *,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List memory notes with optional category/tag filters.

        Returns list of note info dicts.
        """
        if self._structured_writer is None:
            return []
        notes = self._structured_writer.list_notes(category=category, tag=tag)
        return [self._file_info_to_dict(n) for n in notes]

    def link_notes(self, source_filename: str, target_filename: str) -> bool:
        """Create a wikilink between two notes.

        Returns True if link was created successfully.
        """
        if self._structured_writer is None:
            return False
        return self._structured_writer.link_notes(source_filename, target_filename)

    def get_memory_index(self) -> Optional[Dict[str, Any]]:
        """Get the full memory index for API responses."""
        if self._index_manager is None:
            return None
        idx = self._index_manager.index
        return {
            "files": {k: self._file_info_to_dict(v) for k, v in idx.files.items()},
            "tag_map": idx.tag_map,
            "total_files": idx.total_files,
            "total_chars": idx.total_chars,
        }

    def get_memory_tags(self) -> Dict[str, int]:
        """Get tag counts from the index."""
        if self._index_manager is None:
            return {}
        idx = self._index_manager.index
        tag_counts: Dict[str, int] = {}
        for tag, filenames in idx.tag_map.items():
            tag_counts[tag] = len(filenames)
        return tag_counts

    def get_memory_graph(self) -> Dict[str, Any]:
        """Get link graph data for visualization."""
        if self._index_manager is None:
            return {"nodes": [], "edges": []}
        idx = self._index_manager.index
        nodes = []
        edges = []
        for fn, info in idx.files.items():
            nodes.append({
                "id": fn,
                "label": info.title or fn.replace(".md", ""),
                "category": info.category,
                "importance": info.importance,
            })
            for target in info.links_to:
                edges.append({"source": fn, "target": target})
        return {"nodes": nodes, "edges": edges}

    def reindex_memory(self) -> int:
        """Force a full rebuild of the memory index.

        Returns total number of indexed files.
        """
        if self._index_manager is None:
            return 0
        self._index_manager.rebuild()
        return self._index_manager.index.total_files

    @staticmethod
    def _file_info_to_dict(info) -> Dict[str, Any]:
        """Convert MemoryFileInfo to dict."""
        return {
            "filename": info.filename,
            "title": info.title,
            "category": info.category,
            "tags": info.tags,
            "importance": info.importance,
            "created": info.created,
            "modified": info.modified,
            "source": info.source,
            "char_count": info.char_count,
            "links_to": info.links_to,
            "linked_from": info.linked_from,
            "summary": info.summary,
        }

    async def record_execution(
        self,
        *,
        input_text: str,
        result_state: Dict[str, Any],
        duration_ms: int,
        execution_number: int = 0,
        success: bool = True,
    ) -> None:
        """Record a structured execution summary to long-term memory.

        Called after each graph invoke/astream to persist a concise,
        structured record of work done — modeled after WORK_LOG.md's
        methodology but designed for long-term memory recall.

        Writes to ``memory/YYYY-MM-DD.md`` with structured sections.
        When the vector memory layer is enabled, the entry is also
        indexed into FAISS (awaited to prevent race conditions with
        ``auto_flush`` / ``vmm.save()``).

        File/DB recording is always active regardless of LTM config.
        Only vector indexing (FAISS) requires LTM to be enabled.

        Args:
            input_text: The user's input prompt.
            result_state: The final AutonomousState dict from the graph.
            duration_ms: Total execution wall-time in milliseconds.
            execution_number: Sequential execution counter for this session.
            success: Whether execution completed without errors.
        """
        try:
            entry = self._build_execution_entry(
                input_text=input_text,
                result_state=result_state,
                duration_ms=duration_ms,
                execution_number=execution_number,
                success=success,
            )
            self._ltm.write_dated(entry)
            logger.info(
                "record_execution: #%d (%d chars) → long-term memory",
                execution_number, len(entry),
            )

            # ── Structured note (dual-write) ─────────────────────────
            if self._structured_writer is not None:
                try:
                    auto_tags = self._extract_execution_tags(
                        input_text, result_state,
                    )
                    status_tag = "success" if success else "failure"
                    all_tags = ["execution", status_tag] + auto_tags
                    imp = "medium" if success else "high"
                    title = (
                        f"Execution #{execution_number} — "
                        f"{input_text[:60].strip()}"
                    )
                    self._structured_writer.write_note(
                        title=title,
                        content=entry,
                        category="daily",
                        tags=all_tags,
                        importance=imp,
                        source="execution",
                    )
                except Exception:
                    logger.debug(
                        "record_execution: structured write failed (non-critical)",
                        exc_info=True,
                    )

            # Index into vector DB (only when LTM config is enabled)
            from service.config.sub_config.general.ltm_config import LTMConfig

            if LTMConfig.is_enabled() and self._vmm.enabled:
                try:
                    date_str = datetime.now(_get_tz()).strftime("%Y-%m-%d")
                    source = f"memory/{date_str}.md"
                    await self._vmm.index_text(entry, source)
                except Exception:
                    logger.debug(
                        "record_execution: vector indexing failed (non-critical)",
                        exc_info=True,
                    )

        except Exception:
            logger.warning(
                "record_execution: failed to write (non-critical)",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Execution entry builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_execution_entry(
        *,
        input_text: str,
        result_state: Dict[str, Any],
        duration_ms: int,
        execution_number: int,
        success: bool,
    ) -> str:
        """Build a structured markdown entry for one graph execution.

        Format:
            ### [✅/❌] Execution #N — <difficulty> path
            > **Task:** <truncated user input>
            > **Duration:** X.Xs | **Iterations:** N/max

            **Result:**
            <truncated final output>

            **TODOs:** (hard path only)
            - ✅ Task title
            - ⬜ Task title

            **Review:** approved/rejected (medium path only)

        Returns:
            Formatted markdown string.
        """
        status_icon = "✅" if success else "❌"

        # --- Extract fields from state ---
        difficulty = result_state.get("difficulty", "unknown")
        iteration = result_state.get("iteration", 0)
        max_iterations = result_state.get("max_iterations", 0)
        error = result_state.get("error")
        completion_signal = result_state.get("completion_signal", "")
        completion_detail = result_state.get("completion_detail", "")

        # Best output: final_answer > answer > last_output
        final_output = (
            result_state.get("final_answer", "")
            or result_state.get("answer", "")
            or result_state.get("last_output", "")
            or ""
        )

        # Truncate for readability
        input_preview = input_text[:_LTM_INPUT_PREVIEW]
        if len(input_text) > _LTM_INPUT_PREVIEW:
            input_preview += "..."

        output_preview = final_output[:_LTM_OUTPUT_PREVIEW]
        if len(final_output) > _LTM_OUTPUT_PREVIEW:
            output_preview += "..."

        # Duration formatting
        if duration_ms >= 60_000:
            duration_str = f"{duration_ms / 60_000:.1f}m"
        elif duration_ms >= 1_000:
            duration_str = f"{duration_ms / 1_000:.1f}s"
        else:
            duration_str = f"{duration_ms}ms"

        # --- Build markdown ---
        lines: list[str] = []

        # Header
        lines.append(
            f"### [{status_icon}] Execution #{execution_number}"
            f" — {difficulty} path"
        )
        lines.append("")

        # Task & metrics
        lines.append(f"> **Task:** {input_preview}")
        lines.append(
            f"> **Duration:** {duration_str}"
            f" | **Iterations:** {iteration}/{max_iterations}"
        )
        lines.append("")

        # TODO list (hard path)
        todos = result_state.get("todos") or []
        if todos and difficulty == "hard":
            lines.append("**TODOs:**")
            for todo in todos:
                title = todo.get("title", "Untitled")
                status = todo.get("status", "pending")
                if status in ("completed",):
                    icon = "✅"
                elif status in ("in_progress",):
                    icon = "🔄"
                elif status in ("failed",):
                    icon = "❌"
                else:
                    icon = "⬜"

                result_text = todo.get("result", "")
                if result_text:
                    result_text = result_text[:_LTM_TODO_RESULT_PREVIEW]
                    if len(todo.get("result", "")) > _LTM_TODO_RESULT_PREVIEW:
                        result_text += "..."
                    lines.append(f"- {icon} **{title}** → {result_text}")
                else:
                    lines.append(f"- {icon} **{title}**")
            lines.append("")

        # Review feedback (medium path)
        review_result = result_state.get("review_result")
        review_feedback = result_state.get("review_feedback")
        if review_result and difficulty == "medium":
            feedback_preview = ""
            if review_feedback:
                feedback_preview = f" — {review_feedback[:200]}"
                if len(review_feedback) > 200:
                    feedback_preview += "..."
            lines.append(f"**Review:** {review_result}{feedback_preview}")
            lines.append("")

        # Completion signal
        if completion_signal and completion_signal not in ("none", "continue"):
            detail = f" ({completion_detail})" if completion_detail else ""
            lines.append(f"**Signal:** {completion_signal}{detail}")
            lines.append("")

        # Error
        if error:
            lines.append(f"**Error:** {error[:300]}")
            lines.append("")

        # Result output
        if output_preview:
            lines.append("**Result:**")
            lines.append(output_preview)
            lines.append("")

        # Fallback info
        fallback = result_state.get("fallback")
        if fallback and fallback.get("degraded"):
            lines.append(
                f"**Model Fallback:** {fallback.get('original_model', '?')}"
                f" → {fallback.get('current_model', '?')}"
                f" (attempts: {fallback.get('attempts', 0)})"
            )
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _extract_execution_tags(
        input_text: str,
        result_state: Dict[str, Any],
    ) -> List[str]:
        """Extract auto-tags from execution input and state."""
        tags: List[str] = []
        difficulty = result_state.get("difficulty")
        if difficulty:
            tags.append(difficulty)
        if result_state.get("todos"):
            tags.append("todos")
        if result_state.get("review_result"):
            tags.append("reviewed")
        # Extract simple keyword tags from input
        text = input_text.lower()
        keyword_tags = {
            "debug": "debug",
            "fix": "fix",
            "error": "error",
            "test": "test",
            "deploy": "deploy",
            "build": "build",
            "refactor": "refactor",
            "design": "design",
            "analyze": "analysis",
            "review": "review",
        }
        for keyword, tag in keyword_tags.items():
            if keyword in text and tag not in tags:
                tags.append(tag)
        return tags[:10]  # cap at 10

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

    async def build_memory_context_async(
        self,
        query: Optional[str] = None,
        *,
        include_summary: bool = True,
        include_recent: int = 0,
        max_chars: Optional[int] = None,
    ) -> Optional[str]:
        """Async version of ``build_memory_context`` with vector search.

        Includes FAISS vector search results when the vector memory
        layer is enabled, in addition to keyword search and file-based
        retrieval.

        Args:
            query: Optional query to search for relevant memories.
            include_summary: Include session summary if available.
            include_recent: Number of recent messages to include.
            max_chars: Character budget.

        Returns:
            Formatted memory context string, or None.
        """
        budget = max_chars or self._max_inject_chars
        parts: list[str] = []
        total_chars = 0

        # 1. Session summary
        if include_summary:
            summary = self._stm.get_summary()
            if summary and (total_chars + len(summary)) <= budget:
                parts.append(f"<session-summary>\n{summary}\n</session-summary>")
                total_chars += len(summary)

        # 2. Main MEMORY.md
        main_mem = self._ltm.load_main()
        if main_mem and (total_chars + main_mem.char_count) <= budget:
            parts.append(
                f"<long-term-memory source=\"{main_mem.filename}\">\n"
                f"{main_mem.content}\n"
                f"</long-term-memory>"
            )
            total_chars += main_mem.char_count

        # 3. Vector semantic search (if enabled)
        if query and self._vmm.enabled:
            try:
                v_results = await self._vmm.search(query)
                v_context = self._vmm.build_vector_context(
                    v_results, max_chars=budget - total_chars
                )
                if v_context:
                    parts.append(v_context)
                    total_chars += len(v_context)
            except Exception:
                logger.debug(
                    "build_memory_context_async: vector search failed",
                    exc_info=True,
                )

        # 4. Keyword-based memory recall (complementary)
        if query:
            remaining_budget = budget - total_chars
            if remaining_budget > 200:
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

        # 5. Recent transcript messages
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
        """Generate a structured session-end summary for long-term storage.

        Called during session cleanup. Instead of dumping raw transcript,
        produces a concise session summary with conversation statistics
        that is useful for future memory recall.

        Skipped entirely when LTM is disabled in config.

        Args:
            recent_n: Number of recent messages to include excerpts from.

        Returns:
            The flushed text, or None if nothing to flush.
        """
        # Guard: skip when long-term memory is disabled in config
        from service.config.sub_config.general.ltm_config import LTMConfig

        if not LTMConfig.is_enabled():
            logger.debug("auto_flush: LTM disabled by config — skipping")
            return None

        now = datetime.now(_get_tz())
        all_entries = self._stm.load_all()
        if not all_entries:
            return None

        # --- Gather statistics ---
        user_msgs = [e for e in all_entries if "[user]" in e.content.lower()]
        assistant_msgs = [e for e in all_entries if "[assistant]" in e.content.lower()]
        total_chars = sum(e.char_count for e in all_entries)

        # First and last timestamps
        timestamps = [e.timestamp for e in all_entries if e.timestamp]
        first_ts = min(timestamps) if timestamps else None
        last_ts = max(timestamps) if timestamps else None

        duration_str = ""
        if first_ts and last_ts:
            delta = last_ts - first_ts
            total_minutes = int(delta.total_seconds() / 60)
            if total_minutes >= 60:
                duration_str = f"{total_minutes // 60}h {total_minutes % 60}m"
            else:
                duration_str = f"{total_minutes}m"

        # --- Build summary ---
        lines: list[str] = []
        lines.append("### 📋 Session End Summary")
        lines.append("")

        metrics = [f"**Messages:** {len(all_entries)} total"]
        metrics.append(
            f"({len(user_msgs)} user, {len(assistant_msgs)} assistant)"
        )
        if duration_str:
            metrics.append(f"| **Duration:** {duration_str}")
        metrics.append(f"| **Total chars:** {total_chars:,}")
        lines.append(" ".join(metrics))
        lines.append("")

        # Conversation flow: list user requests as bullet points
        if user_msgs:
            lines.append("**Conversation Flow:**")
            for i, entry in enumerate(user_msgs, 1):
                # Extract just the content (strip [user] prefix)
                content = entry.content
                if content.lower().startswith("[user] "):
                    content = content[7:]
                preview = content[:150]
                if len(content) > 150:
                    preview += "..."
                ts_str = ""
                if entry.timestamp:
                    ts_str = f"[{entry.timestamp.strftime('%H:%M')}] "
                lines.append(f"{i}. {ts_str}{preview}")

                # Limit to 20 entries for readability
                if i >= 20:
                    remaining = len(user_msgs) - 20
                    if remaining > 0:
                        lines.append(f"   ... +{remaining} more requests")
                    break
            lines.append("")

        summary_text = "\n".join(lines)

        if len(summary_text) < 50:
            return None  # Too short to bother

        # Save to dated file
        self._ltm.write_dated(summary_text)

        # Persist session summary for future context injection on restore
        self._stm.write_summary(summary_text)

        # Persist vector index
        if self._vmm.enabled:
            self._vmm.save()

        logger.info(
            "auto_flush: session summary (%d chars, %d messages) → long-term",
            len(summary_text), len(all_entries),
        )
        return summary_text

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> MemoryStats:
        """Compute memory statistics.

        Uses DB aggregation when available for efficiency;
        falls back to loading all entries from file.
        """
        # Try lightweight DB aggregation first
        if self._db_manager is not None and self._session_id is not None:
            try:
                from service.database.memory_db_helper import db_memory_stats

                db_stats = db_memory_stats(self._db_manager, self._session_id)
                if db_stats is not None:
                    last_write = None
                    ts_str = db_stats.get("last_write")
                    if ts_str:
                        try:
                            last_write = datetime.fromisoformat(ts_str)
                        except (ValueError, TypeError):
                            pass

                    # Add structured stats from index
                    categories: Dict[str, int] = {}
                    total_tags = 0
                    total_links = 0
                    if self._index_manager is not None:
                        idx = self._index_manager.index
                        for info in idx.files.values():
                            cat = info.category or "root"
                            categories[cat] = categories.get(cat, 0) + 1
                        total_tags = len(idx.tag_map)
                        total_links = sum(
                            len(info.links_to) for info in idx.files.values()
                        )

                    return MemoryStats(
                        long_term_entries=db_stats.get("long_term_entries", 0),
                        short_term_entries=db_stats.get("short_term_entries", 0),
                        long_term_chars=db_stats.get("long_term_chars", 0),
                        short_term_chars=db_stats.get("short_term_chars", 0),
                        total_files=db_stats.get("total_files", 0),
                        last_write=last_write,
                        categories=categories,
                        total_tags=total_tags,
                        total_links=total_links,
                    )
            except Exception:
                pass

        # Fallback: load all entries from file system
        ltm_entries = self._ltm.load_all()
        stm_entries = self._stm.load_all()

        ltm_chars = sum(e.char_count for e in ltm_entries)
        stm_chars = sum(e.char_count for e in stm_entries)

        all_timestamps = [
            e.timestamp for e in ltm_entries + stm_entries
            if e.timestamp is not None
        ]
        last_write = max(all_timestamps) if all_timestamps else None

        # Structured stats from index
        categories: Dict[str, int] = {}
        total_tags = 0
        total_links = 0
        if self._index_manager is not None:
            idx = self._index_manager.index
            for info in idx.files.values():
                cat = info.category or "root"
                categories[cat] = categories.get(cat, 0) + 1
            total_tags = len(idx.tag_map)
            total_links = sum(len(info.links_to) for info in idx.files.values())

        return MemoryStats(
            long_term_entries=len(ltm_entries),
            short_term_entries=len(stm_entries),
            long_term_chars=ltm_chars,
            short_term_chars=stm_chars,
            total_files=len(ltm_entries),
            last_write=last_write,
            categories=categories,
            total_tags=total_tags,
            total_links=total_links,
        )
