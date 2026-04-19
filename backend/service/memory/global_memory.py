"""
Global Memory Manager — Cross-session shared knowledge store.

Provides a singleton global memory that all sessions can read from
and promote notes to. Modelled after SharedFolderManager's pattern.
"""

from __future__ import annotations

import json
import os
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)


class GlobalMemoryManager:
    """Cross-session global memory for shared knowledge.

    Uses the same structured note format (YAML frontmatter + Markdown)
    as session-level memory, but stored in a shared ``_global_memory/``
    directory accessible to all sessions.
    """

    def __init__(self, base_path: Optional[str] = None):
        if base_path is None:
            base_path = self._default_path()
        self.memory_dir = os.path.join(base_path, "_global_memory")
        os.makedirs(self.memory_dir, exist_ok=True)

        self._writer: Optional[Any] = None
        self._index: Optional[Any] = None
        self._db = None
        self._initialize()

    @staticmethod
    def _default_path() -> str:
        from service.claude_manager.platform_utils import DEFAULT_STORAGE_ROOT
        return DEFAULT_STORAGE_ROOT

    def _initialize(self):
        """Set up writer and index manager."""
        try:
            from service.memory.structured_writer import StructuredMemoryWriter
            from service.memory.index import MemoryIndexManager

            self._writer = StructuredMemoryWriter(self.memory_dir)
            self._index = MemoryIndexManager(self.memory_dir)
            self._index.load()
            logger.info(
                "GlobalMemoryManager initialized at %s", self.memory_dir,
            )
        except Exception:
            logger.warning(
                "GlobalMemoryManager: init failed (non-critical)",
                exc_info=True,
            )

    def set_database(self, db):
        """Attach database connection for dual-write."""
        self._db = db
        if self._writer is not None:
            self._writer.set_database(db, "global")

    # ── Read Operations ───────────────────────────────────────────────

    def list_notes(
        self,
        *,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if self._writer is None:
            return []
        notes = self._writer.list_notes(category=category, tag=tag)
        return [self._file_info_to_dict(n) for n in notes]

    @staticmethod
    def _file_info_to_dict(info) -> Dict[str, Any]:
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

    def read_note(self, filename: str) -> Optional[Dict[str, Any]]:
        if self._writer is None:
            return None
        return self._writer.read_note(filename)

    def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Simple keyword search across global notes."""
        if self._writer is None:
            return []
        all_notes = self._writer.list_notes()
        query_lower = query.lower()
        results = []
        for note_info in all_notes:
            fn = note_info.filename
            note = self._writer.read_note(fn)
            if note is None:
                continue
            body = (note.get("body") or "").lower()
            title = (note.get("metadata", {}).get("title") or "").lower()
            tags = note.get("metadata", {}).get("tags") or []
            # Simple relevance score
            score = 0.0
            if query_lower in title:
                score += 2.0
            if query_lower in body:
                score += 1.0
            for tag in tags:
                if query_lower in tag.lower():
                    score += 0.5
            if score > 0:
                results.append({
                    **self._file_info_to_dict(note_info),
                    "score": score,
                    "snippet": (note.get("body") or "")[:300],
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]

    def get_index(self) -> Optional[Dict[str, Any]]:
        if self._index is None:
            return None
        idx = self._index.index
        return {
            "files": {
                k: {
                    "filename": v.filename,
                    "title": v.title,
                    "category": v.category,
                    "tags": v.tags,
                    "importance": v.importance,
                    "char_count": v.char_count,
                    "links_to": v.links_to,
                    "linked_from": v.linked_from,
                }
                for k, v in idx.files.items()
            },
            "tag_map": idx.tag_map,
            "total_files": idx.total_files,
            "total_chars": idx.total_chars,
        }

    def get_stats(self) -> Dict[str, Any]:
        idx = self.get_index()
        if idx is None:
            return {"total_files": 0, "total_chars": 0}
        categories: Dict[str, int] = {}
        for info in (idx.get("files") or {}).values():
            cat = info.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        return {
            "total_files": idx.get("total_files", 0),
            "total_chars": idx.get("total_chars", 0),
            "categories": categories,
            "total_tags": len(idx.get("tag_map", {})),
        }

    # ── Write Operations ──────────────────────────────────────────────

    def write_note(
        self,
        title: str,
        content: str,
        *,
        category: str = "topics",
        tags: Optional[List[str]] = None,
        importance: str = "medium",
        source: str = "global",
        source_session_id: Optional[str] = None,
    ) -> Optional[str]:
        try:
            from service.memory_provider.adapters.curated_adapter import (
                try_global_write_note,
            )
            result = try_global_write_note(
                title, content,
                category=category, tags=tags, importance=importance,
                source=source, source_session_id=source_session_id,
            )
            if result is not None:
                return result
        except Exception as exc:
            logger.warning(
                f"Global provider adapter failed, using legacy path: {exc}"
            )
        if self._writer is None:
            return None
        return self._writer.write_note(
            title=title,
            content=content,
            category=category,
            tags=tags,
            importance=importance,
            source=source,
        )

    def update_note(
        self,
        filename: str,
        *,
        body: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
    ) -> bool:
        try:
            from service.memory_provider.adapters.curated_adapter import (
                try_global_update_note,
            )
            result = try_global_update_note(
                filename, body=body, tags=tags, importance=importance,
            )
            if result is not None:
                return result
        except Exception as exc:
            logger.warning(
                f"Global provider adapter failed, using legacy path: {exc}"
            )
        if self._writer is None:
            return False
        return self._writer.update_note(
            filename, content=body, tags=tags, importance=importance,
        )

    def delete_note(self, filename: str) -> bool:
        try:
            from service.memory_provider.adapters.curated_adapter import (
                try_global_delete_note,
            )
            result = try_global_delete_note(filename)
            if result is not None:
                return result
        except Exception as exc:
            logger.warning(
                f"Global provider adapter failed, using legacy path: {exc}"
            )
        if self._writer is None:
            return False
        return self._writer.delete_note(filename)

    # ── Promote from Session ──────────────────────────────────────────

    def promote(
        self,
        session_memory_manager,
        filename: str,
        *,
        session_id: str = "",
    ) -> Optional[str]:
        """Copy a note from session memory to global memory.

        Returns the new global filename, or None on failure.
        """
        note = session_memory_manager.read_note(filename)
        if note is None:
            logger.warning(
                "promote: source note not found: %s", filename,
            )
            return None

        meta = note.get("metadata") or {}
        body = note.get("body") or ""

        tags = list(meta.get("tags") or [])
        if "promoted" not in tags:
            tags.append("promoted")

        global_fn = self.write_note(
            title=meta.get("title", filename.replace(".md", "")),
            content=body,
            category=meta.get("category", "topics"),
            tags=tags,
            importance=meta.get("importance", "medium"),
            source="promoted",
            source_session_id=session_id,
        )

        if global_fn:
            logger.info(
                "promote: %s → global %s (from session %s)",
                filename, global_fn, session_id or "unknown",
            )
        return global_fn

    def inject_context(
        self,
        query: str,
        max_chars: int = 4000,
    ) -> str:
        """Build a global memory context block for injection into prompts.

        Returns formatted XML-tagged text or empty string.
        """
        results = self.search(query, max_results=5)
        if not results:
            return ""

        parts = []
        total = 0
        for r in results:
            snippet = r.get("snippet", "")
            fn = r.get("filename", "")
            chunk = (
                f'<global-memory source="{fn}">\n'
                f"{snippet}\n"
                f"</global-memory>"
            )
            if total + len(chunk) > max_chars:
                break
            parts.append(chunk)
            total += len(chunk)

        return "\n\n".join(parts)


# ── Singleton ─────────────────────────────────────────────────────────

_global_memory_manager: Optional[GlobalMemoryManager] = None


def get_global_memory_manager() -> GlobalMemoryManager:
    """Get or create the singleton global memory manager."""
    global _global_memory_manager
    if _global_memory_manager is None:
        _global_memory_manager = GlobalMemoryManager()
    return _global_memory_manager
