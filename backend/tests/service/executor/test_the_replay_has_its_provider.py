"""The turn replay needs Stage 2 to hold the memory provider — and it didn't.

``_init_memory_provider`` attaches the provider to the pipeline's stages,
but it runs before the pipeline exists and returned early: in production the
"attached directly" line never appeared. Stage 18 kept recording (Geny's
strategy carries its own reference), so nothing looked wrong — while the
replay, which reads Stage 2's provider, silently did nothing and every turn
still started from an empty history. The probe that caught it: a number that
lived only in a tool result was answered from mental arithmetic, wrongly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

pytest.importorskip("pydantic")

from geny_executor.core.config import PipelineConfig  # noqa: E402
from geny_executor.core.pipeline import Pipeline  # noqa: E402
from geny_executor.core.state import PipelineState  # noqa: E402
from geny_executor.memory.provider import Turn  # noqa: E402
from geny_executor.memory.providers.ephemeral import EphemeralMemoryProvider  # noqa: E402
from geny_executor.stages.s02_context.artifact.default.stage import ContextStage  # noqa: E402

from service.executor.agent_session import AgentSession  # noqa: E402


def _session_with(provider, pipeline) -> AgentSession:
    s = AgentSession.__new__(AgentSession)
    s._session_id = "replay"
    s._memory_provider = provider
    s._pipeline = pipeline
    return s


async def _provider_with_a_tool_turn() -> EphemeralMemoryProvider:
    provider = EphemeralMemoryProvider()
    await provider.initialize()
    now = datetime.now(timezone.utc)
    for role, content in (
        ("user", "run it"),
        ("assistant", [{"type": "tool_use", "id": "t1", "name": "Bash",
                        "input": {"command": "echo $((7919*13+4))"}}]),
        ("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "102951"}]),
        ("assistant", [{"type": "text", "text": "done"}]),
    ):
        await provider.stm().append(Turn(role=role, content=content, timestamp=now))
    return provider


def test_after_the_attach_a_fresh_turn_sees_the_tool_result() -> None:
    async def go():
        provider = await _provider_with_a_tool_turn()
        pipeline = Pipeline(PipelineConfig(name="t"))
        pipeline.register_stage(ContextStage())
        _session_with(provider, pipeline)._attach_provider_to_pipeline_stages()

        state = PipelineState(session_id="replay")
        state.messages = [{"role": "user", "content": "what was the number?"}]
        await pipeline.get_stage(2).execute(None, state)
        return state

    state = asyncio.run(go())
    results = [
        b for m in state.messages if isinstance(m.get("content"), list)
        for b in m["content"] if b.get("type") == "tool_result"
    ]
    assert results and "102951" in str(results[0]["content"])
    assert state.messages[-1]["content"] == "what was the number?"


def test_the_build_attaches_after_the_pipeline_exists() -> None:
    """The call has to sit where ``self._pipeline`` is already set — the
    early one returns without a word when it is not."""
    import inspect

    source = inspect.getsource(AgentSession)
    adopted = source.index("Pipeline adopted + runtime attached")
    attach = source.rfind("self._attach_provider_to_pipeline_stages()", 0, adopted)
    overlay = source.rfind("apply_overlay(self._pipeline, overlay)", 0, adopted)
    assert attach != -1 and attach < overlay, (
        "the post-adoption attach is missing, or runs after the owner's overlay"
    )
