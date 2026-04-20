"""Integration: a VTuber pipeline can actually dispatch send_direct_message_internal.

The 20260420_5 cycle root-caused LOG2 (``Tool error [...] Executed with 1 errors``)
to the following chain:

1. VTuber env was hardcoded to three web tools (``web_search``,
   ``news_search``, ``web_fetch``) — the DM tool was never in
   ``manifest.tools.external``.
2. Even if the VTuber *tried* to call the DM tool, the pipeline's
   tool registry had no entry for it, so the router short-circuited
   with ``unknown_tool``.

PR #2 fixed (1) by giving the VTuber every platform tool plus the
three web tools. PR #1 (and the v0.26.1 / v0.26.2 executor bumps)
fixed the registration/rebind invariant.

Cycle 20260420_8 / plan/01 split the DM tool into two variants
(``send_direct_message_internal`` for the bound counterpart,
``send_direct_message_external`` for addressed DMs) and added
``send_direct_message_external`` + every ``session_*`` primitive to
the VTuber deny list. The VTuber's *only* inter-agent outbound
channel is now ``send_direct_message_internal``, so that is the
registration / dispatch contract this integration test enforces.

Similar in spirit to the existing
``test_delegation_round_trip.py::test_tool_stage_executes_pending_calls_for_worker_manifest``
— different role (VTuber), and focused on the DM tool that was
specifically broken in LOG2.

The full live round-trip (VTuber session → API → tool stage → DM into
the Sub-Worker inbox) requires a live Anthropic key and the full
``AgentSessionManager`` bootstrap, which this layer of tests
intentionally avoids. Manual smoke is the verification for that layer;
see ``dev_docs/20260420_8/plan/01_tool_surface_redesign.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from geny_executor.tools.base import Tool, ToolContext, ToolResult


class _RecordingInternalDMTool(Tool):
    """Stub ``send_direct_message_internal`` that records every call.

    The real tool resolves the counterpart via
    ``AgentSession._linked_session_id`` and takes only ``content`` as
    input — no ``target_session_id`` is exposed to the LLM. Matching
    that shape here keeps the dispatch contract honest."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "send_direct_message_internal"

    @property
    def description(self) -> str:
        return "Recording stub for send_direct_message_internal."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
            },
            "required": ["content"],
        }

    async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls.append(dict(input))
        return ToolResult(content="dm recorded")


class _DMProvider:
    """Supplies only ``send_direct_message_internal`` via the
    AdhocToolProvider Protocol — the pipeline will skip every other
    manifest name with a warning, which is exactly the production
    behaviour if a deployment chose to not wire a given tool."""

    def __init__(self, tool: _RecordingInternalDMTool) -> None:
        self._tool = tool

    def list_names(self) -> List[str]:
        return [self._tool.name]

    def get(self, name: str) -> Optional[_RecordingInternalDMTool]:
        return self._tool if name == self._tool.name else None


class _FakeToolLoader:
    """Minimal ToolLoader stand-in for create_vtuber_env."""

    def __init__(self, source_map: Dict[str, str]) -> None:
        self._source = source_map

    def get_tool_source(self, name: str) -> Optional[str]:
        return self._source.get(name)


