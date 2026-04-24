"""
Model Fallback System

Built with reference to OpenClaw's ModelFallbackRunner pattern.
Automatically switches to an alternative model when the primary model fails.

Core design:
- Try candidate models in order
- Automatically detect Rate limit / Overloaded / Timeout errors
- Remember the last successful model within the session (prefer it on next call)
- Immediately propagate AbortError (user cancellation) and similar errors

Usage:
    fallback = ModelFallbackRunner(
        preferred_model="claude-sonnet-4-20250514",
        candidates=["claude-sonnet-4-20250514", "claude-haiku-4-20250414"],
    )
    result = await fallback.run(execute_fn)
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum
from logging import getLogger
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

logger = getLogger(__name__)

T = TypeVar("T")


class FailureReason(str, Enum):
    """Classification of model failure reasons."""
    RATE_LIMITED = "rate_limited"
    OVERLOADED = "overloaded"
    TIMEOUT = "timeout"
    CONTEXT_WINDOW = "context_window"
    AUTH_ERROR = "auth_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"
    ABORT = "abort"  # User cancellation — cannot fall back


class AbortError(Exception):
    """User cancellation or unrecoverable error. Propagated immediately without fallback."""
    pass


class ModelExhaustedError(Exception):
    """Raised when all candidate models have failed."""

    def __init__(self, failures: List[Dict[str, Any]]):
        self.failures = failures
        models = [f.get("model", "?") for f in failures]
        super().__init__(f"All candidate models exhausted: {models}")


@dataclass
class FallbackAttempt:
    """Record of an individual fallback attempt."""
    model: str
    success: bool
    failure_reason: Optional[FailureReason] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class FallbackResult:
    """Result of a fallback execution."""
    result: Any = None
    model_used: str = ""
    attempts: List[FallbackAttempt] = field(default_factory=list)
    fallback_occurred: bool = False

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)


# ============================================================================
# Error Classification
# ============================================================================

# Error message patterns → FailureReason mapping
_ERROR_PATTERNS: List[tuple[str, FailureReason]] = [
    (r"rate.?limit", FailureReason.RATE_LIMITED),
    (r"429", FailureReason.RATE_LIMITED),
    (r"too many requests", FailureReason.RATE_LIMITED),
    (r"overloaded", FailureReason.OVERLOADED),
    (r"503", FailureReason.OVERLOADED),
    (r"capacity", FailureReason.OVERLOADED),
    (r"timeout", FailureReason.TIMEOUT),
    (r"timed?\s*out", FailureReason.TIMEOUT),
    (r"context.?window", FailureReason.CONTEXT_WINDOW),
    (r"too long", FailureReason.CONTEXT_WINDOW),
    (r"max.?tokens?.?exceeded", FailureReason.CONTEXT_WINDOW),
    (r"auth", FailureReason.AUTH_ERROR),
    (r"401", FailureReason.AUTH_ERROR),
    (r"403", FailureReason.AUTH_ERROR),
    (r"api.?key", FailureReason.AUTH_ERROR),
    (r"connection", FailureReason.NETWORK_ERROR),
    (r"network", FailureReason.NETWORK_ERROR),
    (r"abort", FailureReason.ABORT),
    (r"cancel", FailureReason.ABORT),
]

# Error types that can be recovered via fallback
_RECOVERABLE_FAILURES = {
    FailureReason.RATE_LIMITED,
    FailureReason.OVERLOADED,
    FailureReason.TIMEOUT,
    FailureReason.NETWORK_ERROR,
}


def classify_error(error: Exception) -> FailureReason:
    """Classify an error into a FailureReason."""
    if isinstance(error, AbortError):
        return FailureReason.ABORT
    if isinstance(error, asyncio.TimeoutError):
        return FailureReason.TIMEOUT

    error_str = str(error).lower()

    for pattern, reason in _ERROR_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return reason

    return FailureReason.UNKNOWN


def classify_error_message(error_msg: str) -> FailureReason:
    """Classify an error message string into a FailureReason."""
    error_str = error_msg.lower()
    for pattern, reason in _ERROR_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return reason
    return FailureReason.UNKNOWN


def is_recoverable(reason: FailureReason) -> bool:
    """Determine whether an error is recoverable via fallback."""
    return reason in _RECOVERABLE_FAILURES


# ============================================================================
# Model Fallback Runner
# ============================================================================

# Default candidate models (in priority order)
DEFAULT_MODEL_CANDIDATES = [
    "claude-sonnet-4-6",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
]

# Retry wait time per model (seconds)
_RETRY_DELAYS: Dict[FailureReason, float] = {
    FailureReason.RATE_LIMITED: 5.0,
    FailureReason.OVERLOADED: 3.0,
    FailureReason.TIMEOUT: 1.0,
    FailureReason.NETWORK_ERROR: 2.0,
}


class ModelFallbackRunner:
    """Model fallback runner.

    Tries candidate models sequentially when the primary model fails.

    Usage:
        runner = ModelFallbackRunner(
            preferred_model="claude-sonnet-4-20250514",
        )

        async def execute(model_name: str) -> str:
            return await some_llm_call(model=model_name)

        result = await runner.run(execute)
        print(result.model_used, result.result)
    """

    def __init__(
        self,
        preferred_model: str = "claude-sonnet-4-20250514",
        candidates: Optional[List[str]] = None,
        max_retries_per_model: int = 1,
        allowlist: Optional[List[str]] = None,
    ):
        """
        Args:
            preferred_model: Preferred model (tried first)
            candidates: List of candidate models (including preferred_model)
            max_retries_per_model: Maximum number of retries per model
            allowlist: List of allowed models (None means all candidates are allowed)
        """
        self._preferred_model = preferred_model
        self._candidates = candidates or DEFAULT_MODEL_CANDIDATES
        self._max_retries = max_retries_per_model
        self._allowlist: Optional[set[str]] = set(allowlist) if allowlist else None

        # If preferred model is not in candidates, prepend it
        if preferred_model not in self._candidates:
            self._candidates.insert(0, preferred_model)

        # Filter by allowlist
        if self._allowlist:
            self._candidates = [m for m in self._candidates if m in self._allowlist]

        # Remember the last successful model
        self._last_successful_model: Optional[str] = None

    @property
    def candidates(self) -> List[str]:
        return list(self._candidates)

    @property
    def last_successful_model(self) -> Optional[str]:
        return self._last_successful_model

    def _get_ordered_candidates(self) -> List[str]:
        """Determine the order to try: last successful model → preferred model → the rest."""
        ordered = []
        seen = set()

        # 1. Last successful model first
        if self._last_successful_model and self._last_successful_model in self._candidates:
            ordered.append(self._last_successful_model)
            seen.add(self._last_successful_model)

        # 2. Preferred model
        if self._preferred_model not in seen and self._preferred_model in self._candidates:
            ordered.append(self._preferred_model)
            seen.add(self._preferred_model)

        # 3. The rest
        for model in self._candidates:
            if model not in seen:
                ordered.append(model)
                seen.add(model)

        return ordered

    async def run(
        self,
        execute_fn: Callable[[str], Awaitable[T]],
        on_fallback: Optional[Callable[[str, str, FailureReason], Awaitable[None]]] = None,
    ) -> FallbackResult:
        """Execute with fallback logic applied.

        Args:
            execute_fn: Async function that accepts a model name and runs it
            on_fallback: Callback when fallback occurs (from_model, to_model, reason)

        Returns:
            FallbackResult (success result + attempt history)

        Raises:
            AbortError: User cancellation
            ModelExhaustedError: All candidates failed
        """
        import time

        result = FallbackResult()
        candidates = self._get_ordered_candidates()

        for idx, model in enumerate(candidates):
            for retry in range(self._max_retries + 1):
                start = time.time()
                attempt = FallbackAttempt(model=model, success=False)

                try:
                    output = await execute_fn(model)
                    elapsed = (time.time() - start) * 1000

                    attempt.success = True
                    attempt.duration_ms = elapsed
                    result.attempts.append(attempt)
                    result.result = output
                    result.model_used = model
                    result.fallback_occurred = (idx > 0 or retry > 0)

                    # Remember the successful model
                    self._last_successful_model = model

                    if result.fallback_occurred:
                        logger.info(
                            f"Fallback succeeded: model={model}, "
                            f"attempt={result.total_attempts}"
                        )

                    return result

                except AbortError:
                    # User cancellation — propagate immediately
                    raise

                except Exception as e:
                    elapsed = (time.time() - start) * 1000
                    reason = classify_error(e)

                    attempt.failure_reason = reason
                    attempt.error_message = str(e)[:200]
                    attempt.duration_ms = elapsed
                    result.attempts.append(attempt)

                    logger.warning(
                        f"Model failed: model={model}, "
                        f"reason={reason.value}, "
                        f"retry={retry}/{self._max_retries}, "
                        f"error={str(e)[:100]}"
                    )

                    # Unrecoverable error → move to next model
                    if not is_recoverable(reason):
                        break

                    # Wait before retrying
                    if retry < self._max_retries:
                        delay = _RETRY_DELAYS.get(reason, 2.0)
                        await asyncio.sleep(delay)

            # Current model failed → fall back to next model
            if idx < len(candidates) - 1:
                next_model = candidates[idx + 1]
                logger.info(f"Falling back: {model} → {next_model}")

                if on_fallback:
                    last_reason = result.attempts[-1].failure_reason or FailureReason.UNKNOWN
                    try:
                        await on_fallback(model, next_model, last_reason)
                    except Exception:
                        pass  # Ignore callback errors

        # All candidates exhausted
        failures = [
            {
                "model": a.model,
                "reason": a.failure_reason.value if a.failure_reason else "unknown",
                "error": a.error_message,
            }
            for a in result.attempts
            if not a.success
        ]
        raise ModelExhaustedError(failures)


# ============================================================================
# Utility
# ============================================================================

def create_fallback_runner(
    model: str = "claude-sonnet-4-20250514",
    candidates: Optional[List[str]] = None,
) -> ModelFallbackRunner:
    """Convenience function to create a ModelFallbackRunner."""
    return ModelFallbackRunner(
        preferred_model=model,
        candidates=candidates,
    )
