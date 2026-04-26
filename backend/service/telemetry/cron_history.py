"""Per-job cron fire history (PR-F.4.4).

The executor's CronRunner doesn't keep a fire history out of the box —
it tracks ``last_fired_at`` / ``last_task_id`` on the CronJob itself.
This module is the Geny-side ring that captures every fire, keyed by
job name, with a small fixed-capacity deque per job.

Today the recorder is invoked from the cron run-now endpoint and the
runner's audit_callback (set up in the cron install layer). Keeping
this in-process keeps the dep surface tiny — no DB write per fire.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

_PER_JOB_CAP = 50
_buffers: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_PER_JOB_CAP))
_lock = Lock()


def record_fire(
    name: str,
    *,
    task_id: Optional[str] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
    fired_at: Optional[datetime] = None,
) -> None:
    record = {
        "fired_at": (fired_at or datetime.now(timezone.utc)).isoformat(),
        "task_id": task_id,
        "status": status,
        "error": error,
    }
    with _lock:
        _buffers[name].append(record)


def history(name: str, limit: int = 20) -> List[Dict[str, Any]]:
    with _lock:
        items = list(_buffers.get(name, []))
    if limit < len(items):
        return items[-limit:]
    return items


def clear() -> None:
    with _lock:
        _buffers.clear()


__all__ = ["record_fire", "history", "clear"]
