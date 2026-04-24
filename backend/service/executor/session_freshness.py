"""
Session Freshness Policy — staleness detection and auto-revival for sessions.

Tracks session age, idle time, and execution count to determine when a
session should be:
* **revived** — session was idle; reset timestamps, restart process if needed.
* **compacted** — summarise conversation history to reclaim context space.
* **reset** — terminate and recreate the session with a fresh state (hard limit).
* **warned** — emit a warning but allow continued use.

Design Philosophy:
    Sessions should NEVER die due to idle time alone.  An idle session is
    simply sleeping — when the user returns, it should wake up seamlessly.
    Only truly unrecoverable conditions (extreme age, runaway iterations)
    warrant a hard reset.

The policy is configurable via ``FreshnessConfig`` and is designed to be
called from ``AgentSession`` or ``AgentSessionManager`` at the start of
every ``invoke()`` / ``astream()`` call.

Public API
~~~~~~~~~~
* ``FreshnessConfig``  — dataclass with tunable thresholds.
* ``FreshnessStatus``  — enum of FRESH / STALE_WARN / STALE_IDLE / STALE_COMPACT / STALE_RESET.
* ``SessionFreshness`` — evaluator that computes freshness for a session.

Usage::

    from service.executor.session_freshness import SessionFreshness, FreshnessConfig

    freshness = SessionFreshness(config=FreshnessConfig())
    result = freshness.evaluate(
        created_at=session.created_at,
        last_activity=session.last_activity,
        iteration_count=session.current_iteration,
        message_count=len(state.get("messages", [])),
    )

    if result.should_revive:
        await session.revive()   # auto-revival: reset timers, restart process
    elif result.should_reset:
        await session.cleanup()
        session = await AgentSession.create(...)  # hard reset (extreme cases)
    elif result.should_compact:
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

    Design: Idle sessions are NEVER killed.  They enter STALE_IDLE which
    triggers automatic revival (timestamp reset + process restart if needed).
    Only extreme age or runaway iterations trigger a hard STALE_RESET.
    """

    # --- Age limits (hard reset) ---
    max_session_age_seconds: float = 86400.0
    """Maximum wall-clock session age (default 24 hours).  After this the
    session is considered STALE_RESET — the only hard-kill condition."""

    warn_session_age_seconds: float = 43200.0
    """Age at which a warning is emitted (default 12 hours)."""

    # --- Idle limits (auto-transition + revival, NOT reset) ---
    idle_transition_seconds: float = 600.0
    """Time since last activity before session transitions to IDLE status
    (default 10 minutes / 600 seconds).  The session is NOT destroyed —
    it simply enters a sleeping state.  On next execution request it
    auto-revives transparently."""

    warn_idle_seconds: float = 300.0
    """Idle time at which a warning is emitted (default 5 minutes)."""

    # --- Iteration / message limits ---
    max_iterations: int = 500
    """Iteration count after which STALE_RESET is recommended."""

    compact_after_messages: int = 80
    """Message count after which STALE_COMPACT is recommended."""

    warn_after_iterations: int = 200
    """Iteration count for warning."""

    # --- Revival settings ---
    max_revive_attempts: int = 3
    """Maximum consecutive revival attempts before giving up."""

    revive_cooldown_seconds: float = 10.0
    """Minimum seconds between revival attempts to avoid thrashing."""


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class FreshnessStatus(str, Enum):
    """Result of a freshness evaluation."""

    FRESH = "fresh"
    """Session is within normal operating parameters."""

    STALE_WARN = "stale_warn"
    """Approaching limits — log a warning but continue."""

    STALE_IDLE = "stale_idle"
    """Session was idle too long — auto-revival required.
    This is NOT a terminal state.  The session should be revived
    (timestamps reset, process restarted if dead) and then continue."""

    STALE_COMPACT = "stale_compact"
    """Message history is large — context compaction recommended."""

    STALE_RESET = "stale_reset"
    """Session has hit a hard limit (extreme age or runaway iterations)
    and should be terminated and recreated."""

    @property
    def should_revive(self) -> bool:
        """True when auto-revival should be attempted (idle sessions)."""
        return self == FreshnessStatus.STALE_IDLE

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
    def should_revive(self) -> bool:
        """True when auto-revival should be attempted."""
        return self.status.should_revive

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
        self._revive_count: int = 0
        self._last_revive_time: Optional[datetime] = None

    @property
    def config(self) -> FreshnessConfig:
        return self._config

    def record_revival(self, now: Optional[datetime] = None) -> None:
        """Record that a revival was performed.

        Called by AgentSession after successfully reviving.
        """
        self._revive_count += 1
        self._last_revive_time = now or datetime.now()
        logger.info(
            "[freshness] Revival recorded (count=%d)",
            self._revive_count,
        )

    def reset_revive_counter(self) -> None:
        """Reset revival counter after a successful execution.

        Called when the session completes an execution successfully,
        proving it is healthy.
        """
        if self._revive_count > 0:
            logger.info(
                "[freshness] Revive counter reset (was %d)",
                self._revive_count,
            )
        self._revive_count = 0

    @property
    def revive_count(self) -> int:
        return self._revive_count

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

        # --- Check HARD RESET conditions (most severe first) ---
        # These are truly unrecoverable — session must be recreated.

        if age >= cfg.max_session_age_seconds:
            base.status = FreshnessStatus.STALE_RESET
            base.reason = (
                f"Session age {age:.0f}s exceeds hard max "
                f"{cfg.max_session_age_seconds:.0f}s"
            )
            logger.warning("[freshness] %s", base.reason)
            return base

        if iteration_count >= cfg.max_iterations:
            base.status = FreshnessStatus.STALE_RESET
            base.reason = (
                f"Iterations {iteration_count} exceeds hard max "
                f"{cfg.max_iterations}"
            )
            logger.warning("[freshness] %s", base.reason)
            return base

        # --- Check IDLE condition (revivable, NOT fatal) ---
        # Idle sessions are sleeping, not dead.  They get auto-revived.
        # However, if we've already tried reviving too many times in
        # sequence without a successful execution, escalate to RESET.

        if idle >= cfg.idle_transition_seconds:
            if self._revive_count >= cfg.max_revive_attempts:
                base.status = FreshnessStatus.STALE_RESET
                base.reason = (
                    f"Idle time {idle:.0f}s with {self._revive_count} "
                    f"failed revival attempts \u2014 hard reset required"
                )
                logger.warning("[freshness] %s", base.reason)
                return base

            base.status = FreshnessStatus.STALE_IDLE
            base.reason = (
                f"Idle time {idle:.0f}s exceeds idle threshold "
                f"{cfg.idle_transition_seconds:.0f}s \u2014 session is idle, "
                f"auto-revival will be attempted on next activity"
            )
            logger.info("[freshness] %s", base.reason)
            return base

        # --- Check COMPACT conditions ---

        if message_count >= cfg.compact_after_messages:
            base.status = FreshnessStatus.STALE_COMPACT
            base.reason = (
                f"Message count {message_count} exceeds compact threshold "
                f"{cfg.compact_after_messages}"
            )
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
