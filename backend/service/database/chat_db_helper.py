"""
Chat DB Helper — Read/write chat rooms and messages from/to PostgreSQL.

Provides the same logical operations as the file-based ChatConversationStore
but backed by the 'chat_rooms' and 'chat_messages' tables.
Used by ChatConversationStore when DB is available.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from service.database.database_manager import DatabaseManager
    from service.database.app_database_manager import AppDatabaseManager

logger = logging.getLogger("chat-db-helper")

ROOMS_TABLE = "chat_rooms"
MESSAGES_TABLE = "chat_messages"


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
#  Room CRUD
# ======================================================================

def db_create_room(db_manager, room_id: str, name: str,
                   session_ids: List[str]) -> Optional[Dict[str, Any]]:
    """Create a new chat room."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        now = datetime.now(timezone.utc).isoformat()
        session_ids_json = json.dumps(session_ids, ensure_ascii=False)

        query = (
            f"INSERT INTO {ROOMS_TABLE} (room_id, name, session_ids, message_count) "
            f"VALUES (%s, %s, %s, %s) "
            f"ON CONFLICT (room_id) DO UPDATE SET "
            f"  name = EXCLUDED.name, session_ids = EXCLUDED.session_ids, "
            f"  updated_at = CURRENT_TIMESTAMP "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (room_id, name, session_ids_json, 0))

        return {
            "id": room_id,
            "name": name,
            "session_ids": session_ids,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }
    except Exception as e:
        logger.error(f"Failed to create room {room_id} in DB: {e}")
        return None


def db_list_rooms(db_manager) -> List[Dict[str, Any]]:
    """Return all chat rooms sorted by last activity."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return []

    try:
        query = f"SELECT * FROM {ROOMS_TABLE} ORDER BY updated_at DESC"
        rows = mgr.execute_query(query)
        if not rows:
            return []

        result = []
        for row in rows:
            r = dict(row)
            # Parse session_ids from JSON text
            raw_ids = r.get("session_ids", "[]") or "[]"
            try:
                ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
            except (json.JSONDecodeError, TypeError):
                ids = []
            result.append({
                "id": r["room_id"],
                "name": r.get("name", ""),
                "session_ids": ids,
                "created_at": str(r.get("created_at", "")),
                "updated_at": str(r.get("updated_at", "")),
                "message_count": r.get("message_count", 0),
            })
        return result
    except Exception as e:
        logger.error(f"Failed to list rooms from DB: {e}")
        return []


def db_get_room(db_manager, room_id: str) -> Optional[Dict[str, Any]]:
    """Get a single room by room_id."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = f"SELECT * FROM {ROOMS_TABLE} WHERE room_id = %s LIMIT 1"
        row = mgr.execute_query_one(query, (room_id,))
        if not row:
            return None

        r = dict(row)
        raw_ids = r.get("session_ids", "[]") or "[]"
        try:
            ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
        except (json.JSONDecodeError, TypeError):
            ids = []

        return {
            "id": r["room_id"],
            "name": r.get("name", ""),
            "session_ids": ids,
            "created_at": str(r.get("created_at", "")),
            "updated_at": str(r.get("updated_at", "")),
            "message_count": r.get("message_count", 0),
        }
    except Exception as e:
        logger.error(f"Failed to get room {room_id} from DB: {e}")
        return None


def db_update_room_sessions(db_manager, room_id: str,
                            session_ids: List[str]) -> bool:
    """Update session list for a room."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        session_ids_json = json.dumps(session_ids, ensure_ascii=False)
        query = (
            f"UPDATE {ROOMS_TABLE} SET session_ids = %s, "
            f"updated_at = CURRENT_TIMESTAMP WHERE room_id = %s"
        )
        mgr.execute_update_delete(query, (session_ids_json, room_id))
        return True
    except Exception as e:
        logger.error(f"Failed to update room sessions {room_id}: {e}")
        return False


def db_update_room_name(db_manager, room_id: str, name: str) -> bool:
    """Rename a room."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        query = (
            f"UPDATE {ROOMS_TABLE} SET name = %s, "
            f"updated_at = CURRENT_TIMESTAMP WHERE room_id = %s"
        )
        mgr.execute_update_delete(query, (name, room_id))
        return True
    except Exception as e:
        logger.error(f"Failed to update room name {room_id}: {e}")
        return False


