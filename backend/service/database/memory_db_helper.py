"""
Memory DB Helper — Read/write session memory entries from/to PostgreSQL.

Provides DB-backed persistence for both long-term (MEMORY.md, dated files)
and short-term (JSONL transcript) memory entries.
Used by LongTermMemory and ShortTermMemory when DB is available.
"""
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from service.database.app_database_manager import AppDatabaseManager

logger = logging.getLogger("memory-db-helper")

TABLE = "session_memory_entries"
# Use configured timezone from GENY_TIMEZONE env var
from service.utils.utils import _configured_tz as _get_tz


def _get_db_manager(db_manager):
    """Extract the actual DatabaseManager instance."""
    if db_manager is None:
        return None
    if hasattr(db_manager, "db_manager"):
        return db_manager.db_manager
    return db_manager


def _is_db_available(db_manager) -> bool:
    """Check if the DB connection is available."""
    actual = _get_db_manager(db_manager)
    if actual is None:
        return False
    if hasattr(actual, "_is_pool_healthy"):
        return actual._is_pool_healthy()
    return False


# ======================================================================
#  Long-Term Memory — Write
# ======================================================================

def db_ltm_append(
    db_manager,
    session_id: str,
    content: str,
    *,
    filename: str = "memory/MEMORY.md",
    heading: str = "",
) -> bool:
    """Append a long-term memory entry.

    Args:
        db_manager: AppDatabaseManager or DatabaseManager.
        session_id: Session ID.
        content: Memory content text.
        filename: Relative file path within session.
        heading: Optional markdown heading.

    Returns:
        True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        entry_id = str(uuid.uuid4())
        now = datetime.now(_get_tz()).isoformat()
        query = (
            f"INSERT INTO {TABLE} "
            f"(entry_id, session_id, source, entry_type, content, filename, heading, entry_timestamp) "
            f"VALUES (%s, %s, 'long_term', 'text', %s, %s, %s, %s) "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (entry_id, session_id, content, filename, heading, now))
        return True
    except Exception as e:
        logger.debug(f"Failed to insert LTM entry for {session_id}: {e}")
        return False


def db_ltm_write_dated(
    db_manager,
    session_id: str,
    content: str,
    date_str: str = "",
) -> bool:
    """Write a dated long-term memory entry.

    Args:
        db_manager: AppDatabaseManager or DatabaseManager.
        session_id: Session ID.
        content: Memory content text.
        date_str: Date string (YYYY-MM-DD).

    Returns:
        True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        entry_id = str(uuid.uuid4())
        now = datetime.now(_get_tz()).isoformat()
        if not date_str:
            date_str = datetime.now(_get_tz()).strftime("%Y-%m-%d")
        filename = f"memory/{date_str}.md"
        query = (
            f"INSERT INTO {TABLE} "
            f"(entry_id, session_id, source, entry_type, content, filename, entry_timestamp) "
            f"VALUES (%s, %s, 'long_term', 'dated', %s, %s, %s) "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (entry_id, session_id, content, filename, now))
        return True
    except Exception as e:
        logger.debug(f"Failed to insert LTM dated entry for {session_id}: {e}")
        return False


