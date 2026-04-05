"""
Inter-agent Inbox — Lightweight per-session direct message store.

Provides a simple inbox system for agents to send direct messages to
each other outside of chat rooms.  Messages are stored in JSON files
on disk, one file per target session.

Storage layout::

    backend/service/chat_conversations/
        inbox/
            {session_id}.json   — Inbox for one session (list of messages)

Public API::

    inbox = get_inbox_manager()
    msg   = inbox.deliver(target_session_id, content, sender_session_id, sender_name)
    msgs  = inbox.read(session_id, limit=20, unread_only=False)
    inbox.mark_read(session_id, message_ids)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)

# Store inbox files alongside chat_conversations
_INBOX_DIR = Path(__file__).parent.parent / "chat_conversations" / "inbox"
_DLQ_DIR = Path(__file__).parent.parent / "chat_conversations" / "inbox_dlq"


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically via temp file + rename to prevent corruption."""
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except Exception:
        # Clean up temp file on failure
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


class InboxManager:
    """Thread-safe per-session inbox for direct messages between agents."""

    def __init__(self, inbox_dir: Optional[Path] = None, dlq_dir: Optional[Path] = None) -> None:
        self._dir = inbox_dir or _INBOX_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._dlq_dir = dlq_dir or _DLQ_DIR
        self._dlq_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _inbox_path(self, session_id: str) -> Path:
        """Return the JSON file path for a session's inbox."""
        # Sanitise session_id to prevent path traversal
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self._dir / f"{safe_id}.json"

    def _load_inbox(self, session_id: str) -> List[Dict[str, Any]]:
        """Load messages for a session (returns empty list if none)."""
        path = self._inbox_path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load inbox for %s: %s", session_id, exc)
            return []

    def _save_inbox(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        """Persist messages for a session (atomic write)."""
        path = self._inbox_path(session_id)
        _atomic_write_json(path, messages)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deliver(
        self,
        target_session_id: str,
        content: str,
        sender_session_id: str = "",
        sender_name: str = "",
    ) -> Dict[str, Any]:
        """Deliver a direct message to a session's inbox.

        Returns the created message dict.
        """
        msg: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "sender_session_id": sender_session_id or None,
            "sender_name": sender_name or None,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }

        with self._lock:
            messages = self._load_inbox(target_session_id)
            messages.append(msg)
            self._save_inbox(target_session_id, messages)

        logger.info(
            "Inbox: delivered message %s → %s (from %s)",
            msg["id"], target_session_id, sender_session_id or "unknown",
        )
        return msg

    def read(
        self,
        session_id: str,
        limit: int = 20,
        unread_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Read messages from a session's inbox.

        Args:
            session_id: The session whose inbox to read.
            limit: Maximum number of messages to return (most recent first).
            unread_only: If True, return only unread messages.

        Returns:
            List of message dicts (newest last).
        """
        with self._lock:
            messages = self._load_inbox(session_id)

        if unread_only:
            messages = [m for m in messages if not m.get("read", False)]

        # Return the *last* `limit` messages (most recent)
        return messages[-limit:] if len(messages) > limit else messages

    def mark_read(self, session_id: str, message_ids: List[str]) -> int:
        """Mark specific messages as read.

        Args:
            session_id: The session whose inbox to update.
            message_ids: List of message IDs to mark as read.

        Returns:
            Number of messages actually marked.
        """
        ids_set = set(message_ids)
        marked = 0

        with self._lock:
            messages = self._load_inbox(session_id)
            for m in messages:
                if m["id"] in ids_set and not m.get("read", False):
                    m["read"] = True
                    marked += 1
            if marked:
                self._save_inbox(session_id, messages)

        return marked

    def clear(self, session_id: str) -> None:
        """Clear all messages for a session."""
        with self._lock:
            path = self._inbox_path(session_id)
            if path.exists():
                path.unlink()

    def unread_count(self, session_id: str) -> int:
        """Return the number of unread messages for a session."""
        messages = self._load_inbox(session_id)
        return sum(1 for m in messages if not m.get("read", False))

    # ------------------------------------------------------------------
    # Dead Letter Queue (DLQ)
    # ------------------------------------------------------------------

    def _dlq_path(self, session_id: str) -> Path:
        """Return the DLQ file path for a session."""
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self._dlq_dir / f"{safe_id}.json"

    def _load_dlq(self, session_id: str) -> List[Dict[str, Any]]:
        """Load DLQ messages for a session."""
        path = self._dlq_path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load DLQ for %s: %s", session_id, exc)
            return []

    def _save_dlq(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        """Persist DLQ messages (atomic write)."""
        path = self._dlq_path(session_id)
        _atomic_write_json(path, messages)

    def send_to_dlq(
        self,
        target_session_id: str,
        content: str,
        sender_session_id: str = "",
        sender_name: str = "",
        reason: str = "delivery_failed",
        original_error: str = "",
    ) -> Dict[str, Any]:
        """Store a failed message in the Dead Letter Queue for later recovery.

        Returns the created DLQ message dict.
        """
        msg: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "sender_session_id": sender_session_id or None,
            "sender_name": sender_name or None,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "original_error": original_error[:500] if original_error else "",
            "retries": 0,
        }

        with self._lock:
            dlq_messages = self._load_dlq(target_session_id)
            dlq_messages.append(msg)
            self._save_dlq(target_session_id, dlq_messages)

        logger.warning(
            "DLQ: message %s stored for %s (reason=%s)",
            msg["id"], target_session_id, reason,
        )
        return msg

    def get_dlq_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Read all DLQ messages for a session."""
        with self._lock:
            return self._load_dlq(session_id)

    def retry_dlq(self, session_id: str) -> List[Dict[str, Any]]:
        """Move all DLQ messages back to the main inbox for retry.

        Returns the list of messages moved back to the inbox.
        """
        with self._lock:
            dlq_messages = self._load_dlq(session_id)
            if not dlq_messages:
                return []

            inbox_messages = self._load_inbox(session_id)
            moved = []
            for dlq_msg in dlq_messages:
                inbox_msg = {
                    "id": str(uuid.uuid4()),
                    "sender_session_id": dlq_msg.get("sender_session_id"),
                    "sender_name": dlq_msg.get("sender_name"),
                    "content": dlq_msg["content"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "read": False,
                }
                inbox_messages.append(inbox_msg)
                moved.append(inbox_msg)

            self._save_inbox(session_id, inbox_messages)
            # Clear DLQ after successful move
            self._save_dlq(session_id, [])

        logger.info(
            "DLQ: moved %d messages back to inbox for %s",
            len(moved), session_id,
        )
        return moved

    def clear_dlq(self, session_id: str) -> None:
        """Clear all DLQ messages for a session."""
        with self._lock:
            path = self._dlq_path(session_id)
            if path.exists():
                path.unlink()


# ── Singleton ──

_inbox_instance: Optional[InboxManager] = None


def get_inbox_manager() -> InboxManager:
    """Get or create the singleton InboxManager."""
    global _inbox_instance
    if _inbox_instance is None:
        _inbox_instance = InboxManager()
    return _inbox_instance
