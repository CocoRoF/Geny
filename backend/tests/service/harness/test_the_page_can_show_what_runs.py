"""The last mile: a control that cannot render its own value.

The whole harness view exists so a settings page reports what is actually
running rather than what the manifest declared. That was true of the API and
false of the screen: three of the values Geny installs at build time are
INSTANCES, not names the stage's registry knows — ``persisting_llm_summary``,
``memory_aware``, ``geny_dedupe`` — so the dropdown offering only registry
names fell back to its first option. The page said ``llm_summary`` where the
persisting one ran, and a reader who touched the control replaced something
they had never been shown.

Also pinned here: every dynamic i18n key the page builds from this
catalogue. A missing one renders as the raw key, and the keys are generated
from data, so adding a slot to ``BASIC_SLOTS`` without copy is a silent
regression on the screen and nowhere else.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from service.harness import build_harness_view
from service.harness.catalogue import BASIC_SLOTS, LOCKED_SLOTS, RUNTIME_INSTALLED

_I18N = Path(__file__).resolve().parents[3] / ".." / "frontend" / "src" / "lib" / "i18n"

STAGE_NAMES = [
    "input", "context", "system", "guard", "cache", "api", "token", "think",
    "parse", "tool", "tool_review", "agent", "task_registry", "evaluate",
    "hitl", "loop", "emit", "memory", "summarize", "persist", "yield",
]
SOURCES = ["default", "manifest", "runtime", "session", "route", "assumed", "none"]


def _view(slot_name: str, value, options, is_chain_config=None, order=2, name="context"):
    stage = SimpleNamespace(
        order=order, name=name, category="ingress", is_active=True,
        strategies=[SimpleNamespace(
            slot_name=slot_name, current_impl=value,
            available_impls=options, config=is_chain_config or {},
        )],
    )
    return build_harness_view(pipeline=SimpleNamespace(describe=lambda: [stage]))


def _slot(view):
    return view["stages"][0]["slots"][0]


class TestADropdownShowsItsOwnValue:
    def test_an_installed_instance_is_offered(self) -> None:
        slot = _slot(_view("compactor", "persisting_llm_summary",
                           ["llm_summary", "truncate"]))
        names = [o["name"] for o in slot["options"]]
        assert slot["value"] in names, "the control cannot render what runs"
        assert names[0] == "persisting_llm_summary", "and it should lead"

    def test_it_is_marked_as_the_installed_one(self) -> None:
        """So picking another is a visible replacement, not an accident."""
        slot = _slot(_view("compactor", "persisting_llm_summary", ["llm_summary"]))
        assert slot["options"][0]["installed"] is True
        assert all(not o["installed"] for o in slot["options"][1:])

    def test_a_registry_value_is_not_duplicated(self) -> None:
        slot = _slot(_view("compactor", "truncate", ["llm_summary", "truncate"]))
        assert [o["name"] for o in slot["options"]] == ["llm_summary", "truncate"]

    def test_a_chain_is_left_alone(self) -> None:
        """A chain renders as its members, not as a dropdown."""
        # Stage 4's ``guards`` is a real chain, so the catalogue says so.
        slot = _slot(_view("guards", "none", ["token_budget"],
                           {"items": [{"name": "token_budget"}]},
                           order=4, name="guard"))
        assert slot["isChain"] is True
        assert [o["name"] for o in slot["options"]] == ["token_budget"]

    def test_an_empty_value_invents_no_option(self) -> None:
        slot = _slot(_view("retriever", "", ["null", "static"]))
        assert [o["name"] for o in slot["options"]] == ["null", "static"]


class TestEveryKeyThePageBuildsExists:
    """Generated keys, so a catalogue edit without copy shows a raw key on
    the screen and nowhere else."""

    @staticmethod
    def _section(locale: str, name: str) -> set[str]:
        text = (_I18N / f"{locale}.ts").read_text(encoding="utf-8")
        body = re.search(r"\n    harness: \{(.*?)\n    \},\n", text, re.S)
        assert body, f"{locale}: no harness block"
        sub = re.search(rf"\n      {name}: \{{(.*?)\n      \}},", body.group(1), re.S)
        assert sub, f"{locale}: no harness.{name} block"
        return set(re.findall(r"([a-zA-Z0-9_]+)\s*:", sub.group(1)))

    @pytest.mark.parametrize("locale", ["ko", "en"])
    def test_the_questions(self, locale: str) -> None:
        have = self._section(locale, "question")
        assert not set(BASIC_SLOTS.values()) - have

    @pytest.mark.parametrize("locale", ["ko", "en"])
    def test_the_lock_reasons(self, locale: str) -> None:
        have = self._section(locale, "locked")
        assert not set(LOCKED_SLOTS.values()) - have

    @pytest.mark.parametrize("locale", ["ko", "en"])
    def test_what_geny_installs(self, locale: str) -> None:
        have = self._section(locale, "installed")
        assert not set(RUNTIME_INSTALLED.values()) - have

    @pytest.mark.parametrize("locale", ["ko", "en"])
    def test_every_stage_name(self, locale: str) -> None:
        have = self._section(locale, "stage")
        assert not set(STAGE_NAMES) - have

    @pytest.mark.parametrize("locale", ["ko", "en"])
    def test_every_source_the_server_can_report(self, locale: str) -> None:
        """Including the three the budgets use, which the slots never do."""
        have = self._section(locale, "source")
        assert not set(SOURCES) - have
