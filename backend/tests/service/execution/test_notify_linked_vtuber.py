"""Regression tests for the Sub-Worker → VTuber auto-report chat broadcast.

Cycle 20260420_8 / plan/02 closes Bug 2a: when a Sub-Worker finishes a
delegated task, ``_notify_linked_vtuber`` fires a ``[SUB_WORKER_RESULT]``
trigger to the paired VTuber. Before this fix the VTuber generated a
conversational reply to that trigger (observable in the logs as
``output_len=164``) but the reply was never posted to the user's chat
room — it died inside the fire-and-forget task. These tests pin the
new ``_save_subworker_reply_to_chat_room`` helper and the one call
site that invokes it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from service.execution import agent_executor
from service.execution.agent_executor import (
    AlreadyExecutingError,
    ExecutionResult,
    _save_subworker_reply_to_chat_room,
)


class _FakeAgent:
    """Stand-in AgentSession that exposes the handful of attributes
    the executor inspects during notify/broadcast."""

    def __init__(
        self,
        session_id: str,
        *,
        session_type: str = "sub",
        linked_id: Optional[str] = None,
        chat_room_id: Optional[str] = None,
        session_name: str = "Test",
        role: str = "vtuber",
    ) -> None:
        self.session_id = session_id
        self._session_type = session_type
        self.linked_session_id = linked_id
        self._chat_room_id = chat_room_id
        self._session_name = session_name
        self._role = role
        self.role = MagicMock(value=role)


class _FakeAgentManager:
    def __init__(self, agents: Dict[str, _FakeAgent]) -> None:
        self._agents = agents

    def get_agent(self, session_id: str) -> Optional[_FakeAgent]:
        return self._agents.get(session_id)


class _FakeChatStore:
    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []

    def add_message(self, room_id: str, msg: Dict[str, Any]) -> Dict[str, Any]:
        entry = {"id": f"msg-{len(self.messages)}", "room_id": room_id, **msg}
        self.messages.append(entry)
        return entry


@pytest.fixture
def patched_world(monkeypatch):
    """Install fakes for the agent manager, chat store, and
    ``_notify_room``; return references so tests can assert."""
    vtuber = _FakeAgent(
        "vtuber-1",
        session_type="vtuber",
        linked_id="sub-1",
        chat_room_id="room-1",
    )
    sub = _FakeAgent(
        "sub-1",
        session_type="sub",
        linked_id="vtuber-1",
        chat_room_id="room-1",
    )
    agents = {"vtuber-1": vtuber, "sub-1": sub}
    manager = _FakeAgentManager(agents)
    store = _FakeChatStore()
    notify_calls: List[str] = []

    monkeypatch.setattr(agent_executor, "_get_agent_manager", lambda: manager)

    # Stub the lazy imports that the helpers pull in.
    monkeypatch.setattr(
        "service.chat.conversation_store.get_chat_store",
        lambda: store,
        raising=False,
    )
    monkeypatch.setattr(
        "controller.chat_controller._notify_room",
        lambda rid: notify_calls.append(rid),
        raising=False,
    )

    return {
        "manager": manager,
        "store": store,
        "notify_calls": notify_calls,
        "vtuber": vtuber,
        "sub": sub,
    }


# ─────────────────────────────────────────────────────────────────
# Helper — _save_subworker_reply_to_chat_room
# ─────────────────────────────────────────────────────────────────


def test_successful_reply_posts_to_chat_room(patched_world) -> None:
    result = ExecutionResult(
        success=True,
        session_id="vtuber-1",
        output="와! Sub-Worker가 파일 만들었어!",
        duration_ms=1234,
        cost_usd=0.0042,
    )
    _save_subworker_reply_to_chat_room("vtuber-1", result)

    store = patched_world["store"]
    assert len(store.messages) == 1
    msg = store.messages[0]
    assert msg["room_id"] == "room-1"
    assert msg["type"] == "agent"
    assert msg["session_id"] == "vtuber-1"
    assert msg["content"] == "와! Sub-Worker가 파일 만들었어!"
    assert msg["source"] == "sub_worker_reply"
    assert msg["duration_ms"] == 1234
    assert msg["cost_usd"] == 0.0042

    # SSE notify fires once
    assert patched_world["notify_calls"] == ["room-1"]


def test_empty_output_skips_broadcast(patched_world) -> None:
    """Zero-length or whitespace-only outputs are not worth
    surfacing — the VTuber intentionally stayed silent."""
    result = ExecutionResult(
        success=True, session_id="vtuber-1", output="   \n  ", duration_ms=10,
    )
    _save_subworker_reply_to_chat_room("vtuber-1", result)

    assert patched_world["store"].messages == []
    assert patched_world["notify_calls"] == []


def test_failed_execution_skips_broadcast(patched_world) -> None:
    result = ExecutionResult(
        success=False,
        session_id="vtuber-1",
        output="would-be-output",
        error="boom",
        duration_ms=50,
    )
    _save_subworker_reply_to_chat_room("vtuber-1", result)

    assert patched_world["store"].messages == []


def test_vtuber_without_chat_room_is_noop(monkeypatch, patched_world) -> None:
    patched_world["vtuber"]._chat_room_id = None

    result = ExecutionResult(
        success=True, session_id="vtuber-1", output="hi", duration_ms=1,
    )
    _save_subworker_reply_to_chat_room("vtuber-1", result)

    assert patched_world["store"].messages == []
    assert patched_world["notify_calls"] == []


def test_unknown_vtuber_session_is_noop(patched_world) -> None:
    result = ExecutionResult(
        success=True, session_id="ghost", output="hi", duration_ms=1,
    )
    _save_subworker_reply_to_chat_room("ghost", result)

    assert patched_world["store"].messages == []


# ─────────────────────────────────────────────────────────────────
# _notify_linked_vtuber wiring — call site for the helper above
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_linked_vtuber_broadcasts_reply(monkeypatch, patched_world):
    """End-to-end on the wiring: the Sub-Worker result triggers the
    VTuber, the VTuber's reply (returned by ``execute_command``) lands
    in the chat room, and SSE subscribers are notified."""
    reply = ExecutionResult(
        success=True,
        session_id="vtuber-1",
        output="와! 완료됐네!",
        duration_ms=200,
        cost_usd=0.002,
    )

    async def _fake_execute_command(target: str, content: str, **_kwargs):
        # The helper should hand us the VTuber session id + the
        # [SUB_WORKER_RESULT]-tagged prompt. Pretend the VTuber
        # produced its reply.
        assert target == "vtuber-1"
        assert content.startswith("[SUB_WORKER_RESULT]")
        return reply

    monkeypatch.setattr(agent_executor, "execute_command", _fake_execute_command)
    # _get_session_logger is used for the delegation.sent event; stub it.
    monkeypatch.setattr(
        agent_executor, "_get_session_logger", lambda *_a, **_kw: None
    )

    # The Sub-Worker finished with this result:
    sub_result = ExecutionResult(
        success=True,
        session_id="sub-1",
        output="test.txt created",
        duration_ms=500,
    )

    # _notify_linked_vtuber schedules a fire-and-forget task; we need
    # to await the *scheduled* coroutine, not the notify coroutine.
    # Capture the task and await it explicitly so the assertion runs
    # after the broadcast completes.
    created_tasks: List[asyncio.Task] = []
    original_create_task = asyncio.create_task

    def _capturing_create_task(coro, *args, **kwargs):
        task = original_create_task(coro, *args, **kwargs)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", _capturing_create_task)

    await agent_executor._notify_linked_vtuber("sub-1", sub_result)

    # Drain the single scheduled trigger task.
    for task in created_tasks:
        await task

    store = patched_world["store"]
    assert len(store.messages) == 1, (
        "VTuber reply should be posted exactly once to the chat room"
    )
    assert store.messages[0]["content"] == "와! 완료됐네!"
    assert store.messages[0]["source"] == "sub_worker_reply"
    assert patched_world["notify_calls"] == ["room-1"]


@pytest.mark.asyncio
async def test_notify_linked_vtuber_already_executing_falls_back_to_inbox(
    monkeypatch, patched_world
):
    """When the VTuber is busy, the existing inbox fallback still runs
    and the chat room is *not* posted to — the pending reply will be
    broadcast by the drain path when the busy turn completes."""
    inbox_calls: List[Dict[str, Any]] = []

    class _FakeInbox:
        def deliver(self, **kwargs):
            inbox_calls.append(kwargs)

        def send_to_dlq(self, **kwargs):
            raise AssertionError("DLQ should not fire in this path")

    async def _busy_execute(*_a, **_kw):
        raise AlreadyExecutingError("busy")

    monkeypatch.setattr(agent_executor, "execute_command", _busy_execute)
    monkeypatch.setattr(
        agent_executor, "_get_session_logger", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        "service.chat.inbox.get_inbox_manager",
        lambda: _FakeInbox(),
        raising=False,
    )

    created_tasks: List[asyncio.Task] = []
    original_create_task = asyncio.create_task

    def _capturing_create_task(coro, *args, **kwargs):
        task = original_create_task(coro, *args, **kwargs)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", _capturing_create_task)

    sub_result = ExecutionResult(
        success=True, session_id="sub-1", output="done", duration_ms=1,
    )
    await agent_executor._notify_linked_vtuber("sub-1", sub_result)

    for task in created_tasks:
        await task

    assert len(inbox_calls) == 1
    assert inbox_calls[0]["target_session_id"] == "vtuber-1"
    assert patched_world["store"].messages == [], (
        "Chat room must not receive a message when the VTuber was busy — "
        "the pending reply will surface via the inbox drain path"
    )
