"""Shared helpers for game-tool tests.

``pytest`` yielding fixtures don't propagate :mod:`contextvars` binds
to the test body (the bind happens in the fixture's own context copy,
and pytest re-enters the test in a separate context). A plain
:func:`contextlib.contextmanager` used *inside* the test does share
context — the ``with`` body runs in the test's own context copy, so
the bind is visible everywhere the test reaches.
"""

from __future__ import annotations

from contextlib import contextmanager

from service.state import (
    MutationBuffer,
    bind_mutation_buffer,
    reset_mutation_buffer,
)


@contextmanager
def bound_buffer():
    buf = MutationBuffer()
    tok = bind_mutation_buffer(buf)
    try:
        yield buf
    finally:
        reset_mutation_buffer(tok)


def by_path(buf: MutationBuffer, path: str) -> list:
    return [m for m in buf.items if m.path == path]
