"""Integration: Sub-Worker (worker env) file creation lands on disk.

Cycle 20260420_7 / PR-3. Proves the end-to-end wiring that closes the
Sub-Worker file-creation gap:

1. :func:`create_worker_env` builds a manifest with
   ``tools.built_in = ["*"]``.
2. :meth:`Pipeline.from_manifest` (geny-executor >= 0.27.0) resolves
   ``"*"`` against :data:`BUILT_IN_TOOL_CLASSES` and registers every
   framework tool — including ``Write``.
3. ``Write.execute`` sandboxes every path against
   ``ToolContext.working_dir`` — for real Sub-Workers this is the
   session's ``storage_path``, i.e. ``backend/storage/<session_id>/``.

Before v0.27.0 the ``.built_in`` field on the manifest was dead
metadata; a Sub-Worker asked to "create test.txt" had no filesystem
tool and fell back to ``memory_write``, never producing a file.

A pipeline Stage 10 dispatch test (``test_delegation_round_trip.py``)
already proves the registry → executor wiring. This test closes the
gap: it shows the manifest → registry → on-disk-file path works too.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_worker_pipeline_write_tool_creates_file(tmp_path) -> None:
    """End-to-end: Sub-Worker env registers ``Write``; calling it with
    ``working_dir=tmp_path`` produces a real file under tmp_path."""
    from geny_executor.core.pipeline import Pipeline
    from geny_executor.tools.base import ToolContext

    from service.environment.templates import create_worker_env

    manifest = create_worker_env(external_tool_names=[])
    pipeline = Pipeline.from_manifest(
        manifest, api_key="sk-test", strict=False, adhoc_providers=[]
    )

    write_tool = pipeline.tool_registry.get("Write")
    assert write_tool is not None, (
        "worker env must expose 'Write' after PR-3. "
        f"Got registry: {sorted(pipeline.tool_registry.list_names())}"
    )

    target = tmp_path / "test.txt"
    ctx = ToolContext(
        session_id="sub-worker-session",
        working_dir=str(tmp_path),
        storage_path=str(tmp_path),
        allowed_paths=[str(tmp_path)],
    )
    result = await write_tool.execute(
        {"file_path": str(target), "content": "hello from sub-worker"},
        ctx,
    )
    assert result.is_error is False, result.content
    assert target.exists(), (
        "Write tool reported success but produced no file — "
        "sandbox/path wiring is broken."
    )
    assert target.read_text(encoding="utf-8") == "hello from sub-worker"


@pytest.mark.asyncio
async def test_worker_pipeline_write_tool_rejects_escape(tmp_path) -> None:
    """Negative control: Write must reject paths outside working_dir.

    The executor's :func:`_path_guard.resolve_and_validate` enforces
    this — if a future refactor of :class:`AgentSession` stops passing
    ``working_dir`` / ``storage_path`` into :class:`ToolContext`, a
    Sub-Worker could silently escape its session's storage directory.
    """
    from geny_executor.core.pipeline import Pipeline
    from geny_executor.tools.base import ToolContext

    from service.environment.templates import create_worker_env

    manifest = create_worker_env(external_tool_names=[])
    pipeline = Pipeline.from_manifest(
        manifest, api_key="sk-test", strict=False, adhoc_providers=[]
    )
    write_tool = pipeline.tool_registry.get("Write")

    escape = tmp_path.parent / "escape.txt"
    ctx = ToolContext(
        session_id="sub-worker-session",
        working_dir=str(tmp_path),
        storage_path=str(tmp_path),
        allowed_paths=[str(tmp_path)],
    )
    result = await write_tool.execute(
        {"file_path": str(escape), "content": "should not be written"},
        ctx,
    )
    assert result.is_error is True, (
        "Write must reject paths outside working_dir — sandbox failed."
    )
    assert not escape.exists()


def test_vtuber_env_has_no_write_tool() -> None:
    """Symmetric guard for PR-3: the VTuber env must *not* register
    ``Write`` (or any framework built-in). Every file operation for
    the VTuber goes through its bound Sub-Worker via
    ``geny_message_counterpart``."""
    from geny_executor.core.pipeline import Pipeline

    from service.environment.templates import create_vtuber_env

    manifest = create_vtuber_env(all_tool_names=["web_search"])
    pipeline = Pipeline.from_manifest(
        manifest, api_key="sk-test", strict=False, adhoc_providers=[]
    )
    assert pipeline.tool_registry.get("Write") is None, (
        "VTuber env leaked Write tool — role separation regressed."
    )
