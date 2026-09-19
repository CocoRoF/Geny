"""The page has to show what runs, not what was declared.

Geny puts placeholders in its one manifest and installs the real
implementations when a session is built — the guard chain, the session's file
persister, the HITL resume requester, the persisting compactor, the affect
emitter. A page rendered from the manifest shows ``no_persist`` on a stage
that persists and an empty guard chain on a session that guards: the same
class of mistake as drawing a switch from a sparse override, which is how the
capability toggles ended up lying last week.

So the view is built from the LIVE pipeline, and every value says where it
came from — because knowing what runs is only half of what a settings page
owes the reader. The other half is whether changing it will stick.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from service.harness import build_harness_view, slot_catalogue, tier_of
from service.harness.catalogue import BASIC_SLOTS, LOCKED_SLOTS, RUNTIME_INSTALLED


def _slot(name: str, impl: Any, options: List[str], config: Dict[str, Any] | None = None):
    return SimpleNamespace(
        slot_name=name, current_impl=impl, available_impls=options, config=config or {}
    )


def _pipeline(*descriptions):
    return SimpleNamespace(describe=lambda: list(descriptions))


def _stage(order: int, name: str, slots, category: str = "execution", active: bool = True):
    return SimpleNamespace(
        order=order, name=name, category=category, is_active=active, strategies=slots
    )


def _manifest(per_order: Dict[int, Dict[str, Any]] | None = None):
    entries = [
        SimpleNamespace(order=o, strategies=v.get("strategies", {}),
                        config=v.get("config", {}), strategy_configs={},
                        chain_order=v.get("chains", {}), active=True)
        for o, v in (per_order or {}).items()
    ]
    return SimpleNamespace(stage_entries=lambda: entries)


def _find(view, order: int, slot: str):
    for stage in view["stages"]:
        if stage["order"] == order:
            for s in stage["slots"]:
                if s["slot"] == slot:
                    return s
    raise AssertionError(f"{order}.{slot} not in the view")


class TestWhereEachValueCameFrom:
    def test_the_manifest_gets_the_credit_when_it_matches(self) -> None:
        view = build_harness_view(
            pipeline=_pipeline(_stage(18, "memory", [_slot("strategy", "reflective", ["reflective"])])),
            manifest=_manifest({18: {"strategies": {"strategy": "reflective"}}}),
        )
        assert _find(view, 18, "strategy")["source"] == "manifest"

    def test_a_value_nobody_declared_is_the_stages_own(self) -> None:
        view = build_harness_view(
            pipeline=_pipeline(_stage(9, "parse", [_slot("parser", "default", ["default"])])),
            manifest=_manifest(),
        )
        assert _find(view, 9, "parser")["source"] == "default"

    def test_a_live_value_the_manifest_did_not_ask_for_is_runtime(self) -> None:
        """This is the case that made the whole view necessary: the manifest
        says ``no_persist`` and the running session writes files."""
        view = build_harness_view(
            pipeline=_pipeline(_stage(20, "persist", [_slot("persister", "file", ["file", "no_persist"])])),
            manifest=_manifest({20: {"strategies": {"persister": "no_persist"}}}),
        )
        slot = _find(view, 20, "persister")
        assert slot["value"] == "file"
        assert slot["source"] == "runtime"

    def test_the_sessions_own_choice_outranks_both(self) -> None:
        view = build_harness_view(
            pipeline=_pipeline(_stage(2, "context", [_slot("compactor", "truncate", ["truncate"])])),
            manifest=_manifest({2: {"strategies": {"compactor": "llm_summary"}}}),
            overlay={"config": {"slots": {"2.compactor": "truncate"}}},
        )
        assert _find(view, 2, "compactor")["source"] == "session"

    def test_a_slot_geny_installs_says_so_even_when_it_matches(self) -> None:
        """``2.compactor`` is on the install list. Reporting ``manifest``
        would tell the reader their change will stick, and it will not."""
        view = build_harness_view(
            pipeline=_pipeline(_stage(2, "context", [_slot("compactor", "llm_summary", ["llm_summary"])])),
            manifest=_manifest({2: {"strategies": {"compactor": "llm_summary"}}}),
        )
        slot = _find(view, 2, "compactor")
        assert slot["source"] == "runtime"
        assert slot["installedBy"] == "persistingCompactor"


class TestWhatAPersonIsOffered:
    def test_the_loop_is_not_a_setting(self) -> None:
        """A provider may be a model; it may not be an agent. Handing the
        tool loop to the backend costs the conversation its portability, its
        permission ladder and its memory in one move."""
        view = build_harness_view(
            pipeline=_pipeline(
                _stage(6, "api", [_slot("tool_loop", "pipeline", ["internal", "pipeline"])])
            ),
        )
        slot = _find(view, 6, "tool_loop")
        assert slot["tier"] == "locked"
        assert slot["lockedBecause"] == "weOwnTheLoop"

    def test_the_common_ones_are_on_the_first_screen(self) -> None:
        assert tier_of(2, "compactor") == "basic"
        assert tier_of(14, "strategy") == "basic"

    def test_an_unlisted_slot_lands_one_screen_deeper_not_nowhere(self) -> None:
        """A stage added to the library without an edit here still renders."""
        assert tier_of(99, "something-new") == "advanced"

    def test_a_basic_slot_carries_the_question_it_answers(self) -> None:
        view = build_harness_view(
            pipeline=_pipeline(_stage(10, "tool", [_slot("executor", "partition", ["partition"])])),
        )
        assert _find(view, 10, "executor")["question"] == "toolsAtOnce"


class TestAChainRendersAsItsMembers:
    def test_the_installed_order_is_the_value(self) -> None:
        view = build_harness_view(
            pipeline=_pipeline(
                _stage(4, "guard", [
                    _slot("guards", "none", ["token_budget", "permission"],
                          {"items": [{"name": "token_budget"}, {"name": "permission"}]})
                ], category="pre_flight")
            ),
        )
        slot = _find(view, 4, "guards")
        assert slot["isChain"] is True
        assert slot["value"] == ["token_budget", "permission"]


class TestTheCatalogueComesFromTheLibrary:
    """Descriptions copied into Geny are descriptions that stop matching the
    code they describe."""

    def test_it_knows_the_real_slots(self) -> None:
        catalogue = slot_catalogue()
        assert "4.guards" in catalogue
        assert "6.tool_loop" in catalogue

    def test_it_carries_the_config_forms(self) -> None:
        schemas = slot_catalogue()["4.guards"]["implSchemas"]
        fields = {f["name"] for f in schemas["token_budget"]["fields"]}
        assert "min_remaining_tokens" in fields

    @pytest.mark.parametrize("key", sorted({*BASIC_SLOTS, *LOCKED_SLOTS, *RUNTIME_INSTALLED}))
    def test_every_slot_we_name_actually_exists(self, key) -> None:
        """A catalogue entry for a slot the library does not have is a claim
        about a screen nobody will ever see."""
        order, slot = key
        assert f"{order}.{slot}" in slot_catalogue(), f"{order}.{slot}"


class TestTheWholePipelineIsShown:
    def test_a_slot_with_no_stage_behind_it_still_gets_a_row(self) -> None:
        view = build_harness_view(
            pipeline=_pipeline(
                _stage(13, "task_registry", [], category="unregistered", active=False)
            ),
        )
        assert view["stages"][0]["active"] is False
        assert view["stages"][0]["slots"] == []

    def test_the_budgets_ride_along(self) -> None:
        view = build_harness_view(
            pipeline=_pipeline(), budgets={"maxIterations": {"value": 50}}
        )
        assert view["budgets"]["maxIterations"]["value"] == 50
