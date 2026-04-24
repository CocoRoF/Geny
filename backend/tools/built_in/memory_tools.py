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
from typing import Optional

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
            category: Category — one of: topics, decisions, insights, people, projects, reference (default: topics).
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


# ============================================================================
# Memory Read Tool
# ============================================================================


class MemoryReadTool(BaseTool):
    """Read a specific memory note by filename."""

    name = "memory_read"
    description = (
        "Read a specific memory note by its filename. Returns the full content "
        "including metadata (tags, category, importance) and body text."
    )

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
            return _error(f"Note not found: {filename}")
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


# ============================================================================
# Memory Search Tool
# ============================================================================


class MemorySearchTool(BaseTool):
    """Search across all memory notes using text and vector search."""

    name = "memory_search"
    description = (
        "Search your memory for relevant notes. Uses both text matching "
        "and semantic vector search to find the most relevant results. "
        "Great for recalling past decisions, knowledge, or context."
    )

    def run(
        self,
        session_id: str,
        query: str,
        max_results: int = 10,
    ) -> str:
        """Search memory notes.

        Args:
            session_id: Your session ID.
            query: Search query — can be a keyword, phrase, or question.
            max_results: Maximum number of results to return (default: 10).
        """
        mem = _get_memory_manager(session_id)
        if mem is None:
            return _error(f"Session not found: {session_id}")

        results = mem.search(query, max_results=max_results)
        items = []
        for r in results:
            entry = r.entry
            items.append({
                "filename": entry.filename,
                "source": entry.source.value if hasattr(entry.source, "value") else str(entry.source),
                "snippet": r.snippet[:500],
                "score": round(r.score, 4),
                "title": getattr(entry, "title", None),
                "category": getattr(entry, "category", None),
                "tags": getattr(entry, "tags", None),
            })
        return _ok({"query": query, "total": len(items), "results": items})


# ============================================================================
# Memory List Tool
# ============================================================================


class MemoryListTool(BaseTool):
    """List all memory notes, optionally filtered by category or tag."""

    name = "memory_list"
    description = (
        "List all your memory notes. You can filter by category "
        "(topics, decisions, insights, people, projects, reference) "
        "or by tag to narrow down results."
    )

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
]
