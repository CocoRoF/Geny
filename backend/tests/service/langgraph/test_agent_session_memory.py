"""Regression tests for STM role-classified message recording.

Cycle 20260420_8 / plan/03 Bug 2b-α: ``_invoke_pipeline`` /
``_astream_pipeline`` used to record every input as ``role="user"``
and never recorded the assistant's reply. Two downstream consequences:

1. Internal triggers (``[THINKING_TRIGGER:*]``) and inter-agent DMs
   (``[SUB_WORKER_RESULT]``) got stored as user turns, so later
   retrieval saw them as real user messages.
2. The assistant's reply was absent from STM, so
   ``session_summary`` / keyword retrieval / vector retrieval had no
   record of what the assistant just said — breaking trigger-driven
   continuity ("아직 답이 없다" regression).

These tests pin the new ``_classify_input_role`` helper and the two
``record_message`` call sites in both pipeline paths.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

from service.langgraph.agent_session import (
    AgentSession,
    _classify_input_role,
)


# ─────────────────────────────────────────────────────────────────
# _classify_input_role — pure function
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        # Plain user input
        ("hello world", "user"),
        ("  hi there", "user"),
        # Internal triggers — emitted by service/vtuber/thinking_trigger.py
        ("[THINKING_TRIGGER] user has been quiet", "internal_trigger"),
        ("[THINKING_TRIGGER:first_idle] check in", "internal_trigger"),
        ("[THINKING_TRIGGER:continued_idle]", "internal_trigger"),
        ("[ACTIVITY_TRIGGER] curiosity time", "internal_trigger"),
        ("[ACTIVITY_TRIGGER:user_return] hi", "internal_trigger"),
        # Sub-worker auto-reports — emitted by service/execution/agent_executor.py
        ("[SUB_WORKER_RESULT] Task done: file.txt created", "assistant_dm"),
        ("[SUB_WORKER_RESULT] Task failed: boom", "assistant_dm"),
        # Legacy alias still accepted by DelegationMessage.is_result_message
        ("[CLI_RESULT] legacy payload", "assistant_dm"),
        # Delegation protocol tags — service/vtuber/delegation.py
        ("[DELEGATION_REQUEST] please handle this task", "assistant_dm"),
        ("[DELEGATION_RESULT] task completed", "assistant_dm"),
        # DM prompt wrapper — tools/built_in/geny_tools.py _trigger_dm_response
        (
            "[SYSTEM] You received a direct message from alice (session: s-1). "
            "Read the message below...",
            "assistant_dm",
        ),
        # Forward-compat placeholders from plan/03 § 4-2
        ("[SUB_WORKER_PROGRESS] 50% done", "assistant_dm"),
        ("[FROM_COUNTERPART:sub-1] hey worker", "assistant_dm"),
        # Inbox drain wrappers — emitted by _drain_inbox in
        # service/execution/agent_executor.py when a queued DM is
        # picked up after the busy window closes. Covers the common
        # regression path where a [SUB_WORKER_RESULT] arrives while
        # the VTuber is still running its own turn and ends up being
        # replayed via drain (cycle 20260421_1).
        (
            "[INBOX from Sub-Worker]\n"
            "[SUB_WORKER_RESULT] Task completed successfully.\n\nfound a fact",
            "assistant_dm",
        ),
        ("[INBOX from Sub-Worker]\nplain body with no inner tag", "assistant_dm"),
        ("[INBOX from alice]\nhi there", "assistant_dm"),
        # Leading whitespace must not defeat the match
        ("   [SUB_WORKER_RESULT] leading ws stripped", "assistant_dm"),
        ("   [INBOX from Bob]\nhello", "assistant_dm"),
        # Ambiguous / embedded — must stay "user"
        ("fake [THINKING_TRIGGER] inside prose", "user"),
        ("[OTHER_TAG] not ours", "user"),
        ("fake [INBOX from foo] mid-sentence", "user"),
        # Unrelated [SYSTEM] prompts must not be swept up
        ("[SYSTEM] Something else entirely", "user"),
    ],
)
def test_classify_input_role(text: str, expected: str) -> None:
    assert _classify_input_role(text) == expected


# ─────────────────────────────────────────────────────────────────
# _invoke_pipeline / _astream_pipeline — record_message wiring
# ─────────────────────────────────────────────────────────────────


class _FakeMemoryManager:
    def __init__(self) -> None:
        self.messages: List[Tuple[str, str]] = []
        self.executions: List[Dict[str, Any]] = []

    def record_message(self, role: str, content: str) -> None:
        self.messages.append((role, content))

    async def record_execution(self, **kwargs: Any) -> None:
        self.executions.append(kwargs)


class _FakeEvent:
    def __init__(self, event_type: str, data: Dict[str, Any]) -> None:
        self.type = event_type
        self.data = data


class _FakePipeline:
    """Yields a scripted sequence of PipelineEvents from run_stream."""

    def __init__(self, events: List[_FakeEvent]) -> None:
        self._events = events

    async def run_stream(self, input_text: str, state: Any):
        for evt in self._events:
            yield evt


def _make_session(events: List[_FakeEvent]) -> Tuple[AgentSession, _FakeMemoryManager]:
    """Construct an AgentSession with just enough wiring to exercise
    the pipeline-invocation helpers. Heavy construction is skipped —
    we only need the memory manager + a scripted pipeline."""
    session = AgentSession(session_id="s-test", session_name="T")
    mem = _FakeMemoryManager()
    session._memory_manager = mem  # type: ignore[assignment]
    session._pipeline = _FakePipeline(events)  # type: ignore[assignment]
    session._execution_count = 0
    return session, mem


def _success_events(output: str = "hello back") -> List[_FakeEvent]:
    return [
        _FakeEvent("text.delta", {"text": output}),
        _FakeEvent(
            "pipeline.complete",
            {"result": output, "total_cost_usd": 0.001, "iterations": 1},
        ),
    ]


@pytest.mark.asyncio
async def test_invoke_records_user_and_assistant_to_stm() -> None:
    session, mem = _make_session(_success_events("와! 안녕"))
    await session._invoke_pipeline("hi there", start_time=0.0, session_logger=None)

    roles = [r for r, _ in mem.messages]
    assert roles == ["user", "assistant"]
    assert mem.messages[0][1] == "hi there"
    assert mem.messages[1][1] == "와! 안녕"


@pytest.mark.asyncio
async def test_thinking_trigger_classified_as_internal_trigger() -> None:
    session, mem = _make_session(_success_events("음 조용하네"))
    await session._invoke_pipeline(
        "[THINKING_TRIGGER:first_idle] user has been quiet",
        start_time=0.0,
        session_logger=None,
    )

    roles = [r for r, _ in mem.messages]
    assert roles == ["internal_trigger", "assistant"]


@pytest.mark.asyncio
async def test_sub_worker_result_classified_as_assistant_dm() -> None:
    session, mem = _make_session(_success_events("완료됐네!"))
    await session._invoke_pipeline(
        "[SUB_WORKER_RESULT] test.txt created",
        start_time=0.0,
        session_logger=None,
    )

    roles = [r for r, _ in mem.messages]
    assert roles == ["assistant_dm", "assistant"]


@pytest.mark.asyncio
async def test_empty_output_does_not_record_assistant() -> None:
    session, mem = _make_session([
        _FakeEvent(
            "pipeline.complete",
            {"result": "", "total_cost_usd": 0.0, "iterations": 0},
        ),
    ])
    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    roles = [r for r, _ in mem.messages]
    assert roles == ["user"], "assistant record must be skipped on empty output"


@pytest.mark.asyncio
async def test_failed_execution_does_not_record_assistant() -> None:
    session, mem = _make_session([
        _FakeEvent("text.delta", {"text": "partial"}),
        _FakeEvent(
            "pipeline.error",
            {"error": "boom", "total_cost_usd": 0.0},
        ),
    ])
    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    roles = [r for r, _ in mem.messages]
    assert roles == ["user"], (
        "on failure the STM should not persist a possibly-truncated "
        "assistant reply as a successful turn"
    )


@pytest.mark.asyncio
async def test_assistant_record_is_non_critical() -> None:
    """Exception inside record_message must not propagate and break
    the invoke path — LTM recording and the return value should still
    succeed."""
    session, _mem = _make_session(_success_events("ok"))
    calls: List[Tuple[str, str]] = []

    class _ExplodingMemory:
        def __init__(self) -> None:
            self.executions: List[Dict[str, Any]] = []

        def record_message(self, role: str, content: str) -> None:
            calls.append((role, content))
            raise RuntimeError("stm down")

        async def record_execution(self, **kwargs: Any) -> None:
            self.executions.append(kwargs)

    exploding = _ExplodingMemory()
    session._memory_manager = exploding  # type: ignore[assignment]

    result = await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    assert result["output"] == "ok"
    # Both the user and assistant attempts happened before being swallowed
    assert [r for r, _ in calls] == ["user", "assistant"]
    # LTM write still happened
    assert len(exploding.executions) == 1


# ─────────────────────────────────────────────────────────────────
# _astream_pipeline mirrors the same wiring
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_classifies_input_role_the_same_way() -> None:
    session, mem = _make_session(_success_events("yup"))
    async for _ in session._astream_pipeline(
        "[SUB_WORKER_RESULT] done",
        start_time=0.0,
        session_logger=None,
    ):
        pass

    roles = [r for r, _ in mem.messages]
    assert roles == ["assistant_dm", "assistant"]


@pytest.mark.asyncio
async def test_stream_empty_output_does_not_record_assistant() -> None:
    session, mem = _make_session([
        _FakeEvent(
            "pipeline.complete",
            {"result": "", "total_cost_usd": 0.0, "iterations": 0},
        ),
    ])
    async for _ in session._astream_pipeline(
        "plain user input",
        start_time=0.0,
        session_logger=None,
    ):
        pass

    assert [r for r, _ in mem.messages] == ["user"]
