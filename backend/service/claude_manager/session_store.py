"""
SessionStore — Persistent session metadata storage via sessions.json.

Provides a file-based registry of ALL sessions (active + deleted) so that
session metadata survives server restarts and soft-deleted sessions can be
restored.

Storage location: claude_control/service/claude_manager/sessions.json

Each entry stores the full CreateSessionRequest parameters plus lifecycle
metadata (created_at, deleted_at, status, last_output, etc.).

Usage:
    from service.claude_manager.session_store import get_session_store

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

# sessions.json lives next to this file
_STORE_DIR = Path(__file__).parent
_STORE_PATH = _STORE_DIR / "sessions.json"


class SessionStore:
    """Thread-safe, file-backed session metadata registry."""

    def __init__(self, path: Path = _STORE_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}  # session_id -> record
        self._load()

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

        Args:
            session_id: Unique session ID.
            info: SessionInfo-like dict (from session_info.dict()).
        """
        with self._lock:
            record = {
                **info,
                "session_id": session_id,
                "is_deleted": False,
                "deleted_at": None,
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }
            self._data[session_id] = record
            self._save()
        logger.info(f"[SessionStore] Registered session {session_id}")

    def update(self, session_id: str, updates: Dict[str, Any]):
        """Update fields of an existing record.

        Args:
            session_id: Session ID.
            updates: Dict of fields to merge.
        """
        with self._lock:
            if session_id not in self._data:
                return
            self._data[session_id].update(updates)
            self._save()

    def soft_delete(self, session_id: str):
        """Mark a session as deleted (soft-delete).

        The record is kept with is_deleted=True and deleted_at timestamp.
        """
        with self._lock:
            if session_id not in self._data:
                logger.warning(f"[SessionStore] Cannot soft-delete unknown session {session_id}")
                return
            self._data[session_id]["is_deleted"] = True
            self._data[session_id]["deleted_at"] = datetime.now(timezone.utc).isoformat()
            self._data[session_id]["status"] = "stopped"
            self._save()
        logger.info(f"[SessionStore] Soft-deleted session {session_id}")

    def restore(self, session_id: str) -> bool:
        """Un-delete a soft-deleted session (mark as active again).

        Returns True if found and restored, False otherwise.
        """
        with self._lock:
            rec = self._data.get(session_id)
            if not rec or not rec.get("is_deleted"):
                return False
            rec["is_deleted"] = False
            rec["deleted_at"] = None
            self._save()
        logger.info(f"[SessionStore] Restored session {session_id}")
        return True

    def permanent_delete(self, session_id: str) -> bool:
        """Permanently remove a session record from the store.

        Returns True if found and removed, False otherwise.
        """
        with self._lock:
            if session_id not in self._data:
                return False
            del self._data[session_id]
            self._save()
        logger.info(f"[SessionStore] Permanently deleted session {session_id}")
        return True

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session record by ID."""
        with self._lock:
            return self._data.get(session_id)

    def list_all(self) -> List[Dict[str, Any]]:
        """Return all session records (active + deleted)."""
        with self._lock:
            return list(self._data.values())

    def list_active(self) -> List[Dict[str, Any]]:
        """Return only active (non-deleted) session records."""
        with self._lock:
            return [r for r in self._data.values() if not r.get("is_deleted")]

    def list_deleted(self) -> List[Dict[str, Any]]:
        """Return only soft-deleted session records."""
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
            "timeout": rec.get("timeout", 1800),
            "max_iterations": rec.get("max_iterations", rec.get("autonomous_max_iterations", 100)),
            "role": rec.get("role", "worker"),
            "manager_id": rec.get("manager_id"),
            "graph_name": rec.get("graph_name"),
            "workflow_id": rec.get("workflow_id"),
        }

    def contains(self, session_id: str) -> bool:
        """Check if session_id exists in the store."""
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