def db_ltm_write_topic(
    db_manager,
    session_id: str,
    topic: str,
    content: str,
) -> bool:
    """Write a topic-specific long-term memory entry.

    Returns:
        True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        import re
        slug = re.sub(r"[^a-z0-9_-]", "_", topic.lower().strip())[:64]
        entry_id = str(uuid.uuid4())
        now = datetime.now(_get_tz()).isoformat()
        filename = f"memory/topics/{slug}.md"
        query = (
            f"INSERT INTO {TABLE} "
            f"(entry_id, session_id, source, entry_type, content, filename, topic, entry_timestamp) "
            f"VALUES (%s, %s, 'long_term', 'topic', %s, %s, %s, %s) "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (entry_id, session_id, content, filename, topic, now))
        return True
    except Exception as e:
        logger.debug(f"Failed to insert LTM topic entry for {session_id}: {e}")
        return False


# ======================================================================
#  Long-Term Memory — Read
# ======================================================================

def db_ltm_load_all(
    db_manager,
    session_id: str,
) -> Optional[List[Dict[str, Any]]]:
    """Load all long-term memory entries for a session.

    Returns:
        List of entry dicts with keys: content, filename, entry_type, heading, topic, entry_timestamp.
        None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = (
            f"SELECT entry_id, content, filename, entry_type, heading, topic, entry_timestamp "
            f"FROM {TABLE} "
            f"WHERE session_id = %s AND source = 'long_term' "
            f"ORDER BY id ASC"
        )
        rows = mgr.execute_query(query, (session_id,))
        if rows is None:
            return None

        return [
            {
                "entry_id": row.get("entry_id", ""),
                "content": row.get("content", ""),
                "filename": row.get("filename", ""),
                "entry_type": row.get("entry_type", "text"),
                "heading": row.get("heading", ""),
                "topic": row.get("topic", ""),
                "entry_timestamp": row.get("entry_timestamp", ""),
            }
            for row in rows
        ]
    except Exception as e:
        logger.debug(f"Failed to load LTM entries for {session_id}: {e}")
        return None


def db_ltm_search(
    db_manager,
    session_id: str,
    query_text: str,
    max_results: int = 5,
) -> Optional[List[Dict[str, Any]]]:
    """Keyword search over long-term memory entries in DB.

    Uses PostgreSQL ILIKE for case-insensitive matching.

    Returns:
        List of matching entry dicts, or None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    keywords = [w for w in query_text.lower().split() if len(w) >= 2]
    if not keywords:
        return None

    try:
        # Build WHERE clause: content ILIKE '%keyword1%' AND content ILIKE '%keyword2%' ...
        # Use OR for broader results
        conditions = " OR ".join(["content ILIKE %s"] * len(keywords))
        params = [session_id] + [f"%{kw}%" for kw in keywords] + [max_results]

        query = (
            f"SELECT entry_id, content, filename, entry_type, heading, topic, entry_timestamp "
            f"FROM {TABLE} "
            f"WHERE session_id = %s AND source = 'long_term' AND ({conditions}) "
            f"ORDER BY id DESC LIMIT %s"
        )
        rows = mgr.execute_query(query, tuple(params))
        if rows is None:
            return None

        return [
            {
                "entry_id": row.get("entry_id", ""),
                "content": row.get("content", ""),
                "filename": row.get("filename", ""),
                "entry_type": row.get("entry_type", "text"),
                "heading": row.get("heading", ""),
                "topic": row.get("topic", ""),
                "entry_timestamp": row.get("entry_timestamp", ""),
            }
            for row in rows
        ]
    except Exception as e:
        logger.debug(f"Failed to search LTM entries for {session_id}: {e}")
        return None


# ======================================================================
#  Short-Term Memory — Write
# ======================================================================

def db_stm_add_message(
    db_manager,
    session_id: str,
    role: str,
    content: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Add a short-term memory message (conversation transcript).

    Args:
        db_manager: AppDatabaseManager or DatabaseManager.
        session_id: Session ID.
        role: "user", "assistant", or "system".
        content: Message text.
        metadata: Optional extra fields.

    Returns:
        True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        entry_id = str(uuid.uuid4())
        now = datetime.now(_get_tz()).isoformat()
        meta_str = json.dumps(metadata, ensure_ascii=False, default=str) if metadata else "{}"
        query = (
            f"INSERT INTO {TABLE} "
            f"(entry_id, session_id, source, entry_type, content, role, metadata_json, entry_timestamp) "
            f"VALUES (%s, %s, 'short_term', 'message', %s, %s, %s, %s) "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (entry_id, session_id, content, role, meta_str, now))
        return True
    except Exception as e:
        logger.debug(f"Failed to insert STM message for {session_id}: {e}")
        return False


def db_stm_add_event(
    db_manager,
    session_id: str,
    event_name: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Add a short-term memory event (tool call, state change, etc.).

    Returns:
        True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        entry_id = str(uuid.uuid4())
        now = datetime.now(_get_tz()).isoformat()
        data_str = json.dumps(data, ensure_ascii=False, default=str) if data else "{}"
        query = (
            f"INSERT INTO {TABLE} "
            f"(entry_id, session_id, source, entry_type, content, event_name, metadata_json, entry_timestamp) "
            f"VALUES (%s, %s, 'short_term', 'event', '', %s, %s, %s) "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (entry_id, session_id, event_name, data_str, now))
        return True
    except Exception as e:
        logger.debug(f"Failed to insert STM event for {session_id}: {e}")
        return False


def db_stm_write_summary(
    db_manager,
    session_id: str,
    summary: str,
) -> bool:
    """Write or replace the session summary in DB.

    Uses UPSERT on a well-known entry_id pattern: {session_id}__summary.

    Returns:
        True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        entry_id = f"{session_id}__summary"
        now = datetime.now(_get_tz()).isoformat()
        query = (
            f"INSERT INTO {TABLE} "
            f"(entry_id, session_id, source, entry_type, content, filename, entry_timestamp) "
            f"VALUES (%s, %s, 'short_term', 'summary', %s, 'transcripts/summary.md', %s) "
            f"ON CONFLICT (entry_id) DO UPDATE SET "
            f"content = EXCLUDED.content, entry_timestamp = EXCLUDED.entry_timestamp, "
            f"updated_at = CURRENT_TIMESTAMP "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (entry_id, session_id, summary, now))
        return True
    except Exception as e:
        logger.debug(f"Failed to write STM summary for {session_id}: {e}")
        return False


