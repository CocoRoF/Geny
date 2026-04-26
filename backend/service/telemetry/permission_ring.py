"""In-process ring buffer for recent permission decisions (PR-E.4.2).

Fed from the agent_session bridge whenever a guard.check or
loop.escalate event indicates a permission decision (allow / deny /
ask). The /api/admin/recent-permissions endpoint reads the snapshot
for AdminPanel "Permission Activity".

Same shape as tool_event_ring — process-wide, deque, lock-protected.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

_CAPACITY = 200
_buffer: Deque[Dict[str, Any]] = deque(maxlen=_CAPACITY)
_lock = Lock()


def record_decision(
    *,
    decision: str,                # "allow" | "deny" | "ask" | "guard_reject"
    tool_name: Optional[str] = None,
    rule_tool: Optional[str] = None,
    rule_pattern: Optional[str] = None,
    rule_source: Optional[str] = None,
    rule_reason: Optional[str] = None,
    session_id: Optional[str] = None,
    message: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    record: Dict[str, Any] = {
        "ts": time.time(),
        "decision": decision,
        "tool_name": tool_name,
        "rule_tool": rule_tool,
        "rule_pattern": rule_pattern,
        "rule_source": rule_source,
        "rule_reason": rule_reason,
        "session_id": session_id,
        "message": message,
    }
    if extra:
        record["extra"] = dict(extra)
    with _lock:
        _buffer.append(record)


def snapshot(limit: int = 50) -> List[Dict[str, Any]]:
    with _lock:
        items = list(_buffer)
    if limit < len(items):
        return items[-limit:]
    return items


def clear() -> None:
    with _lock:
        _buffer.clear()


def capacity() -> int:
    return _CAPACITY


__all__ = ["record_decision", "snapshot", "clear", "capacity"]