def db_delete_room(db_manager, room_id: str) -> bool:
    """Delete a room and all its messages."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        # Delete messages first (child records)
        mgr.execute_update_delete(
            f"DELETE FROM {MESSAGES_TABLE} WHERE room_id = %s", (room_id,)
        )
        # Delete room
        affected = mgr.execute_update_delete(
            f"DELETE FROM {ROOMS_TABLE} WHERE room_id = %s", (room_id,)
        )
        return affected is not None and affected > 0
    except Exception as e:
        logger.error(f"Failed to delete room {room_id}: {e}")
        return False


def db_update_room_metadata(db_manager, room_id: str,
                            message_count: int, updated_at: str) -> bool:
    """Update room metadata (message_count, updated_at)."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        query = (
            f"UPDATE {ROOMS_TABLE} SET message_count = %s, "
            f"updated_at = %s WHERE room_id = %s"
        )
        mgr.execute_update_delete(query, (message_count, updated_at, room_id))
        return True
    except Exception as e:
        logger.error(f"Failed to update room metadata {room_id}: {e}")
        return False


# ======================================================================
#  Message CRUD
# ======================================================================

def db_add_message(db_manager, room_id: str,
                   message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Insert a single message into the DB."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        msg_id = message.get("id") or str(uuid.uuid4())
        timestamp = message.get("timestamp") or datetime.now(timezone.utc).isoformat()

        # Serialize file_changes list to JSON string for TEXT column
        fc_raw = message.get("file_changes")
        fc_json = json.dumps(fc_raw, ensure_ascii=False) if fc_raw else None
        # Serialize attachments list (image / file refs uploaded via
        # POST /api/uploads). The DB stores only metadata + URLs;
        # raw bytes live on disk under backend/static/uploads.
        att_raw = message.get("attachments")
        att_json = json.dumps(att_raw, ensure_ascii=False) if att_raw else None

        query = (
            f"INSERT INTO {MESSAGES_TABLE} "
            f"(message_id, room_id, type, content, session_id, session_name, role, duration_ms, cost_usd, timestamp, file_changes, attachments) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"ON CONFLICT (message_id) DO NOTHING "
            f"RETURNING id"
        )
        mgr.execute_insert(query, (
            msg_id,
            room_id,
            message.get("type", "user"),
            message.get("content", ""),
            message.get("session_id", ""),
            message.get("session_name", ""),
            message.get("role", ""),
            message.get("duration_ms", 0) or 0,
            message.get("cost_usd"),
            timestamp,
            fc_json,
            att_json,
        ))

        result = dict(message)
        result["id"] = msg_id
        result["timestamp"] = timestamp
        return result
    except Exception as e:
        logger.error(f"Failed to add message to room {room_id}: {e}")
        return None


def db_add_messages_batch(db_manager, room_id: str,
                          messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Insert multiple messages at once."""
    results = []
    for msg in messages:
        result = db_add_message(db_manager, room_id, msg)
        if result:
            results.append(result)
    return results


def db_get_messages(db_manager, room_id: str, *, limit: int = 0, before: str = "") -> List[Dict[str, Any]]:
    """Load messages for a room, ordered by timestamp.

    Args:
        limit: Max messages to return. 0 = unlimited (all).
        before: If given, return only messages with DB ``id`` less than the row
                whose ``message_id`` matches this value (cursor-based paging).
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return []

    try:
        params: list = [room_id]
        where_clause = f"WHERE room_id = %s"

        if before:
            where_clause += (
                f" AND id < (SELECT id FROM {MESSAGES_TABLE}"
                f" WHERE room_id = %s AND message_id = %s LIMIT 1)"
            )
            params.extend([room_id, before])

        if limit > 0:
            # When paging backwards we want the *last* N rows before the cursor,
            # so we sort DESC, take N, then re-sort ASC in a subquery.
            query = (
                f"SELECT * FROM ("
                f"  SELECT * FROM {MESSAGES_TABLE} {where_clause}"
                f"  ORDER BY id DESC LIMIT %s"
                f") sub ORDER BY id ASC"
            )
            params.append(limit)
        else:
            query = (
                f"SELECT * FROM {MESSAGES_TABLE} {where_clause} "
                f"ORDER BY id ASC"
            )

        rows = mgr.execute_query(query, tuple(params))
        if not rows:
            return []

        result = []
        for row in rows:
            r = dict(row)
            msg: Dict[str, Any] = {
                "id": r.get("message_id", ""),
                "type": r.get("type", "user"),
                "content": r.get("content", ""),
                "timestamp": r.get("timestamp", ""),
                "session_id": r.get("session_id", ""),
                "session_name": r.get("session_name", ""),
                "role": r.get("role", ""),
                "duration_ms": r.get("duration_ms", 0),
                "cost_usd": r.get("cost_usd"),
            }
            # Deserialize file_changes from JSON string
            fc_str = r.get("file_changes")
            if fc_str:
                try:
                    msg["file_changes"] = json.loads(fc_str)
                except (json.JSONDecodeError, TypeError):
                    pass
            # Deserialize attachments (list of upload metadata refs).
            att_str = r.get("attachments")
            if att_str:
                try:
                    msg["attachments"] = json.loads(att_str)
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(msg)
        return result
    except Exception as e:
        logger.error(f"Failed to get messages for room {room_id}: {e}")
        return []


def db_get_message_count(db_manager, room_id: str) -> int:
    """Get the number of messages in a room."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return 0

    try:
        query = f"SELECT COUNT(*) as cnt FROM {MESSAGES_TABLE} WHERE room_id = %s"
        row = mgr.execute_query_one(query, (room_id,))
        if row:
            return row.get("cnt", 0)
        return 0
    except Exception:
        return 0


def db_delete_old_messages(db_manager, retention_days: int) -> int:
    """Delete messages older than ``retention_days`` across all rooms.

    Returns the number of deleted rows.
    """
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return 0

    try:
        query = (
            f"DELETE FROM {MESSAGES_TABLE} "
            f"WHERE timestamp < (NOW() - INTERVAL '%s days')"
        )
        result = mgr.execute_query(query, (retention_days,))
        # execute_query may return row count or None depending on driver
        if isinstance(result, int):
            return result
        return 0
    except Exception as e:
        logger.error(f"Failed to delete old messages: {e}")
        return 0


# ======================================================================
#  Migration helper
# ======================================================================

def db_migrate_rooms_from_json(db_manager, rooms: List[Dict[str, Any]],
                               messages_loader=None) -> int:
    """
    Migrate chat room and message data from JSON files into DB.

    Args:
        db_manager: DB manager instance.
        rooms: List of room dicts from rooms.json.
        messages_loader: Callable(room_id) -> List[Dict] that loads messages
                         for a given room from JSON file.

    Returns:
        Number of rooms migrated.
    """
    if not _is_db_available(db_manager):
        return 0

    migrated = 0
    for room in rooms:
        room_id = room.get("id", "")
        if not room_id:
            continue

        # Skip if room already exists in DB
        existing = db_get_room(db_manager, room_id)
        if existing:
            continue

        # Create room
        session_ids = room.get("session_ids", [])
        result = db_create_room(db_manager, room_id, room.get("name", ""), session_ids)
        if not result:
            continue

        # Migrate messages if loader is available
        if messages_loader:
            try:
                msgs = messages_loader(room_id)
                if msgs:
                    db_add_messages_batch(db_manager, room_id, msgs)
                    db_update_room_metadata(db_manager, room_id, len(msgs),
                                            datetime.now(timezone.utc).isoformat())
            except Exception as e:
                logger.warning(f"Failed to migrate messages for room {room_id}: {e}")

        migrated += 1

    if migrated > 0:
        logger.info(f"Migrated {migrated} chat rooms from JSON to DB")
    return migrated
