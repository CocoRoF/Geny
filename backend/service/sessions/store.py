"""
SessionStore — Persistent session metadata storage.

Primary storage: PostgreSQL database ('sessions' table)
Fallback storage: sessions.json file

Provides a registry of ALL sessions (active + deleted) so that
session metadata survives server restarts and soft-deleted sessions can be
restored.

Each entry stores the full CreateSessionRequest parameters plus lifecycle
metadata (created_at, deleted_at, status, last_output, etc.).

Usage:
    from service.sessions.store import get_session_store

    store = get_session_store()

    # Register a new session
    store.register(session_id, session_info_dict)

    # Mark as deleted (soft-delete)
    store.soft_delete(session_id)

    # Permanently remove
    store.permanent_delete(session_id)

    # List deleted sessions
    deleted = store.list_deleted()

    # Restore a soft-deleted session (returns its creation params)
    params = store.get_creation_params(session_id)
"""

import json
import os
import threading
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)

# sessions.json — use session_data/ subdirectory (Docker bind-mount friendly).
# Falls back to same directory as this file if session_data/ doesn't exist.
_STORE_DIR = Path(__file__).parent
_SESSION_DATA_DIR = _STORE_DIR / "session_data"
if _SESSION_DATA_DIR.is_dir():
    _STORE_PATH = _SESSION_DATA_DIR / "sessions.json"
else:
    _STORE_PATH = _STORE_DIR / "sessions.json"


