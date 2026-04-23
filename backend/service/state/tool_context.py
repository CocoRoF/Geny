"""Turn-scoped ContextVar bridge for game tools (PR-X3-6).

`BaseTool.run(**kwargs)` is called by the executor through
``_GenyToolAdapter`` with only the LLM-supplied input kwargs plus an
optional ``session_id`` injection. Neither ``PipelineState`` nor the
per-turn ``MutationBuffer`` crosses that boundary.

The game tools (``feed`` / ``play`` / ``gift`` / ``talk``) need to push
mutations onto the same buffer that ``SessionRuntimeRegistry.persist``
will commit after the turn. Rather than reshape the adapter signature
(which would ripple into every third-party tool and break executor
compatibility), we publish the current-turn buffer through a
``contextvars.ContextVar`` that ``AgentSession`` binds before
``pipeline.run`` / ``run_stream`` and resets in a ``finally`` block.

`ContextVar` is the right primitive here:

- Each asyncio task gets its own copy (no cross-session leakage even
  when the FastAPI process is handling many concurrent sessions).
- The reset semantics (via the returned ``Token``) are exception-safe
  — a crash inside the pipeline still unbinds the buffer.
- Tools running inside the pipeline (same task) see the value; code
  outside the session (decay service, REST handlers) sees ``None``.

The helpers are intentionally thin: ``bind`` returns a ``Token`` that
the caller MUST ``reset``; the paired ``reset_mutation_buffer`` wraps
``.reset()`` with a tolerant no-op when the token is ``None`` so the
AgentSession plumbing can skip the bind cleanly in classic mode
(no provider).
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

from .schema import MutationBuffer
from .schema.creature_state import CHARACTER_ROLE_VTUBER

_current_mutation_buffer: ContextVar[Optional[MutationBuffer]] = ContextVar(
    "geny_current_mutation_buffer", default=None
)

# Plan/Phase04 §4.2 — current-turn role contextvar so game tools can
# refuse to mutate when the active session belongs to a non-VTuber
# character. Default is VTuber so legacy / classic-mode invocations
# (where AgentSession never calls ``bind_creature_role``) preserve
# today's behavior — mutate when a buffer is bound, no-op otherwise.
_current_creature_role: ContextVar[str] = ContextVar(
    "geny_current_creature_role", default=CHARACTER_ROLE_VTUBER
)


def current_mutation_buffer() -> Optional[MutationBuffer]:
    """Return the mutation buffer bound for the current turn, or ``None``.

    Callers (game tools) receive ``None`` outside a pipeline turn or
    when running under classic mode (no creature state provider wired).
    In that case tools should degrade to a narrated no-op — the LLM
    still sees a friendly result, but no state transition is recorded.
    """
    return _current_mutation_buffer.get()


def current_creature_role() -> str:
    """Return the role string for the current-turn creature.

    Defaults to :data:`CHARACTER_ROLE_VTUBER` when nothing was bound.
    Game tools should treat any non-VTuber role as "skip the mutation"
    and degrade to narrated-only (mirrors the buffer-None path).
    """
    return _current_creature_role.get()


def bind_mutation_buffer(buffer: MutationBuffer) -> Token:
    """Publish *buffer* as the current-turn buffer and return a token.

    The caller must pass the returned token to
    :func:`reset_mutation_buffer` in a ``finally`` block so the binding
    does not leak into sibling tasks that inherit the caller's context.
    """
    return _current_mutation_buffer.set(buffer)


def bind_creature_role(role: str) -> Token:
    """Publish *role* as the current-turn creature role.

    Paired with :func:`reset_creature_role`. Falsy strings collapse to
    the VTuber default — preserves the legacy contract where untagged
    sessions are treated as VTuber.
    """
    return _current_creature_role.set(role or CHARACTER_ROLE_VTUBER)


def reset_mutation_buffer(token: Optional[Token]) -> None:
    """Counterpart to :func:`bind_mutation_buffer`.

    Accepting ``None`` lets AgentSession unconditionally call
    ``reset`` without branching on whether a bind occurred, which
    keeps the hot path in ``_invoke_pipeline`` / ``_astream_pipeline``
    symmetric with the hydrate / persist helpers.
    """
    if token is None:
        return
    _current_mutation_buffer.reset(token)


def reset_creature_role(token: Optional[Token]) -> None:
    """Counterpart to :func:`bind_creature_role`. Tolerates ``None``."""
    if token is None:
        return
    _current_creature_role.reset(token)


__all__ = [
    "bind_creature_role",
    "bind_mutation_buffer",
    "current_creature_role",
    "current_mutation_buffer",
    "reset_creature_role",
    "reset_mutation_buffer",
]
