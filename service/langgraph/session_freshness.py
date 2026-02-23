"""
Session Freshness Policy — staleness detection and auto-reset for sessions.

Tracks session age, idle time, and execution count to determine when a
session should be:
* **compacted** — summarise conversation history to reclaim context space.
* **reset** — terminate and recreate the session with a fresh state.
* **warned** — emit a warning but allow continued use.

The policy is configurable via ``FreshnessConfig`` and is designed to be
called from ``AgentSession`` or ``AgentSessionManager`` at the start of
every ``invoke()`` / ``astream()`` call.

Public API
~~~~~~~~~~
* ``FreshnessConfig``  — dataclass with tunable thresholds.
* ``FreshnessStatus``  — enum of FRESH / STALE_WARN / STALE_COMPACT / STALE_RESET.
* ``SessionFreshness`` — evaluator that computes freshness for a session.

Usage::

    from service.langgraph.session_freshness import SessionFreshness, FreshnessConfig

    freshness = SessionFreshness(config=FreshnessConfig())
    status = freshness.evaluate(
        created_at=session.created_at,
        last_activity=session.last_activity,
        iteration_count=session.current_iteration,
        message_count=len(state.get("messages", [])),
    )

    if status.should_reset:
        await session.cleanup()
        session = await AgentSession.create(...)  # recreate
    elif status.should_compact:
        # trigger context compaction
        ...
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from logging import getLogger
from typing import Optional

logger = getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FreshnessConfig:
    """Tunable thresholds for session freshness evaluation.

    All durations are in seconds unless noted.
    """

    # --- Age limits ---
    max_session_age_seconds: float = 14400.0
    """Maximum wall-clock session age (default 4 hours).  After this the
    session is considered STALE_RESET."""

    warn_session_age_seconds: float = 7200.0
    """Age at which a warning is emitted (default 2 hours)."""

    # --- Idle limits ---
    max_idle_seconds: float = 3600.0
    """Maximum time since last activity before STALE_RESET (default 1 hour)."""

    warn_idle_seconds: float = 1800.0
    """Idle time at which a warning is emitted (default 30 minutes)."""

    # --- Iteration / message limits ---
    max_iterations: int = 200
    """Iteration count after which STALE_RESET is recommended."""

    compact_after_messages: int = 80
    """Message count after which STALE_COMPACT is recommended."""

    warn_after_iterations: int = 100
    """Iteration count for warning."""


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class FreshnessStatus(str, Enum):
    """Result of a freshness evaluation."""

    FRESH = "fresh"
    """Session is within normal operating parameters."""

    STALE_WARN = "stale_warn"
    """Approaching limits — log a warning but continue."""

    STALE_COMPACT = "stale_compact"
    """Message history is large — context compaction recommended."""

    STALE_RESET = "stale_reset"
    """Session should be terminated and recreated."""

    @property
    def should_compact(self) -> bool:
        return self in (FreshnessStatus.STALE_COMPACT,)

    @property
    def should_reset(self) -> bool:
        return self == FreshnessStatus.STALE_RESET

    @property
    def is_fresh(self) -> bool:
        return self == FreshnessStatus.FRESH


# ---------------------------------------------------------------------------
# Evaluation result
# ---------------------------------------------------------------------------

@dataclass
class FreshnessResult:
    """Detailed result from freshness evaluation."""

    status: FreshnessStatus
    reason: str = ""
    session_age_seconds: float = 0.0
    idle_seconds: float = 0.0
    iteration_count: int = 0
    message_count: int = 0

    @property
    def should_compact(self) -> bool:
        return self.status.should_compact

    @property
    def should_reset(self) -> bool:
        return self.status.should_reset

    @property
    def is_fresh(self) -> bool:
        return self.status.is_fresh


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class SessionFreshness:
    """Evaluates whether a session is still within acceptable freshness.

    Instantiate once (e.g. at session creation) and call ``evaluate()``
    before every execution.
    """

    def __init__(self, config: Optional[FreshnessConfig] = None) -> None:
        self._config = config or FreshnessConfig()

    @property
    def config(self) -> FreshnessConfig:
        return self._config

    def evaluate(
        self,
        created_at: datetime,
        last_activity: Optional[datetime] = None,
        iteration_count: int = 0,
        message_count: int = 0,
        now: Optional[datetime] = None,
    ) -> FreshnessResult:
        """Evaluate session freshness.

        Args:
            created_at: When the session was created.
            last_activity: Timestamp of last user/agent activity.
            iteration_count: Number of graph iterations completed.
            message_count: Number of messages in state.
            now: Current time override (for testing).

        Returns:
            A :class:`FreshnessResult` with the computed status.
        """
        now = now or datetime.now()
        cfg = self._config

        age = (now - created_at).total_seconds()
        idle = (
            (now - last_activity).total_seconds()
            if last_activity else age
        )

        base = FreshnessResult(
            status=FreshnessStatus.FRESH,
            session_age_seconds=age,
            idle_seconds=idle,
            iteration_count=iteration_count,
            message_count=message_count,
        )

        # --- Check RESET conditions (most severe first) ---

        if age >= cfg.max_session_age_seconds:
            base.status = FreshnessStatus.STALE_RESET
            base.reason = f"Session age {age:.0f}s exceeds max {cfg.max_session_age_seconds:.0f}s"
            logger.warning("[freshness] %s", base.reason)
            return base

        if idle >= cfg.max_idle_seconds:
            base.status = FreshnessStatus.STALE_RESET
            base.reason = f"Idle time {idle:.0f}s exceeds max {cfg.max_idle_seconds:.0f}s"
            logger.warning("[freshness] %s", base.reason)
            return base

        if iteration_count >= cfg.max_iterations:
            base.status = FreshnessStatus.STALE_RESET
            base.reason = f"Iterations {iteration_count} exceeds max {cfg.max_iterations}"
            logger.warning("[freshness] %s", base.reason)
            return base

        # --- Check COMPACT conditions ---

        if message_count >= cfg.compact_after_messages:
            base.status = FreshnessStatus.STALE_COMPACT
            base.reason = f"Message count {message_count} exceeds compact threshold {cfg.compact_after_messages}"
            logger.info("[freshness] %s", base.reason)
            return base

        # --- Check WARN conditions ---

        if age >= cfg.warn_session_age_seconds:
            base.status = FreshnessStatus.STALE_WARN
            base.reason = f"Session age {age:.0f}s approaching limit"
            logger.info("[freshness] %s", base.reason)
            return base

        if idle >= cfg.warn_idle_seconds:
            base.status = FreshnessStatus.STALE_WARN
            base.reason = f"Idle time {idle:.0f}s approaching limit"
            logger.info("[freshness] %s", base.reason)
            return base

        if iteration_count >= cfg.warn_after_iterations:
            base.status = FreshnessStatus.STALE_WARN
            base.reason = f"Iterations {iteration_count} approaching limit"
            logger.info("[freshness] %s", base.reason)
            return base

        # --- All clear ---
        return base
