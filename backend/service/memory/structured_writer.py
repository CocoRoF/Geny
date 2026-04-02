"""
Structured Memory Writer — Obsidian-like note creation with frontmatter.

Builds on top of LongTermMemory's file I/O, adding:
- YAML frontmatter metadata
- Wikilink-based backlinks
- Category-based directory organisation
- Incremental index updates
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.memory.frontmatter import (
    build_default_metadata,
    extract_wikilinks,
    parse_frontmatter,
    render_frontmatter,
)
from service.memory.index import MemoryIndexManager, MemoryFileInfo

logger = getLogger(__name__)

# Use configured timezone from GENY_TIMEZONE env var
from service.utils.utils import _configured_tz as _get_tz

# Valid categories that map to subdirectories.
VALID_CATEGORIES = {"daily", "topics", "entities", "projects", "insights", "root"}

# Maximum slug length for filenames.
_MAX_SLUG = 80


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9가-힣\s_-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug[:_MAX_SLUG] or "untitled"


class StructuredMemoryWriter:
    """Structured note creation with Obsidian-like frontmatter and links.

    Usage::

        writer = StructuredMemoryWriter(memory_dir, index_manager)
        filename = writer.write_note(
            title="FastAPI 비동기 패턴",
            content="# FastAPI\\n\\n- async def 사용...",
            category="topics",
            tags=["python", "fastapi"],
        )
    """

    def __init__(
        self,
        memory_dir: str,
        index_manager: MemoryIndexManager,
        session_id: str = "",
        db_manager=None,
    ):
        """
        Args:
            memory_dir: Absolute path to the memory/ directory.
            index_manager: MemoryIndexManager instance for index updates.
            session_id: Session ID for metadata.
            db_manager: Optional DB manager for dual-write.
        """
        self._memory_dir = Path(memory_dir)
        self._index = index_manager
        self._session_id = session_id
        self._db_manager = db_manager

    @property
    def memory_dir(self) -> Path:
        return self._memory_dir

    def set_database(self, db_manager, session_id: str) -> None:
        """Enable DB-backed persistence after construction."""
        self._db_manager = db_manager
        self._session_id = session_id

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def write_note(
        self,
        title: str,
        content: str,
        *,
        category: str = "topics",
        tags: Optional[List[str]] = None,
        importance: str = "medium",
        source: str = "agent",
        links: Optional[List[str]] = None,
        filename_override: Optional[str] = None,
    ) -> str:
        """Create a new structured note with YAML frontmatter.

        Args:
            title: Note title.
            content: Markdown body content.
            category: Category (daily/topics/entities/projects/insights).
            tags: List of tag strings.
            importance: low/medium/high/critical.
            source: Creation source (execution/user/agent/system/import).
            links: Explicit wikilink targets to add.
            filename_override: Override the auto-generated filename.

        Returns:
            Relative path of the created file (e.g. "topics/fastapi-async.md").
        """
        category = category if category in VALID_CATEGORIES else "topics"
        tags = [t.lower().strip() for t in (tags or []) if t.strip()]

        # Build metadata
        metadata = build_default_metadata(
            title=title,
            category=category,
            tags=tags,
            importance=importance,
            source=source,
            session_id=self._session_id,
        )

        # Extract wikilinks from content and merge with explicit links
        auto_links = extract_wikilinks(content)
        all_links = list(set(auto_links + (links or [])))
        metadata["links_to"] = all_links

        # Build full markdown
        full_content = render_frontmatter(metadata, content)

        # Determine file path
        if filename_override:
            relative_path = filename_override
        else:
            relative_path = self._make_filepath(title, category)

        filepath = self._memory_dir / relative_path
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Handle duplicate filenames
        if filepath.exists() and not filename_override:
            relative_path = self._deduplicate(relative_path)
            filepath = self._memory_dir / relative_path

        filepath.write_text(full_content, encoding="utf-8")

        logger.info(
            "StructuredMemoryWriter: created %s (%d chars, %d tags)",
            relative_path, len(full_content), len(tags),
        )

        # Update index
        self._index.update_file(relative_path)

        # Dual-write to DB
        self._db_write(relative_path, full_content, metadata)

        return relative_path

    def update_note(
        self,
        filename: str,
        *,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
        append: bool = False,
    ) -> bool:
        """Update an existing note's content and/or metadata.

        Args:
            filename: Relative path within memory_dir.
            content: New body content (or content to append).
            tags: Tags to add (merged with existing).
            importance: New importance level.
            append: If True, append content instead of replacing.

        Returns:
            True if the file was successfully updated.
        """
        filepath = self._memory_dir / filename
        if not filepath.exists():
            logger.warning("update_note: file not found: %s", filename)
            return False

        try:
            existing = filepath.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(existing)

            # If no frontmatter, create minimal metadata
            if not metadata:
                metadata = build_default_metadata(
                    title=Path(filename).stem.replace("-", " ").title(),
                    category=self._infer_category(filename),
                    source="system",
                    session_id=self._session_id,
                )

            # Update metadata fields
            now = datetime.now(_get_tz()).isoformat()
            metadata["modified"] = now

            if tags:
                existing_tags = set(metadata.get("tags", []))
                existing_tags.update(t.lower().strip() for t in tags if t.strip())
                metadata["tags"] = sorted(existing_tags)

            if importance:
                metadata["importance"] = importance

            # Update content
            if content is not None:
                if append:
                    body = body.rstrip() + "\n\n" + content
                else:
                    body = content

            # Re-extract wikilinks
            metadata["links_to"] = extract_wikilinks(body)

            full_content = render_frontmatter(metadata, body)
            filepath.write_text(full_content, encoding="utf-8")

            # Update index
            self._index.update_file(filename)

            logger.debug("update_note: updated %s", filename)
            return True

        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("update_note(%s): %s", filename, exc)
            return False

    def delete_note(self, filename: str) -> bool:
        """Delete a note and remove from index.

        Args:
            filename: Relative path within memory_dir.

        Returns:
            True if deleted.
        """
        filepath = self._memory_dir / filename
        if not filepath.exists():
            return False

        try:
            filepath.unlink()
            self._index.remove_file(filename)
            logger.info("delete_note: removed %s", filename)
            return True
        except OSError as exc:
            logger.warning("delete_note(%s): %s", filename, exc)
            return False

    def link_notes(self, source_file: str, target_file: str) -> bool:
        """Create a bidirectional link between two notes.

        Adds ``[[target]]`` reference to source file and updates backlinks.

        Args:
            source_file: Source note filename.
            target_file: Target note filename.

        Returns:
            True if link was created.
        """
        filepath = self._memory_dir / source_file
        if not filepath.exists():
            return False

        target_stem = Path(target_file).stem

        try:
            existing = filepath.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(existing)

            # Check if link already exists
            if f"[[{target_stem}]]" in body.lower() or target_stem.lower() in [
                l.lower() for l in metadata.get("links_to", [])
            ]:
                return True  # Already linked

            # Append link reference
            body = body.rstrip() + f"\n\n> See also: [[{target_stem}]]\n"

            metadata["modified"] = datetime.now(_get_tz()).isoformat()
            metadata["links_to"] = extract_wikilinks(body)

            full_content = render_frontmatter(metadata, body)
            filepath.write_text(full_content, encoding="utf-8")

            # Update both files in index
            self._index.update_file(source_file)
            self._index.update_file(target_file)

            return True
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("link_notes: %s", exc)
            return False

    def read_note(self, filename: str) -> Optional[Dict[str, Any]]:
        """Read a note and return parsed metadata + body.

        Returns:
            Dict with keys: filename, title, metadata, content, raw,
            links_to, linked_from.  Or None if not found.
        """
        filepath = self._memory_dir / filename
        if not filepath.exists():
            return None

        try:
            raw = filepath.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(raw)

            # Get backlinks from index
            idx_info = self._index.index.files.get(filename)
            linked_from = idx_info.linked_from if idx_info else []

            return {
                "filename": filename,
                "title": metadata.get("title", Path(filename).stem),
                "metadata": metadata,
                "body": body,
                "raw": raw,
                "links_to": metadata.get("links_to", []),
                "linked_from": linked_from,
            }
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("read_note(%s): %s", filename, exc)
            return None

    def list_notes(
        self,
        *,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        importance: Optional[str] = None,
    ) -> List[MemoryFileInfo]:
        """List notes with optional filtering.

        Args:
            category: Filter by category.
            tag: Filter by tag.
            importance: Filter by importance.

        Returns:
            Filtered list of MemoryFileInfo.
        """
        idx = self._index.index
        results = list(idx.files.values())

        if category:
            results = [f for f in results if f.category == category]
        if tag:
            tag_lower = tag.lower()
            results = [f for f in results if tag_lower in f.tags]
        if importance:
            results = [f for f in results if f.importance == importance]

        # Sort by modified date (newest first)
        results.sort(key=lambda f: f.modified, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_filepath(self, title: str, category: str) -> str:
        """Generate a relative file path from title and category."""
        slug = _slugify(title)
        if category == "root":
            return f"{slug}.md"
        return f"{category}/{slug}.md"

    def _deduplicate(self, path: str) -> str:
        """Add numeric suffix if path already exists."""
        base, ext = os.path.splitext(path)
        counter = 1
        while (self._memory_dir / f"{base}-{counter}{ext}").exists():
            counter += 1
        return f"{base}-{counter}{ext}"

    def _infer_category(self, filename: str) -> str:
        """Infer category from directory name."""
        parts = filename.replace("\\", "/").split("/")
        if len(parts) > 1 and parts[0] in VALID_CATEGORIES:
            return parts[0]
        return "root"

    def _db_write(self, filename: str, content: str, metadata: Dict[str, Any]) -> None:
        """Dual-write to database (non-critical)."""
        if self._db_manager is None or not self._session_id:
            return
        try:
            import json
            import uuid
            from service.database.memory_db_helper import _get_db_manager, _is_db_available

            if not _is_db_available(self._db_manager):
                return

            mgr = _get_db_manager(self._db_manager)
            entry_id = str(uuid.uuid4())
            now = datetime.now(_get_tz()).isoformat()
            tags_json = json.dumps(metadata.get("tags", []), ensure_ascii=False)
            category = metadata.get("category", "topics")
            importance = metadata.get("importance", "medium")
            links_json = json.dumps(metadata.get("links_to", []), ensure_ascii=False)

            query = (
                "INSERT INTO session_memory_entries "
                "(entry_id, session_id, source, entry_type, content, filename, "
                "heading, topic, metadata_json, entry_timestamp, "
                "category, tags_json, importance, links_to_json, source_type) "
                "VALUES (%s, %s, 'long_term', %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s) "
                "RETURNING id"
            )
            params = (
                entry_id, self._session_id,
                category,  # entry_type = category
                content,
                f"memory/{filename}",
                metadata.get("title", ""),
                "",  # topic
                json.dumps(metadata, ensure_ascii=False, default=str),
                now,
                category,
                tags_json,
                importance,
                links_json,
                metadata.get("source", "system"),
            )
            mgr.execute_insert(query, params)
        except Exception as exc:
            logger.debug("StructuredMemoryWriter: DB write failed (non-critical): %s", exc)
