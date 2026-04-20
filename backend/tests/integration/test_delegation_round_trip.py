"""Integration smoke: tool calls actually execute end-to-end.

Why this exists (per `plan/01_tool_execution_fix.md` §PR #3):
unit tests can verify the *manifest declares* Stage 10 (see
``test_default_manifest.py``). They cannot catch the class of
bug where Stage 10 is declared but, for some reason, does not
actually dispatch ``state.pending_tool_calls`` to the tool
registry — e.g. if a future refactor moves executor selection
to runtime and the manifest's ``"executor": "sequential"``
stops resolving.

This test builds a real ``Pipeline`` from the canonical
``build_default_manifest("worker_adaptive")`` output, registers
one fake tool into its tool registry, primes a pipeline state
with a pending call for that tool, runs Stage 10, and asserts
the fake tool actually executed. If this passes, we have proof
that the manifest → pipeline → tool-stage wiring is end-to-end
functional, which is exactly the invariant the PR #1 fix
restores.

The full VTuber ↔ Sub-Worker delegation round-trip (mocked LLM,
two AgentSession instances, ``send_direct_message_external``) is
deliberately out of scope — it requires stubbing the Anthropic
client and bootstrapping the full ``AgentSessionManager``,
whose infrastructure (SessionStore, EnvironmentService, etc.)
is too heavy for a unit-level integration test. PR #1's fix is
covered by the narrower Stage-10-executes-pending-calls check
below; the wider round-trip is verified by the manual smoke in
``plan/01_tool_execution_fix.md`` Phase 1 verification.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from geny_executor.tools.base import Tool, ToolContext, ToolResult


class _RecordingTool(Tool):
    """Minimal Tool implementation that records every execute() call."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "recording_tool"

    @property
    def description(self) -> str:
        return "Records invocations without performing side effects."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"payload": {"type": "string"}},
            "required": [],
        }

    async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls.append(dict(input))
        return ToolResult(content=f"recorded: {input.get('payload', '')}")


@pytest.mark.asyncio
async def test_tool_stage_executes_pending_calls_for_worker_manifest() -> None:
    """Stage 10, as wired by the worker_adaptive manifest, actually
    dispatches a pending tool call to a registered tool.

    This is the *functional* proof that PR #1's manifest change
    restored tool execution: the Stage 10 the manifest emits is
    not just present, it runs.
    """
    from geny_executor.core.pipeline import Pipeline
    from geny_executor.core.state import PipelineState

    from service.langgraph.default_manifest import build_default_manifest

    manifest = build_default_manifest(
        "worker_adaptive", model="claude-haiku-4-5-20251001"
    )
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)

    tool_stage = next(s for s in pipeline.stages if s.order == 10)

    recording = _RecordingTool()
    tool_stage.registry.register(recording)

    state = PipelineState(session_id="test-session")
    state.pending_tool_calls = [
        {
            "tool_name": "recording_tool",
            "tool_input": {"payload": "hello"},
            "tool_use_id": "call_1",
        }
    ]

    await tool_stage.execute(input=None, state=state)

    assert recording.calls == [{"payload": "hello"}], (
        "Stage 10 did not dispatch the pending tool call — "
        "manifest stages are wired but tool execution is broken."
    )
    assert state.pending_tool_calls == [], (
        "Stage 10 should clear pending_tool_calls after execution."
    )
    assert state.tool_results, "Stage 10 should populate tool_results."


@pytest.mark.asyncio
async def test_tool_stage_bypasses_when_no_pending_calls() -> None:
    """Negative control: with no tool calls pending, Stage 10 is a
    no-op. Confirms `should_bypass` still works as the fast path
    for turns that don't request tools."""
    from geny_executor.core.pipeline import Pipeline
    from geny_executor.core.state import PipelineState

    from service.langgraph.default_manifest import build_default_manifest

    pipeline = Pipeline.from_manifest(
        build_default_manifest("worker_adaptive", model="claude-haiku-4-5-20251001"),
        api_key="sk-test",
        strict=False,
    )
    tool_stage = next(s for s in pipeline.stages if s.order == 10)

    state = PipelineState(session_id="test-session")
    assert tool_stage.should_bypass(state) is True
