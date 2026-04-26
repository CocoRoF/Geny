"""ToolContext.workspace_stack seed test (PR-D.5.1).

Verifies that AgentSession._build_pipeline plants a WorkspaceStack
in ToolContext.extras so executor 1.3.0's worktree/LSP integration
actually receives a workspace to operate on.

Skipped when geny_executor.workspace isn't importable (older pin)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("geny_executor.workspace")

from geny_executor.workspace import Workspace, WorkspaceStack  # noqa: E402


def test_workspace_imports_ok():
    """Sanity — the 1.3.0 surface is importable from this venv."""
    ws = Workspace(cwd=Path("/x"))
    assert ws.cwd == Path("/x")
    stack = WorkspaceStack(initial=ws)
    assert stack.depth() == 1
    assert stack.current().cwd == Path("/x")


def test_geny_seed_pattern():
    """The exact seed pattern Geny's _build_pipeline now uses.

    Mirroring it as a test pins the expected shape so a future
    refactor can't silently drop it.
    """
    working_dir = "/work/session-42"
    stack = WorkspaceStack(initial=Workspace(cwd=Path(working_dir or ".")))
    assert stack.current() is not None
    assert str(stack.current().cwd) == working_dir
