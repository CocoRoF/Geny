"""Unit tests for :func:`service.langgraph.default_manifest.build_default_manifest`.

Regression protection for PR #1 of the 20260420_4 cycle
(`fix/manifest-tool-stages`). If a future change drops stages
10/11/14 from the builder — intentionally or accidentally — the
system would silently regress to the pre-fix "tool calls never
run" state because :meth:`Pipeline._try_run_stage` bypasses
missing stages with only a ``stage.bypass`` event. These tests
make that regression loud.
"""

from __future__ import annotations

import pytest


def _known_preset_ids():
    return ("worker_adaptive", "vtuber", "worker_easy")


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_manifest_declares_tool_stage(preset: str) -> None:
    from service.langgraph.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    orders = {entry["order"] for entry in manifest.stages}

    assert 10 in orders, f"{preset} manifest missing Stage 10 (tool)"
    assert 11 in orders, f"{preset} manifest missing Stage 11 (agent)"
    assert 14 in orders, f"{preset} manifest missing Stage 14 (emit)"


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_tool_stage_has_default_strategies(preset: str) -> None:
    from service.langgraph.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    entry = next(e for e in manifest.stages if e["order"] == 10)

    assert entry["name"] == "tool"
    assert entry["strategies"] == {"executor": "sequential", "router": "registry"}


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_agent_stage_has_single_agent_orchestrator(preset: str) -> None:
    from service.langgraph.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    entry = next(e for e in manifest.stages if e["order"] == 11)

    assert entry["name"] == "agent"
    assert entry["strategies"] == {"orchestrator": "single_agent"}
    assert entry["config"] == {"max_delegations": 4}


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_emit_stage_uses_empty_chain(preset: str) -> None:
    from service.langgraph.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    entry = next(e for e in manifest.stages if e["order"] == 14)

    assert entry["name"] == "emit"
    assert entry["chain_order"] == {"emitters": []}


def test_vtuber_manifest_omits_think_stage() -> None:
    """Negative control: Stage 8 (think) is intentionally dropped on
    VTuber. Guards against a future 'add every stage' regression that
    would re-introduce the think stage on VTuber."""
    from service.langgraph.default_manifest import build_default_manifest

    orders = {e["order"] for e in build_default_manifest("vtuber").stages}
    assert 8 not in orders, "VTuber should not declare Stage 8 (think)"


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_manifest_built_in_is_empty(preset: str) -> None:
    """`manifest.tools.built_in` is dead metadata — the executor's
    `_register_external_tools` only walks `.external`. The factory
    should leave `.built_in` empty to keep the manifest honest
    about what actually reaches the registry. Regression guard
    against re-introducing a hardcoded builtin list (e.g. the old
    ``["Read", "Write", "Edit", ...]`` that pointed at names no
    provider supplied)."""
    from service.langgraph.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    assert list(manifest.tools.built_in) == [], (
        f"{preset}: manifest.tools.built_in must be empty — the "
        f"executor does not consume it; populating it creates dead "
        f"metadata. Got: {list(manifest.tools.built_in)}"
    )


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_manifest_external_is_caller_supplied(preset: str) -> None:
    """Everything the caller passes as ``external_tool_names`` lands
    verbatim in ``manifest.tools.external`` — this is the single
    registration path the executor honours."""
    from service.langgraph.default_manifest import build_default_manifest

    names = ["geny_send_direct_message", "memory_read", "web_search"]
    manifest = build_default_manifest(preset, external_tool_names=names)
    assert list(manifest.tools.external) == names


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_pipeline_from_manifest_registers_tool_stages(preset: str) -> None:
    """End-to-end wiring check: the stage entries the builder emits
    actually produce registered Stage objects in a materialized
    Pipeline. Catches regressions where a stage name or artifact
    pair no longer resolves through ``create_stage``."""
    from geny_executor.core.pipeline import Pipeline

    from service.langgraph.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset, model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)

    registered_orders = {s.order for s in pipeline.stages}
    assert {10, 11, 14}.issubset(registered_orders), (
        f"{preset}: pipeline stages = {sorted(registered_orders)}"
    )
