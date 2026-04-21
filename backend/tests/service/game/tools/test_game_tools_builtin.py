"""Loader-facing module re-exports the four tools (cycle 20260421_9 PR-X3-6).

:class:`~service.tool_loader.ToolLoader` scans ``tools/built_in/*_tools.py``
and reads ``module.TOOLS``. These tests assert that the bridge file at
``backend/tools/built_in/game_tools.py`` exposes the expected four
instances so loader discovery doesn't silently drop tools.
"""

from __future__ import annotations

import importlib


def test_game_tools_module_exposes_TOOLS_list() -> None:
    mod = importlib.import_module("backend.tools.built_in.game_tools")
    assert hasattr(mod, "TOOLS")
    assert isinstance(mod.TOOLS, list)


def test_game_tools_module_exports_four_game_tools() -> None:
    mod = importlib.import_module("backend.tools.built_in.game_tools")
    names = {t.name for t in mod.TOOLS}
    assert names == {"feed", "play", "gift", "talk"}


def test_game_tools_are_expected_classes() -> None:
    """Assert class-name identity rather than ``isinstance`` because the
    loader path and the test path import through two different package
    prefixes (``service.game.tools`` vs ``backend.service.game.tools``)
    and end up with distinct class objects even though they share a
    source file. Production only ever sees one of those paths."""
    mod = importlib.import_module("backend.tools.built_in.game_tools")
    by_name = {t.name: t.__class__.__name__ for t in mod.TOOLS}
    assert by_name == {
        "feed": "FeedTool",
        "play": "PlayTool",
        "gift": "GiftTool",
        "talk": "TalkTool",
    }


def test_game_tools_all_have_parameters_schema() -> None:
    # ToolLoader builds JSON-schema API metadata from ``.parameters`` —
    # if any of the four tools produced an empty or missing schema it
    # would confuse Claude's tool selection and silently break calls.
    mod = importlib.import_module("backend.tools.built_in.game_tools")
    for t in mod.TOOLS:
        assert isinstance(t.parameters, dict)
        assert t.parameters.get("type") == "object"
        assert "properties" in t.parameters