# ======================================================================
#  Short-Term Memory — Read
# ======================================================================

def db_stm_load_all(
    db_manager,
    session_id: str,
) -> Optional[List[Dict[str, Any]]]:
    """Load all short-term memory entries (messages + events) for a session.

    Returns:
        List of entry dicts in chronological order, or None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = (
            f"SELECT entry_id, entry_type, content, role, event_name, "
            f"metadata_json, entry_timestamp "
            f"FROM {TABLE} "
            f"WHERE session_id = %s AND source = 'short_term' AND entry_type != 'summary' "
            f"ORDER BY id ASC"
        )
        rows = mgr.execute_query(query, (session_id,))
        if rows is None:
            return None

        entries = []
        for row in rows:
            meta = {}
            meta_str = row.get("metadata_json", "{}")
            if meta_str:
                try:
                    meta = json.loads(meta_str)
                except (json.JSONDecodeError, TypeError):
                    pass
            entries.append({
                "entry_id": row.get("entry_id", ""),
                "entry_type": row.get("entry_type", "message"),
                "content": row.get("content", ""),
                "role": row.get("role", ""),
                "event_name": row.get("event_name", ""),
                "metadata": meta,
                "entry_timestamp": row.get("entry_timestamp", ""),
            })
        return entries
    except Exception as e:
        logger.debug(f"Failed to load STM entries for {session_id}: {e}")
        return None


def db_stm_get_recent(
    db_manager,
    session_id: str,
    n: int = 20,
) -> Optional[List[Dict[str, Any]]]:
    """Get the N most recent short-term memory messages.

    Returns:
        List of message dicts (chronological order), or None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        # Sub-query: get last N messages, then sort ascending
        query = (
            f"SELECT * FROM ("
            f"  SELECT entry_id, content, role, metadata_json, entry_timestamp "
            f"  FROM {TABLE} "
            f"  WHERE session_id = %s AND source = 'short_term' AND entry_type = 'message' "
            f"  ORDER BY id DESC LIMIT %s"
            f") sub ORDER BY sub.entry_timestamp ASC"
        )
        rows = mgr.execute_query(query, (session_id, n))
        if rows is None:
            return None

        entries = []
        for row in rows:
            meta = {}
            meta_str = row.get("metadata_json", "{}")
            if meta_str:
                try:
                    meta = json.loads(meta_str)
                except (json.JSONDecodeError, TypeError):
                    pass
            entries.append({
                "entry_id": row.get("entry_id", ""),
                "content": row.get("content", ""),
                "role": row.get("role", ""),
                "metadata": meta,
                "entry_timestamp": row.get("entry_timestamp", ""),
            })
        return entries
    except Exception as e:
        logger.debug(f"Failed to get recent STM for {session_id}: {e}")
        return None


