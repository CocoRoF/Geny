"""
Context Window Guard System

Built with reference to OpenClaw's context management pattern.
Prevents context window overflow as conversations grow longer.

Core design:
- Token count estimation (character/word-based heuristic without exact tokenization)
- Two-level warning based on Warn / Block thresholds
- Suggests or automatically applies compaction strategy when threshold is reached
- Integrable with LangGraph state

Usage:
    guard = ContextWindowGuard(
        model="claude-sonnet-4-20250514",
        warn_ratio=0.75,
        block_ratio=0.90,
    )

    # Check on every message addition
    status = guard.check(messages)
    if status.should_block:
        # Stop execution or compact
        messages = guard.compact(messages)
    elif status.should_warn:
        # Warning log
        logger.warning(status.message)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from logging import getLogger
from typing import Any, Dict, List, Optional, Tuple

logger = getLogger(__name__)


# ============================================================================
# Model Context Limits
# ============================================================================

# Context window size (tokens) per Claude model
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    # Claude 4.6
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    # Claude 4.5
    "claude-opus-4-5-20251101": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    # Claude 4
    "claude-opus-4-20250514": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-sonnet-4-20250715": 200_000,
    "claude-haiku-4-20250414": 200_000,
    # Legacy
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
}

# Default value when model name cannot be recognized
DEFAULT_CONTEXT_LIMIT = 200_000

# Token estimation constants
# English: ~4 chars/token, Korean: ~2-3 chars/token
# Conservatively using 3 chars/token
CHARS_PER_TOKEN_ESTIMATE = 3.0


def get_context_limit(model: Optional[str]) -> int:
    """Return the context window size for a model."""
    if not model:
        return DEFAULT_CONTEXT_LIMIT

    # Exact name match
    if model in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[model]

    # Partial match (when the model name contains a keyword)
    model_lower = model.lower()
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if key in model_lower or model_lower in key:
            return limit

    return DEFAULT_CONTEXT_LIMIT


def estimate_tokens(text: str) -> int:
    """Estimate the token count of text.

    Estimates based on character count heuristic without exact tokenization.
    Estimates conservatively to prevent overflow.
    """
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN_ESTIMATE))


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimate the total token count of a message list.

    Sums role, content, tool_calls, etc. for each message.
    Also includes message overhead (role tags, etc.).
    """
    total = 0
    for msg in messages:
        # Message overhead (~4 tokens for role tag)
        total += 4

        # content
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            # Multimodal content (text blocks)
            for block in content:
                if isinstance(block, dict):
                    total += estimate_tokens(block.get("text", ""))
                elif isinstance(block, str):
                    total += estimate_tokens(block)

        # tool_calls / tool_use
        tool_calls = msg.get("tool_calls") or msg.get("additional_kwargs", {}).get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                total += estimate_tokens(str(tc))

    return total


# ============================================================================
# Guard Status
# ============================================================================

class ContextStatus(str, Enum):
    """Context status."""
    OK = "ok"           # Normal
    WARN = "warn"       # Warning threshold reached
    BLOCK = "block"     # Block threshold reached
    OVERFLOW = "overflow"  # Already exceeded


@dataclass
class ContextCheckResult:
    """Context check result."""
    status: ContextStatus
    estimated_tokens: int
    context_limit: int
    usage_ratio: float
    message: str = ""

    @property
    def should_warn(self) -> bool:
        return self.status in (ContextStatus.WARN, ContextStatus.BLOCK, ContextStatus.OVERFLOW)

    @property
    def should_block(self) -> bool:
        return self.status in (ContextStatus.BLOCK, ContextStatus.OVERFLOW)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.context_limit - self.estimated_tokens)


# ============================================================================
# Compaction Strategies
# ============================================================================

class CompactionStrategy(str, Enum):
    """Context compaction strategy."""
    TRUNCATE_EARLY = "truncate_early"       # Remove early messages
    SUMMARIZE_PREFIX = "summarize_prefix"    # Summarize the early portion
    KEEP_RECENT = "keep_recent"             # Keep only the most recent N messages
    REMOVE_TOOL_DETAILS = "remove_tool_details"  # Remove tool call details


