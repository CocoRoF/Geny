"""Contextvar bridge for game tools (cycle 20260421_9 PR-X3-6).

Covers the bind / get / reset helpers that expose the current-turn
``MutationBuffer`` to tools running inside ``pipeline.run_stream``.
"""

from __future__ import annotations

import asyncio
import contextvars

from backend.service.state import (
    MutationBuffer,
    bind_mutation_buffer,
    current_mutation_buffer,
    reset_mutation_buffer,
)


def test_default_is_none() -> None:
    # Run in a fresh context so prior tests' binds (if any leaked)
    # don't colour this assertion.
    ctx = contextvars.copy_context()
    assert ctx.run(current_mutation_buffer) is None


def test_bind_exposes_buffer_then_reset_clears() -> None:
    buf = MutationBuffer()
    token = bind_mutation_buffer(buf)
    try:
        assert current_mutation_buffer() is buf
    finally:
        reset_mutation_buffer(token)
    assert current_mutation_buffer() is None


def test_reset_tolerates_none_token() -> None:
    # AgentSession.plumb_buffer returns ``None`` in classic mode;
    # reset_mutation_buffer(None) must be a no-op rather than raising.
    reset_mutation_buffer(None)
    assert current_mutation_buffer() is None


def test_independent_tasks_do_not_see_sibling_binds() -> None:
    """Each asyncio task inherits its own context copy, so a bind in one
    coroutine must not leak into a concurrent sibling. This mirrors the
    FastAPI request-per-task pattern where two simultaneous AgentSession
    turns share nothing at the contextvar level.
    """

    seen: dict[str, object] = {}

    async def binder(buf: MutationBuffer) -> None:
        tok = bind_mutation_buffer(buf)
        try:
            await asyncio.sleep(0.01)
            seen["binder"] = current_mutation_buffer()
        finally:
            reset_mutation_buffer(tok)

    async def observer() -> None:
        # Give the binder a chance to bind first.
        await asyncio.sleep(0.005)
        seen["observer"] = current_mutation_buffer()

    async def main() -> None:
        b = MutationBuffer()
        await asyncio.gather(binder(b), observer())

    asyncio.run(main())

    assert seen["binder"] is not None
    # The observer runs as its own task — it must NOT see the binder's
    # bind unless the context was intentionally shared. Python 3.11+
    # asyncio.gather spawns each coroutine in a fresh copy of the
    # parent context; the observer's context is a copy taken *before*
    # the binder mutated anything, so the observer sees None.
    assert seen["observer"] is None


def test_nested_binds_unwind_in_reverse_order() -> None:
    a = MutationBuffer()
    b = MutationBuffer()

    tok_a = bind_mutation_buffer(a)
    tok_b = bind_mutation_buffer(b)
    try:
        assert current_mutation_buffer() is b
    finally:
        reset_mutation_buffer(tok_b)
        assert current_mutation_buffer() is a
        reset_mutation_buffer(tok_a)
    assert current_mutation_buffer() is None


def test_buffer_visible_to_function_called_during_bind() -> None:
    buf = MutationBuffer()

    def tool_like() -> MutationBuffer | None:
        return current_mutation_buffer()

    tok = bind_mutation_buffer(buf)
    try:
        assert tool_like() is buf
    finally:
        reset_mutation_buffer(tok)