def db_stm_get_summary(
    db_manager,
    session_id: str,
) -> Optional[str]:
    """Get the session summary from DB.

    Returns:
        Summary text, or None if not found or on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        entry_id = f"{session_id}__summary"
        query = (
            f"SELECT content FROM {TABLE} "
            f"WHERE entry_id = %s"
        )
        row = mgr.execute_query_one(query, (entry_id,))
        if row:
            content = row.get("content", "")
            return content if content else None
        return None
    except Exception as e:
        logger.debug(f"Failed to get STM summary for {session_id}: {e}")
        return None


def db_stm_search(
    db_manager,
    session_id: str,
    query_text: str,
    max_results: int = 10,
) -> Optional[List[Dict[str, Any]]]:
    """Keyword search over short-term memory entries in DB.

    Returns:
        List of matching entry dicts, or None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    keywords = [w for w in query_text.lower().split() if len(w) >= 2]
    if not keywords:
        return None

    try:
        conditions = " OR ".join(["content ILIKE %s"] * len(keywords))
        params = [session_id] + [f"%{kw}%" for kw in keywords] + [max_results]

        query = (
            f"SELECT entry_id, content, role, metadata_json, entry_timestamp "
            f"FROM {TABLE} "
            f"WHERE session_id = %s AND source = 'short_term' "
            f"AND entry_type = 'message' AND ({conditions}) "
            f"ORDER BY id DESC LIMIT %s"
        )
        rows = mgr.execute_query(query, tuple(params))
        if rows is None:
            return None

        entries = []
        for row in rows:
            meta = {}
            meta_str = row.get("metadata_json", "{}")
            if meta_str:
                try:
                    meta = json.loads(meta_str)
                except (json.JSONDecodeError, TypeError):
                    pass
            entries.append({
                "entry_id": row.get("entry_id", ""),
                "content": row.get("content", ""),
                "role": row.get("role", ""),
                "metadata": meta,
                "entry_timestamp": row.get("entry_timestamp", ""),
            })
        return entries
    except Exception as e:
        logger.debug(f"Failed to search STM entries for {session_id}: {e}")
        return None


