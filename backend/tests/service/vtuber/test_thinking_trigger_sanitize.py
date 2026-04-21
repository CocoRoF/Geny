"""Pin that ``ThinkingTriggerService._save_to_chat_room`` sanitizes
the VTuber's trigger response before it hits the chat room.

Cycle 20260421_2 / plan 02, sink #4. Idle-trigger responses are a
common source of ``[joy]``/``[surprise]`` leaks because the VTuber
prompt explicitly invites emotion-tagged replies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from service.vtuber.thinking_trigger import ThinkingTriggerService


class _FakeAgent:
    def __init__(self, chat_room_id: Optional[str] = "room-1") -> None:
        self.session_id = "vtuber-1"
        self._chat_room_id = chat_room_id
        self._session_name = "Test VTuber"
        self._role = "vtuber"
        self.role = MagicMock(value="vtuber")


class _FakeAgentManager:
    def __init__(self, agent: _FakeAgent) -> None:
        self._agent = agent

    def get_agent(self, _session_id: str) -> _FakeAgent:
        return self._agent


class _FakeChatStore:
    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []

    def add_message(self, room_id: str, msg: Dict[str, Any]) -> Dict[str, Any]:
        entry = {"id": f"msg-{len(self.messages)}", "room_id": room_id, **msg}
        self.messages.append(entry)
        return entry


class _FakeResult:
    def __init__(self, output: str, success: bool = True) -> None:
        self.output = output
        self.success = success
        self.duration_ms = 200
        self.cost_usd = 0.0


@pytest.fixture
def world(monkeypatch):
    agent = _FakeAgent()
    store = _FakeChatStore()
    monkeypatch.setattr(
        "service.langgraph.get_agent_session_manager",
        lambda: _FakeAgentManager(agent),
        raising=False,
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
    return {"store": store}


def test_trigger_reply_strips_emotion_tags(world) -> None:
    svc = ThinkingTriggerService()
    result = _FakeResult("음~ 조용하네 [joy] 편안해 [calm]")
    svc._save_to_chat_room("vtuber-1", result)

    assert world["store"].messages[0]["content"] == "음~ 조용하네 편안해"


def test_trigger_reply_strips_routing_prefix(world) -> None:
    svc = ThinkingTriggerService()
    result = _FakeResult("[THINKING_TRIGGER:first_idle] 조용하네")
    svc._save_to_chat_room("vtuber-1", result)

    assert world["store"].messages[0]["content"] == "조용하네"


def test_trigger_reply_skips_when_only_tags(world) -> None:
    svc = ThinkingTriggerService()
    result = _FakeResult("[thoughtful] [calm]")
    svc._save_to_chat_room("vtuber-1", result)

    assert world["store"].messages == []
