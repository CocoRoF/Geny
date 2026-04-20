"""
Delegation Protocol
===================

Defines the structured message format for VTuber ↔ Sub-Worker
delegation and response reporting.

Tags:
  [DELEGATION_REQUEST]    — VTuber → Sub-Worker: task assignment
  [DELEGATION_RESULT]     — Sub-Worker → VTuber: task completion report
  [THINKING_TRIGGER]      — System → VTuber: idle thinking
  [SUB_WORKER_RESULT]     — System → VTuber: Sub-Worker finished (auto-report)

Loop Prevention:
  Messages tagged with [DELEGATION_RESULT] or [SUB_WORKER_RESULT]
  are classified as "thinking" by VTuberClassifyNode and never
  re-delegated.

Legacy:
  The canonical tag is [SUB_WORKER_RESULT]. [CLI_RESULT] is the
  pre-rename alias and is still accepted by the matcher below so
  any in-flight inbox messages or persisted history keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# Legacy tag accepted on read for backward compatibility with messages
# that may have been persisted before the rename. Emitters always use
# DelegationTag.SUB_WORKER_RESULT.
_LEGACY_SUB_WORKER_RESULT_TAG = "[CLI_RESULT]"


class DelegationTag(str, Enum):
    """Standard message tags for inter-agent communication."""
    REQUEST = "[DELEGATION_REQUEST]"
    RESULT = "[DELEGATION_RESULT]"
    THINKING = "[THINKING_TRIGGER]"
    SUB_WORKER_RESULT = "[SUB_WORKER_RESULT]"


@dataclass
class DelegationMessage:
    """Structured delegation message between VTuber and Sub-Worker agents."""
    tag: DelegationTag
    sender_session_id: str
    target_session_id: str
    content: str
    task_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def format(self) -> str:
        """Format as a string for DM delivery."""
        parts = [
            f"{self.tag.value}",
            f"From: {self.sender_session_id}",
        ]
        if self.task_id:
            parts.append(f"Task: {self.task_id}")
        parts.append(f"\n{self.content}")
        return "\n".join(parts)

    @staticmethod
    def is_delegation_message(text: str) -> bool:
        """Check if a message is a delegation protocol message."""
        if any(text.startswith(tag.value) for tag in DelegationTag):
            return True
        # Legacy tag fallback.
        return text.startswith(_LEGACY_SUB_WORKER_RESULT_TAG)

    @staticmethod
    def is_result_message(text: str) -> bool:
        """Check if a message is a result/report (should not be re-delegated)."""
        return (
            text.startswith(DelegationTag.RESULT.value)
            or text.startswith(DelegationTag.SUB_WORKER_RESULT.value)
            or text.startswith(_LEGACY_SUB_WORKER_RESULT_TAG)
        )

    @staticmethod
    def is_thinking_trigger(text: str) -> bool:
        """Check if a message is a thinking trigger."""
        return text.startswith(DelegationTag.THINKING.value)


def format_delegation_request(
    sender_id: str,
    target_id: str,
    task: str,
    task_id: Optional[str] = None,
) -> str:
    """Create a formatted delegation request message."""
    msg = DelegationMessage(
        tag=DelegationTag.REQUEST,
        sender_session_id=sender_id,
        target_session_id=target_id,
        content=task,
        task_id=task_id,
    )
    return msg.format()


def format_delegation_result(
    sender_id: str,
    target_id: str,
    result: str,
    task_id: Optional[str] = None,
) -> str:
    """Create a formatted delegation result message."""
    msg = DelegationMessage(
        tag=DelegationTag.RESULT,
        sender_session_id=sender_id,
        target_session_id=target_id,
        content=result,
        task_id=task_id,
    )
    return msg.format()


def parse_delegation_headers(text: str) -> Optional[dict]:
    """Extract the tag (+ optional From/Task headers) from a formatted
    delegation message. Returns None if *text* is not a delegation
    message. Tolerates formats that omit the From/Task lines — the
    SUB_WORKER_RESULT template in agent_executor skips them.
    """
    if not text or not DelegationMessage.is_delegation_message(text):
        return None
    first_line = text.split("\n", 1)[0].strip()
    tag: Optional[str] = None
    for known in list(DelegationTag) + [DelegationTag.SUB_WORKER_RESULT]:  # type: ignore[list-item]
        if first_line.startswith(known.value):
            tag = known.value
            break
    if tag is None and first_line.startswith(_LEGACY_SUB_WORKER_RESULT_TAG):
        tag = DelegationTag.SUB_WORKER_RESULT.value
    headers: dict = {"tag": tag}
    for line in text.split("\n")[1:5]:  # scan the first few lines only
        stripped = line.strip()
        if stripped.startswith("From:"):
            headers["from_session_id"] = stripped[len("From:"):].strip()
        elif stripped.startswith("Task:"):
            headers["task_id"] = stripped[len("Task:"):].strip()
        elif not stripped:
            break
    return headers
