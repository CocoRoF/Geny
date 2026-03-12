"""
Session DB Helper — Read/write session metadata from/to PostgreSQL.

Provides the same logical operations as the file-based SessionStore
but backed by the 'sessions' table. Used by SessionStore when DB is available.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from service.database.database_manager import DatabaseManager
    from service.database.app_database_manager import AppDatabaseManager

logger = logging.getLogger("session-db-helper")

TABLE = "sessions"

# Fields stored in dedicated columns (everything else goes into extra_data).
_COLUMN_FIELDS = {
    "session_id", "session_name", "status", "model", "storage_path",
    "role", "workflow_id", "graph_name",
    "tool_preset_id", "tool_preset_name", "max_turns", "timeout",
    "max_iterations", "pid", "error_message", "is_deleted",
    "deleted_at", "registered_at",
}


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


def _split_fields(info: Dict[str, Any]) -> Dict[str, Any]:
    """Split a session record into column fields + extra_data JSON blob."""
    column_data: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for k, v in info.items():
        if k in _COLUMN_FIELDS:
            column_data[k] = v
        elif k not in ("id", "created_at", "updated_at", "extra_data"):
            extra[k] = v
    if extra:
        column_data["extra_data"] = json.dumps(extra, ensure_ascii=False, default=str)
    return column_data


def _merge_extra(row: Dict[str, Any]) -> Dict[str, Any]:
    """Merge extra_data JSON blob back into top-level keys."""
    result = dict(row)
    extra_raw = result.pop("extra_data", "") or ""
    if extra_raw:
        try:
            extra = json.loads(extra_raw)
            if isinstance(extra, dict):
                result.update(extra)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


# ======================================================================
#  CRUD helpers
# ======================================================================

def db_register_session(db_manager, session_id: str, info: Dict[str, Any]) -> bool:
    """Insert a new session record (UPSERT on session_id)."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        data = _split_fields(info)
        data.setdefault("session_id", session_id)
        data.setdefault("is_deleted", False)
        data.setdefault("registered_at", datetime.now(timezone.utc).isoformat())

        columns = list(data.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(columns)

        # UPSERT — update all columns on conflict
        set_clause = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in columns if c != "session_id"
        )
        query = (
            f"INSERT INTO {TABLE} ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT (session_id) DO UPDATE SET {set_clause}, "
            f"updated_at = CURRENT_TIMESTAMP "
            f"RETURNING id"
        )
        mgr.execute_insert(query, tuple(data.values()))
        logger.debug(f"Registered session in DB: {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to register session {session_id} in DB: {e}")
        return False


def db_update_session(db_manager, session_id: str, updates: Dict[str, Any]) -> bool:
    """Update specific fields of a session record."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        # Separate column updates from extra_data updates
        col_updates: Dict[str, Any] = {}
        extra_updates: Dict[str, Any] = {}
        for k, v in updates.items():
            if k in _COLUMN_FIELDS:
                col_updates[k] = v
            elif k not in ("id", "created_at", "updated_at", "extra_data"):
                extra_updates[k] = v

        if not col_updates and not extra_updates:
            return True

        set_parts = []
        values = []

        for col, val in col_updates.items():
            set_parts.append(f"{col} = %s")
            values.append(val)

        # Merge extra_data updates with existing extra_data
        if extra_updates:
            set_parts.append(
                "extra_data = CASE "
                "  WHEN extra_data IS NULL OR extra_data = '' THEN %s "
                "  ELSE (extra_data::jsonb || %s::jsonb)::text "
                "END"
            )
            extra_json = json.dumps(extra_updates, ensure_ascii=False, default=str)
            values.extend([extra_json, extra_json])

        set_parts.append("updated_at = CURRENT_TIMESTAMP")
        set_clause = ", ".join(set_parts)
        values.append(session_id)

        query = f"UPDATE {TABLE} SET {set_clause} WHERE session_id = %s"
        mgr.execute_update_delete(query, tuple(values))
        logger.debug(f"Updated session in DB: {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to update session {session_id} in DB: {e}")
        return False


def db_soft_delete_session(db_manager, session_id: str) -> bool:
    """Mark a session as soft-deleted."""
    return db_update_session(db_manager, session_id, {
        "is_deleted": True,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "status": "stopped",
    })


def db_restore_session(db_manager, session_id: str) -> bool:
    """Restore a soft-deleted session."""
    return db_update_session(db_manager, session_id, {
        "is_deleted": False,
        "deleted_at": "",
    })


def db_permanent_delete_session(db_manager, session_id: str) -> bool:
    """Permanently delete a session record."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        query = f"DELETE FROM {TABLE} WHERE session_id = %s"
        mgr.execute_update_delete(query, (session_id,))
        logger.debug(f"Permanently deleted session from DB: {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to permanently delete session {session_id}: {e}")
        return False