def compact_messages(
    messages: List[Dict[str, Any]],
    strategy: CompactionStrategy = CompactionStrategy.KEEP_RECENT,
    keep_count: int = 10,
    keep_system: bool = True,
) -> List[Dict[str, Any]]:
    """Compact messages to reduce context.

    Args:
        messages: Original message list
        strategy: Compaction strategy
        keep_count: Number of recent messages to keep
        keep_system: Whether to always retain system messages

    Returns:
        Compacted message list
    """
    if not messages:
        return messages

    if strategy == CompactionStrategy.KEEP_RECENT:
        return _compact_keep_recent(messages, keep_count, keep_system)
    elif strategy == CompactionStrategy.TRUNCATE_EARLY:
        return _compact_truncate_early(messages, keep_count, keep_system)
    elif strategy == CompactionStrategy.REMOVE_TOOL_DETAILS:
        return _compact_remove_tool_details(messages)
    else:
        # Default: KEEP_RECENT
        return _compact_keep_recent(messages, keep_count, keep_system)


def _compact_keep_recent(
    messages: List[Dict[str, Any]],
    keep_count: int,
    keep_system: bool,
) -> List[Dict[str, Any]]:
    """Keep only the most recent N messages."""
    result = []

    # Extract system messages
    if keep_system:
        for msg in messages:
            if msg.get("role") == "system":
                result.append(msg)

    # Add recent messages
    non_system = [m for m in messages if m.get("role") != "system"]
    recent = non_system[-keep_count:] if len(non_system) > keep_count else non_system

    # Insert summary marker
    if len(non_system) > keep_count:
        removed_count = len(non_system) - keep_count
        result.append({
            "role": "system",
            "content": (
                f"[Context compacted: {removed_count} earlier messages removed. "
                f"Showing most recent {keep_count} messages.]"
            )
        })

    result.extend(recent)
    return result


def _compact_truncate_early(
    messages: List[Dict[str, Any]],
    keep_count: int,
    keep_system: bool,
) -> List[Dict[str, Any]]:
    """Truncate early messages (keep system messages + most recent N)."""
    # Same as KEEP_RECENT but with a different summary marker
    result = []

    if keep_system:
        for msg in messages:
            if msg.get("role") == "system":
                result.append(msg)

    non_system = [m for m in messages if m.get("role") != "system"]
    recent = non_system[-keep_count:] if len(non_system) > keep_count else non_system

    if len(non_system) > keep_count:
        result.append({
            "role": "system",
            "content": "[Earlier conversation context truncated to fit context window.]"
        })

    result.extend(recent)
    return result


