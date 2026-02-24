"""
Long-term memory — file-based Markdown store.

Inspired by OpenClaw's MEMORY.md + memory/*.md pattern.

Layout inside *storage_path*::

    <storage_path>/
        memory/
            MEMORY.md           ← evergreen knowledge
            2026-02-19.md       ← dated journal entries (auto-named)
            topics/
                architecture.md ← optional sub-topics

Long-term memory is durable across session restarts.
The agent writes to it explicitly (via a tool or flush), and
reads are done through keyword search over the markdown files.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from logging import getLogger
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from service.memory.types import MemoryEntry, MemorySearchResult, MemorySource

logger = getLogger(__name__)

KST = timezone(timedelta(hours=9))

# Maximum file size we will index (256 KB).
MAX_FILE_SIZE = 256_000

# Only markdown files are indexed.
_MD_PATTERN = re.compile(r"\.md$", re.IGNORECASE)

# Dated filename pattern for temporal scoring.
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class LongTermMemory:
    """File-backed long-term memory inside the session storage directory.

    Usage::

        ltm = LongTermMemory("/tmp/sessions/abc123")
        ltm.ensure_directory()

        # Write
        ltm.append("Decided to use PostgreSQL for persistence.")
        ltm.write_dated("Completed Phase 1 migration.")

        # Read / Search
        results = ltm.search("PostgreSQL")
        entries = ltm.load_all()
    """

    MEMORY_DIR = "memory"
    MAIN_FILE = "MEMORY.md"

    def __init__(self, storage_path: str):
        """
        Args:
            storage_path: The session's root storage directory.
        """
        self._storage_path = Path(storage_path)
        self._memory_dir = self._storage_path / self.MEMORY_DIR
        self._main_file = self._memory_dir / self.MAIN_FILE

    @property
    def memory_dir(self) -> Path:
        return self._memory_dir

    @property
    def main_file(self) -> Path:
        return self._main_file

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------

    def ensure_directory(self) -> None:
        """Create the memory/ directory tree if absent."""
        self._memory_dir.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        """True if the memory directory has any .md files."""
        if not self._memory_dir.exists():
            return False
        return any(self._memory_dir.rglob("*.md"))

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def append(self, text: str, *, heading: Optional[str] = None) -> None:
        """Append text to the main MEMORY.md file.

        Args:
            text: Content to append.
            heading: Optional markdown heading to prepend.
        """
        self.ensure_directory()
        now = datetime.now(KST)

        lines: list[str] = []
        if heading:
            lines.append(f"\n## {heading}\n")
        lines.append(f"<!-- {now.strftime('%Y-%m-%d %H:%M KST')} -->\n")
        lines.append(text.rstrip() + "\n")

        with open(self._main_file, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.debug(
            "LongTermMemory.append: wrote %d chars to %s",
            len(text), self._main_file,
        )

    def write_dated(self, text: str, *, date: Optional[datetime] = None) -> Path:
        """Write text to a dated file (memory/YYYY-MM-DD.md).

        If the file already exists, content is appended.

        Args:
            text: Content to write.
            date: Date to use for the filename (default: now KST).

        Returns:
            Path to the written file.
        """
        self.ensure_directory()
        date = date or datetime.now(KST)
        filename = f"{date.strftime('%Y-%m-%d')}.md"
        filepath = self._memory_dir / filename

        now_str = date.strftime("%H:%M KST")
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"\n---\n_({now_str})_\n\n{text.rstrip()}\n")

        logger.debug(
            "LongTermMemory.write_dated: wrote %d chars to %s",
            len(text), filepath,
        )
        return filepath

    def write_topic(self, topic: str, text: str) -> Path:
        """Write text to a topic file (memory/topics/<topic>.md).

        Args:
            topic: Topic slug (will be slugified).
            text: Content to write.

        Returns:
            Path to the written file.
        """
        self.ensure_directory()
        topics_dir = self._memory_dir / "topics"
        topics_dir.mkdir(exist_ok=True)

        slug = re.sub(r"[^a-z0-9_-]", "_", topic.lower().strip())[:64]
        filepath = topics_dir / f"{slug}.md"

        now = datetime.now(KST)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(
                f"\n---\n_({now.strftime('%Y-%m-%d %H:%M KST')})_\n\n"
                f"{text.rstrip()}\n"
            )

        logger.debug("LongTermMemory.write_topic: %s → %s", topic, filepath)
        return filepath

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def load_all(self) -> List[MemoryEntry]:
        """Load all markdown files as MemoryEntry objects.

        Returns entries sorted by: MEMORY.md first, then dated files
        newest-first, then alphabetical.
        """
        if not self._memory_dir.exists():
            return []

        files = self._list_md_files()
        entries: list[MemoryEntry] = []

        for filepath in files:
            try:
                stat = filepath.stat()
                if stat.st_size > MAX_FILE_SIZE or stat.st_size == 0:
                    continue
                content = filepath.read_text(encoding="utf-8").strip()
                if not content:
                    continue

                rel = str(filepath.relative_to(self._storage_path))
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=KST)

                entries.append(MemoryEntry(
                    source=MemorySource.LONG_TERM,
                    content=content,
                    timestamp=mtime,
                    filename=rel,
                    metadata={"size": stat.st_size},
                ))
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("LongTermMemory: skip %s: %s", filepath, exc)

        return entries

    def load_main(self) -> Optional[MemoryEntry]:
        """Load only the main MEMORY.md file."""
        if not self._main_file.exists():
            return None
        try:
            content = self._main_file.read_text(encoding="utf-8").strip()
            if not content:
                return None
            return MemoryEntry(
                source=MemorySource.LONG_TERM,
                content=content,
                filename=str(self._main_file.relative_to(self._storage_path)),
                timestamp=datetime.fromtimestamp(
                    self._main_file.stat().st_mtime, tz=KST
                ),
            )
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("LongTermMemory.load_main: %s", exc)
            return None

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> List[MemorySearchResult]:
        """Simple keyword search over all long-term memory files.

        Scores are based on keyword hit density + recency bonus.

        Args:
            query: Search query string.
            max_results: Maximum results to return.
        """
        if not query.strip():
            return []

        entries = self.load_all()
        query_lower = query.lower()
        keywords = [w for w in query_lower.split() if len(w) >= 2]

        if not keywords:
            return []

        results: list[MemorySearchResult] = []
        now = datetime.now(KST)

        for entry in entries:
            content_lower = entry.content.lower()
            # Keyword density score
            hits = sum(
                content_lower.count(kw) for kw in keywords
            )
            if hits == 0:
                continue

            density = hits / max(1, len(entry.content.split()))

            # Recency bonus (exponential decay, half-life 30 days)
            recency = 0.0
            if entry.timestamp:
                age_days = (now - entry.timestamp).total_seconds() / 86400
                recency = 2 ** (-age_days / 30.0)

                # Evergreen bonus: MEMORY.md gets no decay
                if entry.filename and self.MAIN_FILE in entry.filename:
                    recency = 1.0

            score = (density * 0.7) + (recency * 0.3)

            # Build snippet around first hit
            snippet = self._extract_snippet(entry.content, keywords[0])

            results.append(MemorySearchResult(
                entry=entry,
                score=score,
                snippet=snippet,
                match_type="combined",
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:max_results]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _list_md_files(self) -> List[Path]:
        """List .md files in priority order."""
        if not self._memory_dir.exists():
            return []

        all_files = [
            f for f in self._memory_dir.rglob("*.md")
            if f.is_file() and f.stat().st_size <= MAX_FILE_SIZE
        ]

        def sort_key(p: Path) -> Tuple[int, str]:
            # MEMORY.md first (priority 0)
            if p.name == self.MAIN_FILE:
                return (0, "")
            # Dated files next (priority 1), newest first
            m = _DATE_RE.search(p.stem)
            if m:
                return (1, f"9999-{m.group(1)}")  # inverted for desc
            # Others last
            return (2, p.name)

        all_files.sort(key=sort_key)
        return all_files

    @staticmethod
    def _extract_snippet(text: str, keyword: str, context: int = 120) -> str:
        """Extract a snippet centered on the first keyword occurrence."""
        idx = text.lower().find(keyword.lower())
        if idx < 0:
            return text[:context * 2]
        start = max(0, idx - context)
        end = min(len(text), idx + len(keyword) + context)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet
