"""
Curated Knowledge Tools — Built-in tools for agent access to curated knowledge.

These tools allow agents to search, read, and list curated knowledge notes
that have been quality-filtered from User Opsidian. They also provide
optional read access to User Opsidian notes (controlled by LTMConfig).

Tool categories:
  - Read: search, read, list curated knowledge notes
  - Opsidian: browse and read User Opsidian notes (gated by config)
  - Promote: promote session notes to curated knowledge

These tools are auto-loaded by ToolLoader (matches *_tools.py pattern).
"""

from __future__ import annotations

import json
from logging import getLogger

from tools.base import BaseTool

logger = getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

def _get_agent_manager():
    from service.executor import get_agent_session_manager
    return get_agent_session_manager()


def _get_context_managers(session_id: str):
    """Get curated_knowledge_manager and user_opsidian_manager from an agent session.

    Returns (curated_mgr, opsidian_mgr) tuple. Either may be None.
    """
    manager = _get_agent_manager()
    agent = manager.get_agent(session_id)
    if agent is None:
        agent = manager.resolve_session(session_id)
    if agent is None:
        return None, None

    # Try to get from the agent's graph context
    curated = getattr(agent, "_curated_knowledge_manager", None)
    opsidian = getattr(agent, "_user_opsidian_manager", None)

    # Fallback: try from the owner_username
    if curated is None or opsidian is None:
        username = getattr(agent, "_owner_username", None) or getattr(agent, "owner_username", None)
        if username:
            if curated is None:
                try:
                    from service.memory.curated_knowledge import get_curated_knowledge_manager
                    curated = get_curated_knowledge_manager(username)
                except Exception:
                    pass
            if opsidian is None:
                try:
                    from service.memory.user_opsidian import get_user_opsidian_manager
                    opsidian = get_user_opsidian_manager(username)
                except Exception:
                    pass

    return curated, opsidian


def _get_ltm_config():
    """Load LTMConfig for feature gating."""
    try:
        from service.config import get_config_manager
        from service.config.sub_config.general.ltm_config import LTMConfig
        mgr = get_config_manager()
        return mgr.load_config(LTMConfig)
    except Exception:
        return None


