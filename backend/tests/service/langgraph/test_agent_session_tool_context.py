"""AgentSession × mutation-buffer ContextVar bridge (cycle 20260421_9 PR-X3-6).

PR-X3-6 publishes the current-turn ``MutationBuffer`` to game tools
through a ``ContextVar`` bound while ``pipeline.run_stream`` is
iterating. This module pins the contract:

1. When hydrate installs a buffer, the ContextVar reads back the
   *same* buffer object during the pipeline loop (so tools can push
   mutations that persist picks up).
2. When hydrate fails (no buffer in ``state.shared``), the ContextVar
   stays ``None`` and tools degrade to narrated-only mode.
3. After the pipeline loop ends — normal completion OR via an
   exception raised inside a fake stage — the ContextVar is reset to
   ``None`` so no binding leaks into subsequent work on the same task.
4. The stream path (``_astream_pipeline``) mirrors the invoke path.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from service.langgraph.agent_session import AgentSession
from service.state import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    InMemoryCreatureStateProvider,
    current_mutation_buffer,
)


class _Event:
    def __init__(self, event_type: str, data: Dict[str, Any]) -> None:
        self.type = event_type
        self.data = data


def _success_events(output: str = "ok") -> List[_Event]:
    return [
        _Event("text.delta", {"text": output}),
        _Event(
            "pipeline.complete",
            {"result": output, "total_cost_usd": 0.0, "iterations": 1},
        ),
    ]


class _ContextVarProbePipeline:
    """Fake pipeline that records the ContextVar state *during* streaming.

    The check happens at the point the pipeline would normally invoke
    stages — this is precisely when real game tools read the
    ContextVar, so probing here captures the observable-to-tools value.
    """

    def __init__(self, events: List[_Event]) -> None:
        self._events = events
        self.seen_buffer: Any = "NOT_PROBED"  # sentinel distinct from None

    async def run_stream(self, input_text: str, state: Any):
        self.seen_buffer = current_mutation_buffer()
        for evt in self._events:
            yield evt


class _RaisingPipeline:
    async def run_stream(self, input_text: str, state: Any):
        yield _Event("text.delta", {"text": "partial"})
        raise RuntimeError("stage exploded")


class _FakeMemoryManager:
    def __init__(self) -> None:
        self.messages: list = []
        self.executions: list = []

    def record_message(self, role: str, content: str) -> None:
        self.messages.append((role, content))

    async def record_execution(self, **kwargs: Any) -> None:
        self.executions.append(kwargs)


def _make_session(pipeline: Any, *, state_provider=None, character_id=None):
    session = AgentSession(
        session_id="s-ctxvar",
        session_name="T",
        state_provider=state_provider,
        character_id=character_id,
    )
    session._memory_manager = _FakeMemoryManager()  # type: ignore[assignment]
    session._pipeline = pipeline  # type: ignore[assignment]
    session._execution_count = 0
    return session


@pytest.mark.asyncio
async def test_classic_mode_contextvar_stays_none() -> None:
    """No provider → no bind; tools see ``None``."""
    pipe = _ContextVarProbePipeline(_success_events())
    session = _make_session(pipe)  # state_provider=None

    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    assert pipe.seen_buffer is None
    # And nothing leaked after.
    assert current_mutation_buffer() is None


@pytest.mark.asyncio
async def test_buffer_visible_during_pipeline_loop() -> None:
    """With a wired provider, the ContextVar returns the same buffer
    instance the pipeline sees in ``state.shared[MUTATION_BUFFER_KEY]``
    — so a tool calling ``current_mutation_buffer()`` and a stage
    reading ``state.shared`` touch identical state."""
    prov = InMemoryCreatureStateProvider()

    class _Probe(_ContextVarProbePipeline):
        async def run_stream(self, input_text, state):
            # Capture both views so we can assert equality.
            self.seen_buffer = current_mutation_buffer()
            self.state_buffer = state.shared[MUTATION_BUFFER_KEY]
            for evt in self._events:
                yield evt

    pipe = _Probe(_success_events())
    session = _make_session(pipe, state_provider=prov, character_id="c1")

    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    assert pipe.seen_buffer is pipe.state_buffer
    assert pipe.seen_buffer is not None


@pytest.mark.asyncio
async def test_contextvar_resets_after_normal_completion() -> None:
    prov = InMemoryCreatureStateProvider()
    pipe = _ContextVarProbePipeline(_success_events())
    session = _make_session(pipe, state_provider=prov, character_id="c1")

    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    # Binding must not leak into subsequent work on this task.
    assert current_mutation_buffer() is None


@pytest.mark.asyncio
async def test_contextvar_resets_on_pipeline_exception() -> None:
    """A stage raising inside ``run_stream`` must not leave the bind
    hanging. ``_pipeline_events_scoped`` wraps the iteration in a
    ``try/finally`` so the reset fires regardless."""
    prov = InMemoryCreatureStateProvider()
    session = _make_session(
        _RaisingPipeline(), state_provider=prov, character_id="c1",
    )

    with pytest.raises(RuntimeError, match="stage exploded"):
        await session._invoke_pipeline(
            "hi", start_time=0.0, session_logger=None,
        )

    assert current_mutation_buffer() is None


@pytest.mark.asyncio
async def test_astream_binds_and_resets_symmetrically() -> None:
    """``_astream_pipeline`` must go through the same scoped helper so
    the stream path gets the same bind semantics as invoke."""
    prov = InMemoryCreatureStateProvider()
    pipe = _ContextVarProbePipeline(_success_events())
    session = _make_session(pipe, state_provider=prov, character_id="c1")

    async for _ in session._astream_pipeline(
        "hi", start_time=0.0, session_logger=None,
    ):
        pass

    assert pipe.seen_buffer is not None
    assert current_mutation_buffer() is None


@pytest.mark.asyncio
async def test_hydrate_failure_leaves_contextvar_none() -> None:
    """If hydrate raises, no buffer is installed on ``state.shared`` —
    the bind must skip so tools see ``None`` and degrade to
    narrated-only mode rather than pushing onto a phantom buffer."""

    class _ExplodingHydrateProvider:
        async def tick(self, *a, **k):
            return None

        async def list_characters(self, *a, **k):
            return []

        async def load(self, *a, **k):
            raise RuntimeError("hydrate exploded")

        async def apply(self, *a, **k):
            return None

        async def set_absolute(self, *a, **k):
            return None

    pipe = _ContextVarProbePipeline(_success_events())
    session = _make_session(
        pipe, state_provider=_ExplodingHydrateProvider(), character_id="c1",
    )

    # Hydrate failure must not raise — AgentSession swallows it.
    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    assert pipe.seen_buffer is None
    assert current_mutation_buffer() is None
