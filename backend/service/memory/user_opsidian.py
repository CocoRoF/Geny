"""
User Opsidian Manager — Personal knowledge base per user.

Unlike session memory (scoped to a session) or global memory (shared across
sessions), the User Opsidian is a private knowledge vault that belongs to a
specific user.  Users can store personal notes, ideas, and structured
information that persists independently of any agent session.

Storage layout::

    {STORAGE_ROOT}/_user_opsidian/{username}/
        daily/
        topics/
        entities/
        projects/
        insights/
        _index.json
"""

from __future__ import annotations

import os
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)


class UserOpsidianManager:
    """Per-user personal knowledge vault with Obsidian-like notes.

    Each user gets an isolated directory under ``_user_opsidian/{username}/``.
    Internally reuses the same StructuredMemoryWriter and MemoryIndexManager
    used by session and global memory.
    """

    def __init__(self, username: str, base_path: Optional[str] = None):
        if base_path is None:
            base_path = self._default_path()
        self.username = username
        self.memory_dir = os.path.join(base_path, "_user_opsidian", username)
        os.makedirs(self.memory_dir, exist_ok=True)

        self._writer: Optional[Any] = None
        self._index: Optional[Any] = None
        self._initialize()

    @staticmethod
    def _default_path() -> str:
        from service.utils.platform import DEFAULT_STORAGE_ROOT
        return DEFAULT_STORAGE_ROOT

    def _initialize(self):
        """Set up writer and index manager."""
        try:
            from service.memory.structured_writer import StructuredMemoryWriter
            from service.memory.index import MemoryIndexManager

            self._index = MemoryIndexManager(self.memory_dir)
            self._index.load_or_rebuild()
            self._writer = StructuredMemoryWriter(
                self.memory_dir, self._index, session_id=f"user:{self.username}",
            )
            logger.info(
                "UserOpsidianManager initialized for '%s' at %s",
                self.username, self.memory_dir,
            )
        except Exception:
            logger.warning(
                "UserOpsidianManager: init failed for '%s' (non-critical)",
                self.username, exc_info=True,
            )

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

    def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Keyword search across user notes."""
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
            return {"total_files": 0, "total_chars": 0, "categories": {}, "total_tags": 0}
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

    def get_graph(self) -> Dict[str, Any]:
        """Get graph data for visualization (enhanced with tag edges + metadata)."""
        idx = self.get_index()
        if idx is None:
            return {"nodes": [], "edges": []}
        nodes = []
        edges = []
        edge_set: set = set()
        tag_to_files: Dict[str, List[str]] = {}
        files_map = idx.get("files", {})

        for fn, info in files_map.items():
            links_to = info.get("links_to", [])
            linked_from = info.get("linked_from", [])
            tags = info.get("tags", [])

            nodes.append({
                "id": fn,
                "label": info.get("title", fn),
                "category": info.get("category", "root"),
                "importance": info.get("importance", "medium"),
                "tags": tags,
                "connectionCount": len(links_to) + len(linked_from),
                "summary": info.get("summary", ""),
                "charCount": info.get("char_count", 0),
            })

            # Wikilink edges
            for target in links_to:
                if target in files_map:
                    key = (fn, target)
                    if key not in edge_set:
                        edge_set.add(key)
                        edges.append({
                            "source": fn,
                            "target": target,
                            "type": "wikilink",
                            "weight": 1.0,
                        })

            # Build tag map
            for tag in tags:
                tag_to_files.setdefault(tag, []).append(fn)

        # Tag-based edges
        for tag, fns in tag_to_files.items():
            if len(fns) < 2:
                continue
            for i in range(len(fns)):
                for j in range(i + 1, len(fns)):
                    a, b = fns[i], fns[j]
                    if (a, b) not in edge_set and (b, a) not in edge_set:
                        edge_set.add((a, b))
                        edges.append({
                            "source": a,
                            "target": b,
                            "type": "tag",
                            "weight": 0.5,
                            "label": tag,
                        })

        return {"nodes": nodes, "edges": edges}

    # ── Write Operations ──────────────────────────────────────────────

    def write_note(
        self,
        title: str,
        content: str,
        *,
        category: str = "topics",
        tags: Optional[List[str]] = None,
        importance: str = "medium",
        source: str = "user",
        links_to: Optional[List[str]] = None,
    ) -> Optional[str]:
        if self._writer is None:
            return None
        return self._writer.write_note(
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
        category: Optional[str] = None,
    ) -> bool:
        if self._writer is None:
            return False
        return self._writer.update_note(
            filename, content=body, tags=tags, importance=importance, category=category,
        )

    def delete_note(self, filename: str) -> bool:
        if self._writer is None:
            return False
        return self._writer.delete_note(filename)

    def create_link(self, source_filename: str, target_filename: str) -> bool:
        """Create a wikilink between two notes."""
        if self._writer is None:
            return False
        note = self._writer.read_note(source_filename)
        if note is None:
            return False
        body = note.get("body", "")
        link_ref = f"[[{target_filename}]]"
        if link_ref not in body:
            body = body.rstrip() + f"\n\n{link_ref}\n"
            return self._writer.update_note(source_filename, content=body)
        return True

    def reindex(self) -> int:
        """Rebuild the full index from disk."""
        if self._index is None:
            return 0
        self._index.rebuild()
        return self._index.index.total_files


# ── Manager cache (username → manager) ────────────────────────────────

_user_managers: Dict[str, UserOpsidianManager] = {}


def get_user_opsidian_manager(username: str) -> UserOpsidianManager:
    """Get or create the UserOpsidianManager for a given user."""
    if username not in _user_managers:
        _user_managers[username] = UserOpsidianManager(username)
    return _user_managers[username]