def db_stm_message_count(
    db_manager,
    session_id: str,
) -> Optional[int]:
    """Count total messages in short-term memory.

    Returns:
        Message count, or None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = (
            f"SELECT COUNT(*) as cnt FROM {TABLE} "
            f"WHERE session_id = %s AND source = 'short_term' AND entry_type = 'message'"
        )
        row = mgr.execute_query_one(query, (session_id,))
        if row:
            return row.get("cnt", 0)
        return 0
    except Exception as e:
        logger.debug(f"Failed to count STM messages for {session_id}: {e}")
        return None


# ======================================================================
#  Statistics (Aggregation)
# ======================================================================

def db_memory_stats(
    db_manager,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Get memory statistics efficiently via SQL aggregation.

    Returns aggregate counts and char totals grouped by source,
    without loading individual entries into memory.

    Returns:
        Dict with long_term_entries, short_term_entries,
        long_term_chars, short_term_chars, total_files, last_write.
        None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = (
            f"SELECT source, "
            f"COUNT(*) as entry_count, "
            f"COALESCE(SUM(LENGTH(content)), 0) as total_chars, "
            f"MAX(entry_timestamp) as last_ts "
            f"FROM {TABLE} "
            f"WHERE session_id = %s "
            f"GROUP BY source"
        )
        rows = mgr.execute_query(query, (session_id,))
        if rows is None:
            return None

        stats = {
            "long_term_entries": 0,
            "short_term_entries": 0,
            "long_term_chars": 0,
            "short_term_chars": 0,
            "total_files": 0,
            "last_write": None,
        }

        last_ts = None
        for row in rows:
            source = row.get("source", "")
            count = row.get("entry_count", 0)
            chars = row.get("total_chars", 0)
            ts_str = row.get("last_ts", "")

            if source == "long_term":
                stats["long_term_entries"] = count
                stats["long_term_chars"] = chars
                stats["total_files"] = count
            elif source == "short_term":
                stats["short_term_entries"] = count
                stats["short_term_chars"] = chars

            if ts_str and (last_ts is None or ts_str > last_ts):
                last_ts = ts_str

        stats["last_write"] = last_ts
        return stats
    except Exception as e:
        logger.debug(f"Failed to get memory stats for {session_id}: {e}")
        return None


# ======================================================================
#  Delete
# ======================================================================

def db_delete_session_memory(db_manager, session_id: str) -> bool:
    """Delete all memory entries for a session.

    Returns True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        query = f"DELETE FROM {TABLE} WHERE session_id = %s"
        mgr.execute_update_delete(query, (session_id,))
        return True
    except Exception as e:
        logger.debug(f"Failed to delete memory for {session_id}: {e}")
        return False


# ======================================================================
#  Migration
# ======================================================================

def db_session_has_memory(db_manager, session_id: str) -> bool:
    """Check if a session already has memory entries in DB."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        query = f"SELECT 1 FROM {TABLE} WHERE session_id = %s LIMIT 1"
        result = mgr.execute_query_one(query, (session_id,))
        return result is not None
    except Exception:
        return False


# ======================================================================
#  Structured Memory — Write
# ======================================================================

def db_structured_write(
    db_manager,
    session_id: str,
    *,
    content: str,
    filename: str,
    title: str = "",
    category: str = "topics",
    tags: Optional[List[str]] = None,
    importance: str = "medium",
    links_to: Optional[List[str]] = None,
    linked_from: Optional[List[str]] = None,
    source_type: str = "system",
    summary: str = "",
    entry_type: str = "text",
    heading: str = "",
    topic: str = "",
) -> bool:
    """Write a structured memory entry with full metadata.

    Returns True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        entry_id = str(uuid.uuid4())
        now = datetime.now(_get_tz()).isoformat()
        tags_str = json.dumps(tags or [], ensure_ascii=False)
        links_to_str = json.dumps(links_to or [], ensure_ascii=False)
        linked_from_str = json.dumps(linked_from or [], ensure_ascii=False)

        query = (
            f"INSERT INTO {TABLE} "
            f"(entry_id, session_id, source, entry_type, content, filename, heading, topic, "
            f"entry_timestamp, category, tags_json, importance, links_to_json, "
            f"linked_from_json, source_type, summary) "
            f"VALUES (%s, %s, 'long_term', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (
            entry_id, session_id, entry_type, content, filename, heading, topic,
            now, category, tags_str, importance, links_to_str,
            linked_from_str, source_type, summary,
        ))
        return True
    except Exception as e:
        logger.debug(f"Failed to insert structured memory for {session_id}: {e}")
        return False


