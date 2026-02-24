"""
Short-term memory — JSONL transcript store.

Inspired by OpenClaw's session JSONL transcript pattern.

Layout inside *storage_path*::

    <storage_path>/
        transcripts/
            session.jsonl       ← main conversation transcript
            summary.md          ← auto-generated session summary (optional)

Each line in the JSONL file is a JSON object::

    {"type": "message", "role": "user",      "content": "...", "ts": "..."}
    {"type": "message", "role": "assistant",  "content": "...", "ts": "..."}
    {"type": "event",   "event": "tool_call", "data": {...},    "ts": "..."}

Short-term memory is ephemeral — it lives for the duration of the
session (and maybe a bit longer for post-mortem analysis).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.memory.types import MemoryEntry, MemorySearchResult, MemorySource

logger = getLogger(__name__)

KST = timezone(timedelta(hours=9))

# Maximum transcript size before we start dropping old entries from search.
MAX_TRANSCRIPT_ENTRIES = 2000


class ShortTermMemory:
    """JSONL-backed short-term transcript memory.

    Each message exchanged with the LLM is persisted as a JSONL line,
    enabling post-session review, search, and context replay.

    Usage::

        stm = ShortTermMemory("/tmp/sessions/abc123")
        stm.ensure_directory()

        stm.add_message("user", "Implement the login feature")
        stm.add_message("assistant", "I'll start by creating...")

        recent = stm.get_recent(n=10)
        results = stm.search("login")
    """

    TRANSCRIPT_DIR = "transcripts"
    MAIN_FILE = "session.jsonl"
    SUMMARY_FILE = "summary.md"

    def __init__(self, storage_path: str):
        """
        Args:
            storage_path: The session's root storage directory.
        """
        self._storage_path = Path(storage_path)
        self._transcript_dir = self._storage_path / self.TRANSCRIPT_DIR
        self._main_file = self._transcript_dir / self.MAIN_FILE
        self._summary_file = self._transcript_dir / self.SUMMARY_FILE

    @property
    def transcript_file(self) -> Path:
        return self._main_file

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------

    def ensure_directory(self) -> None:
        """Create the transcripts/ directory if absent."""
        self._transcript_dir.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        """True if the transcript file has content."""
        return self._main_file.exists() and self._main_file.stat().st_size > 0

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_message(
        self,
        role: str,
        content: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a message to the transcript.

        Args:
            role: "user", "assistant", or "system".
            content: Message text.
            metadata: Optional extra fields (tool_calls, duration_ms, etc.).
        """
        self.ensure_directory()
        now = datetime.now(KST)

        record: Dict[str, Any] = {
            "type": "message",
            "role": role,
            "content": content,
            "ts": now.isoformat(),
        }
        if metadata:
            record["metadata"] = metadata

        self._append_jsonl(record)

    def add_event(
        self,
        event: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an event (tool call, state change, etc.) to the transcript.

        Args:
            event: Event type string (e.g., "tool_call", "state_change").
            data: Event payload.
        """
        self.ensure_directory()
        now = datetime.now(KST)

        record: Dict[str, Any] = {
            "type": "event",
            "event": event,
            "ts": now.isoformat(),
        }
        if data:
            record["data"] = data

        self._append_jsonl(record)

    def write_summary(self, summary: str) -> None:
        """Write or overwrite the session summary.

        Args:
            summary: Markdown-formatted session summary.
        """
        self.ensure_directory()
        self._summary_file.write_text(summary, encoding="utf-8")
        logger.debug(
            "ShortTermMemory: wrote summary (%d chars) to %s",
            len(summary), self._summary_file,
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def load_all(self) -> List[MemoryEntry]:
        """Load all transcript entries as MemoryEntry objects."""
        records = self._read_jsonl()
        entries: list[MemoryEntry] = []

        for i, record in enumerate(records):
            if record.get("type") != "message":
                continue

            role = record.get("role", "unknown")
            content = record.get("content", "")
            ts_str = record.get("ts")

            timestamp = None
            if ts_str:
                try:
                    timestamp = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    pass

            entries.append(MemoryEntry(
                source=MemorySource.SHORT_TERM,
                content=f"[{role}] {content}",
                timestamp=timestamp,
                filename=str(self._main_file.relative_to(self._storage_path)),
                line_start=i + 1,
                line_end=i + 1,
                metadata={"role": role, **(record.get("metadata") or {})},
            ))

        return entries

    def get_recent(self, n: int = 20) -> List[MemoryEntry]:
        """Load the N most recent messages.

        Args:
            n: Number of messages to return.
        """
        all_entries = self.load_all()
        return all_entries[-n:] if len(all_entries) > n else all_entries

    def get_summary(self) -> Optional[str]:
        """Load the session summary if it exists."""
        if not self._summary_file.exists():
            return None
        try:
            return self._summary_file.read_text(encoding="utf-8").strip() or None
        except (OSError, UnicodeDecodeError):
            return None

    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> List[MemorySearchResult]:
        """Keyword search over transcript messages.

        Args:
            query: Search string.
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

        for entry in entries:
            content_lower = entry.content.lower()
            hits = sum(content_lower.count(kw) for kw in keywords)
            if hits == 0:
                continue

            score = hits / max(1, len(entry.content.split()))

            # Recency boost: more recent entries score higher
            if entry.line_start is not None:
                recency = entry.line_start / max(1, len(entries))
                score = score * 0.6 + recency * 0.4

            snippet = entry.content[:240]
            if len(entry.content) > 240:
                snippet += "..."

            results.append(MemorySearchResult(
                entry=entry,
                score=score,
                snippet=snippet,
                match_type="keyword",
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:max_results]

    def message_count(self) -> int:
        """Count total messages in the transcript."""
        records = self._read_jsonl()
        return sum(1 for r in records if r.get("type") == "message")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_jsonl(self, record: Dict[str, Any]) -> None:
        """Append a JSON record to the transcript file."""
        try:
            with open(self._main_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning("ShortTermMemory: write failed: %s", exc)

    def _read_jsonl(self) -> List[Dict[str, Any]]:
        """Read all records from the transcript file."""
        if not self._main_file.exists():
            return []

        records: list[Dict[str, Any]] = []
        try:
            with open(self._main_file, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.debug(
                            "ShortTermMemory: bad JSON at line %d", line_no
                        )
        except OSError as exc:
            logger.warning("ShortTermMemory: read failed: %s", exc)

        return records
