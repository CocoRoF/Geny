"""
모델 폴백 시스템

OpenClaw의 ModelFallbackRunner 패턴을 참고하여 구축.
주 모델이 실패하면 대체 모델로 자동 전환합니다.

핵심 설계:
- 모델 후보군을 순서대로 시도
- Rate limit / Overloaded / Timeout 에러 자동 감지
- 성공한 모델을 세션 내 기억 (다음 호출에서 우선 사용)
- AbortError (사용자 취소) 등은 즉시 전파

사용법:
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
    """모델 실패 원인 분류."""
    RATE_LIMITED = "rate_limited"
    OVERLOADED = "overloaded"
    TIMEOUT = "timeout"
    CONTEXT_WINDOW = "context_window"
    AUTH_ERROR = "auth_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"
    ABORT = "abort"  # 사용자 취소 — 폴백 불가


class AbortError(Exception):
    """사용자 취소 또는 복구 불가 에러. 폴백하지 않고 즉시 전파."""
    pass


class ModelExhaustedError(Exception):
    """모든 후보 모델이 실패한 경우."""

    def __init__(self, failures: List[Dict[str, Any]]):
        self.failures = failures
        models = [f.get("model", "?") for f in failures]
        super().__init__(f"All candidate models exhausted: {models}")


@dataclass
class FallbackAttempt:
    """개별 폴백 시도 기록."""
    model: str
    success: bool
    failure_reason: Optional[FailureReason] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class FallbackResult:
    """폴백 실행 결과."""
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

# 에러 메시지 패턴 → FailureReason 매핑
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

# 폴백 가능한 에러 유형
_RECOVERABLE_FAILURES = {
    FailureReason.RATE_LIMITED,
    FailureReason.OVERLOADED,
    FailureReason.TIMEOUT,
    FailureReason.NETWORK_ERROR,
}


def classify_error(error: Exception) -> FailureReason:
    """에러를 FailureReason으로 분류."""
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
    """에러 메시지 문자열을 FailureReason으로 분류."""
    error_str = error_msg.lower()
    for pattern, reason in _ERROR_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return reason
    return FailureReason.UNKNOWN


def is_recoverable(reason: FailureReason) -> bool:
    """폴백으로 복구 가능한 에러인지 판단."""
    return reason in _RECOVERABLE_FAILURES


# ============================================================================
# Model Fallback Runner
# ============================================================================

# 기본 모델 후보군 (우선순위 순)
DEFAULT_MODEL_CANDIDATES = [
    "claude-sonnet-4-20250514",
    "claude-haiku-4-20250414",
]

# 모델별 재시도 대기 시간 (초)
_RETRY_DELAYS: Dict[FailureReason, float] = {
    FailureReason.RATE_LIMITED: 5.0,
    FailureReason.OVERLOADED: 3.0,
    FailureReason.TIMEOUT: 1.0,
    FailureReason.NETWORK_ERROR: 2.0,
}


class ModelFallbackRunner:
    """모델 폴백 실행기.

    주 모델이 실패하면 후보군을 순차적으로 시도합니다.

    사용법:
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
            preferred_model: 선호 모델 (첫 번째로 시도)
            candidates: 후보 모델 목록 (preferred_model 포함)
            max_retries_per_model: 모델당 최대 재시도 횟수
            allowlist: 허용된 모델 목록 (None이면 모든 후보 허용)
        """
        self._preferred_model = preferred_model
        self._candidates = candidates or DEFAULT_MODEL_CANDIDATES
        self._max_retries = max_retries_per_model
        self._allowlist: Optional[set[str]] = set(allowlist) if allowlist else None

        # 선호 모델이 후보군에 없으면 맨 앞에 추가
        if preferred_model not in self._candidates:
            self._candidates.insert(0, preferred_model)

        # allowlist 필터링
        if self._allowlist:
            self._candidates = [m for m in self._candidates if m in self._allowlist]

        # 마지막 성공 모델 기억
        self._last_successful_model: Optional[str] = None

    @property
    def candidates(self) -> List[str]:
        return list(self._candidates)

    @property
    def last_successful_model(self) -> Optional[str]:
        return self._last_successful_model

    def _get_ordered_candidates(self) -> List[str]:
        """시도 순서 결정: 마지막 성공 모델 → 선호 모델 → 나머지."""
        ordered = []
        seen = set()

        # 1. 마지막 성공 모델 우선
        if self._last_successful_model and self._last_successful_model in self._candidates:
            ordered.append(self._last_successful_model)
            seen.add(self._last_successful_model)

        # 2. 선호 모델
        if self._preferred_model not in seen and self._preferred_model in self._candidates:
            ordered.append(self._preferred_model)
            seen.add(self._preferred_model)

        # 3. 나머지
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
        """폴백 로직을 적용하여 실행.

        Args:
            execute_fn: 모델명을 받아 실행하는 비동기 함수
            on_fallback: 폴백 발생 시 콜백 (from_model, to_model, reason)

        Returns:
            FallbackResult (성공 결과 + 시도 기록)

        Raises:
            AbortError: 사용자 취소
            ModelExhaustedError: 모든 후보 실패
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

                    # 성공한 모델 기억
                    self._last_successful_model = model

                    if result.fallback_occurred:
                        logger.info(
                            f"Fallback succeeded: model={model}, "
                            f"attempt={result.total_attempts}"
                        )

                    return result

                except AbortError:
                    # 사용자 취소 — 즉시 전파
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

                    # 복구 불가능한 에러 → 다음 모델로
                    if not is_recoverable(reason):
                        break

                    # 재시도 대기
                    if retry < self._max_retries:
                        delay = _RETRY_DELAYS.get(reason, 2.0)
                        await asyncio.sleep(delay)

            # 현재 모델 실패 → 다음 모델로 폴백
            if idx < len(candidates) - 1:
                next_model = candidates[idx + 1]
                logger.info(f"Falling back: {model} → {next_model}")

                if on_fallback:
                    last_reason = result.attempts[-1].failure_reason or FailureReason.UNKNOWN
                    try:
                        await on_fallback(model, next_model, last_reason)
                    except Exception:
                        pass  # 콜백 에러는 무시

        # 모든 후보 소진
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
    """ModelFallbackRunner 생성 편의 함수."""
    return ModelFallbackRunner(
        preferred_model=model,
        candidates=candidates,
    )
