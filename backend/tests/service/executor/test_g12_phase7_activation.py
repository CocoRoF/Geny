"""G12 — Phase 7 strategy activations on worker_adaptive.

Each flip is documented in cycle 20260425_2 / G12. Strict-superset
defaults mean behaviour is unchanged at default config; the
activation just opens the strategy_configs path for runtime tuning.

vtuber and worker_easy presets are negative controls — they stay
on the conservative defaults (vtuber doesn't run worker tools, and
worker_easy is single-turn so the chain wrappers add no value).
"""

from __future__ import annotations

import pytest

pytest.importorskip("geny_executor")

from service.executor.default_manifest import build_default_manifest  # noqa: E402


def _entry(preset: str, order: int) -> dict:
    manifest = build_default_manifest(preset)
    return next(e for e in manifest.stages if e["order"] == order)


# ── s06 api router ─────────────────────────────────────────────────


def test_worker_adaptive_uses_adaptive_router() -> None:
    api = _entry("worker_adaptive", 6)
    assert api["strategies"]["router"] == "adaptive"


def test_worker_easy_uses_adaptive_router() -> None:
    """worker_easy inherits the worker_adaptive layout — same router."""
    api = _entry("worker_easy", 6)
    assert api["strategies"]["router"] == "adaptive"


def test_vtuber_keeps_passthrough_router() -> None:
    api = _entry("vtuber", 6)
    # vtuber's preset has its own api stage entry (not from worker_adaptive).
    # Whichever it picked, the regression check is "not adaptive" — vtuber
    # turns are short and the router would only add latency.
    assert api["strategies"]["router"] != "adaptive"


# ── s14 evaluate strategy ───────────────────────────────────────────


def test_worker_adaptive_uses_evaluation_chain() -> None:
    eval_entry = _entry("worker_adaptive", 14)
    assert eval_entry["strategies"]["strategy"] == "evaluation_chain"
    chain_cfg = eval_entry.get("strategy_configs", {}).get("strategy", {})
    assert chain_cfg.get("evaluators") == ["binary_classify", "signal_based"]


def test_vtuber_keeps_signal_based_evaluator() -> None:
    eval_entry = _entry("vtuber", 14)
    assert eval_entry["strategies"]["strategy"] == "signal_based"


# ── s16 loop controller ─────────────────────────────────────────────


def test_worker_adaptive_uses_multi_dim_budget() -> None:
    loop = _entry("worker_adaptive", 16)
    assert loop["strategies"]["controller"] == "multi_dim_budget"
    dims = loop.get("strategy_configs", {}).get("controller", {}).get("dimensions")
    assert dims == ["iterations"]
    # max_turns config is preserved (the loop controller reads it
    # for the iteration dimension cap).
    assert "max_turns" in loop["config"]


def test_vtuber_keeps_standard_controller() -> None:
    loop = _entry("vtuber", 16)
    assert loop["strategies"]["controller"] == "standard"


# ── s18 memory strategy ────────────────────────────────────────────


def test_worker_adaptive_uses_structured_reflective() -> None:
    mem = _entry("worker_adaptive", 18)
    assert mem["strategies"]["strategy"] == "structured_reflective"
    # persistence stays "null" — the attach_runtime path swaps in
    # the real GenyPersistence rooted at the session's memory_manager.
    assert mem["strategies"]["persistence"] == "null"


def test_vtuber_keeps_append_only_memory() -> None:
    mem = _entry("vtuber", 18)
    assert mem["strategies"]["strategy"] == "append_only"


# ── End-to-end: pipeline still materialises ────────────────────────


@pytest.mark.parametrize("preset", ("worker_adaptive", "worker_easy", "vtuber"))
def test_pipeline_builds_with_new_strategies(preset: str) -> None:
    """Strict-superset defaults mean the new strategies must
    instantiate cleanly through Pipeline.from_manifest. If a strategy
    needs a required config field that we forgot to set, this fails
    here with a clear ValueError."""
    from geny_executor.core.pipeline import Pipeline

    manifest = build_default_manifest(preset, model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)
    # Sanity: stages we flipped are all registered.
    orders = {s.order for s in pipeline.stages}
    if preset == "vtuber":
        assert {6, 14, 16, 18}.issubset(orders)
    else:
        assert {6, 14, 16, 18}.issubset(orders)
