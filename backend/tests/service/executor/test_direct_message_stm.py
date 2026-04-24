"""Regression tests for outgoing-DM STM recording.

Cycle 20260421_1 Bug B: ``send_direct_message_internal`` and
``send_direct_message_external`` delivered the DM body to the
recipient's inbox and fired ``_trigger_dm_response`` on them, but
the sender's own short-term memory saw nothing — the DM content
survived only inside the tool event log, so next turn's retrieval
(L0 recent turns / session summary / keyword / vector) had no
record of what the sender just asked. Combined with Bug A (inbox
drain wrapper misclassification) this silently erased the entire
VTuber↔Sub-Worker exchange from memory.

These tests pin the new ``_record_dm_on_sender_stm`` helper and the
two tool call sites wired to it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from tools.built_in import geny_tools
from tools.built_in.geny_tools import (
    SendDirectMessageExternalTool,
    SendDirectMessageInternalTool,
    _record_dm_on_sender_stm,
)


# ─────────────────────────────────────────────────────────────────
# Fake infrastructure
# ─────────────────────────────────────────────────────────────────


class _FakeMemoryManager:
    def __init__(self) -> None:
        self.messages: List[Tuple[str, str]] = []

    def record_message(self, role: str, content: str) -> None:
        self.messages.append((role, content))


class _ExplodingMemoryManager:
    def record_message(self, role: str, content: str) -> None:
        raise RuntimeError("stm down")


class _FakeAgent:
    def __init__(
        self,
        session_id: str,
        *,
        session_name: str = "Agent",
        linked_session_id: str = "",
        memory: Any = None,
    ) -> None:
        self.session_id = session_id
        self.session_name = session_name
        self._linked_session_id = linked_session_id
        self._memory_manager = memory


class _FakeAgentManager:
    def __init__(self, agents: Dict[str, _FakeAgent]) -> None:
        self._agents = agents

    def get_agent(self, session_id: str) -> Any:
        return self._agents.get(session_id)

    def resolve_session(self, name_or_id: str) -> Any:
        a = self._agents.get(name_or_id)
        if a is not None:
            return a
        for agent in self._agents.values():
            if agent.session_name == name_or_id:
                return agent
        return None


class _FakeInbox:
    def __init__(self) -> None:
        self.delivered: List[Dict[str, Any]] = []
        self.fail = False

    def deliver(
        self,
        target_session_id: str,
        content: str,
        sender_session_id: str,
        sender_name: str,
    ) -> Dict[str, Any]:
        if self.fail:
            raise RuntimeError("inbox down")
        entry = {
            "id": f"msg-{len(self.delivered)}",
            "target_session_id": target_session_id,
            "content": content,
            "sender_session_id": sender_session_id,
            "sender_name": sender_name,
            "timestamp": "2026-04-21T10:20:00Z",
        }
        self.delivered.append(entry)
        return entry


@pytest.fixture
def patched_world(monkeypatch):
    """Install fakes for the agent manager, inbox, and trigger so DM
    tools can run in isolation. Returns refs for assertions."""
    vtuber_mem = _FakeMemoryManager()
    sub_mem = _FakeMemoryManager()
    vtuber = _FakeAgent(
        "vtuber-1",
        session_name="testsa",
        linked_session_id="sub-1",
        memory=vtuber_mem,
    )
    sub = _FakeAgent(
        "sub-1",
        session_name="Sub-Worker",
        linked_session_id="vtuber-1",
        memory=sub_mem,
    )
    colleague = _FakeAgent(
        "coll-1",
        session_name="Colleague",
        memory=_FakeMemoryManager(),
    )
    manager = _FakeAgentManager({
        "vtuber-1": vtuber,
        "sub-1": sub,
        "coll-1": colleague,
    })
    inbox = _FakeInbox()
    trigger_calls: List[Dict[str, Any]] = []

    monkeypatch.setattr(geny_tools, "_get_agent_manager", lambda: manager)
    monkeypatch.setattr(geny_tools, "_get_inbox_manager", lambda: inbox)

    def _fake_trigger(**kwargs):
        trigger_calls.append(kwargs)

    monkeypatch.setattr(geny_tools, "_trigger_dm_response", _fake_trigger)

    # _resolve_session uses the manager directly; nothing to patch.

    return {
        "vtuber": vtuber,
        "sub": sub,
        "colleague": colleague,
        "vtuber_mem": vtuber_mem,
        "sub_mem": sub_mem,
        "inbox": inbox,
        "trigger_calls": trigger_calls,
    }


# ─────────────────────────────────────────────────────────────────
# _record_dm_on_sender_stm — pure helper
# ─────────────────────────────────────────────────────────────────


def test_record_helper_writes_assistant_dm(patched_world) -> None:
    _record_dm_on_sender_stm(
        session_id="vtuber-1",
        content="find something fun",
        target_label="Sub-Worker",
        channel="internal",
    )
    assert patched_world["vtuber_mem"].messages == [
        ("assistant_dm", "[DM to Sub-Worker (internal)]: find something fun"),
    ]


def test_record_helper_noop_when_session_missing(patched_world) -> None:
    _record_dm_on_sender_stm(
        session_id="unknown",
        content="x",
        target_label="Sub-Worker",
        channel="internal",
    )
    # No agent with that id → no record on any known agent
    assert patched_world["vtuber_mem"].messages == []
    assert patched_world["sub_mem"].messages == []


def test_record_helper_noop_when_no_memory_manager(
    patched_world, monkeypatch
) -> None:
    """Early-session or stubbed agents may not have a memory manager
    yet — the helper must quietly skip, never crash."""
    patched_world["vtuber"]._memory_manager = None
    _record_dm_on_sender_stm(
        session_id="vtuber-1",
        content="x",
        target_label="Sub-Worker",
        channel="internal",
    )
    # No crash; nothing written anywhere else
    assert patched_world["sub_mem"].messages == []


def test_record_helper_swallows_exception(patched_world) -> None:
    patched_world["vtuber"]._memory_manager = _ExplodingMemoryManager()
    # Must not raise
    _record_dm_on_sender_stm(
        session_id="vtuber-1",
        content="boom",
        target_label="Sub-Worker",
        channel="internal",
    )


def test_record_helper_caps_body_length(patched_world) -> None:
    huge = "x" * 20_000
    _record_dm_on_sender_stm(
        session_id="vtuber-1",
        content=huge,
        target_label="Sub-Worker",
        channel="internal",
    )
    recorded = patched_world["vtuber_mem"].messages[0][1]
    assert len(recorded) <= 10_000


# ─────────────────────────────────────────────────────────────────
# SendDirectMessageInternalTool.run
# ─────────────────────────────────────────────────────────────────


def test_internal_tool_records_outgoing_dm(patched_world) -> None:
    tool = SendDirectMessageInternalTool()
    out = tool.run(session_id="vtuber-1", content="find something fun")

    # Inbox write happened + recipient trigger fired
    assert len(patched_world["inbox"].delivered) == 1
    assert len(patched_world["trigger_calls"]) == 1

    # Sender STM now carries the outgoing DM as assistant_dm
    msgs = patched_world["vtuber_mem"].messages
    assert msgs == [
        ("assistant_dm", "[DM to Sub-Worker (internal)]: find something fun"),
    ]

    # Recipient STM untouched by this tool (recipient records its own
    # side via _trigger_dm_response → classifier on the other end)
    assert patched_world["sub_mem"].messages == []

    # Return JSON is unchanged
    assert '"success": true' in out


def test_internal_tool_no_record_when_no_counterpart(patched_world) -> None:
    """If the caller has no linked counterpart the tool short-circuits
    with an error and must not write anything to STM."""
    patched_world["vtuber"]._linked_session_id = ""
    tool = SendDirectMessageInternalTool()
    out = tool.run(session_id="vtuber-1", content="hi")

    assert '"error"' in out
    assert patched_world["vtuber_mem"].messages == []
    assert patched_world["inbox"].delivered == []


def test_internal_tool_empty_content_rejected(patched_world) -> None:
    tool = SendDirectMessageInternalTool()
    out = tool.run(session_id="vtuber-1", content="   ")
    assert '"error"' in out
    assert patched_world["vtuber_mem"].messages == []


# ─────────────────────────────────────────────────────────────────
# SendDirectMessageExternalTool.run
# ─────────────────────────────────────────────────────────────────


def test_external_tool_records_outgoing_dm(patched_world) -> None:
    tool = SendDirectMessageExternalTool()
    out = tool.run(
        target_session_id="coll-1",
        content="quick question",
        sender_session_id="vtuber-1",
        sender_name="testsa",
    )

    assert len(patched_world["inbox"].delivered) == 1
    msgs = patched_world["vtuber_mem"].messages
    assert msgs == [
        ("assistant_dm", "[DM to Colleague (external)]: quick question"),
    ]
    assert '"success": true' in out


def test_external_tool_no_sender_id_skips_record(patched_world) -> None:
    """Tool kept working for ad-hoc calls without a sender id; in that
    case there's no session to write to, and the helper must not try
    a blind lookup."""
    tool = SendDirectMessageExternalTool()
    tool.run(
        target_session_id="coll-1",
        content="hi",
        sender_session_id="",
        sender_name="",
    )
    # No STM mutation on any known agent
    assert patched_world["vtuber_mem"].messages == []
    assert patched_world["sub_mem"].messages == []
    assert patched_world["colleague"]._memory_manager.messages == []


def test_external_tool_unknown_target_no_record(patched_world) -> None:
    tool = SendDirectMessageExternalTool()
    out = tool.run(
        target_session_id="ghost",
        content="hi",
        sender_session_id="vtuber-1",
        sender_name="testsa",
    )
    assert '"error"' in out
    assert patched_world["vtuber_mem"].messages == []
    assert patched_world["inbox"].delivered == []