@pytest.mark.asyncio
async def test_vtuber_pipeline_dispatches_internal_dm_call() -> None:
    """VTuber pipeline, built through the real manifest + Pipeline
    path, routes a ``send_direct_message_internal`` call to the
    registered tool.

    Functional proof that cycle 20260420_8 / plan/01 composes into a
    working end-to-end path for the VTuber persona: the tool is *on
    the manifest* (cycle-7-1 gap closed), the pipeline registers it,
    and Stage 10 dispatches the call to it."""
    from geny_executor.core.pipeline import Pipeline
    from geny_executor.core.state import PipelineState

    from service.environment.templates import create_vtuber_env

    all_names = [
        "send_direct_message_external",
        "send_direct_message_internal",
        "read_inbox",
        "session_list",
        "memory_read",
        "memory_write",
        "knowledge_search",
        "web_search",
        "news_search",
        "web_fetch",
        "browser_navigate",
    ]
    platform_stems = {
        name: "geny_tools" if not name.startswith("memory_") and not name.startswith("knowledge_") else (
            "memory_tools" if name.startswith("memory_") else "knowledge_tools"
        )
        for name in (
            "send_direct_message_external",
            "send_direct_message_internal",
            "read_inbox",
            "session_list",
            "memory_read",
            "memory_write",
            "knowledge_search",
        )
    }
    loader = _FakeToolLoader(platform_stems)
    manifest = create_vtuber_env(all_tool_names=all_names, tool_loader=loader)

    recording = _RecordingInternalDMTool()
    provider = _DMProvider(recording)

    pipeline = Pipeline.from_manifest(
        manifest,
        api_key="sk-test",
        strict=False,
        adhoc_providers=[provider],
    )

    registered = pipeline.tool_registry.list_names()
    assert "send_direct_message_internal" in registered, (
        "VTuber pipeline should have send_direct_message_internal registered. "
        f"Got: {registered}"
    )
    assert "send_direct_message_external" not in registered, (
        "VTuber pipeline leaked send_direct_message_external — deny list "
        f"regressed. Got: {registered}"
    )

    tool_stage = next(s for s in pipeline.stages if getattr(s, "order", None) == 10)

    state = PipelineState(session_id="vtuber-session")
    state.pending_tool_calls = [
        {
            "tool_name": "send_direct_message_internal",
            "tool_input": {"content": "please create test.txt"},
            "tool_use_id": "call_dm_1",
        }
    ]

    await tool_stage.execute(input=None, state=state)

    assert recording.calls == [{"content": "please create test.txt"}], (
        "Stage 10 did not dispatch send_direct_message_internal to the "
        "registered tool. This is the exact failure path LOG2 reported — "
        "the manifest/registration chain is broken."
    )
    assert state.pending_tool_calls == [], (
        "Stage 10 should clear pending_tool_calls once dispatched."
    )
    assert state.tool_results, (
        "Stage 10 should populate tool_results with the DM tool's output."
    )


@pytest.mark.asyncio
async def test_vtuber_pipeline_skips_browser_dispatch() -> None:
    """Negative control: even if a VTuber session somehow emitted a
    pending ``browser_navigate`` call, the pipeline has no such tool
    registered (PR #2 excluded browser tools from the VTuber roster)
    so the router resolves to ``unknown_tool`` and records an error.

    This guards against a regression where ``browser_*`` leaks back
    into the VTuber roster via a fallback path."""
    from geny_executor.core.pipeline import Pipeline
    from geny_executor.core.state import PipelineState

    from service.environment.templates import create_vtuber_env

    loader = _FakeToolLoader(
        {"send_direct_message_internal": "geny_tools"}
    )
    manifest = create_vtuber_env(
        all_tool_names=[
            "send_direct_message_internal",
            "web_search",
            "browser_navigate",
        ],
        tool_loader=loader,
    )
    pipeline = Pipeline.from_manifest(
        manifest,
        api_key="sk-test",
        strict=False,
        adhoc_providers=[_DMProvider(_RecordingInternalDMTool())],
    )

    assert "browser_navigate" not in pipeline.tool_registry.list_names(), (
        "PR #2 filter missed browser_navigate — VTuber roster is leaking "
        "browser tools again."
    )

    tool_stage = next(s for s in pipeline.stages if getattr(s, "order", None) == 10)
    state = PipelineState(session_id="vtuber-session")
    state.pending_tool_calls = [
        {
            "tool_name": "browser_navigate",
            "tool_input": {"url": "https://example.com"},
            "tool_use_id": "call_nav_1",
        }
    ]

    await tool_stage.execute(input=None, state=state)

    assert state.tool_results, "Stage 10 should still record a result entry"
    result_entry = state.tool_results[0]
    is_error = (
        result_entry.get("is_error")
        or result_entry.get("error")
        or "unknown" in str(result_entry.get("content", "")).lower()
    )
    assert is_error, (
        f"browser_navigate should have failed resolution on a VTuber pipeline "
        f"(tool not registered); got result: {result_entry}"
    )
