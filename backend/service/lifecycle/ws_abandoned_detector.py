"""Detect sessions whose WebSocket has stayed disconnected past a threshold.

Cycle 20260421_8 X2 PR-X2-6 — introduces the 7th canonical lifecycle
event (``SESSION_ABANDONED``). WS connect/disconnect itself is a
transport-level signal — one session can have multiple WS attached, and
a transient drop does not mean the user left. This detector bridges the
two by:

1. Tracking ``(session_id → active_ws_count)`` via
   :meth:`connect` / :meth:`disconnect` (ws handlers call into these).
2. Recording the epoch of the most recent transition from
   connected → fully-disconnected.
3. On each tick, emitting ``SESSION_ABANDONED`` when the gap since
   that transition exceeds ``threshold_seconds`` — *once* per
   disconnect episode.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from .bus import SessionLifecycleBus
from .events import LifecycleEvent

logger = logging.getLogger(__name__)


class WSAbandonedDetector:
    def __init__(
        self,
        bus: SessionLifecycleBus,
        *,
        threshold_seconds: float = 120.0,
    ) -> None:
        if threshold_seconds <= 0:
            raise ValueError("threshold_seconds must be > 0")
        self._bus = bus
        self._threshold = threshold_seconds
        # Per-session active WS count. A session stays "connected" while
        # this value is > 0. When it drops to 0 we record the timestamp.
        self._active_counts: Dict[str, int] = {}
        # session_id → epoch at which active count last reached 0.
        # Cleared when (a) a new WS arrives, or (b) abandoned event fires.
        self._disconnect_ts: Dict[str, float] = {}

    @property
    def threshold_seconds(self) -> float:
        return self._threshold

    def connect(self, session_id: str) -> None:
        """Record a new WS arrival for ``session_id``."""
        self._active_counts[session_id] = (
            self._active_counts.get(session_id, 0) + 1
        )
        # Any pending abandoned episode is cancelled by a reconnect.
        self._disconnect_ts.pop(session_id, None)

    def disconnect(self, session_id: str) -> None:
        """Record a WS drop for ``session_id``.

        If this was the last attached WS the session enters a pending
        abandoned state; the next :meth:`scan` past ``threshold_seconds``
        will fire ``SESSION_ABANDONED``.
        """
        count = self._active_counts.get(session_id, 0) - 1
        if count <= 0:
            # Remove from active map entirely so the detector doesn't
            # mistakenly think this session has 0 connections without
            # ever having had one.
            self._active_counts.pop(session_id, None)
            self._disconnect_ts[session_id] = time.time()
        else:
            self._active_counts[session_id] = count

    def is_connected(self, session_id: str) -> bool:
        return self._active_counts.get(session_id, 0) > 0

    def pending_count(self) -> int:
        """Number of sessions currently in a disconnected-but-not-yet-abandoned state."""
        return len(self._disconnect_ts)

    async def scan(self) -> None:
        """TickEngine handler — emit SESSION_ABANDONED for long-disconnected sessions."""
        if not self._disconnect_ts:
            return
        now = time.time()
        to_emit: list[tuple[str, float]] = []
        for sid, disconnect_ts in list(self._disconnect_ts.items()):
            gap = now - disconnect_ts
            if gap >= self._threshold:
                to_emit.append((sid, gap))

        for sid, gap in to_emit:
            # Clear *before* emit so a re-entrant handler can't double-fire.
            self._disconnect_ts.pop(sid, None)
            try:
                await self._bus.emit(
                    LifecycleEvent.SESSION_ABANDONED,
                    sid,
                    disconnect_gap_seconds=gap,
                    threshold_seconds=self._threshold,
                )
            except Exception:
                logger.exception(
                    "WSAbandonedDetector failed to emit SESSION_ABANDONED "
                    "for session_id=%s",
                    sid,
                )
