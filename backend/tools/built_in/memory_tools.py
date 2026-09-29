"""
Memory Tools — Built-in tools for structured knowledge management.

These tools allow agents to read, write, search, and organize their
long-term memory as structured Markdown notes with YAML frontmatter,
tags, categories, and wikilinks (Obsidian-like knowledge base).

Tool categories:
  - Read/Write: create, read, update, delete notes
  - Search: full-text + vector search across memory
  - Organization: list notes, create links between notes

These tools are auto-loaded by ToolLoader (matches *_tools.py pattern).
"""

from __future__ import annotations

import json
from logging import getLogger
from typing import Any, Dict, List, Optional

from geny_executor.tools.base import ToolCapabilities
from tools.base import BaseTool

logger = getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================


def _get_agent_manager():
    """Lazy import to avoid circular imports at module load time."""
    from service.executor import get_agent_session_manager
    return get_agent_session_manager()


def _get_memory_manager(session_id: str):
    """Resolve session and return its memory_manager, or None."""
    manager = _get_agent_manager()
    agent = manager.get_agent(session_id)
    if agent is None:
        agent = manager.resolve_session(session_id)
    if agent is None:
        return None
    return getattr(agent, "memory_manager", None)


def _error(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _ok(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ============================================================================
# Memory Write Tool
# ============================================================================


class MemoryWriteTool(BaseTool):
    """Create a new structured memory note with title, content, tags, and category."""

    name = "memory_write"
    description = (
        "Create a new memory note. Use this to save important information, "
        "decisions, knowledge, or insights as a structured note with metadata. "
        "The note will be stored as a Markdown file with YAML frontmatter."
    )
    # New file write — must serialize to avoid filename collision.
    CAPABILITIES = ToolCapabilities(concurrency_safe=False)

    def run(
        self,
        session_id: str,
        title: str,
        content: str,
        category: str = "topics",
        tags: str = "",
        importance: str = "medium",
    ) -> str:
        """Create a new structured memory note.

        Args:
            session_id: Your session ID.
            title: Title of the note.
            content: Body content in Markdown format.
            category: Category — one of: topics, projects, insights, daily, critical (default: topics; unknown values fall back to topics).
            tags: Comma-separated tags, e.g. "python,architecture,important".
            importance: Importance level — low, medium, high, critical (default: medium).
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        filename = mem.write_note(
            title=title,
            content=content,
            category=category,
            tags=tag_list,
            importance=importance,
            source="agent",
        )
        if filename:
            return _ok({
                "status": "created",
                "filename": filename,
                "title": title,
                "category": category,
                "tags": tag_list,
            })
        return _error("Failed to create memory note")

    async def arun(
        self,
        session_id: str,
        title: str,
        content: str,
        category: str = "topics",
        tags: str = "",
        importance: str = "medium",
    ) -> str:
        """Async sibling of :meth:`run` — calls ``mem.awrite_note``
        directly so the tool dispatch never crosses the sync→async
        bridge."""
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        awrite = getattr(mem, "awrite_note", None)
        if callable(awrite):
            filename = await awrite(
                title=title, content=content, category=category,
                tags=tag_list, importance=importance, source="agent",
            )
        else:
            filename = mem.write_note(
                title=title, content=content, category=category,
                tags=tag_list, importance=importance, source="agent",
            )
        if filename:
            return _ok({
                "status": "created",
                "filename": filename,
                "title": title,
                "category": category,
                "tags": tag_list,
            })
        return _error("Failed to create memory note")


# ============================================================================
# Memory Read Tool
# ============================================================================

#: Suggestions on a miss, and how many filenames are compared.
_MISS_SUGGESTIONS = 5
_MISS_SCAN_LIMIT = 500


def _note_names(notes) -> list:
    return [str(n.get("filename")) for n in (notes or [])[:_MISS_SCAN_LIMIT] if n.get("filename")]


def _read_miss_payload(filename: str, names: list) -> str:
    """"Not found" with the real filenames closest to the one asked for.

    A bare "Note not found" left the model guessing the next name — it
    invents filenames from titles, and each wrong guess is another round
    trip. The vault assigns the names; show the nearest ones.
    """
    import difflib

    payload = {"error": f"Note not found: {filename}"}
    if not names:
        payload["hint"] = "This memory has no notes yet. Write one with memory_write before reading."
        return json.dumps(payload, ensure_ascii=False)
    base = filename.rsplit("/", 1)[-1]
    by_base = {n.rsplit("/", 1)[-1]: n for n in names}
    close = difflib.get_close_matches(filename, names, n=_MISS_SUGGESTIONS, cutoff=0.5)
    close += [
        by_base[b]
        for b in difflib.get_close_matches(base, list(by_base), n=_MISS_SUGGESTIONS, cutoff=0.5)
        if by_base[b] not in close
    ]
    payload["did_you_mean"] = close[:_MISS_SUGGESTIONS] or names[:_MISS_SUGGESTIONS]
    payload["hint"] = (
        "Filenames are assigned by the memory, not chosen by you — do not guess them. "
        "Use memory_search (by content) or memory_list (by category) to get a real "
        "filename, then read that."
    )
    return json.dumps(payload, ensure_ascii=False)


async def _read_miss(mem, filename: str) -> str:
    try:
        alist = getattr(mem, "alist_notes", None)
        notes = await alist() if callable(alist) else mem.list_notes()
    except Exception:  # noqa: BLE001 — the miss is still a miss
        notes = []
    return _read_miss_payload(filename, _note_names(notes))



class MemoryReadTool(BaseTool):
    """Read a specific memory note by filename."""

    name = "memory_read"
    description = (
        "Read a specific memory note by its filename. Returns the full content "
        "including metadata (tags, category, importance) and body text."
    )
    CAPABILITIES = ToolCapabilities(concurrency_safe=True, read_only=True, idempotent=True)

    def run(self, session_id: str, filename: str) -> str:
        """Read a memory note.

        Args:
            session_id: Your session ID.
            filename: The filename of the note to read (e.g. "my_note.md").
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        note = mem.read_note(filename)
        if note is None:
            return _read_miss_payload(filename, _note_names(mem.list_notes()))
        return _ok(note)

    async def arun(self, session_id: str, filename: str) -> str:
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")
        aread = getattr(mem, "aread_note", None)
        note = await aread(filename) if callable(aread) else mem.read_note(filename)
        if note is None:
            return await _read_miss(mem, filename)
        return _ok(note)


# ============================================================================
# Memory Update Tool
# ============================================================================


class MemoryUpdateTool(BaseTool):
    """Update an existing memory note's content, tags, or importance."""

    name = "memory_update"
    description = (
        "Update an existing memory note. You can change its body content, "
        "tags, or importance level. Only provided fields will be updated."
    )
    # File mutation — must serialize against concurrent updates to same note.
    CAPABILITIES = ToolCapabilities(concurrency_safe=False)

    def run(
        self,
        session_id: str,
        filename: str,
        content: str = "",
        tags: str = "",
        importance: str = "",
    ) -> str:
        """Update an existing memory note.

        Args:
            session_id: Your session ID.
            filename: The filename of the note to update.
            content: New body content (leave empty to keep current).
            tags: New comma-separated tags (leave empty to keep current).
            importance: New importance level (leave empty to keep current).
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        kwargs = {}
        if content:
            kwargs["body"] = content
        if tags:
            kwargs["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if importance:
            kwargs["importance"] = importance

        if not kwargs:
            return _error("No fields to update. Provide content, tags, or importance.")

        ok = mem.update_note(filename, **kwargs)
        if ok:
            return _ok({"status": "updated", "filename": filename, **kwargs})
        return _error(f"Failed to update note: {filename}")

    async def arun(
        self,
        session_id: str,
        filename: str,
        content: str = "",
        tags: str = "",
        importance: str = "",
    ) -> str:
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        kwargs: Dict[str, Any] = {}
        if content:
            kwargs["body"] = content
        if tags:
            kwargs["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if importance:
            kwargs["importance"] = importance

        if not kwargs:
            return _error("No fields to update. Provide content, tags, or importance.")

        aupdate = getattr(mem, "aupdate_note", None)
        ok = (
            await aupdate(filename, **kwargs) if callable(aupdate)
            else mem.update_note(filename, **kwargs)
        )
        if ok:
            return _ok({"status": "updated", "filename": filename, **kwargs})
        return _error(f"Failed to update note: {filename}")


# ============================================================================
# Memory Delete Tool
# ============================================================================


class MemoryDeleteTool(BaseTool):
    """Delete a memory note by filename."""

    name = "memory_delete"
    description = (
        "Delete a memory note permanently. Use with caution — "
        "this removes the note from both file storage and database."
    )
    # Permanent delete — destructive, idempotent (deleting twice is a no-op).
    CAPABILITIES = ToolCapabilities(
        concurrency_safe=False, destructive=True, idempotent=True,
    )

    def run(self, session_id: str, filename: str) -> str:
        """Delete a memory note.

        Args:
            session_id: Your session ID.
            filename: The filename of the note to delete.
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        ok = mem.delete_note(filename)
        if ok:
            return _ok({"status": "deleted", "filename": filename})
        return _error(f"Failed to delete note: {filename}")

    async def arun(self, session_id: str, filename: str) -> str:
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")
        adelete = getattr(mem, "adelete_note", None)
        ok = (
            await adelete(filename) if callable(adelete)
            else mem.delete_note(filename)
        )
        if ok:
            return _ok({"status": "deleted", "filename": filename})
        return _error(f"Failed to delete note: {filename}")


# ============================================================================
# Memory Search Tool
# ============================================================================


class MemorySearchTool(BaseTool):
    """Search across all memory notes using text and vector search."""

    name = "memory_search"
    description = (
        "Search your memory for relevant notes by text + vector. "
        "Use this when you have a *query* but don't know which "
        "specific file holds the answer. "
        "If you instead want to *browse* a folder, prefer "
        "`memory_categories` (vault overview) → `memory_list("
        "category=...)` (folder contents) — that ladder is cheaper "
        "and more deterministic than search. "
        "Optional InteractionEvent filters: `counterpart` narrows "
        "to events with a specific other party (e.g. "
        "'paired_subworker', 'user', or a session id), `kinds` "
        "narrows by event kind (e.g. ['tool_run_summary', "
        "'task_result']). Filters apply only to InteractionEvent "
        "lines — non-event memories (long-term notes, knowledge) "
        "are returned regardless."
    )
    CAPABILITIES = ToolCapabilities(
        concurrency_safe=True, read_only=True, idempotent=True,
        max_result_chars=20_000,
    )

    def run(
        self,
        session_id: str,
        query: str,
        max_results: int = 10,
        counterpart: Optional[str] = None,
        kinds: Optional[List[str]] = None,
    ) -> str:
        """Search memory notes.

        Args:
            session_id: Your session ID.
            query: Search query — can be a keyword, phrase, or question.
            max_results: Maximum number of results to return (default: 10).
            counterpart: Optional InteractionEvent filter — alias
                ('paired_subworker' / 'user' / 'self') or canonical id.
                Resolves against the caller's own session
                (`_linked_session_id`, `_owner_username`).
            kinds: Optional InteractionEvent filter — list of kinds
                to allow (e.g. ['tool_run_summary']).
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        # Cycle 20260430_2 B5 — InteractionEvent filters. Resolution
        # mirrors `memory_status` / `memory_with` so any tool in the
        # progressive ladder accepts the same alias vocabulary.
        canonical_counterpart: Optional[str] = None
        if counterpart:
            try:
                from tools.built_in.memory_inspect_tools import (
                    _get_caller as _get_inspect_caller,
                    _resolve_counterpart_id,
                )
                caller_agent = _get_inspect_caller(session_id)
                canonical_counterpart = _resolve_counterpart_id(
                    caller_agent, counterpart,
                )
            except Exception:
                logger.debug(
                    "memory_search: counterpart resolution failed",
                    exc_info=True,
                )
                canonical_counterpart = None
            # Alias resolved to None (e.g. unpaired) → still set the
            # marker so we can short-circuit InteractionEvent lines
            # that have a specific counterpart_id, while leaving
            # non-event entries (LTM notes / knowledge) untouched.

        kind_filter = (
            {str(k) for k in kinds if isinstance(k, str)}
            if kinds else None
        )

        results = mem.search(query, max_results=max_results)
        return self._format(
            query=query,
            results=results,
            counterpart=counterpart,
            canonical_counterpart=canonical_counterpart,
            kind_filter=kind_filter,
        )

    async def arun(
        self,
        session_id: str,
        query: str,
        max_results: int = 10,
        counterpart: Optional[str] = None,
        kinds: Optional[List[str]] = None,
    ) -> str:
        """Async sibling of :meth:`run`.

        Memory v2 PR 12 — when invoked through the async tool path
        (which the executor uses for ``memory_search``), this calls
        :meth:`SessionMemoryManager.search_async` so the result set
        also includes vector-similarity hits. That fixes the case
        where a Korean query must match an English-titled note via
        embedding similarity rather than keyword density. Falls
        back to the sync path when ``search_async`` is unavailable
        (e.g. older managers).
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        # Resolve counterpart alias the same way as ``run``.
        canonical_counterpart: Optional[str] = None
        if counterpart:
            try:
                from tools.built_in.memory_inspect_tools import (
                    _get_caller as _get_inspect_caller,
                    _resolve_counterpart_id,
                )
                caller_agent = _get_inspect_caller(session_id)
                canonical_counterpart = _resolve_counterpart_id(
                    caller_agent, counterpart,
                )
            except Exception:
                logger.debug(
                    "memory_search.arun: counterpart resolution failed",
                    exc_info=True,
                )
                canonical_counterpart = None

        kind_filter = (
            {str(k) for k in kinds if isinstance(k, str)}
            if kinds else None
        )

        search_async = getattr(mem, "search_async", None)
        if callable(search_async):
            try:
                results = await search_async(query, max_results=max_results)
            except Exception:
                logger.debug(
                    "memory_search.arun: search_async failed; falling back",
                    exc_info=True,
                )
                results = mem.search(query, max_results=max_results)
        else:
            results = mem.search(query, max_results=max_results)
        return self._format(
            query=query,
            results=results,
            counterpart=counterpart,
            canonical_counterpart=canonical_counterpart,
            kind_filter=kind_filter,
        )

    @staticmethod
    def _format(
        *,
        query: str,
        results,
        counterpart: Optional[str],
        canonical_counterpart: Optional[str],
        kind_filter,
    ) -> str:
        """Shared formatter for ``run`` / ``arun``. Applies the
        InteractionEvent filters (counterpart/kind) to event-tagged
        hits, builds the progressive-disclosure-friendly snippet,
        and serialises to JSON.
        """
        items = []
        for r in results:
            entry = r.entry
            entry_meta = getattr(entry, "metadata", None) or {}
            event_id = entry_meta.get("event_id")
            entry_kind = entry_meta.get("kind")
            entry_counterpart = entry_meta.get("counterpart_id")

            # Filtering only narrows InteractionEvent lines (those
            # with an event_id). Non-event memories (LTM notes /
            # knowledge / curated) pass through so callers asking
            # "find me everything about X with my Sub-Worker" don't
            # accidentally lose the durable knowledge layer.
            if event_id:
                if counterpart and canonical_counterpart and entry_counterpart != canonical_counterpart:
                    continue
                if counterpart and canonical_counterpart is None and entry_counterpart:
                    # Caller asked for an alias that didn't resolve
                    # (unpaired) — drop event-tagged hits.
                    continue
                if kind_filter is not None and entry_kind not in kind_filter:
                    continue

            # Memory v2 PR 14 — progressive disclosure friendly
            # snippet (plan §5.5). Only the first non-empty line of
            # the snippet, capped at 200 chars, so callers see a
            # *hint* not a body. Full body via memory_read(filename).
            snippet_first_line = ""
            raw_snippet = r.snippet or ""
            for _line in raw_snippet.splitlines():
                _line = _line.strip()
                if _line:
                    snippet_first_line = _line[:200]
                    if len(_line) > 200:
                        snippet_first_line = snippet_first_line.rstrip() + "…"
                    break
            item = {
                "filename": entry.filename,
                "source": entry.source.value if hasattr(entry.source, "value") else str(entry.source),
                "snippet_first_line": snippet_first_line,
                "score": round(r.score, 4),
                "match_type": getattr(r, "match_type", None),
                "title": getattr(entry, "title", None),
                "category": getattr(entry, "category", None),
                "tags": getattr(entry, "tags", None),
                "char_count": getattr(entry, "char_count", None),
            }
            if event_id:
                item.update({
                    "event_id": event_id,
                    "kind": entry_kind,
                    "counterpart_id": entry_counterpart,
                })
            items.append(item)
        return _ok({
            "query": query,
            "total": len(items),
            "results": items,
            "filters": {
                "counterpart": counterpart,
                "counterpart_resolved": canonical_counterpart,
                "kinds": list(kind_filter) if kind_filter else None,
            },
        })


# ============================================================================
# Memory List Tool
# ============================================================================


class MemoryCategoriesTool(BaseTool):
    """Tier-1 of progressive disclosure — return the vault's category map.

    The agent should call this *first* to discover what kinds of
    things are remembered before reaching for ``memory_list`` /
    ``memory_search`` / ``memory_read``. The response is the same
    aggregate the system-prompt vault map renders, but in
    structured form so the agent can branch on counts /
    descriptions programmatically.
    """

    name = "memory_categories"
    description = (
        "Return the memory vault's category map. Use this FIRST when "
        "you need to find something but don't know which folder. "
        "Each entry has: file_count, total_chars, last_modified, and "
        "a one-line description of what that category holds. After "
        "picking a category, call memory_list(category=...) to see "
        "the files inside it, then memory_read(filename=...) for "
        "the body."
    )
    CAPABILITIES = ToolCapabilities(
        concurrency_safe=True, read_only=True, idempotent=True,
        max_result_chars=4_000,
    )

    def run(self, session_id: str) -> str:
        """Return the root memory manifest (categories + totals).

        Args:
            session_id: Your session ID.
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        # Sprint 3 step 4 — ``build_vault_map`` moved to the manager
        # itself; the legacy ``index_manager`` adapter was retired.
        build = getattr(mem, "build_vault_map", None)
        if not callable(build):
            return _error("Memory index not initialised")
        try:
            vmap = build()
        except Exception as exc:
            return _error(f"Failed to build vault map: {exc}")

        # Sort categories by file_count desc so the most useful ones
        # surface first when the agent skims the response.
        categories = vmap.get("categories") or {}
        ranked = sorted(
            (
                {
                    "category": cat,
                    "file_count": int(d.get("files") or 0),
                    "last_modified": d.get("last_modified") or "",
                    "description": d.get("description") or "",
                }
                for cat, d in categories.items()
            ),
            key=lambda x: (-x["file_count"], x["category"]),
        )
        return _ok({
            "categories": ranked,
            "total_files": int(vmap.get("total_files") or 0),
            "memory_md_preview": vmap.get("memory_md_preview") or "",
            "next_steps": [
                "memory_list(category=<name>) — list files in a folder",
                "memory_search(query=<text>, category=<name>) — narrow search",
                "memory_read(filename=<path>) — open a specific note",
            ],
        })

    async def arun(self, session_id: str) -> str:
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")
        abuild = getattr(mem, "abuild_vault_map", None)
        build = getattr(mem, "build_vault_map", None)
        try:
            if callable(abuild):
                vmap = await abuild()
            elif callable(build):
                vmap = build()
            else:
                return _error("Memory index not initialised")
        except Exception as exc:
            return _error(f"Failed to build vault map: {exc}")
        categories = vmap.get("categories") or {}
        ranked = sorted(
            (
                {
                    "category": cat,
                    "file_count": int(d.get("files") or 0),
                    "last_modified": d.get("last_modified") or "",
                    "description": d.get("description") or "",
                }
                for cat, d in categories.items()
            ),
            key=lambda x: (-x["file_count"], x["category"]),
        )
        return _ok({
            "categories": ranked,
            "total_files": int(vmap.get("total_files") or 0),
            "memory_md_preview": vmap.get("memory_md_preview") or "",
            "next_steps": [
                "memory_list(category=<name>) — list files in a folder",
                "memory_search(query=<text>, category=<name>) — narrow search",
                "memory_read(filename=<path>) — open a specific note",
            ],
        })


class MemoryListTool(BaseTool):
    """List memory notes in a single category (Tier 2 — folder browse)."""

    name = "memory_list"
    description = (
        "List memory notes in a single category. Pass `category` "
        "(e.g. 'conversations', 'critical', 'topics', 'projects', "
        "'insights', 'daily', 'executions', 'dms'). Optional `tag` "
        "narrows further. Use `memory_categories` first if you "
        "don't know which category to pick. Returns lightweight "
        "metadata (filename, title, summary, importance, modified, "
        "session_id, turn_count for rollups) — call "
        "`memory_read(filename)` for the full body."
    )
    CAPABILITIES = ToolCapabilities(concurrency_safe=True, read_only=True, idempotent=True)

    def run(
        self,
        session_id: str,
        category: str = "",
        tag: str = "",
    ) -> str:
        """List memory notes.

        Args:
            session_id: Your session ID.
            category: Filter by category (leave empty for all).
            tag: Filter by tag (leave empty for all).
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        kwargs = {}
        if category:
            kwargs["category"] = category
        if tag:
            kwargs["tag"] = tag

        notes = mem.list_notes(**kwargs)
        return _ok({
            "total": len(notes),
            "filters": {"category": category or None, "tag": tag or None},
            "notes": notes,
        })

    async def arun(
        self,
        session_id: str,
        category: str = "",
        tag: str = "",
    ) -> str:
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")
        kwargs: Dict[str, Any] = {}
        if category:
            kwargs["category"] = category
        if tag:
            kwargs["tag"] = tag
        alist = getattr(mem, "alist_notes", None)
        notes = await alist(**kwargs) if callable(alist) else mem.list_notes(**kwargs)
        return _ok({
            "total": len(notes),
            "filters": {"category": category or None, "tag": tag or None},
            "notes": notes,
        })


# ============================================================================
# Memory Link Tool
# ============================================================================


class MemoryLinkTool(BaseTool):
    """Create a wikilink between two memory notes."""

    name = "memory_link"
    description = (
        "Create a link between two memory notes (like a wikilink). "
        "This helps build a connected knowledge graph where related "
        "notes reference each other."
    )
    # Mutates note bodies — must serialize. Idempotent (same link added twice = no-op).
    CAPABILITIES = ToolCapabilities(concurrency_safe=False, idempotent=True)

    def run(
        self,
        session_id: str,
        source_filename: str,
        target_filename: str,
    ) -> str:
        """Link two memory notes.

        Args:
            session_id: Your session ID.
            source_filename: The note that will contain the link.
            target_filename: The note being linked to.
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        ok = mem.link_notes(source_filename, target_filename)
        if ok:
            return _ok({
                "status": "linked",
                "source": source_filename,
                "target": target_filename,
            })
        return _error(f"Failed to link {source_filename} -> {target_filename}")

    async def arun(
        self,
        session_id: str,
        source_filename: str,
        target_filename: str,
    ) -> str:
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")
        alink = getattr(mem, "alink_notes", None)
        ok = (
            await alink(source_filename, target_filename) if callable(alink)
            else mem.link_notes(source_filename, target_filename)
        )
        if ok:
            return _ok({
                "status": "linked",
                "source": source_filename,
                "target": target_filename,
            })
        return _error(f"Failed to link {source_filename} -> {target_filename}")


# ============================================================================
# Memory Pin Tool (Memory v2 PR 12 — T1 always-inject surface)
# ============================================================================


class MemoryPinTool(BaseTool):
    """Pin a fact into the always-inject ``memory/critical/`` category.

    This is how an agent records a "must-always-be-known" fact about
    the user, the persona, or the ongoing work — the next turn's
    retriever lifts these into the system prompt's
    ``# Pinned Facts`` section regardless of the user's query
    wording. Use ``memory_write`` for everything else; reserve
    ``memory_pin`` for facts the agent must never claim ignorance
    of (호칭, persona-defining preferences, binding decisions).
    """

    name = "memory_pin"
    description = (
        "Pin a fact so it is always present in the system prompt's "
        "Pinned Facts section, regardless of the user's query. Use "
        "this for must-know facts (how the user wants to be "
        "addressed, the agent's name, binding preferences, ongoing "
        "project goals). Other notes go through ``memory_write`` "
        "instead. Pinned facts should be short and durable; do not "
        "pin per-turn observations or transient state."
    )
    # New file write — serialize to avoid filename collision.
    CAPABILITIES = ToolCapabilities(concurrency_safe=False)

    def run(
        self,
        session_id: str,
        title: str,
        content: str,
        tags: str = "",
        importance: str = "high",
    ) -> str:
        """Pin a fact to ``memory/critical/<slug>.md``.

        Args:
            session_id: Your session ID.
            title: Short title for the pinned fact (3-10 words).
            content: The fact itself (1-3 sentences).
            tags: Comma-separated tags, e.g. "user,preference".
            importance: ``high`` or ``critical`` — this tool always
                pins regardless of the value, but the importance is
                stored in frontmatter for downstream consumers.
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        if not isinstance(title, str) or not title.strip():
            return _error("title must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            return _error("content must be a non-empty string")

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        for marker in ("pinned",):
            if marker not in tag_list:
                tag_list.append(marker)

        normalized_importance = (importance or "high").strip().lower()
        if normalized_importance not in {"low", "medium", "high", "critical"}:
            normalized_importance = "high"

        # Import locally so the constant is not a hard import-time
        # dependency (keeps tool-module load order forgiving).
        from service.memory.note_utils import PINNED_CATEGORY

        filename = mem.write_note(
            title=title.strip(),
            content=content.strip(),
            category=PINNED_CATEGORY,
            tags=tag_list,
            importance=normalized_importance,
            source="agent_pin",
        )
        if filename:
            return _ok({
                "status": "pinned",
                "filename": filename,
                "title": title.strip(),
                "category": PINNED_CATEGORY,
                "tags": tag_list,
                "importance": normalized_importance,
            })
        return _error("Failed to pin memory note")

    async def arun(
        self,
        session_id: str,
        title: str,
        content: str,
        tags: str = "",
        importance: str = "high",
    ) -> str:
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        if not isinstance(title, str) or not title.strip():
            return _error("title must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            return _error("content must be a non-empty string")

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        for marker in ("pinned",):
            if marker not in tag_list:
                tag_list.append(marker)

        normalized_importance = (importance or "high").strip().lower()
        if normalized_importance not in {"low", "medium", "high", "critical"}:
            normalized_importance = "high"

        from service.memory.note_utils import PINNED_CATEGORY

        awrite = getattr(mem, "awrite_note", None)
        if callable(awrite):
            filename = await awrite(
                title=title.strip(),
                content=content.strip(),
                category=PINNED_CATEGORY,
                tags=tag_list,
                importance=normalized_importance,
                source="agent_pin",
            )
        else:
            filename = mem.write_note(
                title=title.strip(),
                content=content.strip(),
                category=PINNED_CATEGORY,
                tags=tag_list,
                importance=normalized_importance,
                source="agent_pin",
            )
        if filename:
            return _ok({
                "status": "pinned",
                "filename": filename,
                "title": title.strip(),
                "category": PINNED_CATEGORY,
                "tags": tag_list,
                "importance": normalized_importance,
            })
        return _error("Failed to pin memory note")


# ============================================================================
# Explicit TOOLS list for ToolLoader
# ============================================================================

TOOLS = [
    MemoryWriteTool(),
    MemoryReadTool(),
    MemoryUpdateTool(),
    MemoryDeleteTool(),
    MemorySearchTool(),
    MemoryListTool(),
    MemoryLinkTool(),
    MemoryPinTool(),
    MemoryCategoriesTool(),
]
