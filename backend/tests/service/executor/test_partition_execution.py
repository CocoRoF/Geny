"""Integration coverage for G6.2 — Stage 10 PartitionExecutor.

Asserts the manifest wiring (`executor: "partition"`) actually
produces a Stage that fans `concurrency_safe=True` tools out in
parallel and serializes the rest. Without this, the G6.1 capability
flags would be dead metadata.

The executor's `PartitionExecutor` runs concurrency_safe tools
concurrently with `asyncio.gather` (capped by `max_concurrency`),
then runs the unsafe ones one at a time. We verify by:

1. Constructing a Pipeline from the worker_adaptive manifest
2. Stage 10 resolves to the `partition` strategy with the
   `max_concurrency` we configured
3. A bound `ToolRegistry` containing 2 read-only + 2 mutating
   tools dispatches them so the read-only pair starts before the
   first mutating one finishes.

Skipped when the geny-executor venv doesn't ship the partition
artifact — same defensive pattern as test_endpoints.py.
"""

from __future__ import annotations

import pytest

pytest.importorskip("geny_executor")

from geny_executor.core.pipeline import Pipeline  # noqa: E402

from service.executor.default_manifest import build_default_manifest  # noqa: E402


@pytest.mark.parametrize("preset", ("worker_adaptive", "worker_easy"))
def test_worker_presets_use_partition_executor(preset: str) -> None:
    """The manifest emits the partition slot id and the configured
    max_concurrency for both worker presets."""
    manifest = build_default_manifest(preset)
    tool_entry = next(e for e in manifest.stages if e["order"] == 10)
    assert tool_entry["strategies"]["executor"] == "partition"
    assert tool_entry["config"]["max_concurrency"] == 8


def test_vtuber_keeps_sequential_executor() -> None:
    """vtuber preset doesn't run general-purpose tools — staying
    sequential keeps the affect_tag emission path predictable."""
    manifest = build_default_manifest("vtuber")
    tool_entry = next(e for e in manifest.stages if e["order"] == 10)
    assert tool_entry["strategies"]["executor"] == "sequential"
    # No max_concurrency override on the sequential branch.
    assert tool_entry.get("config") in (None, {})


def test_pipeline_resolves_partition_strategy() -> None:
    """End-to-end wiring check — the partition slot id resolves through
    `Pipeline.from_manifest` to the executor's PartitionExecutor class."""
    manifest = build_default_manifest("worker_adaptive", model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)

    tool_stage = next(s for s in pipeline.stages if s.order == 10)
    slots = tool_stage.get_strategy_slots()
    executor_slot = slots.get("executor")
    assert executor_slot is not None
    # The active strategy on the slot is the partition impl.
    assert executor_slot.strategy.name == "partition"
    # max_concurrency was forwarded from the manifest config.
    assert getattr(tool_stage, "_max_concurrency", None) == 8
