"""Unit tests for :func:`service.executor.default_manifest.build_default_manifest`.

Regression protection for PR #1 of the 20260420_4 cycle
(`fix/manifest-tool-stages`). If a future change drops stages
10/12/17 from the builder — intentionally or accidentally — the
system would silently regress to the pre-fix "tool calls never
run" state because :meth:`Pipeline._try_run_stage` bypasses
missing stages with only a ``stage.bypass`` event. These tests
make that regression loud.

geny-executor 1.0+ moved agent 11→12 and emit 14→17 as part of
the 21-stage layout (Sub-phase 9a). The asserts below track
the new orders.
"""

from __future__ import annotations

import pytest


def _known_preset_ids():
    return ("worker_adaptive", "vtuber", "worker_easy")


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_manifest_declares_tool_stage(preset: str) -> None:
    from service.executor.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    orders = {entry["order"] for entry in manifest.stages}

    # 21-stage layout: tool=10, agent=12 (was 11), emit=17 (was 14).
    assert 10 in orders, f"{preset} manifest missing Stage 10 (tool)"
    assert 12 in orders, f"{preset} manifest missing Stage 12 (agent)"
    assert 17 in orders, f"{preset} manifest missing Stage 17 (emit)"


# Per-preset opt-in for the 5 scaffold stages. Updated as each
# G2.x sprint promotes a scaffold from "advisory" to "wired".
#   G2.2 — summarize   (19) on worker_adaptive
#   G2.3 — persist     (20) on worker_adaptive (FilePersister swapped at runtime)
#   G2.4 — tool_review (11) on worker_adaptive
#   G2.5 — hitl        (15) on worker_adaptive (PipelineResumeRequester swapped at runtime)
_ACTIVE_SCAFFOLDS_BY_PRESET: dict[str, set[int]] = {
    "worker_adaptive": {11, 15, 19, 20},
    "worker_easy": set(),
    "vtuber": set(),
}


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_manifest_declares_21_stage_layout(preset: str) -> None:
    """Sub-phase 9a (executor 1.0+) widened the layout to 21 slots.

    Every preset emits all 21 entries. Scaffold opt-in tracked in
    :data:`_ACTIVE_SCAFFOLDS_BY_PRESET` — each G2.x sprint flips
    one or more scaffold stages from default inactive to active.
    """
    from service.executor.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    orders = {entry["order"] for entry in manifest.stages}

    if preset == "vtuber":
        # vtuber omits Stage 8 (think) — same legacy diff.
        expected = set(range(1, 22)) - {8}
    else:
        expected = set(range(1, 22))
    assert orders == expected, (
        f"{preset}: orders={sorted(orders)} expected={sorted(expected)}"
    )

    by_order = {e["order"]: e for e in manifest.stages}
    expected_active = _ACTIVE_SCAFFOLDS_BY_PRESET.get(preset, set())
    for scaffold_order in (11, 13, 15, 19, 20):
        expected_state = scaffold_order in expected_active
        assert by_order[scaffold_order]["active"] is expected_state, (
            f"{preset}: scaffold order {scaffold_order} active state mismatch "
            f"(expected={expected_state}, got={by_order[scaffold_order]['active']})"
        )


def test_worker_adaptive_activates_summarize_with_real_strategies() -> None:
    """G2.2: worker_adaptive opts the Stage 19 Summarize scaffold in
    with the real RuleBasedSummarizer + HeuristicImportance picks.
    Other presets keep summarize off."""
    from service.executor.default_manifest import build_default_manifest

    m = build_default_manifest("worker_adaptive")
    summarize = next(e for e in m.stages if e["order"] == 19)
    assert summarize["active"] is True
    assert summarize["strategies"]["summarizer"] == "rule_based"
    assert summarize["strategies"]["importance"] == "heuristic"

    # vtuber + worker_easy keep the no-op default.
    for preset in ("vtuber", "worker_easy"):
        s = next(e for e in build_default_manifest(preset).stages if e["order"] == 19)
        assert s["active"] is False
        assert s["strategies"]["summarizer"] == "no_summary"


def test_worker_adaptive_activates_tool_review_chain() -> None:
    """G2.4: worker_adaptive opts the Stage 11 Tool Review scaffold
    in. The chain default (schema → sensitive → destructive →
    network → size) carries through; flag events are forwarded
    to the session_logger by the agent_session event loop.
    Other presets keep tool_review off."""
    from service.executor.default_manifest import build_default_manifest

    m = build_default_manifest("worker_adaptive")
    review = next(e for e in m.stages if e["order"] == 11)
    assert review["active"] is True
    assert review["chain_order"]["reviewers"] == [
        "schema",
        "sensitive",
        "destructive",
        "network",
        "size",
    ]

    # vtuber + worker_easy keep tool_review off — VTuber sessions
    # don't run general-purpose tools and worker_easy is a single-
    # turn Q&A path.
    for preset in ("vtuber", "worker_easy"):
        s = next(e for e in build_default_manifest(preset).stages if e["order"] == 11)
        assert s["active"] is False


