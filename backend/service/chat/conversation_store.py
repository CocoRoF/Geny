"""
Chat Conversation Store — Persistent chat room and message storage.

Dual storage strategy:
  - **DB primary** : PostgreSQL tables ``chat_rooms`` / ``chat_messages``
  - **JSON fallback** : Local JSON files (backward-compatible)

Storage layout (JSON fallback)::

    backend/chat_conversations/
        rooms.json            — Room registry (list of all rooms)
        {room_id}.json        — Individual room message history

Public API::

    store = ChatConversationStore()
    store.set_database(app_db)          # Enable DB backend
    room  = store.create_room(name, session_ids)
    rooms = store.list_rooms()
    room  = store.get_room(room_id)
    store.delete_room(room_id)
    store.add_message(room_id, message_dict)
    msgs  = store.get_messages(room_id)
    store.update_room_sessions(room_id, session_ids)
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)

# Storage directory — next to the backend root
_STORE_DIR = Path(__file__).parent.parent / "chat_conversations"


class ChatConversationStore:
    """Thread-safe persistent chat room and message store.

    When a database backend is connected via ``set_database()``, all
    reads go to DB first and fall back to local JSON files.  Writes go
    to **both** DB and JSON to keep them in sync.
    """

    def __init__(self, store_dir: Optional[Path] = None) -> None:
        self._dir = store_dir or _STORE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._rooms_path = self._dir / "rooms.json"
        self._lock = Lock()
        self._rooms: List[Dict[str, Any]] = []
        self._app_db = None   # set later via set_database()
        self._load_rooms()

    # ------------------------------------------------------------------
    # Database integration
    # ------------------------------------------------------------------

    def set_database(self, app_db) -> None:
        """Set the database manager for DB-backed chat storage.

        Called during application startup after DB initialization.
        Triggers migration of existing JSON data to DB.
        """
        self._app_db = app_db
        logger.info("ChatConversationStore: Database backend connected")
        self._migrate_to_db()

    @property
    def _db_available(self) -> bool:
        """Check if DB is available for chat storage."""
        if self._app_db is None:
            return False
        try:
            from service.database.chat_db_helper import _is_db_available
            return _is_db_available(self._app_db)
        except Exception:
            return False

    def _migrate_to_db(self) -> None:
        """Migrate existing JSON rooms + messages to DB (one-time, idempotent).

        Uses a marker file to prevent duplicate migrations on restart.
        """
        if not self._db_available or not self._rooms:
            return

        # Idempotency check: skip if already migrated
        migration_marker = self._dir / ".db_migrated"
        if migration_marker.exists():
            logger.debug("ChatConversationStore: Migration marker found — skipping")
            return

        try:
            from service.database.chat_db_helper import db_migrate_rooms_from_json
            store_ref = self  # capture for the loader callback

            def _messages_loader(room_id: str) -> List[Dict[str, Any]]:
                return store_ref._load_messages(room_id)

            count = db_migrate_rooms_from_json(
                self._app_db, self._rooms, _messages_loader,
            )
            if count > 0:
                logger.info(
                    f"ChatConversationStore: Migrated {count} rooms from JSON to DB"
                )

            # Write marker file to prevent re-migration on next startup
            try:
                migration_marker.write_text(
                    datetime.now(timezone.utc).isoformat(),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning(f"ChatConversationStore: Failed to write migration marker: {e}")

        except Exception as e:
            logger.warning(f"ChatConversationStore: Migration to DB failed: {e}")

    # ------------------------------------------------------------------
    # JSON persistence helpers
    # ------------------------------------------------------------------

    def _load_rooms(self) -> None:
        """Load rooms.json from disk."""
        if self._rooms_path.is_file():
            try:
                with open(self._rooms_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._rooms = data
                else:
                    logger.warning("rooms.json has invalid format — starting fresh")
                    self._rooms = []
            except Exception as e:
                logger.error(f"Failed to load rooms.json: {e}")
                self._rooms = []
        else:
            self._rooms = []

    @staticmethod
    def _atomic_write_json(path: Path, data: Any) -> None:
        """Write JSON data atomically via temp-file-then-rename."""
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=".chat_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, str(path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _save_rooms(self) -> None:
        """Write rooms to disk atomically (must hold _lock)."""
        try:
            self._atomic_write_json(self._rooms_path, self._rooms)
        except Exception as e:
            logger.error(f"Failed to save rooms.json: {e}")

    def _messages_path(self, room_id: str) -> Path:
        return self._dir / f"{room_id}.json"

    def _load_messages(self, room_id: str) -> List[Dict[str, Any]]:
        path = self._messages_path(room_id)
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
            except Exception as e:
                logger.error(f"Failed to load messages for room {room_id}: {e}")
                return []
        return []

    def _save_messages(self, room_id: str, messages: List[Dict[str, Any]]) -> None:
        try:
            self._atomic_write_json(self._messages_path(room_id), messages)
        except Exception as e:
            logger.error(f"Failed to save messages for room {room_id}: {e}")

    # ------------------------------------------------------------------
    # Public API — Rooms
    # ------------------------------------------------------------------

    def list_rooms(self) -> List[Dict[str, Any]]:
        """Return all rooms sorted by last activity (newest first).

        Reads from DB first, falls back to JSON file.
        """
        if self._db_available:
            try:
                from service.database.chat_db_helper import db_list_rooms
                result = db_list_rooms(self._app_db)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"[ChatStore] DB list_rooms failed: {e}")

        with self._lock:
            return sorted(
                self._rooms,
                key=lambda r: r.get("updated_at", r.get("created_at", "")),
                reverse=True,
            )

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Get a single room by ID.

        Reads from DB first, falls back to JSON file.
        """
        if self._db_available:
            try:
                from service.database.chat_db_helper import db_get_room
                result = db_get_room(self._app_db, room_id)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"[ChatStore] DB get_room failed: {e}")

        with self._lock:
            for r in self._rooms:
                if r["id"] == room_id:
                    return r
            return None

    def create_room(
        self,
        name: str,
        session_ids: List[str],
    ) -> Dict[str, Any]:
        """Create a new chat room with given sessions.

        Writes to DB (primary) and JSON file (backup).
        """
        now = datetime.now(timezone.utc).isoformat()
        room_id = str(uuid.uuid4())
        room = {
            "id": room_id,
            "name": name,
            "session_ids": session_ids,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }

        # DB primary
        if self._db_available:
            try:
                from service.database.chat_db_helper import db_create_room
                db_create_room(self._app_db, room_id, name, session_ids)
            except Exception as e:
                logger.warning(f"[ChatStore] DB create_room failed: {e}")

        # JSON backup
        with self._lock:
            self._rooms.append(room)
            self._save_rooms()

        # Create empty messages file
        self._save_messages(room_id, [])

        logger.info(f"Chat room created: {room_id} ({name}) with {len(session_ids)} sessions")
        return room

    def update_room_sessions(
        self, room_id: str, session_ids: List[str]
    ) -> Optional[Dict[str, Any]]:
        """Update the session list for a room.

        Writes to DB (primary) and JSON file (backup).
        """
        # DB primary
        if self._db_available:
            try:
                from service.database.chat_db_helper import db_update_room_sessions
                db_update_room_sessions(self._app_db, room_id, session_ids)
            except Exception as e:
                logger.warning(f"[ChatStore] DB update_room_sessions failed: {e}")

        # JSON backup
        with self._lock:
            for r in self._rooms:
                if r["id"] == room_id:
                    r["session_ids"] = session_ids
                    r["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._save_rooms()
                    return r
            return None

    def update_room_name(
        self, room_id: str, name: str
    ) -> Optional[Dict[str, Any]]:
        """Rename a room.

        Writes to DB (primary) and JSON file (backup).
        """
        # DB primary
        if self._db_available:
            try:
                from service.database.chat_db_helper import db_update_room_name
                db_update_room_name(self._app_db, room_id, name)
            except Exception as e:
                logger.warning(f"[ChatStore] DB update_room_name failed: {e}")

        # JSON backup
        with self._lock:
            for r in self._rooms:
                if r["id"] == room_id:
                    r["name"] = name
                    r["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._save_rooms()
                    return r
            return None

    def delete_room(self, room_id: str) -> bool:
        """Delete a room and its message history.

        Deletes from DB (primary) and JSON file (backup).
        """
        # DB primary (cascade-deletes messages)
        if self._db_available:
            try:
                from service.database.chat_db_helper import db_delete_room
                db_delete_room(self._app_db, room_id)
            except Exception as e:
                logger.warning(f"[ChatStore] DB delete_room failed: {e}")

        # JSON backup
        with self._lock:
            original_len = len(self._rooms)
            self._rooms = [r for r in self._rooms if r["id"] != room_id]
            if len(self._rooms) < original_len:
                self._save_rooms()
                msg_path = self._dir / f"{room_id}.json"
                if msg_path.is_file():
                    msg_path.unlink()
                logger.info(f"Chat room deleted: {room_id}")
                return True
            return False

    # ------------------------------------------------------------------
    # Public API — Messages
    # ------------------------------------------------------------------

    def get_messages(self, room_id: str, *, limit: int = 0, before: str = "") -> List[Dict[str, Any]]:
        """Load messages for a room.

        Reads from DB first, falls back to JSON file.

        Args:
            limit: Max messages to return. 0 = all.
            before: Cursor message ID — return only older messages.
        """
        if self._db_available:
            try:
                from service.database.chat_db_helper import db_get_messages
                result = db_get_messages(self._app_db, room_id, limit=limit, before=before)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"[ChatStore] DB get_messages failed: {e}")

        with self._lock:
            msgs = self._load_messages(room_id)
            # Apply cursor + limit for JSON fallback
            if before:
                idx = next((i for i, m in enumerate(msgs) if m.get("id") == before), None)
                if idx is not None:
                    msgs = msgs[:idx]
            if limit > 0:
                msgs = msgs[-limit:]
            return msgs

    def cleanup_old_messages(self, retention_days: int) -> int:
        """Delete messages older than ``retention_days``. Returns deleted count."""
        if retention_days <= 0:
            return 0
        if self._db_available:
            try:
                from service.database.chat_db_helper import db_delete_old_messages
                return db_delete_old_messages(self._app_db, retention_days)
            except Exception as e:
                logger.warning("[ChatStore] DB cleanup_old_messages failed: %s", e)
        return 0

    def add_message(self, room_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Append a message to a room's history and update room metadata.

        Writes to DB (primary) and JSON file (backup).
        If DB write succeeds but JSON fails, the message is still considered
        saved (DB is the source of truth). JSON inconsistency is logged
        but does not propagate as an error.
        """
        # Ensure message has an id and timestamp
        if "id" not in message:
            message["id"] = str(uuid.uuid4())
        if "timestamp" not in message:
            message["timestamp"] = datetime.now(timezone.utc).isoformat()

        db_saved = False

        # DB primary
        if self._db_available:
            try:
                from service.database.chat_db_helper import (
                    db_add_message,
                    db_update_room_metadata,
                )
                db_add_message(self._app_db, room_id, message)
                # Update room metadata in DB
                from service.database.chat_db_helper import db_get_message_count
                count = db_get_message_count(self._app_db, room_id)
                db_update_room_metadata(
                    self._app_db, room_id,
                    updated_at=message["timestamp"],
                    message_count=count,
                )
                db_saved = True
            except Exception as e:
                logger.warning(f"[ChatStore] DB add_message failed: {e}")

        # JSON backup — always attempt, log failure independently
        try:
            with self._lock:
                messages = self._load_messages(room_id)
                messages.append(message)
                self._save_messages(room_id, messages)

                for r in self._rooms:
                    if r["id"] == room_id:
                        r["updated_at"] = message["timestamp"]
                        r["message_count"] = len(messages)
                        break
                self._save_rooms()
        except Exception as e:
            if db_saved:
                logger.warning(f"[ChatStore] JSON backup failed (DB ok): {e}")
            else:
                logger.error(f"[ChatStore] Both DB and JSON write failed: {e}")
                raise  # Both failed — propagate the error

        return message

    def add_messages_batch(
        self, room_id: str, messages_to_add: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Append multiple messages at once (for broadcast results).

        Writes to DB (primary) and JSON file (backup).
        """
        now = datetime.now(timezone.utc).isoformat()
        for msg in messages_to_add:
            if "id" not in msg:
                msg["id"] = str(uuid.uuid4())
            if "timestamp" not in msg:
                msg["timestamp"] = now

        # DB primary
        if self._db_available:
            try:
                from service.database.chat_db_helper import (
                    db_add_messages_batch,
                    db_update_room_metadata,
                    db_get_message_count,
                )
                db_add_messages_batch(self._app_db, room_id, messages_to_add)
                count = db_get_message_count(self._app_db, room_id)
                db_update_room_metadata(
                    self._app_db, room_id,
                    updated_at=now,
                    message_count=count,
                )
            except Exception as e:
                logger.warning(f"[ChatStore] DB add_messages_batch failed: {e}")

        # JSON backup
        with self._lock:
            messages = self._load_messages(room_id)
            messages.extend(messages_to_add)
            self._save_messages(room_id, messages)

            for r in self._rooms:
                if r["id"] == room_id:
                    r["updated_at"] = now
                    r["message_count"] = len(messages)
                    break
            self._save_rooms()

        return messages_to_add


# ── Singleton ──

_store_instance: Optional[ChatConversationStore] = None


def get_chat_store() -> ChatConversationStore:
    """Get or create the singleton ChatConversationStore."""
    global _store_instance
    if _store_instance is None:
        _store_instance = ChatConversationStore()
    return _store_instance
