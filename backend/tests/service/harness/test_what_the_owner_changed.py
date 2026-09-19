"""The owner's settings, and why they live in their own file.

Two people write settings onto one session. The AGENT evolves itself through
the ``env`` tool and saves ``env_overlay.json``, rewritten whole each time.
The OWNER configures it from the settings page. Sharing one file means the
agent's next self-save serialises its own view of the world and silently
drops what the owner set — a data-loss bug that surfaces as "my setting keeps
reverting" and is very hard to explain.

Also pinned: the owner is applied LAST, after Geny's runtime installs,
because an install is a default upgrade and a default is exactly the thing an
explicit choice should beat.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from service.harness.overlay import (
    HarnessRejected,
    apply_overlay,
    merge_overlay,
    read_overlay,
    validate_overlay,
    write_overlay,
)


class _Slot:
    def __init__(self, name: str, impl: Any, options: List[str], config=None) -> None:
        self.slot_name, self.current_impl = name, impl
        self.available_impls, self.config = options, config or {}


class _Stage:
    """A stage that records what was asked of it."""

    def __init__(self, order: int, slots: List[_Slot]) -> None:
        self.order = order
        self._slots = {s.slot_name: s for s in slots}
        self.calls: List[tuple] = []

    def describe(self):
        return SimpleNamespace(strategies=list(self._slots.values()))

    def set_strategy(self, slot, impl, config=None):
        if slot not in self._slots:
            raise KeyError(slot)
        self._slots[slot].current_impl = impl
        self.calls.append(("set", slot, impl, config))

    def clear_chain(self, slot):
        self._slots[slot].config = {"items": []}
        self.calls.append(("clear", slot))

    def add_to_chain(self, slot, impl, config=None):
        self._slots[slot].config.setdefault("items", []).append({"name": impl})
        self.calls.append(("add", slot, impl, config))


class _Pipeline:
    def __init__(self, *stages: _Stage, **config: Any) -> None:
        self.stages = list(stages)
        self._config = SimpleNamespace(
            max_iterations=50, context_window_budget=200_000, cost_budget_usd=None, **config
        )


def _pipeline():
    return _Pipeline(
        _Stage(2, [_Slot("compactor", "llm_summary", ["llm_summary", "truncate", "summary"])]),
        _Stage(4, [_Slot("guards", "none", ["token_budget", "permission"], {"items": []})]),
        _Stage(6, [_Slot("tool_loop", "pipeline", ["internal", "pipeline"])]),
        _Stage(10, [_Slot("executor", "partition", ["partition", "sequential"])]),
    )


class TestWhatIsRefused:
    def test_the_tool_loop_is_not_a_setting(self) -> None:
        """A provider may be a model; it may not be an agent."""
        with pytest.raises(HarnessRejected) as exc:
            validate_overlay({"slots": {"6.tool_loop": "internal"}}, pipeline=_pipeline())
        assert "weOwnTheLoop" in str(exc.value)

    def test_an_implementation_the_slot_does_not_have(self) -> None:
        with pytest.raises(HarnessRejected) as exc:
            validate_overlay({"slots": {"2.compactor": "telepathy"}}, pipeline=_pipeline())
        assert "telepathy" in str(exc.value)

    def test_a_stage_this_pipeline_does_not_have(self) -> None:
        with pytest.raises(HarnessRejected):
            validate_overlay({"slots": {"19.summarizer": "rule_based"}}, pipeline=_pipeline())

    def test_a_slot_the_stage_does_not_have(self) -> None:
        with pytest.raises(HarnessRejected):
            validate_overlay({"slots": {"2.nonesuch": "x"}}, pipeline=_pipeline())

    def test_a_budget_that_is_not_a_number(self) -> None:
        with pytest.raises(HarnessRejected):
            validate_overlay({"budgets": {"maxIterations": "many"}}, pipeline=_pipeline())

    def test_a_negative_budget(self) -> None:
        with pytest.raises(HarnessRejected):
            validate_overlay({"budgets": {"costCeiling": -1}}, pipeline=_pipeline())

    def test_an_unknown_budget(self) -> None:
        with pytest.raises(HarnessRejected):
            validate_overlay({"budgets": {"vibes": 1}}, pipeline=_pipeline())

    def test_what_is_valid_passes_quietly(self) -> None:
        validate_overlay(
            {"budgets": {"maxIterations": 80}, "slots": {"2.compactor": "truncate"}},
            pipeline=_pipeline(),
        )


class TestWhatGetsApplied:
    def test_a_slot_is_swapped_on_the_live_pipeline(self) -> None:
        pipeline = _pipeline()
        applied = apply_overlay(pipeline, {"slots": {"2.compactor": "truncate"}})
        assert applied == ["2.compactor=truncate"]
        assert pipeline.stages[0].calls == [("set", "compactor", "truncate", None)]

    def test_a_chain_is_rebuilt_in_the_order_given(self) -> None:
        pipeline = _pipeline()
        apply_overlay(pipeline, {"slots": {"4.guards": ["permission", "token_budget"]}})
        assert [c[0] for c in pipeline.stages[1].calls] == ["clear", "add", "add"]
        assert [c[2] for c in pipeline.stages[1].calls[1:]] == ["permission", "token_budget"]

    def test_the_budgets_land_on_the_config(self) -> None:
        pipeline = _pipeline()
        apply_overlay(
            pipeline,
            {"budgets": {"maxIterations": 80, "contextWindow": 32768, "costCeiling": 2.5}},
        )
        assert pipeline._config.max_iterations == 80
        assert pipeline._config.context_window_budget == 32768
        assert pipeline._config.cost_budget_usd == 2.5

    def test_a_zero_ceiling_means_no_ceiling(self) -> None:
        pipeline = _pipeline()
        apply_overlay(pipeline, {"budgets": {"costCeiling": 0}})
        assert pipeline._config.cost_budget_usd is None

    def test_a_locked_slot_is_skipped_even_if_it_reached_here(self) -> None:
        """Validation refuses it; apply refuses it again, because a file
        written by an older build must not become a way in."""
        pipeline = _pipeline()
        apply_overlay(pipeline, {"slots": {"6.tool_loop": "internal"}})
        assert pipeline.stages[2].calls == []

    def test_one_stale_key_does_not_cost_the_others(self) -> None:
        """A slot removed from the library between releases must not take
        every other setting the owner made down with it."""
        pipeline = _pipeline()
        applied = apply_overlay(
            pipeline,
            {"slots": {"99.gone": "x", "2.compactor": "truncate", "10.executor": "sequential"}},
        )
        assert applied == ["2.compactor=truncate", "10.executor=sequential"]

    def test_a_config_with_no_strategy_change_still_lands(self) -> None:
        pipeline = _pipeline()
        applied = apply_overlay(
            pipeline, {"slotConfigs": {"10.executor": {"max_concurrency": 4}}}
        )
        assert applied == ["10.executor(config)"]
        assert pipeline.stages[3].calls == [
            ("set", "executor", "partition", {"max_concurrency": 4})
        ]


class TestAPatchIsAPatch:
    def test_one_field_does_not_clear_the_rest(self) -> None:
        current = {"budgets": {"maxIterations": 80}, "slots": {"2.compactor": "truncate"}}
        merged = merge_overlay(current, {"budgets": {"costCeiling": 1.0}})
        assert merged["budgets"] == {"maxIterations": 80, "costCeiling": 1.0}
        assert merged["slots"] == {"2.compactor": "truncate"}

    def test_null_means_go_back_to_inherited(self) -> None:
        current = {"slots": {"2.compactor": "truncate"}}
        merged = merge_overlay(current, {"slots": {"2.compactor": None}})
        assert merged["slots"] == {}

    def test_an_empty_patch_changes_nothing(self) -> None:
        current = {"budgets": {"maxIterations": 80}, "slots": {}, "slotConfigs": {}}
        assert merge_overlay(current, {}) == current


class TestItSurvivesARestart:
    def test_a_round_trip(self, tmp_path: Path) -> None:
        write_overlay(str(tmp_path), {"slots": {"2.compactor": "truncate"}})
        assert read_overlay(str(tmp_path))["slots"] == {"2.compactor": "truncate"}

    def test_nothing_saved_reads_as_nothing_set(self, tmp_path: Path) -> None:
        assert read_overlay(str(tmp_path)) == {}

    def test_a_corrupt_file_reads_as_nothing_set(self, tmp_path: Path) -> None:
        """A session must still start. Losing the settings is recoverable;
        refusing to build is not."""
        (tmp_path / "harness.json").write_text("{not json", encoding="utf-8")
        assert read_overlay(str(tmp_path)) == {}

    def test_it_is_not_the_agents_own_file(self, tmp_path: Path) -> None:
        """The agent rewrites env_overlay.json whole on every self-save. If
        the owner's settings lived there they would vanish."""
        from service.harness.overlay import HARNESS_FILE

        assert HARNESS_FILE != "env_overlay.json"
        write_overlay(str(tmp_path), {"slots": {"2.compactor": "truncate"}})
        assert (tmp_path / HARNESS_FILE).exists()
        assert not (tmp_path / "env_overlay.json").exists()
