"""
Memory Index — In-memory + JSON-cached index of all memory files.

Maintains a fast lookup structure for file metadata, tags, and
link relationships.  Persisted as ``_index.json`` inside the
memory directory and rebuilt on demand.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from service.memory.frontmatter import (
    parse_frontmatter,
    extract_wikilinks,
)

logger = getLogger(__name__)

# Use configured timezone from GENY_TIMEZONE env var
from service.utils.utils import _configured_tz as _get_tz
_INDEX_FILE = "_index.json"
_MD_PATTERN = re.compile(r"\.md$", re.IGNORECASE)

# Directories that are not user-facing categories.
_SKIP_DIRS = {"__pycache__", ".git", "_attachments"}


@dataclass
class MemoryFileInfo:
    """Metadata for a single memory file."""
    filename: str = ""            # relative path inside memory/ (e.g. "topics/python-async.md")
    title: str = ""
    category: str = "topics"
    tags: List[str] = field(default_factory=list)
    importance: str = "medium"
    created: str = ""
    modified: str = ""
    source: str = "system"
    char_count: int = 0
    links_to: List[str] = field(default_factory=list)
    linked_from: List[str] = field(default_factory=list)
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryFileInfo":
        fields = {k for k in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in fields}
        return cls(**filtered)


@dataclass
class MemoryIndex:
    """Full index of all memory files in a session."""
    files: Dict[str, MemoryFileInfo] = field(default_factory=dict)   # filename → info
    tag_map: Dict[str, List[str]] = field(default_factory=dict)      # tag → [filenames]
    link_graph: Dict[str, List[str]] = field(default_factory=dict)   # filename → [linked filenames]
    last_rebuilt: str = ""
    total_chars: int = 0
    total_files: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files": {k: v.to_dict() for k, v in self.files.items()},
            "tag_map": self.tag_map,
            "link_graph": self.link_graph,
            "last_rebuilt": self.last_rebuilt,
            "total_chars": self.total_chars,
            "total_files": self.total_files,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryIndex":
        files = {}
        for k, v in d.get("files", {}).items():
            files[k] = MemoryFileInfo.from_dict(v)
        return cls(
            files=files,
            tag_map=d.get("tag_map", {}),
            link_graph=d.get("link_graph", {}),
            last_rebuilt=d.get("last_rebuilt", ""),
            total_chars=d.get("total_chars", 0),
            total_files=d.get("total_files", 0),
        )


class MemoryIndexManager:
    """Manages the ``_index.json`` file and provides query helpers.

    Thread-safe via a reentrant lock on mutations.

    Usage::

        idx_mgr = MemoryIndexManager("/sessions/abc/memory")
        idx_mgr.load_or_rebuild()

        # After writing a new file
        idx_mgr.update_file("topics/python-async.md")

        # Queries
        files = idx_mgr.get_files_by_tag("python")
        graph = idx_mgr.get_link_graph()
    """

    def __init__(self, memory_dir: str):
        self._memory_dir = Path(memory_dir)
        self._index_path = self._memory_dir / _INDEX_FILE
        self._index: Optional[MemoryIndex] = None
        self._lock = threading.RLock()

    @property
    def index(self) -> MemoryIndex:
        """Get the current index, loading or rebuilding if needed."""
        if self._index is None:
            self.load_or_rebuild()
        return self._index  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Load / Rebuild
    # ------------------------------------------------------------------

    def load_or_rebuild(self) -> MemoryIndex:
        """Load index from disk, or rebuild from files if missing/stale."""
        with self._lock:
            loaded = self._load_from_disk()
            if loaded is not None:
                self._index = loaded
                return loaded
            return self.rebuild()

    def rebuild(self) -> MemoryIndex:
        """Full rebuild: scan all .md files, parse frontmatter, rebuild index."""
        with self._lock:
            idx = MemoryIndex()

            if not self._memory_dir.exists():
                self._index = idx
                return idx

            md_files = self._list_md_files()
            for filepath in md_files:
                try:
                    info = self._scan_file(filepath)
                    if info:
                        idx.files[info.filename] = info
                except Exception as exc:
                    logger.debug("MemoryIndex: skip %s: %s", filepath, exc)

            # Rebuild derived structures
            self._rebuild_tag_map(idx)
            self._rebuild_link_graph(idx)
            self._compute_totals(idx)

            idx.last_rebuilt = datetime.now(_get_tz()).isoformat()
            self._index = idx
            self._save_to_disk()

            logger.info(
                "MemoryIndex rebuilt: %d files, %d chars, %d tags",
                idx.total_files, idx.total_chars, len(idx.tag_map),
            )
            return idx

    # ------------------------------------------------------------------
    # Incremental updates
    # ------------------------------------------------------------------

    def update_file(self, relative_path: str) -> Optional[MemoryFileInfo]:
        """Update (or add) a single file in the index.

        Args:
            relative_path: Path relative to memory_dir (e.g. "topics/python.md").

        Returns:
            Updated MemoryFileInfo, or None if file not found.
        """
        with self._lock:
            filepath = self._memory_dir / relative_path
            if not filepath.exists() or not filepath.is_file():
                # File removed — delete from index
                self._remove_from_index(relative_path)
                return None

            info = self._scan_file(filepath)
            if not info:
                return None

            idx = self.index
            idx.files[info.filename] = info

            # Rebuild derived structures
            self._rebuild_tag_map(idx)
            self._rebuild_link_graph(idx)
            self._compute_totals(idx)
            idx.last_rebuilt = datetime.now(_get_tz()).isoformat()

            self._save_to_disk()
            return info

    def remove_file(self, relative_path: str) -> None:
        """Remove a file from the index."""
        with self._lock:
            self._remove_from_index(relative_path)
            self._save_to_disk()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_files_by_tag(self, tag: str) -> List[MemoryFileInfo]:
        """Get all files that have a specific tag."""
        idx = self.index
        filenames = idx.tag_map.get(tag.lower(), [])
        return [idx.files[fn] for fn in filenames if fn in idx.files]

    def get_files_by_category(self, category: str) -> List[MemoryFileInfo]:
        """Get all files in a specific category."""
        idx = self.index
        return [f for f in idx.files.values() if f.category == category]

    def get_files_by_importance(self, importance: str) -> List[MemoryFileInfo]:
        """Get all files with a specific importance level."""
        idx = self.index
        return [f for f in idx.files.values() if f.importance == importance]

    def get_all_tags(self) -> Dict[str, int]:
        """Get all tags with their file counts."""
        idx = self.index
        return {tag: len(files) for tag, files in idx.tag_map.items()}

    def get_link_graph(self) -> Dict[str, List[str]]:
        """Get the full link graph (filename → linked filenames)."""
        return dict(self.index.link_graph)

    def get_backlinks(self, filename: str) -> List[str]:
        """Get files that link TO the given file."""
        info = self.index.files.get(filename)
        if info:
            return list(info.linked_from)
        return []

    def get_categories_summary(self) -> Dict[str, int]:
        """Get category → file count mapping."""
        counts: Dict[str, int] = {}
        for f in self.index.files.values():
            cat = f.category or "uncategorized"
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def search_by_title(self, query: str) -> List[MemoryFileInfo]:
        """Simple title substring search."""
        q = query.lower()
        return [f for f in self.index.files.values() if q in f.title.lower()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_file(self, filepath: Path) -> Optional[MemoryFileInfo]:
        """Scan a single .md file and extract MemoryFileInfo."""
        try:
            stat = filepath.stat()
            if stat.st_size == 0 or stat.st_size > 256_000:
                return None

            content = filepath.read_text(encoding="utf-8")
            relative = str(filepath.relative_to(self._memory_dir)).replace("\\", "/")

            metadata, body = parse_frontmatter(content)

            # Infer category from directory
            parts = relative.split("/")
            inferred_category = parts[0] if len(parts) > 1 else "root"
            if inferred_category in ("_attachments", "__pycache__"):
                return None

            # Extract wikilinks from body
            wikilinks = extract_wikilinks(body)

            # Determine mtime
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=_get_tz()).isoformat()

            # Build summary (first 200 chars of body, stripping headings)
            body_text = re.sub(r"^#+\s+.*$", "", body, flags=re.MULTILINE).strip()
            summary = body_text[:200].strip() if body_text else None

            title = metadata.get("title", "")
            if not title:
                # Try to extract from first heading
                heading_match = re.search(r"^#+\s+(.+)$", body, re.MULTILINE)
                if heading_match:
                    title = heading_match.group(1).strip()
                else:
                    title = filepath.stem.replace("-", " ").replace("_", " ").title()

            tags = metadata.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            tags = [t.lower() for t in tags]

            return MemoryFileInfo(
                filename=relative,
                title=title,
                category=metadata.get("category", inferred_category),
                tags=tags,
                importance=metadata.get("importance", "medium"),
                created=metadata.get("created", mtime),
                modified=metadata.get("modified", mtime),
                source=metadata.get("source", "system"),
                char_count=len(content),
                links_to=wikilinks,
                linked_from=[],   # populated by _rebuild_link_graph
                summary=summary,
            )
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("_scan_file(%s): %s", filepath, exc)
            return None

    def _list_md_files(self) -> List[Path]:
        """List all .md files in the memory directory."""
        if not self._memory_dir.exists():
            return []
        return [
            f for f in self._memory_dir.rglob("*.md")
            if f.is_file()
            and not any(part.startswith(".") or part in _SKIP_DIRS for part in f.relative_to(self._memory_dir).parts)
        ]

    def _rebuild_tag_map(self, idx: MemoryIndex) -> None:
        """Rebuild tag → filenames mapping."""
        tag_map: Dict[str, List[str]] = {}
        for filename, info in idx.files.items():
            for tag in info.tags:
                tag_lower = tag.lower()
                if tag_lower not in tag_map:
                    tag_map[tag_lower] = []
                tag_map[tag_lower].append(filename)
        idx.tag_map = tag_map

    def _rebuild_link_graph(self, idx: MemoryIndex) -> None:
        """Rebuild forward links and backlinks."""
        link_graph: Dict[str, List[str]] = {}

        # Reset all linked_from
        for info in idx.files.values():
            info.linked_from = []

        for filename, info in idx.files.items():
            resolved: list[str] = []
            for link_target in info.links_to:
                # Try to resolve wikilink to an actual file
                resolved_file = self._resolve_link(link_target, idx)
                if resolved_file:
                    resolved.append(resolved_file)

            link_graph[filename] = resolved

            # Populate backlinks
            for target in resolved:
                target_info = idx.files.get(target)
                if target_info is not None:
                    if filename not in target_info.linked_from:
                        target_info.linked_from.append(filename)

        idx.link_graph = link_graph

    def _resolve_link(self, link_target: str, idx: MemoryIndex) -> Optional[str]:
        """Resolve a wikilink target to an indexed filename."""
        slug = link_target.lower().strip()

        # 1. Direct filename match
        for filename in idx.files:
            stem = Path(filename).stem.lower()
            if stem == slug:
                return filename

        # 2. Partial match
        for filename in idx.files:
            stem = Path(filename).stem.lower()
            if slug in stem:
                return filename

        return None

    def _remove_from_index(self, relative_path: str) -> None:
        """Remove a file and clean up references."""
        idx = self.index
        if relative_path in idx.files:
            del idx.files[relative_path]

        # Rebuild derived structures
        self._rebuild_tag_map(idx)
        self._rebuild_link_graph(idx)
        self._compute_totals(idx)

    def _compute_totals(self, idx: MemoryIndex) -> None:
        """Compute aggregate totals."""
        idx.total_files = len(idx.files)
        idx.total_chars = sum(f.char_count for f in idx.files.values())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> Optional[MemoryIndex]:
        """Load index from _index.json."""
        if not self._index_path.exists():
            return None
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            return MemoryIndex.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.debug("MemoryIndex: failed to load _index.json: %s", exc)
            return None

    def _save_to_disk(self) -> None:
        """Save index to _index.json."""
        if self._index is None:
            return
        try:
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self._index.to_dict(), ensure_ascii=False, indent=2)
            self._index_path.write_text(data, encoding="utf-8")
        except OSError as exc:
            logger.warning("MemoryIndex: failed to save _index.json: %s", exc)