def db_structured_update(
    db_manager,
    session_id: str,
    filename: str,
    *,
    content: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[List[str]] = None,
    importance: Optional[str] = None,
    links_to: Optional[List[str]] = None,
    linked_from: Optional[List[str]] = None,
    summary: Optional[str] = None,
) -> bool:
    """Update fields of an existing structured memory entry by filename.

    Only non-None fields are updated.

    Returns True if at least one row was updated.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    sets: List[str] = []
    params: list = []

    if content is not None:
        sets.append("content = %s")
        params.append(content)
    if title is not None:
        sets.append("heading = %s")
        params.append(title)
    if tags is not None:
        sets.append("tags_json = %s")
        params.append(json.dumps(tags, ensure_ascii=False))
    if importance is not None:
        sets.append("importance = %s")
        params.append(importance)
    if links_to is not None:
        sets.append("links_to_json = %s")
        params.append(json.dumps(links_to, ensure_ascii=False))
    if linked_from is not None:
        sets.append("linked_from_json = %s")
        params.append(json.dumps(linked_from, ensure_ascii=False))
    if summary is not None:
        sets.append("summary = %s")
        params.append(summary)

    if not sets:
        return False

    sets.append("updated_at = CURRENT_TIMESTAMP")
    set_clause = ", ".join(sets)
    params.extend([session_id, filename])

    try:
        query = (
            f"UPDATE {TABLE} SET {set_clause} "
            f"WHERE session_id = %s AND filename = %s AND source = 'long_term'"
        )
        mgr.execute_update_delete(query, tuple(params))
        return True
    except Exception as e:
        logger.debug(f"Failed to update structured memory for {session_id}/{filename}: {e}")
        return False


def db_structured_delete(
    db_manager,
    session_id: str,
    filename: str,
) -> bool:
    """Delete a structured memory entry by filename.

    Returns True if successful.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        query = (
            f"DELETE FROM {TABLE} "
            f"WHERE session_id = %s AND filename = %s AND source = 'long_term'"
        )
        mgr.execute_update_delete(query, (session_id, filename))
        return True
    except Exception as e:
        logger.debug(f"Failed to delete structured memory for {session_id}/{filename}: {e}")
        return False


def db_structured_read(
    db_manager,
    session_id: str,
    filename: str,
) -> Optional[Dict[str, Any]]:
    """Read a single structured memory entry by filename.

    Returns entry dict or None.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = (
            f"SELECT entry_id, content, filename, entry_type, heading, topic, "
            f"entry_timestamp, category, tags_json, importance, links_to_json, "
            f"linked_from_json, source_type, summary "
            f"FROM {TABLE} "
            f"WHERE session_id = %s AND filename = %s AND source = 'long_term' "
            f"ORDER BY id DESC LIMIT 1"
        )
        row = mgr.execute_query_one(query, (session_id, filename))
        if row is None:
            return None
        return _parse_structured_row(row)
    except Exception as e:
        logger.debug(f"Failed to read structured memory for {session_id}/{filename}: {e}")
        return None


def db_structured_list(
    db_manager,
    session_id: str,
    *,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    importance: Optional[str] = None,
    limit: int = 100,
) -> Optional[List[Dict[str, Any]]]:
    """List structured memory entries with optional filters.

    Returns list of entry dicts or None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        conditions = ["session_id = %s", "source = 'long_term'"]
        params: list = [session_id]

        if category:
            conditions.append("category = %s")
            params.append(category)
        if importance:
            conditions.append("importance = %s")
            params.append(importance)
        if tag:
            conditions.append("tags_json ILIKE %s")
            params.append(f'%"{tag}"%')

        params.append(limit)
        where = " AND ".join(conditions)
        query = (
            f"SELECT entry_id, content, filename, entry_type, heading, topic, "
            f"entry_timestamp, category, tags_json, importance, links_to_json, "
            f"linked_from_json, source_type, summary "
            f"FROM {TABLE} "
            f"WHERE {where} "
            f"ORDER BY id DESC LIMIT %s"
        )
        rows = mgr.execute_query(query, tuple(params))
        if rows is None:
            return None
        return [_parse_structured_row(r) for r in rows]
    except Exception as e:
        logger.debug(f"Failed to list structured memory for {session_id}: {e}")
        return None


