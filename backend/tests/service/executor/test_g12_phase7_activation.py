"""G12 — Phase 7 strategy activations on the one harness.

Each flip is documented in cycle 20260425_2 / G12. Strict-superset
defaults mean behaviour is unchanged at default config; the
activation just opens the strategy_configs path for runtime tuning.

The vtuber preset is the negative control — it stays on the
conservative defaults because vtuber doesn't run worker tools.
"""

from __future__ import annotations

import pytest

pytest.importorskip("geny_executor")

from geny_executor import build_manifest  # noqa: E402


def _entry(preset: str, order: int) -> dict:
    manifest = build_manifest(preset, provider="anthropic")
    return next(e for e in manifest.stages if e["order"] == order)


# ── s06 api router ─────────────────────────────────────────────────


def test_the_router_never_substitutes_the_chosen_model() -> None:
    """``passthrough``: the model is the one the session's account route
    names. An adaptive substitution overrides the user's choice with no
    trace — and once pointed the CLI backend at a model id that did not
    exist, which simply hung."""
    assert _entry("default", 6)["strategies"]["router"] == "passthrough"


# ── s14 evaluate strategy ───────────────────────────────────────────


def test_the_evaluator_is_the_adaptive_chain() -> None:
    eval_entry = _entry("default", 14)
    assert eval_entry["strategies"]["strategy"] == "evaluation_chain"
    chain_cfg = eval_entry.get("strategy_configs", {}).get("strategy", {})
    assert chain_cfg.get("evaluators") == ["binary_classify", "signal_based"]


def test_a_conversational_turn_costs_one_pass() -> None:
    """Why there is no lighter chain for conversation any more: the
    classifier completes a plain answer on the first turn."""
    config = _entry("default", 14)["strategy_configs"]["strategy"]
    assert config["easy_max_turns"] == 1


# ── s16 loop controller ─────────────────────────────────────────────


def test_the_loop_is_budget_aware() -> None:
    loop = _entry("default", 16)
    assert loop["strategies"]["controller"] == "multi_dim_budget"
    dims = loop.get("strategy_configs", {}).get("controller", {}).get("dimensions")
    assert dims == ["iterations"]
    # max_turns config is preserved (the loop controller reads it
    # for the iteration dimension cap).
    assert "max_turns" in loop["config"]




# ── s18 memory strategy ────────────────────────────────────────────


def test_memory_is_structured_reflective() -> None:
    mem = _entry("default", 18)
    assert mem["strategies"]["strategy"] == "structured_reflective"
    # persistence stays "null" — the attach_runtime path swaps in
    # the real GenyPersistence rooted at the session's memory_manager.
    assert mem["strategies"]["persistence"] == "null"




# ── End-to-end: pipeline still materialises ────────────────────────


def test_pipeline_builds_with_these_strategies() -> None:
    """Strict-superset defaults mean the new strategies must
    instantiate cleanly through Pipeline.from_manifest. If a strategy
    needs a required config field that we forgot to set, this fails
    here with a clear ValueError."""
    from geny_executor.core.pipeline import Pipeline

    manifest = build_manifest("default", provider="anthropic", model="claude-haiku-4-5-20251001")
    pipeline = Pipeline.from_manifest(manifest, api_key="sk-test", strict=False)
    # Sanity: the stages these strategies live on are all registered.
    assert {6, 14, 16, 18}.issubset({s.order for s in pipeline.stages})
