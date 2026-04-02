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

# Use configured timezone from GENY_TIMEZONE env var
from service.utils.utils import _configured_tz as _get_tz

# Maximum transcript entries kept in the JSONL file.
# DB retains full history; this limit prevents unbounded file growth.
MAX_TRANSCRIPT_ENTRIES = 2000

# Check for file truncation every N writes (amortised cost).
_TRUNCATE_CHECK_INTERVAL = 100


class ShortTermMemory:
    """JSONL-backed short-term transcript memory.

    Each message exchanged with the LLM is persisted as a JSONL line,
    enabling post-session review, search, and context replay.

    Supports DB-backed storage (primary) with JSONL file fallback.

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

        # DB support (set via set_database)
        self._db_manager = None
        self._session_id: Optional[str] = None

        # Write counter for periodic file truncation
        self._write_count: int = 0

    def set_database(self, db_manager, session_id: str) -> None:
        """Enable DB-backed persistence for this memory store.

        Args:
            db_manager: AppDatabaseManager instance.
            session_id: Session ID for DB queries.
        """
        self._db_manager = db_manager
        self._session_id = session_id
        logger.debug("ShortTermMemory: DB backend enabled for session %s", session_id)

    @property
    def _db_available(self) -> bool:
        """True if DB is configured and the session ID is set."""
        return self._db_manager is not None and self._session_id is not None

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
        now = datetime.now(_get_tz())

        record: Dict[str, Any] = {
            "type": "message",
            "role": role,
            "content": content,
            "ts": now.isoformat(),
        }
        if metadata:
            record["metadata"] = metadata

        self._append_jsonl(record)

        # Dual-write to DB
        if self._db_available:
            try:
                from service.database.memory_db_helper import db_stm_add_message
                db_stm_add_message(
                    self._db_manager,
                    self._session_id,
                    role=role,
                    content=content,
                    metadata=metadata,
                )
            except Exception as e:
                logger.debug("ShortTermMemory: DB write failed (non-critical): %s", e)

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
        now = datetime.now(_get_tz())

        record: Dict[str, Any] = {
            "type": "event",
            "event": event,
            "ts": now.isoformat(),
        }
        if data:
            record["data"] = data

        self._append_jsonl(record)

        # Dual-write to DB
        if self._db_available:
            try:
                from service.database.memory_db_helper import db_stm_add_event
                db_stm_add_event(
                    self._db_manager,
                    self._session_id,
                    event_name=event,
                    data=data,
                )
            except Exception as e:
                logger.debug("ShortTermMemory: DB event write failed (non-critical): %s", e)

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

        # Dual-write to DB
        if self._db_available:
            try:
                from service.database.memory_db_helper import db_stm_write_summary
                db_stm_write_summary(self._db_manager, self._session_id, summary)
            except Exception as e:
                logger.debug("ShortTermMemory: DB summary write failed (non-critical): %s", e)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def load_all(self) -> List[MemoryEntry]:
        """Load all transcript entries as MemoryEntry objects.

        Tries DB first, falls back to JSONL file.
        """
        # Try DB first
        if self._db_available:
            db_entries = self._load_all_from_db()
            if db_entries is not None:
                return db_entries

        # Fallback to file
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

    def _load_all_from_db(self) -> Optional[List[MemoryEntry]]:
        """Load all entries from DB. Returns None if unavailable."""
        try:
            from service.database.memory_db_helper import db_stm_load_all
            rows = db_stm_load_all(self._db_manager, self._session_id)
            if rows is None:
                return None

            entries: list[MemoryEntry] = []
            for i, row in enumerate(rows):
                entry_type = row.get("entry_type", "message")
                role = row.get("role", "unknown")
                content = row.get("content", "")
                ts_str = row.get("entry_timestamp", "")

                timestamp = None
                if ts_str:
                    try:
                        timestamp = datetime.fromisoformat(ts_str)
                    except (ValueError, TypeError):
                        pass

                if entry_type == "message":
                    display = f"[{role}] {content}"
                else:
                    event_name = row.get("event_name", "event")
                    display = f"[event:{event_name}]"

                entries.append(MemoryEntry(
                    source=MemorySource.SHORT_TERM,
                    content=display,
                    timestamp=timestamp,
                    filename=str(self._main_file.relative_to(self._storage_path)),
                    line_start=i + 1,
                    line_end=i + 1,
                    metadata={"role": role, **row.get("metadata", {})},
                ))
            return entries
        except Exception as e:
            logger.debug("ShortTermMemory: DB load_all failed, falling back to file: %s", e)
            return None

    def get_recent(self, n: int = 20) -> List[MemoryEntry]:
        """Load the N most recent messages.

        Tries DB first, falls back to JSONL file.

        Args:
            n: Number of messages to return.
        """
        # Try DB first
        if self._db_available:
            try:
                from service.database.memory_db_helper import db_stm_get_recent
                rows = db_stm_get_recent(self._db_manager, self._session_id, n=n)
                if rows is not None:
                    entries: list[MemoryEntry] = []
                    for i, row in enumerate(rows):
                        role = row.get("role", "unknown")
                        content = row.get("content", "")
                        ts_str = row.get("entry_timestamp", "")
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
                            metadata={"role": role, **row.get("metadata", {})},
                        ))
                    return entries
            except Exception as e:
                logger.debug("ShortTermMemory: DB get_recent failed: %s", e)

        # Fallback
        all_entries = self.load_all()
        return all_entries[-n:] if len(all_entries) > n else all_entries

    def get_summary(self) -> Optional[str]:
        """Load the session summary if it exists.

        Tries DB first, falls back to file.
        """
        # Try DB first
        if self._db_available:
            try:
                from service.database.memory_db_helper import db_stm_get_summary
                summary = db_stm_get_summary(self._db_manager, self._session_id)
                if summary is not None:
                    return summary
            except Exception as e:
                logger.debug("ShortTermMemory: DB get_summary failed: %s", e)

        # Fallback to file
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

        Tries DB first, falls back to file-based search.

        Args:
            query: Search string.
            max_results: Maximum results to return.
        """
        if not query.strip():
            return []

        # Try DB first
        if self._db_available:
            try:
                from service.database.memory_db_helper import db_stm_search
                db_rows = db_stm_search(
                    self._db_manager, self._session_id,
                    query_text=query, max_results=max_results,
                )
                if db_rows is not None and len(db_rows) > 0:
                    results: list[MemorySearchResult] = []
                    for row in db_rows:
                        content = f"[{row.get('role', 'unknown')}] {row.get('content', '')}"
                        ts_str = row.get("entry_timestamp", "")
                        timestamp = None
                        if ts_str:
                            try:
                                timestamp = datetime.fromisoformat(ts_str)
                            except (ValueError, TypeError):
                                pass
                        entry = MemoryEntry(
                            source=MemorySource.SHORT_TERM,
                            content=content,
                            timestamp=timestamp,
                            filename=str(self._main_file.relative_to(self._storage_path)),
                            metadata={"role": row.get("role", ""), **row.get("metadata", {})},
                        )
                        snippet = content[:240] + "..." if len(content) > 240 else content
                        results.append(MemorySearchResult(
                            entry=entry,
                            score=1.0,
                            snippet=snippet,
                            match_type="db_keyword",
                        ))
                    return results
            except Exception as e:
                logger.debug("ShortTermMemory: DB search failed: %s", e)

        # Fallback to file-based search
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
        """Count total messages in the transcript.

        Tries DB first, falls back to file.
        """
        if self._db_available:
            try:
                from service.database.memory_db_helper import db_stm_message_count
                count = db_stm_message_count(self._db_manager, self._session_id)
                if count is not None:
                    return count
            except Exception as e:
                logger.debug("ShortTermMemory: DB message_count failed: %s", e)

        # Fallback
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

        # Periodic truncation to prevent unbounded file growth
        self._write_count += 1
        if self._write_count % _TRUNCATE_CHECK_INTERVAL == 0:
            self._maybe_truncate_file()

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

    def _maybe_truncate_file(self) -> None:
        """Truncate JSONL file to MAX_TRANSCRIPT_ENTRIES if oversized.

        DB retains full history; this only trims the file to prevent
        unbounded growth.  Keeps the most recent entries.
        """
        if not self._main_file.exists():
            return
        try:
            records = self._read_jsonl()
            if len(records) <= MAX_TRANSCRIPT_ENTRIES:
                return

            keep = records[-MAX_TRANSCRIPT_ENTRIES:]
            with open(self._main_file, "w", encoding="utf-8") as f:
                for rec in keep:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

            logger.info(
                "ShortTermMemory: truncated %d → %d entries (DB retains full history)",
                len(records), len(keep),
            )
        except Exception as exc:
            logger.debug("ShortTermMemory: truncation failed (non-critical): %s", exc)
