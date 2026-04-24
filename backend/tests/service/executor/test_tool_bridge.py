"""Regression tests for `_GenyToolAdapter`'s signature probe + arg map.

Cycle 20260420_6: fixes the probe misdirection that was silently
injecting ``session_id`` into every `BaseTool` subclass — even those
whose concrete ``run()`` didn't accept it — because the probe inspected
`arun`'s inherited `**kwargs` forwarder instead of the authoritative
`run` override.

See ``dev_docs/20260420_6/analysis/01_probe_misdirection.md``.

The matrix here covers every tool shape the adapter has to handle:

- BaseTool subclass, ``run`` without ``session_id`` → no inject
- BaseTool subclass, ``run`` with ``session_id`` → inject
- BaseTool subclass, ``run`` with ``**kwargs`` → inject (safe)
- ``@tool``-decorated function without ``session_id`` → no inject
- ``@tool``-decorated function with ``session_id`` → inject
- Duck-typed object with only ``arun`` → probe ``arun`` (fallback)
- Unreadable signature (partial / C-callable) → False (safe default)

Plus: ``execute`` must not mutate the caller's input dict, and a
real-world smoke against ``SendDirectMessageExternalTool`` (the tool that
actually broke in production) with ``_resolve_session`` monkey-patched
so no live SessionStore is required.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from service.executor.tool_bridge import _GenyToolAdapter
from tools.base import BaseTool, tool as tool_decorator


class _BaseToolNoSessionId(BaseTool):
    """Concrete ``run`` without ``session_id`` — the DM tool shape."""

    name = "no_session_tool"
    description = "does work without needing session_id"

    def run(self, target: str, content: str) -> str:
        return f"no-session:{target}:{content}"


class _BaseToolWithSessionId(BaseTool):
    """Concrete ``run`` declaring ``session_id`` — memory tool shape."""

    name = "needs_session_tool"
    description = "reads per-session state"

    def run(self, session_id: str, key: str) -> str:
        return f"with-session:{session_id}:{key}"


class _BaseToolVarKeyword(BaseTool):
    """Concrete ``run`` with ``**kwargs`` — catches anything."""

    name = "varkw_tool"
    description = "accepts arbitrary kwargs"

    def run(self, **kwargs: Any) -> str:
        return f"varkw:{sorted(kwargs.items())}"


@tool_decorator(name="fn_no_session", description="function without session_id")
def _fn_no_session(target: str, content: str) -> str:
    return f"fn-no-session:{target}:{content}"


@tool_decorator(name="fn_with_session", description="function with session_id")
def _fn_with_session(session_id: str, key: str) -> str:
    return f"fn-with-session:{session_id}:{key}"


class _DuckTypedAsyncOnly:
    """No ``run``, no ``func`` — only ``arun`` with explicit session_id.
    Exercises the fallback probe branch."""

    name = "duck_async_only"
    description = "async-only duck-typed tool"
    parameters = {"type": "object", "properties": {"session_id": {"type": "string"}}}

    async def arun(self, session_id: str = "") -> str:
        return f"duck:{session_id}"


class _UnreadableSignature:
    """Tool whose `run`/`arun` have no introspectable signature.

    Simulated by pointing the methods at a C-implemented callable
    whose ``inspect.signature`` raises ``ValueError``. We want the
    probe to *catch* the raise and return False (safe default), not
    propagate it and blow up adapter construction."""

    name = "unreadable_tool"
    description = "has an uninspectable signature"
    parameters = {"type": "object", "properties": {}}


class _SimpleContext:
    """Minimal stand-in for :class:`geny_executor.tools.base.ToolContext`."""

    def __init__(self, session_id: str = "sess-xyz") -> None:
        self.session_id = session_id


# ─────────────────────────────────────────────────────────────────
# Probe matrix
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "tool_factory, expected",
    [
        (_BaseToolNoSessionId, False),
        (_BaseToolWithSessionId, True),
        (_BaseToolVarKeyword, True),
        (lambda: _fn_no_session, False),
        (lambda: _fn_with_session, True),
        (_DuckTypedAsyncOnly, True),
    ],
)
def test_probe_matches_concrete_signature(tool_factory, expected) -> None:
    """The probe returns True iff the *authoritative* callable (func
    for ToolWrapper, run for BaseTool subclass, arun as fallback)
    accepts session_id — explicit or via **kwargs."""
    tool = tool_factory()
    adapter = _GenyToolAdapter(tool)
    assert adapter._accepts_session_id is expected, (
        f"probe returned {adapter._accepts_session_id} for "
        f"{type(tool).__name__}; expected {expected}"
    )


def test_probe_unreadable_signature_returns_false(monkeypatch) -> None:
    """C-implemented / uninspectable callables must probe False — the
    adapter must never crash on construction, and omitting the
    injection is the safe default."""
    from service.executor import tool_bridge as tb

    def _always_raise(fn):
        raise ValueError("simulated uninspectable callable")

    monkeypatch.setattr(tb.inspect, "signature", _always_raise)

    tool = _UnreadableSignature()
    tool.run = lambda **kwargs: None

    adapter = _GenyToolAdapter(tool)
    assert adapter._accepts_session_id is False


# ─────────────────────────────────────────────────────────────────
# execute() behaviour: injection + input-dict isolation
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_no_session_tool_runs_without_injection() -> None:
    """The DM-shape tool (no session_id in run) must complete without
    ``TypeError`` — the production bug."""
    adapter = _GenyToolAdapter(_BaseToolNoSessionId())
    result = await adapter.execute(
        {"target": "alice", "content": "hi"}, _SimpleContext()
    )
    assert result.is_error is False, result.content
    assert "no-session:alice:hi" in str(result.content)


@pytest.mark.asyncio
async def test_execute_session_tool_receives_injected_id() -> None:
    """Memory/knowledge shape: ``run`` declares session_id, adapter
    fills it in from context."""
    adapter = _GenyToolAdapter(_BaseToolWithSessionId())
    result = await adapter.execute({"key": "notes"}, _SimpleContext("sess-42"))
    assert result.is_error is False
    assert "with-session:sess-42:notes" in str(result.content)


@pytest.mark.asyncio
async def test_execute_session_tool_respects_explicit_input() -> None:
    """If the LLM already supplied session_id in input, adapter must
    not overwrite it — ``setdefault`` semantics, not assignment."""
    adapter = _GenyToolAdapter(_BaseToolWithSessionId())
    result = await adapter.execute(
        {"session_id": "llm-chosen", "key": "notes"}, _SimpleContext("ctx-sess")
    )
    assert "with-session:llm-chosen:notes" in str(result.content)


@pytest.mark.asyncio
async def test_execute_does_not_mutate_caller_input() -> None:
    """The caller's ``input`` dict must be untouched after execute —
    adapters are cached in GenyToolProvider and stages can retry."""
    adapter = _GenyToolAdapter(_BaseToolWithSessionId())
    caller_input: Dict[str, Any] = {"key": "x"}
    snapshot = dict(caller_input)
    await adapter.execute(caller_input, _SimpleContext())
    assert caller_input == snapshot, (
        f"adapter mutated caller's input: before={snapshot}, after={caller_input}"
    )


@pytest.mark.asyncio
async def test_execute_tool_wrapper_without_session_id() -> None:
    """@tool-decorated function whose signature lacks session_id
    must not receive the injection, even when context has one."""
    adapter = _GenyToolAdapter(_fn_no_session)
    result = await adapter.execute(
        {"target": "alice", "content": "hi"}, _SimpleContext()
    )
    assert result.is_error is False, result.content
    assert "fn-no-session:alice:hi" in str(result.content)


@pytest.mark.asyncio
async def test_execute_tool_wrapper_with_session_id() -> None:
    """@tool-decorated function with session_id in signature receives
    the injection from context."""
    adapter = _GenyToolAdapter(_fn_with_session)
    result = await adapter.execute({"key": "notes"}, _SimpleContext("sess-1"))
    assert result.is_error is False
    assert "fn-with-session:sess-1:notes" in str(result.content)


# ─────────────────────────────────────────────────────────────────
# Real-world smoke: SendDirectMessageExternalTool via the adapter
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_direct_message_external_adapter_no_type_error(monkeypatch) -> None:
    """End-to-end smoke on the exact class that failed in production.

    Monkey-patches ``_resolve_session`` / ``_get_inbox_manager`` /
    ``_trigger_dm_response`` so the tool runs without a live
    SessionStore or ChatStore. Asserts the adapter's kwargs pass
    through to ``run`` without raising, which was the LOG error
    that triggered this cycle."""
    from tools.built_in import geny_tools

    class _FakeAgent:
        session_id = "resolved-sid"
        session_name = "SubWorker"

    class _FakeInbox:
        def deliver(self, **kwargs):
            return {"id": "msg-1", "timestamp": "2026-04-21T00:00:00Z"}

    monkeypatch.setattr(
        geny_tools, "_resolve_session", lambda _: (_FakeAgent(), "resolved-sid")
    )
    monkeypatch.setattr(geny_tools, "_get_inbox_manager", lambda: _FakeInbox())
    monkeypatch.setattr(
        geny_tools,
        "_trigger_dm_response",
        lambda **kwargs: None,
    )

    tool = geny_tools.SendDirectMessageExternalTool()
    adapter = _GenyToolAdapter(tool)

    # The production bug: probe returned True, adapter injected
    # session_id, run raised TypeError. Assert the probe now gets it
    # right and the call returns cleanly.
    assert adapter._accepts_session_id is False, (
        "SendDirectMessageExternalTool.run does not declare session_id and "
        "has no **kwargs — probe must return False"
    )

    result = await adapter.execute(
        {"target_session_id": "sub-worker", "content": "안녕"},
        _SimpleContext("vtuber-session"),
    )
    assert result.is_error is False, (
        f"SendDirectMessageExternalTool adapter still errors: {result.content}"
    )
    assert "delivered_to" in str(result.content) or "success" in str(result.content)
