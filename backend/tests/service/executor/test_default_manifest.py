"""What Geny needs the one harness to contain.

geny-executor owns the stage blueprint (:func:`geny_executor.build_manifest`)
and pins its own layout. These tests pin the parts Geny *depends* on from the
Geny side — the stages whose absence would break a feature here rather than
in the library:

* Stages 10 / 12 / 17 exist at all. :meth:`Pipeline._try_run_stage` bypasses a
  missing stage with nothing but a ``stage.bypass`` event, so dropping Stage 10
  would silently return the system to "tool calls never run".
* The scaffold stages Geny wires runtime objects into are ACTIVE — tool review,
  HITL (the approval UI), the task registry (delegation + /tasks), summarize
  and persist. An inactive stage accepts the wiring and never runs it.
* Stage 6 names ``geny_router`` and routes ``passthrough``, because the model
  is the account the user picked, not one a stage substitutes.

Since 2.66.0 there is ONE blueprint. The historical ``worker_adaptive`` and
``vtuber`` names still resolve — a stored environment must keep loading — and
they must resolve to the same manifest, which is what
``test_a_legacy_preset_name_is_the_same_harness`` is for.
"""

from __future__ import annotations

import pytest


def _manifest(preset: str = "default", provider: str = "geny_router"):
    from geny_executor import build_manifest

    return build_manifest(preset, provider=provider)


def _stage(manifest, order: int) -> dict:
    return next(e for e in manifest.stages if e["order"] == order)


# ── the stages a missing entry would silently disable ────────────────


def test_the_stages_that_run_tools_delegate_and_emit_exist() -> None:
    orders = {entry["order"] for entry in _manifest().stages}
    assert 10 in orders, "missing Stage 10 (tool) — tool calls would never run"
    assert 12 in orders, "missing Stage 12 (agent) — delegation would never run"
    assert 17 in orders, "missing Stage 17 (emit)"


def test_all_21_slots_are_declared() -> None:
    """Declared, not omitted: the environment canvas renders an inactive slot
    like any other, and a missing one reads as a broken stage."""
    assert [e["order"] for e in _manifest().stages] == list(range(1, 22))


@pytest.mark.parametrize("order,name", [
    (11, "tool_review"), (13, "task_registry"), (15, "hitl"),
    (19, "summarize"), (20, "persist"),
])
def test_the_scaffold_stages_geny_wires_are_active(order: int, name: str) -> None:
    """Geny attaches a real object to each of these at session build — the
    resume-capable HITL requester, the file persister, the memory summariser.
    An inactive stage takes the wiring and never runs it."""
    entry = _stage(_manifest(), order)
    assert entry["name"] == name
    assert entry["active"] is True


def test_hitl_and_persist_carry_their_runtime_placeholders() -> None:
    """The real requester/persister need a Pipeline reference no manifest can
    serialise, so the manifest carries a safe placeholder and Geny swaps it."""
    hitl = _stage(_manifest(), 15)
    assert hitl["strategies"]["requester"] == "null"
    assert hitl["strategies"]["timeout"] == "indefinite"
    persist = _stage(_manifest(), 20)
    assert persist["strategies"]["persister"] == "no_persist"
    assert persist["strategies"]["frequency"] == "on_significant"


def test_task_registry_does_not_block_the_agent_loop() -> None:
    entry = _stage(_manifest(), 13)
    assert entry["strategies"] == {"registry": "in_memory", "policy": "fire_and_forget"}


def test_summarize_uses_real_strategies() -> None:
    entry = _stage(_manifest(), 19)
    assert entry["strategies"] == {"summarizer": "rule_based", "importance": "heuristic"}


# ── stage configuration Geny relies on ───────────────────────────────


def test_stage_6_names_the_router_and_never_substitutes_the_model() -> None:
    """The account route the user picked names the model. A stage that
    substitutes a "better" one overrides that choice invisibly — and did: a
    substitution to a model id that did not exist hung the CLI backend."""
    entry = _stage(_manifest(), 6)
    assert entry["config"]["provider"] == "geny_router"
    assert entry["strategies"]["router"] == "passthrough"


def test_tool_stage_runs_safe_calls_in_parallel() -> None:
    entry = _stage(_manifest(), 10)
    assert entry["name"] == "tool"
    assert entry["strategies"] == {"executor": "partition", "router": "registry"}
    assert entry["config"] == {"max_concurrency": 8}


def test_agent_stage_orchestrates_by_subagent_type() -> None:
    entry = _stage(_manifest(), 12)
    assert entry["name"] == "agent"
    assert entry["strategies"] == {"orchestrator": "subagent_type"}
    assert entry["config"] == {"max_delegations": 4}


def test_emit_stage_uses_empty_chain() -> None:
    entry = _stage(_manifest(), 17)
    assert entry["name"] == "emit"
    assert entry["chain_order"] == {"emitters": []}


def test_the_evaluator_answers_a_chat_turn_in_one_pass() -> None:
    """Why conversation needs no lighter chain of its own: the adaptive
    classifier completes a plain answer immediately, and only opens the full
    loop for a turn that reaches for a tool."""
    entry = _stage(_manifest(), 14)
    config = entry["strategy_configs"]["strategy"]
    assert config["evaluators"] == ["binary_classify", "signal_based"]
    assert config["easy_max_turns"] == 1


# ── environments stored before the collapse ──────────────────────────


@pytest.mark.parametrize("legacy", ["worker_adaptive", "vtuber"])
def test_a_legacy_preset_name_is_the_same_harness(legacy: str) -> None:
    assert _manifest(legacy).stages == _manifest().stages
