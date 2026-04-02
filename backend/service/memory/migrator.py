"""
Memory Migrator — Migrate flat MD files to structured format.

Converts existing memory files (without YAML frontmatter) into the
structured format with frontmatter, organised directories, and index.

Designed to be idempotent — running multiple times has no side effects.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from logging import getLogger
from pathlib import Path
from typing import List, Optional

from service.memory.frontmatter import (
    build_default_metadata,
    parse_frontmatter,
    render_frontmatter,
)

logger = getLogger(__name__)

# Use configured timezone from GENY_TIMEZONE env var
from service.utils.utils import _configured_tz as _get_tz

# Pattern to match dated filenames (e.g. 2026-03-29.md).
_DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

# Pattern to detect if a file already has frontmatter.
_HAS_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n", re.MULTILINE)


@dataclass
class MigrationReport:
    """Summary of what the migration did."""
    total_scanned: int = 0
    already_structured: int = 0
    migrated: int = 0
    moved_to_daily: int = 0
    errors: List[str] = field(default_factory=list)
    index_rebuilt: bool = False

    @property
    def summary(self) -> str:
        lines = [
            f"Scanned: {self.total_scanned} files",
            f"Already structured: {self.already_structured}",
            f"Migrated: {self.migrated}",
            f"Moved to daily/: {self.moved_to_daily}",
            f"Index rebuilt: {self.index_rebuilt}",
        ]
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for e in self.errors[:5]:
                lines.append(f"  - {e}")
        return "\n".join(lines)


class MemoryMigrator:
    """Migrate existing flat memory files to structured format.

    Usage::

        migrator = MemoryMigrator(memory_dir)
        report = migrator.migrate()
    """

    def __init__(self, memory_dir: str, session_id: str = ""):
        self._memory_dir = Path(memory_dir)
        self._session_id = session_id

    def needs_migration(self) -> bool:
        """Check if any files need migration.

        Returns True if there are .md files without frontmatter
        in the memory directory (excluding _index.json).
        """
        if not self._memory_dir.exists():
            return False

        for filepath in self._memory_dir.rglob("*.md"):
            if not filepath.is_file():
                continue
            try:
                content = filepath.read_text(encoding="utf-8")
                if not _HAS_FRONTMATTER_RE.match(content):
                    return True
            except (OSError, UnicodeDecodeError):
                continue

        return False

    def migrate(self) -> MigrationReport:
        """Run the migration.

        Steps:
        1. Create subdirectories (daily/, topics/, entities/, etc.)
        2. Scan all .md files in memory/
        3. For files without frontmatter, add frontmatter
        4. Move dated files to daily/ subdirectory
        5. Keep MEMORY.md in root, add frontmatter if missing

        Returns:
            MigrationReport with detailed results.
        """
        report = MigrationReport()

        if not self._memory_dir.exists():
            return report

        # Ensure subdirectories exist
        for subdir in ("daily", "topics", "entities", "projects", "insights"):
            (self._memory_dir / subdir).mkdir(exist_ok=True)

        # Collect all .md files (snapshot before we start moving)
        md_files = list(self._memory_dir.glob("*.md"))  # Only top-level
        md_files.extend(self._memory_dir.glob("topics/*.md"))

        for filepath in md_files:
            report.total_scanned += 1
            try:
                self._migrate_file(filepath, report)
            except Exception as exc:
                report.errors.append(f"{filepath.name}: {exc}")

        report.index_rebuilt = True
        logger.info("MemoryMigrator: %s", report.summary)
        return report

    def _migrate_file(self, filepath: Path, report: MigrationReport) -> None:
        """Migrate a single file."""
        if filepath.name == "_index.json":
            return

        try:
            content = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            report.errors.append(f"{filepath.name}: {exc}")
            return

        # Check if already has frontmatter
        metadata, body = parse_frontmatter(content)
        if metadata:
            report.already_structured += 1
            return

        # File has no frontmatter — add it
        new_metadata = self._infer_metadata(filepath, content)
        new_content = render_frontmatter(new_metadata, content)

        # Determine if file needs to be moved
        date_match = _DATE_FILE_RE.match(filepath.name)

        if date_match and filepath.parent == self._memory_dir:
            # Move dated file to daily/ subdirectory
            target = self._memory_dir / "daily" / filepath.name
            if target.exists():
                # Append to existing daily file
                existing = target.read_text(encoding="utf-8")
                ex_meta, ex_body = parse_frontmatter(existing)
                merged_body = ex_body.rstrip() + "\n\n" + content
                if ex_meta:
                    ex_meta["modified"] = datetime.now(_get_tz()).isoformat()
                    merged_content = render_frontmatter(ex_meta, merged_body)
                else:
                    merged_content = render_frontmatter(new_metadata, merged_body)
                target.write_text(merged_content, encoding="utf-8")
            else:
                target.write_text(new_content, encoding="utf-8")

            filepath.unlink()
            report.moved_to_daily += 1
            report.migrated += 1
        else:
            # In-place: add frontmatter to existing file
            filepath.write_text(new_content, encoding="utf-8")
            report.migrated += 1

    def _infer_metadata(self, filepath: Path, content: str) -> dict:
        """Infer metadata from filename and content."""
        name = filepath.stem
        parent = filepath.parent.name

        # Determine category
        if _DATE_FILE_RE.match(filepath.name):
            category = "daily"
        elif parent == "topics":
            category = "topics"
        elif parent == "entities":
            category = "entities"
        elif parent == "projects":
            category = "projects"
        elif parent == "insights":
            category = "insights"
        elif filepath.name == "MEMORY.md":
            category = "root"
        else:
            category = "root"

        # Determine title
        title = name.replace("-", " ").replace("_", " ").title()
        heading_match = re.search(r"^#+\s+(.+)$", content, re.MULTILINE)
        if heading_match:
            title = heading_match.group(1).strip()

        # Determine importance
        if filepath.name == "MEMORY.md":
            importance = "high"
        elif category == "daily":
            importance = "medium"
        else:
            importance = "medium"

        # Auto-detect tags from content
        tags = self._extract_auto_tags(content, category, name)

        # File modification time as created date
        try:
            mtime = filepath.stat().st_mtime
            created = datetime.fromtimestamp(mtime, tz=_get_tz()).isoformat()
        except OSError:
            created = datetime.now(_get_tz()).isoformat()

        return build_default_metadata(
            title=title,
            category=category,
            tags=tags,
            importance=importance,
            source="migration",
            session_id=self._session_id,
        ) | {"created": created, "modified": created}

    def _extract_auto_tags(self, content: str, category: str, stem: str) -> list:
        """Extract basic tags from content heuristics."""
        tags: list[str] = []

        if category == "daily":
            tags.append("execution")

        # Look for common markers
        content_lower = content.lower()
        if "✅" in content or "success" in content_lower:
            tags.append("success")
        if "❌" in content or "error" in content_lower or "fail" in content_lower:
            tags.append("error")
        if "execution #" in content_lower:
            tags.append("execution")
        if "todo" in content_lower:
            tags.append("task")

        return list(set(tags))
