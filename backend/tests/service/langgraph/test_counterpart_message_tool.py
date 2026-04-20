"""Regression tests for `GenyMessageCounterpartTool`.

Cycle 20260420_7 / PR-1: the VTuber↔Sub-Worker DM path used to require
the LLM to copy a UUID from its system prompt into
``geny_send_direct_message``'s ``target_session_id`` argument; when the
LLM treated the "## Sub-Worker Agent" header as a literal session name
instead, it created a new session and routed the DM there. The
counterpart tool drops ``target_session_id`` from the LLM-visible
schema entirely — the runtime resolves the linked agent from
``AgentSession._linked_session_id``.

See ``dev_docs/20260420_7/analysis/01_linked_counterpart_discovery.md``
and ``plan/01_counterpart_message_tool.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest

from service.langgraph.tool_bridge import _GenyToolAdapter
from tools.built_in import geny_tools


# ─────────────────────────────────────────────────────────────────
# Fixtures — fakes for the manager/inbox/trigger singletons
# ─────────────────────────────────────────────────────────────────


@dataclass
class _SimpleContext:
    session_id: str


class _FakeAgent:
    def __init__(self, session_id: str, name: str, linked_id: Optional[str]):
        self.session_id = session_id
        self.session_name = name
        self._linked_session_id = linked_id


class _FakeManager:
    """Lookup table keyed by session_id; resolve_session falls back to name."""

    def __init__(self, agents: Dict[str, _FakeAgent]):
        self._by_id = agents
        self._by_name = {a.session_name: a for a in agents.values()}

    def get_agent(self, sid: str) -> Optional[_FakeAgent]:
        return self._by_id.get(sid)

    def resolve_session(self, name_or_id: str) -> Optional[_FakeAgent]:
        return self._by_id.get(name_or_id) or self._by_name.get(name_or_id)


class _FakeInbox:
    def __init__(self) -> None:
        self.delivered: list[Dict[str, Any]] = []

    def deliver(self, **kwargs: Any) -> Dict[str, Any]:
        msg = {
            "id": f"msg-{len(self.delivered) + 1}",
            "timestamp": "2026-04-21T15:30:00Z",
            **kwargs,
        }
        self.delivered.append(msg)
        return msg


@pytest.fixture
def patched_world(monkeypatch):
    """Wire fakes for every singleton the counterpart tool touches."""

    inbox = _FakeInbox()
    trigger_calls: list[Dict[str, Any]] = []

    def _install(agents: Dict[str, _FakeAgent]) -> _FakeInbox:
        manager = _FakeManager(agents)

        def _resolve(name_or_id: str):
            agent = manager.resolve_session(name_or_id)
            if agent is None:
                return (None, None)
            return (agent, agent.session_id)

        monkeypatch.setattr(geny_tools, "_get_agent_manager", lambda: manager)
        monkeypatch.setattr(geny_tools, "_get_inbox_manager", lambda: inbox)
        monkeypatch.setattr(geny_tools, "_resolve_session", _resolve)
        monkeypatch.setattr(
            geny_tools,
            "_trigger_dm_response",
            lambda **kwargs: trigger_calls.append(kwargs),
        )
        return inbox

    return _install, inbox, trigger_calls


# ─────────────────────────────────────────────────────────────────
# LLM-visible schema — target is NOT exposed
# ─────────────────────────────────────────────────────────────────


def test_schema_does_not_expose_target_session_id() -> None:
    tool = geny_tools.GenyMessageCounterpartTool()
    schema = tool.parameters
    props = schema.get("properties", {})
    assert "target_session_id" not in props, (
        "counterpart tool must not expose target_session_id; runtime "
        "resolves the target from _linked_session_id"
    )
    assert "content" in props


def test_adapter_probe_injects_session_id() -> None:
    """`session_id` is a declared run() parameter, so the Cycle-6 probe
    recognises it and the adapter injects ToolContext.session_id."""
    tool = geny_tools.GenyMessageCounterpartTool()
    adapter = _GenyToolAdapter(tool)
    assert adapter._accepts_session_id is True


# ─────────────────────────────────────────────────────────────────
# Happy paths — symmetric delivery for both directions
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vtuber_sends_to_linked_sub_worker(patched_world) -> None:
    install, inbox, triggers = patched_world
    install({
        "vtuber-1": _FakeAgent("vtuber-1", "VTuber", linked_id="sub-1"),
        "sub-1": _FakeAgent("sub-1", "SubWorker", linked_id="vtuber-1"),
    })

    tool = geny_tools.GenyMessageCounterpartTool()
    adapter = _GenyToolAdapter(tool)

    result = await adapter.execute(
        {"content": "please create test.txt"},
        _SimpleContext("vtuber-1"),
    )

    assert result.is_error is False, result.content
    payload = json.loads(result.content)
    assert payload["success"] is True
    assert payload["delivered_to"] == "sub-1"
    assert payload["delivered_to_name"] == "SubWorker"
    assert len(inbox.delivered) == 1
    assert len(triggers) == 1
    assert triggers[0]["target_session_id"] == "sub-1"
    assert triggers[0]["sender_session_id"] == "vtuber-1"


@pytest.mark.asyncio
async def test_sub_worker_replies_to_linked_vtuber(patched_world) -> None:
    """Symmetry: same tool, opposite direction. Sub→VTuber must work
    identically with zero logic change."""
    install, inbox, triggers = patched_world
    install({
        "vtuber-1": _FakeAgent("vtuber-1", "VTuber", linked_id="sub-1"),
        "sub-1": _FakeAgent("sub-1", "SubWorker", linked_id="vtuber-1"),
    })

    tool = geny_tools.GenyMessageCounterpartTool()
    adapter = _GenyToolAdapter(tool)

    result = await adapter.execute(
        {"content": "done"},
        _SimpleContext("sub-1"),
    )

    assert result.is_error is False, result.content
    payload = json.loads(result.content)
    assert payload["delivered_to"] == "vtuber-1"
    assert triggers[0]["sender_session_id"] == "sub-1"


# ─────────────────────────────────────────────────────────────────
# Safe failures — no spurious session creation, no side-effects
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_linked_counterpart_returns_error(patched_world) -> None:
    install, inbox, triggers = patched_world
    install({
        "solo-1": _FakeAgent("solo-1", "Solo", linked_id=None),
    })

    tool = geny_tools.GenyMessageCounterpartTool()
    adapter = _GenyToolAdapter(tool)

    result = await adapter.execute(
        {"content": "hi"},
        _SimpleContext("solo-1"),
    )

    payload = json.loads(result.content)
    assert "error" in payload
    assert "no linked counterpart" in payload["error"]
    assert inbox.delivered == []
    assert triggers == []


@pytest.mark.asyncio
async def test_linked_counterpart_deleted_returns_error(patched_world) -> None:
    """Linked id points at a session that no longer exists — fail loud,
    don't silently reroute or create."""
    install, inbox, triggers = patched_world
    install({
        "vtuber-1": _FakeAgent("vtuber-1", "VTuber", linked_id="ghost-sub"),
    })

    tool = geny_tools.GenyMessageCounterpartTool()
    adapter = _GenyToolAdapter(tool)

    result = await adapter.execute(
        {"content": "hi"},
        _SimpleContext("vtuber-1"),
    )

    payload = json.loads(result.content)
    assert "error" in payload
    assert "no longer exists" in payload["error"]
    assert inbox.delivered == []
    assert triggers == []


@pytest.mark.asyncio
async def test_empty_content_returns_error(patched_world) -> None:
    install, inbox, triggers = patched_world
    install({
        "vtuber-1": _FakeAgent("vtuber-1", "VTuber", linked_id="sub-1"),
        "sub-1": _FakeAgent("sub-1", "SubWorker", linked_id="vtuber-1"),
    })

    tool = geny_tools.GenyMessageCounterpartTool()
    adapter = _GenyToolAdapter(tool)

    result = await adapter.execute(
        {"content": "   "},
        _SimpleContext("vtuber-1"),
    )

    payload = json.loads(result.content)
    assert "error" in payload
    assert inbox.delivered == []


@pytest.mark.asyncio
async def test_unknown_caller_returns_error(patched_world) -> None:
    install, inbox, triggers = patched_world
    install({})  # nothing registered

    tool = geny_tools.GenyMessageCounterpartTool()
    adapter = _GenyToolAdapter(tool)

    result = await adapter.execute(
        {"content": "hi"},
        _SimpleContext("ghost-caller"),
    )

    payload = json.loads(result.content)
    assert "error" in payload
    assert "caller session not found" in payload["error"]
