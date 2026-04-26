"""In-process ring buffer for recent tool execution events (PR-E.4.1).

The executor doesn't expose an audit ring out of the box, so the
agent_session bridge feeds this buffer with one row per tool start /
complete event. The ``/api/admin/recent-tool-events`` endpoint reads
the snapshot for the AdminPanel "Recent Activity" panel.

Design: process-wide deque with capacity 200. Cheap O(1) append, O(n)
snapshot. Thread-safe via a single lock — events are infrequent enough
that the contention is negligible compared to the actual tool call.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

_CAPACITY = 200
_buffer: Deque[Dict[str, Any]] = deque(maxlen=_CAPACITY)
_lock = Lock()


def record_event(
    *,
    kind: str,                       # "start" | "complete"
    tool_name: str,
    tool_use_id: Optional[str] = None,
    session_id: Optional[str] = None,
    is_error: Optional[bool] = None,
    duration_ms: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one tool event to the ring."""
    record = {
        "ts": time.time(),
        "kind": kind,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "session_id": session_id,
    }
    if is_error is not None:
        record["is_error"] = bool(is_error)
    if duration_ms is not None:
        record["duration_ms"] = int(duration_ms)
    if extra:
        record["extra"] = dict(extra)
    with _lock:
        _buffer.append(record)


def snapshot(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent *limit* events (newest last)."""
    with _lock:
        items = list(_buffer)
    if limit < len(items):
        return items[-limit:]
    return items


def clear() -> None:
    """For tests."""
    with _lock:
        _buffer.clear()


def capacity() -> int:
    return _CAPACITY


__all__ = ["record_event", "snapshot", "clear", "capacity"]