class SessionStore:
    """Thread-safe session metadata registry.

    Primary storage: PostgreSQL (via session_db_helper).
    Fallback: sessions.json file when DB is not available.
    All writes go to both DB and file for resilience.
    """

    def __init__(self, path: Path = _STORE_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}  # session_id -> record
        self._app_db = None  # Set via set_database()
        self._load()

    # ------------------------------------------------------------------
    # Database integration
    # ------------------------------------------------------------------

    def set_database(self, app_db) -> None:
        """Set the database manager for DB-backed session storage.

        Called during application startup after DB initialization.
        Triggers migration of existing JSON data to DB.
        """
        self._app_db = app_db
        logger.info("SessionStore: Database backend connected")
        # Migrate existing JSON records to DB
        self._migrate_to_db()

    @property
    def _db_available(self) -> bool:
        """Check if DB is available for session storage."""
        if self._app_db is None:
            return False
        try:
            from service.database.session_db_helper import _is_db_available
            return _is_db_available(self._app_db)
        except Exception:
            return False

    def _migrate_to_db(self) -> None:
        """Migrate existing JSON session records to DB (one-time)."""
        if not self._db_available or not self._data:
            return
        try:
            from service.database.session_db_helper import db_migrate_sessions_from_json
            count = db_migrate_sessions_from_json(self._app_db, self._data)
            if count > 0:
                logger.info(f"SessionStore: Migrated {count} sessions from JSON to DB")
        except Exception as e:
            logger.warning(f"SessionStore: Migration to DB failed: {e}")

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self):
        """Load sessions.json from disk (or start empty)."""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self._data = raw
                    logger.info(f"SessionStore loaded {len(self._data)} records from {self._path}")
                else:
                    logger.warning("sessions.json has invalid format — starting fresh")
                    self._data = {}
            except Exception as e:
                logger.error(f"Failed to load sessions.json: {e}")
                self._data = {}
        else:
            self._data = {}
            logger.info("SessionStore: no sessions.json found — starting fresh")

    def _save(self):
        """Write current data to sessions.json (must hold _lock)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, default=str)
            tmp.replace(self._path)
        except Exception as e:
            logger.error(f"Failed to save sessions.json: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, session_id: str, info: Dict[str, Any]):
        """Register a newly created session.

        Writes to DB (primary) and JSON file (backup).
        """
        record = {
            **info,
            "session_id": session_id,
            "is_deleted": False,
            "deleted_at": None,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

        # DB primary
        if self._db_available:
            try:
                from service.database.session_db_helper import db_register_session
                db_register_session(self._app_db, session_id, record)
            except Exception as e:
                logger.warning(f"[SessionStore] DB register failed for {session_id}: {e}")

        # JSON backup
        with self._lock:
            self._data[session_id] = record
            self._save()

        logger.info(f"[SessionStore] Registered session {session_id}")

    def update(self, session_id: str, updates: Dict[str, Any]):
        """Update fields of an existing record.

        Writes to DB (primary) and JSON file (backup).
        """
        # DB primary
        if self._db_available:
            try:
                from service.database.session_db_helper import db_update_session
                db_update_session(self._app_db, session_id, updates)
            except Exception as e:
                logger.warning(f"[SessionStore] DB update failed for {session_id}: {e}")

        # JSON backup
        with self._lock:
            if session_id not in self._data:
                return
            self._data[session_id].update(updates)
            self._save()

    def increment_cost(self, session_id: str, cost_usd: float):
        """Atomically add execution cost to a session's total_cost."""
        if not cost_usd or cost_usd <= 0:
            return
        # DB primary (atomic increment)
        if self._db_available:
            try:
                from service.database.session_db_helper import db_increment_session_cost
                db_increment_session_cost(self._app_db, session_id, cost_usd)
            except Exception as e:
                logger.warning(f"[SessionStore] DB cost increment failed for {session_id}: {e}")
        # JSON backup
        with self._lock:
            if session_id in self._data:
                prev = self._data[session_id].get("total_cost", 0.0) or 0.0
                self._data[session_id]["total_cost"] = prev + cost_usd
                self._save()

    def soft_delete(self, session_id: str):
        """Mark a session as deleted (soft-delete).

        The record is kept with is_deleted=True and deleted_at timestamp.
        Also cascades to linked sessions (VTuber ↔ CLI pairs).
        """
        # Cascade: if this session has a linked partner, soft-delete it too
        rec = self.get(session_id)
        linked_id = rec.get("linked_session_id") if rec else None

        # DB primary
        if self._db_available:
            try:
                from service.database.session_db_helper import db_soft_delete_session
                db_soft_delete_session(self._app_db, session_id)
            except Exception as e:
                logger.warning(f"[SessionStore] DB soft-delete failed for {session_id}: {e}")

        # JSON backup
        with self._lock:
            if session_id not in self._data:
                logger.warning(f"[SessionStore] Cannot soft-delete unknown session {session_id}")
                return
            self._data[session_id]["is_deleted"] = True
            self._data[session_id]["deleted_at"] = datetime.now(timezone.utc).isoformat()
            self._data[session_id]["status"] = "stopped"
            self._save()
        logger.info(f"[SessionStore] Soft-deleted session {session_id}")

        # Cascade to linked session (avoid infinite recursion via is_deleted check)
        if linked_id:
            linked_rec = self.get(linked_id)
            if linked_rec and not linked_rec.get("is_deleted"):
                logger.info(f"[SessionStore] Cascading soft-delete to linked session {linked_id}")
                self.soft_delete(linked_id)

    def restore(self, session_id: str) -> bool:
        """Un-delete a soft-deleted session (mark as active again).

        Returns True if found and restored, False otherwise.
        """
        restored = False

        # DB primary
        if self._db_available:
            try:
                from service.database.session_db_helper import db_restore_session
                restored = db_restore_session(self._app_db, session_id)
            except Exception as e:
                logger.warning(f"[SessionStore] DB restore failed for {session_id}: {e}")

        # JSON backup
        with self._lock:
            rec = self._data.get(session_id)
            if rec and rec.get("is_deleted"):
                rec["is_deleted"] = False
                rec["deleted_at"] = None
                self._save()
                restored = True

        if restored:
            logger.info(f"[SessionStore] Restored session {session_id}")
        return restored

    def permanent_delete(self, session_id: str) -> bool:
        """Permanently remove a session record from the store.

        Returns True if found and removed, False otherwise.
        """
        deleted = False

        # DB primary
        if self._db_available:
            try:
                from service.database.session_db_helper import db_permanent_delete_session
                deleted = db_permanent_delete_session(self._app_db, session_id)
            except Exception as e:
                logger.warning(f"[SessionStore] DB permanent-delete failed for {session_id}: {e}")

            # Also delete associated memory entries (prevent orphaned data)
            try:
                from service.database.memory_db_helper import db_delete_session_memory
                db_delete_session_memory(self._app_db, session_id)
                logger.debug(f"[SessionStore] Memory entries cleaned for {session_id}")
            except Exception as e:
                logger.debug(f"[SessionStore] Memory cleanup failed for {session_id}: {e}")

            # Session logs (this table is by far the largest per-session store —
            # hundreds of rows each. The helper existed but was never wired into
            # delete, so a purged session left its whole log tail orphaned.)
            try:
                from service.database.session_log_db_helper import db_delete_session_logs
                db_delete_session_logs(self._app_db, session_id)
                logger.debug(f"[SessionStore] Session logs cleaned for {session_id}")
            except Exception as e:
                logger.debug(f"[SessionStore] Session-log cleanup failed for {session_id}: {e}")

            # Chat rooms + their messages. A room lists its sessions in a JSON
            # ``session_ids`` array (usually one). On permanent delete: drop this
            # session from every room it's in; when that empties the room, delete
            # the room and its messages. Rooms shared with a surviving session
            # keep their history. (Previously nothing cleaned these — 78% of
            # prod rooms/messages were orphaned tails of deleted sessions.)
            try:
                from service.database.chat_db_helper import (
                    db_list_rooms, db_delete_room, db_update_room_sessions,
                )
                for room in (db_list_rooms(self._app_db) or []):
                    sids = room.get("session_ids") or []
                    if session_id not in sids:
                        continue
                    remaining = [s for s in sids if s != session_id]
                    rid = room.get("room_id")
                    if not rid:
                        continue
                    if remaining:
                        db_update_room_sessions(self._app_db, rid, remaining)
                    else:
                        db_delete_room(self._app_db, rid)  # cascades to messages
                logger.debug(f"[SessionStore] Chat rooms cleaned for {session_id}")
            except Exception as e:
                logger.debug(f"[SessionStore] Chat-room cleanup failed for {session_id}: {e}")

            # The agent's own runtime side-effects, deleted WITH the agent:
            #   • work queue — its background tasks (+ outputs)
            #   • the crons it self-scheduled (a runaway 1-min cron once spun
            #     29k failed tasks precisely because delete never removed it)
            try:
                from service.database.session_db_helper import (
                    db_delete_tasks_by_session, db_delete_crons_by_session,
                )
                nt = db_delete_tasks_by_session(self._app_db, session_id)
                nc = db_delete_crons_by_session(self._app_db, session_id)
                if nt or nc:
                    logger.info(f"[SessionStore] Cleaned {nt} task(s), {nc} cron(s) for {session_id}")
            except Exception as e:
                logger.debug(f"[SessionStore] Task/cron cleanup failed for {session_id}: {e}")

        # JSON backup
        with self._lock:
            if session_id in self._data:
                del self._data[session_id]
                self._save()
                deleted = True

        if deleted:
            logger.info(f"[SessionStore] Permanently deleted session {session_id}")
        return deleted

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session record by ID.

        Reads from DB first, falls back to JSON file.
        """
        # DB primary
        if self._db_available:
            try:
                from service.database.session_db_helper import db_get_session
                result = db_get_session(self._app_db, session_id)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"[SessionStore] DB get failed for {session_id}: {e}")

        # JSON fallback
        with self._lock:
            return self._data.get(session_id)

    def list_all(self) -> List[Dict[str, Any]]:
        """Return all session records (active + deleted).

        Reads from DB first, falls back to JSON file.
        """
        if self._db_available:
            try:
                from service.database.session_db_helper import db_list_all_sessions
                result = db_list_all_sessions(self._app_db)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"[SessionStore] DB list_all failed: {e}")

        with self._lock:
            return list(self._data.values())

    def list_active(self) -> List[Dict[str, Any]]:
        """Return only active (non-deleted) session records.

        Reads from DB first, falls back to JSON file.
        """
        if self._db_available:
            try:
                from service.database.session_db_helper import db_list_active_sessions
                result = db_list_active_sessions(self._app_db)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"[SessionStore] DB list_active failed: {e}")

        with self._lock:
            return [r for r in self._data.values() if not r.get("is_deleted")]

    def list_deleted(self) -> List[Dict[str, Any]]:
        """Return only soft-deleted session records.

        Reads from DB first, falls back to JSON file.
        """
        if self._db_available:
            try:
                from service.database.session_db_helper import db_list_deleted_sessions
                result = db_list_deleted_sessions(self._app_db)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"[SessionStore] DB list_deleted failed: {e}")

        with self._lock:
            return [r for r in self._data.values() if r.get("is_deleted")]

    def get_creation_params(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Extract the creation parameters needed to re-create a session.

        Returns a dict suitable for CreateSessionRequest, or None.
        """
        rec = self.get(session_id)
        if not rec:
            return None
        # Map stored fields back to CreateSessionRequest fields
        return {
            "session_name": rec.get("session_name"),
            "working_dir": rec.get("storage_path"),
            "model": rec.get("model"),
            "max_turns": rec.get("max_turns", 100),
            "timeout": rec.get("timeout", 21600),
            "max_iterations": rec.get("max_iterations", rec.get("autonomous_max_iterations", 100)),
            "role": rec.get("role", "worker"),
            # The environment the session is bound to. ``_rehydrate`` passes
            # this straight to ``create_agent_session(env_id=...)``; omitting
            # it (the historical bug) made every reload / restart fall back to
            # ``resolve_env_id(role, None)`` — the role's DEFAULT env — so a
            # session bound to a custom env silently lost its binding on the
            # next wake. Restoring it here also lets the change-env feature
            # (PUT /api/agents/{id}/env) survive the manifest reload.
            "env_id": rec.get("env_id"),
            # The accounts this session talks to. Same class of bug as env_id
            # below if omitted: a restart would silently move the session back
            # to the default route, which for a user who deliberately pinned a
            # cheap model is a bill, not a preference.
            "route": rec.get("route"),
            # Same shape of bug as env_id above: the owner was registered but
            # never handed back, so every restart re-created the session with
            # no owner — losing its cloud identity (no adoption, a sandbox
            # bound outside the shared tree, quota on the wrong journal).
            "owner_username": rec.get("owner_username"),
            "graph_name": rec.get("graph_name"),
            "workflow_id": rec.get("workflow_id"),
            "tool_preset_id": rec.get("tool_preset_id"),
            "linked_session_id": rec.get("linked_session_id"),
            "session_type": rec.get("session_type"),
            "chat_room_id": rec.get("chat_room_id"),
            "trigger_preset_id": rec.get("trigger_preset_id"),
            # The session's OWN persona, when it has one. Same class of bug
            # as env_id above if omitted: the override would be dropped on
            # every reload and the session would quietly revert to its
            # environment's persona — the thing the override exists to
            # escape.
            "persona_preset_id": rec.get("persona_preset_id"),
        }

    def contains(self, session_id: str) -> bool:
        """Check if session_id exists in the store."""
        # DB primary
        if self._db_available:
            try:
                from service.database.session_db_helper import db_session_exists
                return db_session_exists(self._app_db, session_id)
            except Exception:
                pass

        with self._lock:
            return session_id in self._data


# =====================================================================
# Singleton
# =====================================================================

_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Get the singleton SessionStore instance."""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store
