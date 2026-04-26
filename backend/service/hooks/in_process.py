"""Geny in-process hook handlers (PR-B.1.3).

Three lightweight handlers wired against the executor's
``register_in_process`` API (executor 1.2.0+):

1. ``log_permission_denied`` — structured logger row on every
   PRE_TOOL_USE that the permission matrix rejected. Subprocess
   hooks would burn ~5ms/spawn for the same effect; in-process is
   sub-millisecond.
2. ``log_high_risk_tool_call`` — flags Bash/Edit/Write before
   subprocess audit hooks even spawn, so a chained allow → log →
   reject is only one subprocess fire instead of two.
3. ``observe_post_tool_use`` — records POST_TOOL_USE outcomes for
   live admin view (read by /api/admin/recent-tool-events).

All handlers fail-isolated by the executor — exceptions are logged,
fire continues. None of them BLOCK; they're observers only. Hosts
that want gate handlers (return ``HookOutcome.block(...)``) write
their own and ``register_in_process`` them.
"""

from __future__ import annotations

import collections
import logging
import time
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger(__name__)


# Ring buffer of the last N tool-use events. Sized small (256) so the
# admin viewer can render without paging but a high-traffic session
# doesn't pile up memory.
_RECENT_EVENTS: Deque[Dict[str, Any]] = collections.deque(maxlen=256)


def recent_tool_events(limit: Optional[int] = None) -> list:
    """Snapshot of the recent-events ring. Newest first."""
    rows = list(reversed(_RECENT_EVENTS))
    if limit is not None:
        rows = rows[: limit]
    return rows


# ── Handlers ─────────────────────────────────────────────────────────


HIGH_RISK_TOOLS = frozenset({"Bash", "Edit", "Write", "NotebookEdit", "MultiEdit"})


async def log_permission_denied(payload) -> None:
    """In-process handler for the permission-denied path.

    The hook runner doesn't fire a dedicated PERMISSION_DENIED event
    in 1.2.0; this handler attaches to PRE_TOOL_USE and inspects
    payload.details for the rejection marker the matrix sets.
    """
    if (payload.details or {}).get("permission_decision") != "deny":
        return None
    logger.warning(
        "permission_denied",
        extra={
            "session_id": payload.session_id,
            "denied_tool": payload.tool_name,
            "reason": (payload.details or {}).get("permission_reason"),
        },
    )
    return None


async def log_high_risk_tool_call(payload) -> None:
    """Lightweight audit row before any subprocess hooks fire."""
    if payload.tool_name not in HIGH_RISK_TOOLS:
        return None
    logger.info(
        "high_risk_tool_call",
        extra={
            "session_id": payload.session_id,
            "high_risk_tool": payload.tool_name,
        },
    )
    return None


async def observe_post_tool_use(payload) -> None:
    """Append POST_TOOL_USE outcome to the recent-events ring."""
    _RECENT_EVENTS.append({
        "ts": time.time(),
        "session_id": payload.session_id,
        "post_tool": payload.tool_name,
        "details": dict(payload.details or {}),
    })
    return None


def install_in_process_handlers(runner) -> int:
    """Register all three handlers. Returns the count installed.

    No-op + warning when ``runner`` doesn't have the executor 1.2.0
    in-process API (graceful for hosts on older versions)."""
    if runner is None or not hasattr(runner, "register_in_process"):
        logger.warning(
            "in_process_hooks_skipped reason=runner_missing_register_in_process",
        )
        return 0
    from geny_executor.hooks.events import HookEvent

    runner.register_in_process(HookEvent.PRE_TOOL_USE, log_permission_denied)
    runner.register_in_process(HookEvent.PRE_TOOL_USE, log_high_risk_tool_call)
    runner.register_in_process(HookEvent.POST_TOOL_USE, observe_post_tool_use)
    return 3


__all__ = [
    "HIGH_RISK_TOOLS",
    "install_in_process_handlers",
    "log_high_risk_tool_call",
    "log_permission_denied",
    "observe_post_tool_use",
    "recent_tool_events",
]
