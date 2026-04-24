"""
Curated Knowledge Manager — Refined knowledge layer between User Opsidian and Agent.

The Curated Knowledge scope acts as a quality-controlled bridge:
- Notes are 100% compatible with the existing Opsidian format
  (StructuredMemoryWriter + MemoryIndexManager + YAML frontmatter)
- Adds optional FAISS vector search for semantic retrieval
- Notes originate from User Opsidian (via curation) or agent promotions

Storage layout::

    {STORAGE_ROOT}/_curated_knowledge/{username}/
        topics/
        decisions/
        insights/
        entities/
        projects/
        reference/
        _index.json
        _vector/               (FAISS index, when vector search is enabled)
"""

from __future__ import annotations

import os
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)


class CuratedKnowledgeManager:
    """Per-user curated knowledge vault with Obsidian-like notes + optional vector search.

    Each user gets an isolated directory under ``_curated_knowledge/{username}/``.
    Reuses StructuredMemoryWriter and MemoryIndexManager for full Opsidian
    compatibility, and optionally layers on VectorMemoryManager for semantic
    retrieval.
    """

    def __init__(self, username: str, base_path: Optional[str] = None):
        if base_path is None:
            base_path = self._default_path()
        self.username = username
        self.memory_dir = os.path.join(base_path, "_curated_knowledge", username)
        os.makedirs(self.memory_dir, exist_ok=True)

        self._writer: Optional[Any] = None
        self._index: Optional[Any] = None
        self._vector: Optional[Any] = None
        self._initialized = False
        self._initialize()

    @staticmethod
    def _default_path() -> str:
        from service.utils.platform import DEFAULT_STORAGE_ROOT
        return DEFAULT_STORAGE_ROOT

    def _initialize(self):
        """Set up writer, index manager, and optional vector store."""
        try:
            from service.memory.structured_writer import StructuredMemoryWriter
            from service.memory.index import MemoryIndexManager

            self._index = MemoryIndexManager(self.memory_dir)
            self._index.load_or_rebuild()
            self._writer = StructuredMemoryWriter(
                self.memory_dir,
                self._index,
                session_id=f"curated:{self.username}",
            )
            self._initialized = True

            logger.info(
                "CuratedKnowledgeManager initialized for '%s' at %s",
                self.username, self.memory_dir,
            )
        except Exception:
            logger.warning(
                "CuratedKnowledgeManager: init failed for '%s' (non-critical)",
                self.username, exc_info=True,
            )

    async def initialize_vector(self) -> bool:
        """Lazily initialize FAISS vector search (requires LTMConfig.curated_vector_enabled).

        Returns:
            True if vector search is now available.
        """
        if self._vector is not None:
            return self._vector.enabled

        try:
            from service.memory.vector_memory import VectorMemoryManager
            self._vector = VectorMemoryManager(self.memory_dir)
            ok = await self._vector.initialize()
            if ok:
                logger.info(
                    "CuratedKnowledgeManager: vector search enabled for '%s'",
                    self.username,
                )
            return ok
        except Exception:
            logger.warning(
                "CuratedKnowledgeManager: vector init failed for '%s'",
                self.username, exc_info=True,
            )
            return False

    # ── Properties ────────────────────────────────────────────────────

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def vector_enabled(self) -> bool:
        return self._vector is not None and self._vector.enabled

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
        """Keyword search across curated notes."""
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
            importance = note.get("metadata", {}).get("importance", "medium")
            score = 0.0
            if query_lower in title:
                score += 2.0
            if query_lower in body:
                score += 1.0
            for tag in tags:
                if query_lower in tag.lower():
                    score += 0.5
            # Boost by importance
            importance_boost = {
                "critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5,
            }
            score *= importance_boost.get(importance, 1.0)
            if score > 0:
                results.append({
                    **self._file_info_to_dict(note_info),
                    "score": score,
                    "snippet": (note.get("body") or "")[:300],
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]

    async def vector_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        score_threshold: float = 0.35,
    ) -> List[Dict[str, Any]]:
        """Semantic vector search across curated notes.

        Requires prior call to `initialize_vector()`.
        Falls back to empty list if vector search is unavailable.
        """
        if not self.vector_enabled or self._vector is None:
            return []
        results = await self._vector.search(
            query, top_k=top_k, score_threshold=score_threshold,
        )
        return [
            {
                "source_file": r.source_file,
                "text": r.text,
                "score": r.score,
                "chunk_index": r.chunk_index,
            }
            for r in results
        ]

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
            return {
                "total_files": 0, "total_chars": 0,
                "categories": {}, "total_tags": 0,
                "vector_enabled": self.vector_enabled,
            }
        categories: Dict[str, int] = {}
        for info in (idx.get("files") or {}).values():
            cat = info.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        return {
            "total_files": idx.get("total_files", 0),
            "total_chars": idx.get("total_chars", 0),
            "categories": categories,
            "total_tags": len(idx.get("tag_map", {})),
            "vector_enabled": self.vector_enabled,
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
        source: str = "curated",
        links_to: Optional[List[str]] = None,
        source_filename: Optional[str] = None,
    ) -> Optional[str]:
        """Create a curated note.

        Args:
            title: Note title.
            content: Markdown body.
            category: Category folder.
            tags: List of tags.
            importance: Importance level (low/medium/high/critical).
            source: Origin indicator (curated, promoted, auto-curated, user).
            links_to: Filenames to wikilink to.
            source_filename: Original filename if curated from User Opsidian.
        """
        try:
            from service.memory_provider.adapters.curated_adapter import (
                try_curated_write_note,
            )
            result = try_curated_write_note(
                self.username, title, content,
                category=category, tags=tags, importance=importance,
                source=source, links_to=links_to,
                source_filename=source_filename,
            )
            if result is not None:
                return result
        except Exception as exc:
            logger.warning(
                f"Curated provider adapter failed, using legacy path: {exc}"
            )
        if self._writer is None:
            return None

        # Add source tracking tags
        all_tags = list(tags or [])
        if source and source not in all_tags:
            all_tags.append(f"source:{source}")
        if source_filename:
            all_tags.append(f"origin:{source_filename}")

        filename = self._writer.write_note(
            title=title,
            content=content,
            category=category,
            tags=all_tags,
            importance=importance,
            source=source,
            links=links_to,
        )

        if filename:
            logger.info(
                "CuratedKnowledgeManager: wrote note '%s' → %s (source=%s)",
                title, filename, source,
            )
        return filename

    def update_note(
        self,
        filename: str,
        *,
        body: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
        category: Optional[str] = None,
    ) -> bool:
        try:
            from service.memory_provider.adapters.curated_adapter import (
                try_curated_update_note,
            )
            result = try_curated_update_note(
                self.username, filename,
                body=body, tags=tags, importance=importance, category=category,
            )
            if result is not None:
                return result
        except Exception as exc:
            logger.warning(
                f"Curated provider adapter failed, using legacy path: {exc}"
            )
        if self._writer is None:
            return False
        return self._writer.update_note(
            filename, content=body, tags=tags, importance=importance, category=category,
        )

    def delete_note(self, filename: str) -> bool:
        try:
            from service.memory_provider.adapters.curated_adapter import (
                try_curated_delete_note,
            )
            result = try_curated_delete_note(self.username, filename)
            if result is not None:
                return result
        except Exception as exc:
            logger.warning(
                f"Curated provider adapter failed, using legacy path: {exc}"
            )
        if self._writer is None:
            return False
        return self._writer.delete_note(filename)

    def create_link(self, source_filename: str, target_filename: str) -> bool:
        """Create a wikilink between two curated notes."""
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

    async def reindex_vector(self) -> Dict[str, int]:
        """Re-index all curated notes for vector search."""
        if not self.vector_enabled or self._vector is None:
            return {}
        return await self._vector.index_memory_files()

    # ── Promote / Curate Operations ───────────────────────────────────

    def promote_from_session(
        self,
        session_memory_manager,
        filename: str,
        *,
        session_id: str = "",
    ) -> Optional[str]:
        """Promote a note from session memory into curated knowledge.

        Returns the new curated filename, or None on failure.
        """
        note = session_memory_manager.read_note(filename)
        if note is None:
            logger.warning("promote_from_session: note not found: %s", filename)
            return None

        meta = note.get("metadata") or {}
        body = note.get("body") or ""

        tags = list(meta.get("tags") or [])
        if "promoted" not in tags:
            tags.append("promoted")

        return self.write_note(
            title=meta.get("title", filename.replace(".md", "")),
            content=body,
            category=meta.get("category", "topics"),
            tags=tags,
            importance=meta.get("importance", "medium"),
            source="promoted",
            source_filename=filename,
        )

    def curate_from_opsidian(
        self,
        user_opsidian_manager,
        filename: str,
        *,
        transformed_content: Optional[str] = None,
        extra_tags: Optional[List[str]] = None,
        importance_override: Optional[str] = None,
    ) -> Optional[str]:
        """Curate a note from the user's Opsidian vault into curated knowledge.

        Optionally transforms the content (e.g., LLM-refined summary).

        Args:
            user_opsidian_manager: The source UserOpsidianManager.
            filename: Source note filename in User Opsidian.
            transformed_content: If provided, uses this instead of raw content.
            extra_tags: Additional tags to add.
            importance_override: Override the importance level.

        Returns:
            New curated filename, or None on failure.
        """
        note = user_opsidian_manager.read_note(filename)
        if note is None:
            logger.warning("curate_from_opsidian: note not found: %s", filename)
            return None

        meta = note.get("metadata") or {}
        body = transformed_content or note.get("body") or ""

        tags = list(meta.get("tags") or [])
        if extra_tags:
            tags.extend(extra_tags)

        return self.write_note(
            title=meta.get("title", filename.replace(".md", "")),
            content=body,
            category=meta.get("category", "topics"),
            tags=tags,
            importance=importance_override or meta.get("importance", "medium"),
            source="auto-curated",
            source_filename=filename,
        )

    # ── Context Injection ─────────────────────────────────────────────

    def inject_context(
        self,
        query: str,
        max_chars: int = 5000,
    ) -> str:
        """Build a curated knowledge context block for prompt injection.

        Uses keyword search. For vector search, use `vector_inject_context`.
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
            importance = r.get("importance", "medium")
            chunk = (
                f'<curated-knowledge source="{fn}" importance="{importance}">\n'
                f"{snippet}\n"
                f"</curated-knowledge>"
            )
            if total + len(chunk) > max_chars:
                break
            parts.append(chunk)
            total += len(chunk)

        return "\n\n".join(parts)

    async def vector_inject_context(
        self,
        query: str,
        max_chars: int = 5000,
        top_k: int = 5,
    ) -> str:
        """Build a curated knowledge context block using vector search.

        Returns formatted XML-tagged text or empty string.
        """
        if not self.vector_enabled or self._vector is None:
            return ""

        results = await self._vector.search(query, top_k=top_k)
        if not results:
            return ""

        budget = max_chars
        parts = []
        total = 0
        for r in results:
            chunk = (
                f'<curated-knowledge source="{r.source_file}" '
                f'score="{r.score:.3f}" chunk="{r.chunk_index}">\n'
                f"{r.text}\n"
                f"</curated-knowledge>"
            )
            if total + len(chunk) > budget:
                break
            parts.append(chunk)
            total += len(chunk)

        return "\n\n".join(parts)


# ── Manager cache (username → manager) ────────────────────────────────

_curated_managers: Dict[str, CuratedKnowledgeManager] = {}


def get_curated_knowledge_manager(username: str) -> CuratedKnowledgeManager:
    """Get or create the CuratedKnowledgeManager for a given user."""
    if username not in _curated_managers:
        _curated_managers[username] = CuratedKnowledgeManager(username)
    return _curated_managers[username]