def db_structured_search(
    db_manager,
    session_id: str,
    query_text: str,
    *,
    max_results: int = 10,
    category: Optional[str] = None,
    tag: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Full-text search over structured memory entries.

    Returns list of entry dicts or None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    keywords = [w for w in query_text.lower().split() if len(w) >= 2]
    if not keywords:
        return None

    try:
        conditions = ["session_id = %s", "source = 'long_term'"]
        params: list = [session_id]

        # Content keyword search (OR for broader matching)
        kw_conds = " OR ".join(
            ["(content ILIKE %s OR heading ILIKE %s OR summary ILIKE %s)"] * len(keywords)
        )
        for kw in keywords:
            pat = f"%{kw}%"
            params.extend([pat, pat, pat])
        conditions.append(f"({kw_conds})")

        if category:
            conditions.append("category = %s")
            params.append(category)
        if tag:
            conditions.append("tags_json ILIKE %s")
            params.append(f'%"{tag}"%')

        params.append(max_results)
        where = " AND ".join(conditions)
        query = (
            f"SELECT entry_id, content, filename, entry_type, heading, topic, "
            f"entry_timestamp, category, tags_json, importance, links_to_json, "
            f"linked_from_json, source_type, summary "
            f"FROM {TABLE} "
            f"WHERE {where} "
            f"ORDER BY id DESC LIMIT %s"
        )
        rows = mgr.execute_query(query, tuple(params))
        if rows is None:
            return None
        return [_parse_structured_row(r) for r in rows]
    except Exception as e:
        logger.debug(f"Failed to search structured memory for {session_id}: {e}")
        return None


def db_structured_tags(
    db_manager,
    session_id: str,
) -> Optional[Dict[str, int]]:
    """Get all tags and their counts for a session.

    Returns dict of {tag: count} or None on failure.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = (
            f"SELECT tags_json FROM {TABLE} "
            f"WHERE session_id = %s AND source = 'long_term' AND tags_json != '[]'"
        )
        rows = mgr.execute_query(query, (session_id,))
        if rows is None:
            return None

        tag_counts: Dict[str, int] = {}
        for row in rows:
            try:
                tags = json.loads(row.get("tags_json", "[]"))
                for t in tags:
                    if isinstance(t, str) and t:
                        tag_counts[t] = tag_counts.get(t, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass
        return tag_counts
    except Exception as e:
        logger.debug(f"Failed to get tags for {session_id}: {e}")
        return None


def db_structured_graph(
    db_manager,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Build link graph data for a session.

    Returns dict with 'nodes' and 'edges' lists for graph visualization.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = (
            f"SELECT filename, heading, category, importance, links_to_json, linked_from_json "
            f"FROM {TABLE} "
            f"WHERE session_id = %s AND source = 'long_term'"
        )
        rows = mgr.execute_query(query, (session_id,))
        if rows is None:
            return None

        nodes = []
        edges = []
        for row in rows:
            fn = row.get("filename", "")
            if not fn:
                continue
            nodes.append({
                "id": fn,
                "label": row.get("heading", "") or fn.split("/")[-1].replace(".md", ""),
                "category": row.get("category", ""),
                "importance": row.get("importance", "medium"),
            })
            try:
                links = json.loads(row.get("links_to_json", "[]"))
                for target in links:
                    if target:
                        edges.append({"source": fn, "target": target})
            except (json.JSONDecodeError, TypeError):
                pass

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.debug(f"Failed to build graph for {session_id}: {e}")
        return None


def _parse_structured_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a DB row into a structured memory dict."""
    tags = []
    links_to = []
    linked_from = []
    try:
        tags = json.loads(row.get("tags_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        links_to = json.loads(row.get("links_to_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        linked_from = json.loads(row.get("linked_from_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "entry_id": row.get("entry_id", ""),
        "content": row.get("content", ""),
        "filename": row.get("filename", ""),
        "entry_type": row.get("entry_type", "text"),
        "heading": row.get("heading", ""),
        "topic": row.get("topic", ""),
        "entry_timestamp": row.get("entry_timestamp", ""),
        "category": row.get("category", ""),
        "tags": tags,
        "importance": row.get("importance", "medium"),
        "links_to": links_to,
        "linked_from": linked_from,
        "source_type": row.get("source_type", "system"),
        "summary": row.get("summary", ""),
    }
