"""How much of the previous turns an agent sees again is the owner's call,
and the page has to be able to make it — and refuse what would not work.

The replay (executor ``replay`` slot on Stage 2) is what brings the last
turns back in front of a fresh turn. Its settings travel as ``slotConfigs``;
the strategy silently keeps its old value when handed a bad one, so the
server is where a bad value has to be refused, or the page reports "saved"
for a change that does nothing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from geny_executor.stages.s02_context.artifact.default.stage import ContextStage

from service.harness.catalogue import tier_of
from service.harness.overlay import HarnessRejected, apply_overlay, validate_overlay
from service.harness.view import build_harness_view


def _pipeline():
    stage = ContextStage()
    return SimpleNamespace(stages=[stage], describe=lambda: [stage.describe()]), stage


def _replay_config(stage) -> dict:
    for info in stage.describe().strategies:
        if info.slot_name == "replay":
            return dict(info.config)
    raise AssertionError("no replay slot")


class TestItIsOnTheFirstScreen:
    def test_the_replay_is_a_basic_question(self) -> None:
        assert tier_of(2, "replay") == "basic"


class TestWhatIsRefused:
    @pytest.mark.parametrize(
        "config",
        [
            {"full_turns": 99},
            {"dialogue_turns": -1},
            {"window_share": 0.9},
            {"window_share": "half"},
            {"full_turns": 2.5},
            {"silent_markers": "[SILENT]"},
        ],
    )
    def test_a_value_the_strategy_would_ignore(self, config) -> None:
        pipeline, _ = _pipeline()
        with pytest.raises(HarnessRejected):
            validate_overlay({"slotConfigs": {"2.replay": config}}, pipeline=pipeline)

    def test_a_good_value_passes(self) -> None:
        pipeline, _ = _pipeline()
        validate_overlay(
            {"slotConfigs": {"2.replay": {"full_turns": 3, "window_share": 0.1}}},
            pipeline=pipeline,
        )


class TestItLands:
    def test_the_setting_reaches_the_live_strategy(self) -> None:
        pipeline, stage = _pipeline()
        apply_overlay(
            pipeline,
            {"slotConfigs": {"2.replay": {"full_turns": 3, "dialogue_turns": 1}}},
        )
        config = _replay_config(stage)
        assert (config["full_turns"], config["dialogue_turns"]) == (3, 1)

    def test_a_changed_setting_is_marked_as_the_owners(self) -> None:
        """Without this the page offered no way back from a config-only
        change: the implementation had not changed, so it read as default."""
        pipeline, stage = _pipeline()
        overlay = {"slotConfigs": {"2.replay": {"full_turns": 3}}}
        apply_overlay(pipeline, overlay)
        view = build_harness_view(pipeline=pipeline, overlay=overlay)
        slot = next(
            s for st in view["stages"] for s in st["slots"] if s["slot"] == "replay"
        )
        assert slot["source"] == "session"
        assert slot["tier"] == "basic" and slot["question"] == "recentTurns"
        schema = next(o["schema"] for o in slot["options"] if o["name"] == "turn_window")
        assert {f["name"] for f in schema["fields"]} >= {"full_turns", "dialogue_turns", "window_share"}