def _compact_remove_tool_details(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Condense the detailed content of tool call results."""
    result = []
    for msg in messages:
        msg_copy = dict(msg)

        # Condense the content of tool result messages
        if msg_copy.get("role") == "tool":
            content = msg_copy.get("content", "")
            if isinstance(content, str) and len(content) > 500:
                msg_copy["content"] = content[:200] + "\n...[truncated]...\n" + content[-200:]

        result.append(msg_copy)

    return result


# ============================================================================
# Context Window Guard
# ============================================================================

class ContextWindowGuard:
    """Context window guard.

    Monitors conversation length and prevents overflow.

    Usage:
        guard = ContextWindowGuard(model="claude-sonnet-4-20250514")

        # Check messages
        result = guard.check(messages)
        if result.should_block:
            messages = guard.auto_compact(messages)
        elif result.should_warn:
            logger.warning(result.message)
    """

    def __init__(
        self,
        model: Optional[str] = None,
        context_limit: Optional[int] = None,
        warn_ratio: float = 0.75,
        block_ratio: float = 0.90,
        auto_compact_strategy: CompactionStrategy = CompactionStrategy.KEEP_RECENT,
        auto_compact_keep_count: int = 20,
    ):
        """
        Args:
            model: Model name (used for automatic context_limit determination)
            context_limit: Context window size (when specified directly)
            warn_ratio: Warning threshold (0.0~1.0)
            block_ratio: Block threshold (0.0~1.0)
            auto_compact_strategy: Auto-compaction strategy
            auto_compact_keep_count: Number of messages to retain during auto-compaction
        """
        self._model = model
        self._context_limit = context_limit or get_context_limit(model)
        self._warn_ratio = warn_ratio
        self._block_ratio = block_ratio
        self._auto_compact_strategy = auto_compact_strategy
        self._auto_compact_keep_count = auto_compact_keep_count

        # Statistics
        self._check_count = 0
        self._warn_count = 0
        self._block_count = 0
        self._compact_count = 0

    @property
    def context_limit(self) -> int:
        return self._context_limit

    @property
    def warn_threshold(self) -> int:
        return int(self._context_limit * self._warn_ratio)

    @property
    def block_threshold(self) -> int:
        return int(self._context_limit * self._block_ratio)

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "checks": self._check_count,
            "warnings": self._warn_count,
            "blocks": self._block_count,
            "compactions": self._compact_count,
        }

    def check(
        self,
        messages: List[Dict[str, Any]],
        system_prompt_tokens: int = 0,
    ) -> ContextCheckResult:
        """Check the context usage of a message list.

        Args:
            messages: Message list (LangChain or dict format)
            system_prompt_tokens: Estimated token count of the system prompt

        Returns:
            ContextCheckResult
        """
        self._check_count += 1

        estimated = estimate_messages_tokens(messages) + system_prompt_tokens
        ratio = estimated / self._context_limit if self._context_limit > 0 else 1.0

        if ratio >= 1.0:
            status = ContextStatus.OVERFLOW
            message = (
                f"⛔ Context OVERFLOW: {estimated:,} tokens estimated "
                f"(limit: {self._context_limit:,}, {ratio:.1%})"
            )
            self._block_count += 1
        elif ratio >= self._block_ratio:
            status = ContextStatus.BLOCK
            message = (
                f"🔴 Context BLOCK threshold: {estimated:,} tokens estimated "
                f"(limit: {self._context_limit:,}, {ratio:.1%}). "
                f"Compaction recommended."
            )
            self._block_count += 1
        elif ratio >= self._warn_ratio:
            status = ContextStatus.WARN
            message = (
                f"🟡 Context WARN threshold: {estimated:,} tokens estimated "
                f"(limit: {self._context_limit:,}, {ratio:.1%}). "
                f"Consider reducing context."
            )
            self._warn_count += 1
        else:
            status = ContextStatus.OK
            message = ""

        if message:
            logger.info(message)

        return ContextCheckResult(
            status=status,
            estimated_tokens=estimated,
            context_limit=self._context_limit,
            usage_ratio=ratio,
            message=message,
        )

    def check_text(self, text: str) -> ContextCheckResult:
        """Check context usage for a single text (convenience method)."""
        estimated = estimate_tokens(text)
        ratio = estimated / self._context_limit if self._context_limit > 0 else 1.0

        if ratio >= self._block_ratio:
            status = ContextStatus.BLOCK
        elif ratio >= self._warn_ratio:
            status = ContextStatus.WARN
        else:
            status = ContextStatus.OK

        return ContextCheckResult(
            status=status,
            estimated_tokens=estimated,
            context_limit=self._context_limit,
            usage_ratio=ratio,
        )

    def auto_compact(
        self,
        messages: List[Dict[str, Any]],
        strategy: Optional[CompactionStrategy] = None,
        keep_count: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Apply automatic compaction.

        Args:
            messages: Original message list
            strategy: Compaction strategy (uses default if None)
            keep_count: Number of messages to keep (uses default if None)

        Returns:
            Compacted message list
        """
        self._compact_count += 1
        used_strategy = strategy or self._auto_compact_strategy
        used_keep_count = keep_count or self._auto_compact_keep_count

        original_tokens = estimate_messages_tokens(messages)
        compacted = compact_messages(
            messages,
            strategy=used_strategy,
            keep_count=used_keep_count,
        )
        new_tokens = estimate_messages_tokens(compacted)

        logger.info(
            f"Context compaction: {original_tokens:,} → {new_tokens:,} tokens "
            f"({len(messages)} → {len(compacted)} messages, "
            f"strategy={used_strategy.value})"
        )

        return compacted

    def check_and_compact(
        self,
        messages: List[Dict[str, Any]],
        system_prompt_tokens: int = 0,
    ) -> Tuple[List[Dict[str, Any]], ContextCheckResult]:
        """Perform check and compaction in one step.

        If at block level, automatically applies compaction.

        Args:
            messages: Message list
            system_prompt_tokens: System prompt token count

        Returns:
            Tuple of (compacted messages, check result)
        """
        result = self.check(messages, system_prompt_tokens)

        if result.should_block:
            compacted = self.auto_compact(messages)
            # Re-check
            result = self.check(compacted, system_prompt_tokens)
            return compacted, result

        return messages, result