def test_worker_adaptive_activates_hitl_with_null_requester_placeholder() -> None:
    """G2.5: worker_adaptive opts the Stage 15 HITL gate in. The
    requester slot stays at ``null`` in the manifest — the real
    PipelineResumeRequester is wired by
    ``service.hitl.install_pipeline_resume_requester`` at session
    build time because it needs a Pipeline reference. Active
    state with the always-approve null requester is a free no-op
    until something writes to ``state.shared['hitl_request']``."""
    from service.executor.default_manifest import build_default_manifest

    m = build_default_manifest("worker_adaptive")
    hitl = next(e for e in m.stages if e["order"] == 15)
    assert hitl["active"] is True
    assert hitl["strategies"]["requester"] == "null"
    assert hitl["strategies"]["timeout"] == "indefinite"

    # vtuber + worker_easy keep hitl off — VTuber sessions have no
    # approval surface and worker_easy is single-turn.
    for preset in ("vtuber", "worker_easy"):
        s = next(e for e in build_default_manifest(preset).stages if e["order"] == 15)
        assert s["active"] is False


def test_worker_adaptive_activates_persist_with_on_significant_frequency() -> None:
    """G2.3: worker_adaptive opts Stage 20 Persist in with the
    on_significant frequency. The persister slot stays at
    no_persist in the manifest — the real FilePersister is wired
    by ``service.persist.install_file_persister`` at session-build
    time once the storage_path is known."""
    from service.executor.default_manifest import build_default_manifest

    m = build_default_manifest("worker_adaptive")
    persist = next(e for e in m.stages if e["order"] == 20)
    assert persist["active"] is True
    # Real persister is runtime-wired; manifest carries the placeholder.
    assert persist["strategies"]["persister"] == "no_persist"
    assert persist["strategies"]["frequency"] == "on_significant"

    # vtuber + worker_easy keep the scaffold default (off).
    for preset in ("vtuber", "worker_easy"):
        s = next(e for e in build_default_manifest(preset).stages if e["order"] == 20)
        assert s["active"] is False


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_tool_stage_has_default_strategies(preset: str) -> None:
    from service.executor.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    entry = next(e for e in manifest.stages if e["order"] == 10)

    assert entry["name"] == "tool"
    assert entry["strategies"] == {"executor": "sequential", "router": "registry"}


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_agent_stage_has_single_agent_orchestrator(preset: str) -> None:
    """Agent moved 11 → 12 in the 21-stage layout."""
    from service.executor.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    entry = next(e for e in manifest.stages if e["order"] == 12)

    assert entry["name"] == "agent"
    assert entry["strategies"] == {"orchestrator": "single_agent"}
    assert entry["config"] == {"max_delegations": 4}


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_emit_stage_uses_empty_chain(preset: str) -> None:
    """Emit moved 14 → 17 in the 21-stage layout."""
    from service.executor.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset)
    entry = next(e for e in manifest.stages if e["order"] == 17)

    assert entry["name"] == "emit"
    assert entry["chain_order"] == {"emitters": []}


def test_vtuber_manifest_omits_think_stage() -> None:
    """Negative control: Stage 8 (think) is intentionally dropped on
    VTuber. Guards against a future 'add every stage' regression that
    would re-introduce the think stage on VTuber."""
    from service.executor.default_manifest import build_default_manifest

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
    from service.executor.default_manifest import build_default_manifest

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
    from service.executor.default_manifest import build_default_manifest

    names = ["send_direct_message_external", "memory_read", "web_search"]
    manifest = build_default_manifest(preset, external_tool_names=names)
    assert list(manifest.tools.external) == names


@pytest.mark.parametrize("preset", _known_preset_ids())
def test_pipeline_from_manifest_registers_tool_stages(preset: str) -> None:
    """End-to-end wiring check: the stage entries the builder emits
    actually produce registered Stage objects in a materialized
    Pipeline. Catches regressions where a stage name or artifact
    pair no longer resolves through ``create_stage``."""
    from geny_executor.core.pipeline import Pipeline

    from service.executor.default_manifest import build_default_manifest

    manifest = build_default_manifest(preset, model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)

    registered_orders = {s.order for s in pipeline.stages}
    # 21-stage layout: tool=10, agent=12, emit=17.
    assert {10, 12, 17}.issubset(registered_orders), (
        f"{preset}: pipeline stages = {sorted(registered_orders)}"
    )
