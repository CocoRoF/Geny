"""Coverage for G6.4 — Stage 4 PermissionGuard chain activation.

Three layers of assertion:

1. **Manifest factory** — worker_adaptive emits an explicit guards
   chain with `permission` at the tail; vtuber stays on the executor's
   silent default (token + cost + iteration only).
2. **Pipeline materialization** — `Pipeline.from_manifest` resolves
   the chain entries to real Guard instances. PermissionGuard is
   present in the registered Stage 4's chain.
3. **Wiring contract** — PermissionGuard reads `state.permission_rules`
   / `state.permission_mode` (set by G6.3's attach_runtime call), so
   when no rules are present the guard is a no-op.
"""

from __future__ import annotations

import pytest

pytest.importorskip("geny_executor")

from geny_executor.core.pipeline import Pipeline  # noqa: E402

from service.executor.default_manifest import build_default_manifest  # noqa: E402


def test_worker_adaptive_declares_permission_guard() -> None:
    manifest = build_default_manifest("worker_adaptive")
    guard_entry = next(e for e in manifest.stages if e["order"] == 4)
    assert guard_entry["name"] == "guard"
    assert guard_entry["chain_order"]["guards"] == [
        "token_budget", "cost_budget", "iteration", "permission",
    ]


def test_worker_easy_declares_permission_guard() -> None:
    """worker_easy inherits the worker_adaptive chain via _build_stage_entries."""
    manifest = build_default_manifest("worker_easy")
    guard_entry = next(e for e in manifest.stages if e["order"] == 4)
    assert "permission" in guard_entry["chain_order"]["guards"]


def test_vtuber_stays_on_default_guard_chain() -> None:
    """VTuber turns don't run general-purpose tools — no permission
    matrix evaluation needed. Stays on the executor's silent default
    (token + cost + iteration)."""
    manifest = build_default_manifest("vtuber")
    guard_entry = next(e for e in manifest.stages if e["order"] == 4)
    # Either no chain_order set, or set without permission.
    chain = guard_entry.get("chain_order", {}).get("guards", [])
    assert "permission" not in chain


def test_pipeline_factory_does_not_populate_chain_alone() -> None:
    """The manifest's chain_order is a *reorder hint* — `Pipeline.from_manifest`
    does NOT automatically add chain items because the executor's
    `reorder_chain` only reorders existing items. Guard chain population
    happens at session-build time via `populate_guard_chain`."""
    manifest = build_default_manifest("worker_adaptive", model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)

    guard_stage = next(s for s in pipeline.stages if s.order == 4)
    chains = guard_stage.get_strategy_chains()
    assert "guards" in chains
    # Empty by default — the install helper fills it.
    assert chains["guards"].items == []


def test_populate_guard_chain_adds_default_guards() -> None:
    """`populate_guard_chain` adds the manifest-declared default order
    of guards including PermissionGuard at the tail."""
    from service.permission.install import populate_guard_chain

    manifest = build_default_manifest("worker_adaptive", model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)
    added = populate_guard_chain(pipeline)
    assert added == 4

    guard_stage = next(s for s in pipeline.stages if s.order == 4)
    chain = guard_stage.get_strategy_chains()["guards"]
    names = [getattr(g, "name", type(g).__name__) for g in chain.items]
    assert names == ["token_budget", "cost_budget", "iteration", "permission"]


def test_populate_guard_chain_is_idempotent() -> None:
    """Calling populate_guard_chain twice doesn't double-add guards."""
    from service.permission.install import populate_guard_chain

    manifest = build_default_manifest("worker_adaptive", model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)
    first = populate_guard_chain(pipeline)
    second = populate_guard_chain(pipeline)
    assert first == 4
    assert second == 0  # already present


def test_populate_guard_chain_custom_list() -> None:
    """Hosts can pass their own chain — useful for tests / per-preset
    variations."""
    from service.permission.install import populate_guard_chain

    manifest = build_default_manifest("worker_adaptive", model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)
    added = populate_guard_chain(pipeline, chain=["token_budget", "permission"])
    assert added == 2

    guard_stage = next(s for s in pipeline.stages if s.order == 4)
    chain = guard_stage.get_strategy_chains()["guards"]
    names = [getattr(g, "name", type(g).__name__) for g in chain.items]
    assert names == ["token_budget", "permission"]