def _error(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _ok(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ============================================================================
# Knowledge Search Tool
# ============================================================================

class KnowledgeSearchTool(BaseTool):
    """Search across curated knowledge notes using keyword matching."""

    name = "knowledge_search"
    description = (
        "Search through your curated knowledge base for relevant notes. "
        "These are quality-verified notes that have been refined from the "
        "user's personal knowledge vault. Returns the most relevant results."
    )

    def run(
        self,
        session_id: str,
        query: str,
        max_results: int = 5,
    ) -> str:
        """Search curated knowledge notes.

        Args:
            session_id: Your session ID.
            query: Search query — keyword, phrase, or question.
            max_results: Maximum results to return (default: 5).
        """
        config = _get_ltm_config()
        if config is None or not config.curated_knowledge_enabled:
            return _error("Curated knowledge is not enabled")

        curated, _ = _get_context_managers(session_id)
        if curated is None:
            return _error("Curated knowledge manager not available")

        results = curated.search(query, max_results=max_results)
        items = []
        for r in results:
            items.append({
                "filename": r.get("filename"),
                "title": r.get("title"),
                "category": r.get("category"),
                "tags": r.get("tags"),
                "importance": r.get("importance"),
                "score": round(r.get("score", 0), 4),
                "snippet": r.get("snippet", "")[:500],
            })
        return _ok({"query": query, "total": len(items), "results": items})


# ============================================================================
# Knowledge Read Tool
# ============================================================================

class KnowledgeReadTool(BaseTool):
    """Read a specific curated knowledge note by filename."""

    name = "knowledge_read"
    description = (
        "Read a specific curated knowledge note by its filename. "
        "Returns the full content including metadata and body text."
    )

    def run(self, session_id: str, filename: str) -> str:
        """Read a curated knowledge note.

        Args:
            session_id: Your session ID.
            filename: The filename of the curated note to read.
        """
        config = _get_ltm_config()
        if config is None or not config.curated_knowledge_enabled:
            return _error("Curated knowledge is not enabled")

        curated, _ = _get_context_managers(session_id)
        if curated is None:
            return _error("Curated knowledge manager not available")

        note = curated.read_note(filename)
        if note is None:
            return _error(f"Note not found: {filename}")
        return _ok(note)


# ============================================================================
# Knowledge List Tool
# ============================================================================

class KnowledgeListTool(BaseTool):
    """List curated knowledge notes with optional filtering."""

    name = "knowledge_list"
    description = (
        "List curated knowledge notes. You can filter by category or tag. "
        "Useful for browsing the user's verified knowledge base."
    )

    def run(
        self,
        session_id: str,
        category: str = "",
        tag: str = "",
    ) -> str:
        """List curated knowledge notes.

        Args:
            session_id: Your session ID.
            category: Filter by category (leave empty for all).
            tag: Filter by tag (leave empty for all).
        """
        config = _get_ltm_config()
        if config is None or not config.curated_knowledge_enabled:
            return _error("Curated knowledge is not enabled")

        curated, _ = _get_context_managers(session_id)
        if curated is None:
            return _error("Curated knowledge manager not available")

        kwargs = {}
        if category:
            kwargs["category"] = category
        if tag:
            kwargs["tag"] = tag

        notes = curated.list_notes(**kwargs)
        return _ok({
            "total": len(notes),
            "filters": {"category": category or None, "tag": tag or None},
            "notes": notes,
        })


# ============================================================================
# Knowledge Promote Tool — promote session note to curated knowledge
# ============================================================================

class KnowledgePromoteTool(BaseTool):
    """Promote a session memory note to curated knowledge."""

    name = "knowledge_promote"
    description = (
        "Promote an important session memory note to the user's curated "
        "knowledge base. This makes the knowledge persistent across sessions "
        "and accessible to future agents."
    )

    def run(self, session_id: str, filename: str) -> str:
        """Promote a session note to curated knowledge.

        Args:
            session_id: Your session ID.
            filename: The session memory note filename to promote.
        """
        config = _get_ltm_config()
        if config is None or not config.curated_knowledge_enabled:
            return _error("Curated knowledge is not enabled")

        curated, _ = _get_context_managers(session_id)
        if curated is None:
            return _error("Curated knowledge manager not available")

        # Get session memory manager
        agent_mgr = _get_agent_manager()
        agent = agent_mgr.get_agent(session_id)
        if agent is None:
            agent = agent_mgr.resolve_session(session_id)
        if agent is None:
            return _error(f"Session not found: {session_id}")

        mem = getattr(agent, "memory_manager", None)
        if mem is None:
            return _error("Session memory manager not available")

        curated_fn = curated.promote_from_session(
            mem, filename, session_id=session_id,
        )
        if curated_fn:
            return _ok({
                "status": "promoted",
                "source_filename": filename,
                "curated_filename": curated_fn,
            })
        return _error(f"Failed to promote note: {filename}")


# ============================================================================
# Opsidian Browse Tool — browse user's personal vault index
# ============================================================================

class OpsidianBrowseTool(BaseTool):
    """Browse the user's personal Opsidian knowledge vault index."""

    name = "opsidian_browse"
    description = (
        "Browse the user's personal Opsidian knowledge vault. "
        "Lists available notes with titles, categories, and tags. "
        "Use this to discover what knowledge the user has."
    )

    def run(
        self,
        session_id: str,
        category: str = "",
        tag: str = "",
    ) -> str:
        """Browse User Opsidian notes.

        Args:
            session_id: Your session ID.
            category: Filter by category (leave empty for all).
            tag: Filter by tag (leave empty for all).
        """
        config = _get_ltm_config()
        if config is None or not config.user_opsidian_index_enabled:
            return _error("User Opsidian index access is not enabled")

        _, opsidian = _get_context_managers(session_id)
        if opsidian is None:
            return _error("User Opsidian manager not available")

        kwargs = {}
        if category:
            kwargs["category"] = category
        if tag:
            kwargs["tag"] = tag

        notes = opsidian.list_notes(**kwargs)
        return _ok({
            "total": len(notes),
            "filters": {"category": category or None, "tag": tag or None},
            "notes": notes,
        })


# ============================================================================
# Opsidian Read Tool — read a specific user note
# ============================================================================

class OpsidianReadTool(BaseTool):
    """Read a specific note from the user's personal Opsidian vault."""

    name = "opsidian_read"
    description = (
        "Read a specific note from the user's personal Opsidian vault. "
        "This gives you access to the user's raw personal knowledge. "
        "Use opsidian_browse first to find the filename."
    )

    def run(self, session_id: str, filename: str) -> str:
        """Read a User Opsidian note.

        Args:
            session_id: Your session ID.
            filename: The filename of the note to read.
        """
        config = _get_ltm_config()
        if config is None or not config.user_opsidian_raw_read_enabled:
            return _error("User Opsidian raw read access is not enabled")

        _, opsidian = _get_context_managers(session_id)
        if opsidian is None:
            return _error("User Opsidian manager not available")

        note = opsidian.read_note(filename)
        if note is None:
            return _error(f"Note not found: {filename}")
        return _ok(note)


# ============================================================================
# Explicit TOOLS list for ToolLoader
# ============================================================================

TOOLS = [
    KnowledgeSearchTool(),
    KnowledgeReadTool(),
    KnowledgeListTool(),
    KnowledgePromoteTool(),
    OpsidianBrowseTool(),
    OpsidianReadTool(),
]
