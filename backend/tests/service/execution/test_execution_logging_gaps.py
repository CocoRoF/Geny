"""Pin the silent-path promotions added in cycle 20260421_3 / plan 02.

Before this cycle, several execution-side events (auto-revival, inbox
delivery onto a busy peer, inbox drain start/item/complete) only went
to stderr via ``logger.info``. That meant the log panel silently hid
the reason a DM was delayed or why an agent was re-created. These
tests assert the matching session_logger entries are now emitted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from service.execution import agent_executor
from service.execution.agent_executor import (
    AlreadyExecutingError,
    ExecutionResult,
    _drain_inbox,
    _notify_linked_vtuber,
    _resolve_agent,
)
from service.logging.session_logger import LogLevel


# ─────────────────────────────────────────────────────────────────
# In-memory fakes
# ─────────────────────────────────────────────────────────────────


class _FakeSessionLogger:
    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []

    def log(self, *, level, message, metadata=None):
        self.entries.append({"level": level, "message": message, "metadata": metadata or {}})

    # Needed by _notify_linked_vtuber delegation.sent
    def log_delegation_event(self, *args, **kwargs) -> None:
        pass


class _FakeAgent:
    def __init__(
        self,
        session_id: str,
        *,
        alive: bool = True,
        revive_result: bool = True,
        session_type: str = "vtuber",
        linked_id: Optional[str] = None,
        chat_room_id: Optional[str] = None,
        role: str = "vtuber",
    ) -> None:
        self.session_id = session_id
        self._alive = alive
        self._revive_result = revive_result
        self.status = "dead" if not alive else "alive"
        self.process = None
        self._session_type = session_type
        self.linked_session_id = linked_id
        self._chat_room_id = chat_room_id
        self._session_name = "T"
        self.role = MagicMock(value=role)

    def is_alive(self) -> bool:
        return self._alive

    async def revive(self) -> bool:
        self._alive = self._revive_result
        return self._revive_result


class _FakeAgentManager:
    def __init__(self, agents: Dict[str, _FakeAgent]) -> None:
        self._agents = agents
        self._local_processes: Dict[str, Any] = {}

    def get_agent(self, session_id: str) -> Optional[_FakeAgent]:
        return self._agents.get(session_id)


# ─────────────────────────────────────────────────────────────────
# Auto-revival
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_revival_emits_session_log_entry(monkeypatch) -> None:
    dead = _FakeAgent("s1", alive=False, revive_result=True)
    manager = _FakeAgentManager({"s1": dead})
    sl = _FakeSessionLogger()

    monkeypatch.setattr(agent_executor, "_get_agent_manager", lambda: manager)
    monkeypatch.setattr(
        agent_executor,
        "_get_session_logger",
        lambda sid, create_if_missing=True: sl,
    )

    await _resolve_agent("s1")

    revival_entries = [
        e for e in sl.entries if e["metadata"].get("event") == "auto_revival"
    ]
    assert len(revival_entries) == 1
    assert revival_entries[0]["level"] == LogLevel.INFO
    assert revival_entries[0]["metadata"]["session_id"] == "s1"


# ─────────────────────────────────────────────────────────────────
# Inbox delivery on busy recipient
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inbox_delivery_on_busy_logs_sender_side_entry(monkeypatch) -> None:
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
        role="worker",
    )
    manager = _FakeAgentManager({"vtuber-1": vtuber, "sub-1": sub})

    sender_sl = _FakeSessionLogger()

    delivered_calls: List[Dict[str, Any]] = []

    class _FakeInbox:
        def deliver(self, **kwargs):
            delivered_calls.append(kwargs)

        def send_to_dlq(self, **kwargs):  # pragma: no cover — must not fire
            raise AssertionError("DLQ path should not be reached")

    async def _busy_execute(*_a, **_kw):
        raise AlreadyExecutingError("busy")

    monkeypatch.setattr(agent_executor, "_get_agent_manager", lambda: manager)
    monkeypatch.setattr(agent_executor, "execute_command", _busy_execute)
    monkeypatch.setattr(
        agent_executor,
        "_get_session_logger",
        lambda sid, create_if_missing=True: sender_sl if sid == "sub-1" else None,
    )
    monkeypatch.setattr(
        "service.chat.inbox.get_inbox_manager",
        lambda: _FakeInbox(),
        raising=False,
    )

    # Capture the fire-and-forget inbox trigger task so the assertion
    # runs after the AlreadyExecutingError handler finishes.
    import asyncio

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
    await _notify_linked_vtuber("sub-1", sub_result)
    for task in created_tasks:
        await task

    assert len(delivered_calls) == 1
    inbox_entries = [
        e for e in sender_sl.entries if e["metadata"].get("event") == "inbox.delivered"
    ]
    assert len(inbox_entries) == 1
    assert inbox_entries[0]["level"] == LogLevel.INFO
    assert inbox_entries[0]["metadata"]["to_session_id"] == "vtuber-1"


# ─────────────────────────────────────────────────────────────────
# Inbox drain lifecycle
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drain_logs_start_item_and_complete(monkeypatch) -> None:
    sl = _FakeSessionLogger()

    monkeypatch.setattr(
        agent_executor,
        "_get_session_logger",
        lambda sid, create_if_missing=True: sl,
    )

    queued = [
        {"id": "m1", "sender_name": "Peer", "content": "first"},
        {"id": "m2", "sender_name": "Peer", "content": "second"},
    ]

    class _FakeInbox:
        def __init__(self) -> None:
            self._queue = list(queued)

        def pull_unread(self, sid: str, limit: int = 1):
            if not self._queue:
                return []
            return [self._queue.pop(0)]

    monkeypatch.setattr(
        "service.chat.inbox.get_inbox_manager",
        lambda: _FakeInbox(),
        raising=False,
    )

    async def _ok_execute(session_id: str, content: str, **_kw):
        return ExecutionResult(success=True, session_id=session_id, output="", duration_ms=1)

    monkeypatch.setattr(agent_executor, "execute_command", _ok_execute)
    # Silence the chat-room broadcast (not the subject of this test)
    monkeypatch.setattr(
        agent_executor,
        "_save_drain_to_chat_room",
        lambda *_a, **_kw: None,
    )

    await _drain_inbox("s1")

    events = [e["metadata"].get("event") for e in sl.entries]
    assert "inbox.drain.start" in events
    assert events.count("inbox.drain.item_ok") == 2
    complete = [
        e for e in sl.entries
        if e["metadata"].get("event") == "inbox.drain.complete"
    ]
    assert len(complete) == 1
    assert complete[0]["metadata"]["n_ok"] == 2
    assert complete[0]["metadata"]["n_err"] == 0


@pytest.mark.asyncio
async def test_drain_empty_queue_emits_no_lifecycle_entries(monkeypatch) -> None:
    """Silent path for the common 'nothing to drain' case — we must not
    spam the log panel with drain.start/complete for zero items."""
    sl = _FakeSessionLogger()

    monkeypatch.setattr(
        agent_executor,
        "_get_session_logger",
        lambda sid, create_if_missing=True: sl,
    )

    class _EmptyInbox:
        def pull_unread(self, *_a, **_kw):
            return []

    monkeypatch.setattr(
        "service.chat.inbox.get_inbox_manager",
        lambda: _EmptyInbox(),
        raising=False,
    )

    await _drain_inbox("s1")

    drain_events = [
        e for e in sl.entries
        if (e["metadata"].get("event") or "").startswith("inbox.drain.")
    ]
    assert drain_events == []
