"""Pin that the Sub-Worker auto-report and inbox-drain chat sinks run
their output through ``sanitize_for_display`` before persisting.

Cycle 20260421_2 / plan 02: these two helpers in ``agent_executor``
(``_save_subworker_reply_to_chat_room``, ``_save_drain_to_chat_room``)
are the paths that historically leaked ``[SUB_WORKER_RESULT] ... [joy]``
into the chat room. The broader logic is already covered by
``test_notify_linked_vtuber.py`` and the drain tests; here we only pin
the new sanitize contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from service.execution import agent_executor
from service.execution.agent_executor import (
    ExecutionResult,
    _save_drain_to_chat_room,
    _save_subworker_reply_to_chat_room,
)


class _FakeAgent:
    def __init__(self, session_id: str, chat_room_id: Optional[str] = "room-1") -> None:
        self.session_id = session_id
        self._session_type = "vtuber"
        self._chat_room_id = chat_room_id
        self._session_name = "Test"
        self._role = "vtuber"
        self.role = MagicMock(value="vtuber")


class _FakeAgentManager:
    def __init__(self, agent: _FakeAgent) -> None:
        self._agent = agent

    def get_agent(self, session_id: str) -> Optional[_FakeAgent]:
        return self._agent if self._agent.session_id == session_id else None


class _FakeChatStore:
    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []

    def add_message(self, room_id: str, msg: Dict[str, Any]) -> Dict[str, Any]:
        entry = {"id": f"msg-{len(self.messages)}", "room_id": room_id, **msg}
        self.messages.append(entry)
        return entry


@pytest.fixture
def world(monkeypatch):
    agent = _FakeAgent("vtuber-1")
    store = _FakeChatStore()
    monkeypatch.setattr(
        agent_executor, "_get_agent_manager", lambda: _FakeAgentManager(agent)
    )
    monkeypatch.setattr(
        "service.chat.conversation_store.get_chat_store",
        lambda: store,
        raising=False,
    )
    monkeypatch.setattr(
        "controller.chat_controller._notify_room",
        lambda _rid: None,
        raising=False,
    )
    return {"store": store, "agent": agent}


# ─────────────────────────────────────────────────────────────────
# _save_subworker_reply_to_chat_room — sink #2
# ─────────────────────────────────────────────────────────────────


def test_subworker_reply_strips_routing_and_emotion_tags(world) -> None:
    result = ExecutionResult(
        success=True,
        session_id="vtuber-1",
        output="[SUB_WORKER_RESULT] 워커가 보고를 전해주었어! [joy] 좋네 [surprise]",
        duration_ms=100,
        cost_usd=0.0,
    )
    _save_subworker_reply_to_chat_room("vtuber-1", result)

    assert len(world["store"].messages) == 1
    assert world["store"].messages[0]["content"] == "워커가 보고를 전해주었어! 좋네"


def test_subworker_reply_skips_when_only_tags(world) -> None:
    """Tags-only output collapses to empty — drop rather than show an
    empty chat turn."""
    result = ExecutionResult(
        success=True,
        session_id="vtuber-1",
        output="[joy] [smirk]",
        duration_ms=10,
    )
    _save_subworker_reply_to_chat_room("vtuber-1", result)

    assert world["store"].messages == []


def test_subworker_reply_strips_think_blocks(world) -> None:
    result = ExecutionResult(
        success=True,
        session_id="vtuber-1",
        output="<think>internal reasoning</think>Hi there!",
        duration_ms=10,
    )
    _save_subworker_reply_to_chat_room("vtuber-1", result)

    assert world["store"].messages[0]["content"] == "Hi there!"


# ─────────────────────────────────────────────────────────────────
# _save_drain_to_chat_room — sink #3
# ─────────────────────────────────────────────────────────────────


def test_drain_reply_strips_tags(world) -> None:
    result = ExecutionResult(
        success=True,
        session_id="vtuber-1",
        output="[SUB_WORKER_RESULT] drained ok [warmth]",
        duration_ms=50,
    )
    _save_drain_to_chat_room("vtuber-1", result)

    assert world["store"].messages[0]["content"] == "drained ok"


def test_drain_reply_skips_when_only_tags(world) -> None:
    result = ExecutionResult(
        success=True,
        session_id="vtuber-1",
        output="[neutral]",
        duration_ms=5,
    )
    _save_drain_to_chat_room("vtuber-1", result)

    assert world["store"].messages == []