def db_get_session(db_manager, session_id: str) -> Optional[Dict[str, Any]]:
    """Get a single session record by session_id."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return None

    try:
        query = f"SELECT * FROM {TABLE} WHERE session_id = %s LIMIT 1"
        row = mgr.execute_query_one(query, (session_id,))
        if row:
            return _merge_extra(dict(row))
        return None
    except Exception as e:
        logger.debug(f"Failed to get session {session_id} from DB: {e}")
        return None


def db_list_all_sessions(db_manager) -> List[Dict[str, Any]]:
    """Return all session records (active + deleted)."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return []

    try:
        query = f"SELECT * FROM {TABLE} ORDER BY created_at DESC"
        rows = mgr.execute_query(query)
        return [_merge_extra(dict(r)) for r in rows] if rows else []
    except Exception as e:
        logger.error(f"Failed to list all sessions from DB: {e}")
        return []


def db_list_active_sessions(db_manager) -> List[Dict[str, Any]]:
    """Return only active (non-deleted) session records."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return []

    try:
        query = f"SELECT * FROM {TABLE} WHERE is_deleted = FALSE ORDER BY created_at DESC"
        rows = mgr.execute_query(query)
        return [_merge_extra(dict(r)) for r in rows] if rows else []
    except Exception as e:
        logger.error(f"Failed to list active sessions from DB: {e}")
        return []


def db_list_deleted_sessions(db_manager) -> List[Dict[str, Any]]:
    """Return only soft-deleted session records."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return []

    try:
        query = f"SELECT * FROM {TABLE} WHERE is_deleted = TRUE ORDER BY deleted_at DESC"
        rows = mgr.execute_query(query)
        return [_merge_extra(dict(r)) for r in rows] if rows else []
    except Exception as e:
        logger.error(f"Failed to list deleted sessions from DB: {e}")
        return []


def db_session_exists(db_manager, session_id: str) -> bool:
    """Check if a session exists in DB."""
    mgr = _get_db_manager(db_manager)
    if not _is_db_available(db_manager):
        return False

    try:
        query = f"SELECT 1 FROM {TABLE} WHERE session_id = %s LIMIT 1"
        result = mgr.execute_query_one(query, (session_id,))
        return result is not None
    except Exception:
        return False


def db_migrate_sessions_from_json(db_manager, json_data: Dict[str, Dict[str, Any]]) -> int:
    """
    Migrate session records from JSON (sessions.json format) into DB.

    Only inserts records that don't already exist in DB.
    Returns the number of records migrated.
    """
    if not _is_db_available(db_manager):
        return 0

    migrated = 0
    for session_id, record in json_data.items():
        if db_session_exists(db_manager, session_id):
            continue
        record["session_id"] = session_id
        if db_register_session(db_manager, session_id, record):
            migrated += 1

    if migrated > 0:
        logger.info(f"Migrated {migrated} session records from JSON to DB")
    return migrated
