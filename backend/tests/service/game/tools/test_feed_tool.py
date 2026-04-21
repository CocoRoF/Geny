"""FeedTool behaviour (cycle 20260421_9 PR-X3-6)."""

from __future__ import annotations

from backend.service.game.tools import FeedTool
from backend.service.game.tools.rules import FEED_RULES

from ._helpers import bound_buffer, by_path


def test_feed_meal_pushes_hunger_affection_and_event() -> None:
    with bound_buffer() as buf:
        tool = FeedTool()
        result = tool.run(kind="meal")

    assert "FEED_OK kind=meal pleasure=medium" in result

    hunger = by_path(buf, "vitals.hunger")
    affection = by_path(buf, "bond.affection")
    events = by_path(buf, "recent_events")

    assert len(hunger) == 1 and hunger[0].op == "add"
    assert hunger[0].value == FEED_RULES["meal"].hunger_delta
    assert len(affection) == 1 and affection[0].op == "add"
    assert affection[0].value == FEED_RULES["meal"].affection_delta
    assert len(events) == 1 and events[0].op == "append"
    assert events[0].value == "fed:meal"


def test_feed_default_kind_is_snack() -> None:
    with bound_buffer() as buf:
        result = FeedTool().run()
    assert "kind=snack" in result
    events = by_path(buf, "recent_events")
    assert events[0].value == "fed:snack"


def test_feed_unknown_kind_falls_back_to_snack() -> None:
    with bound_buffer() as buf:
        result = FeedTool().run(kind="ambrosia")
    events = by_path(buf, "recent_events")
    assert events[0].value == "fed:ambrosia"
    hunger = by_path(buf, "vitals.hunger")
    assert hunger[0].value == FEED_RULES["snack"].hunger_delta
    assert "pleasure=low" in result


def test_feed_medicine_skips_hunger_mutation_but_keeps_event() -> None:
    with bound_buffer() as buf:
        FeedTool().run(kind="medicine")
    assert by_path(buf, "vitals.hunger") == []
    events = by_path(buf, "recent_events")
    assert events[0].value == "fed:medicine"


def test_feed_sources_are_tool_feed() -> None:
    with bound_buffer() as buf:
        FeedTool().run(kind="favorite")
    for m in buf.items:
        assert m.source == "tool:feed"


def test_feed_without_buffer_returns_narrated_only() -> None:
    # No bind — tool must degrade gracefully so classic sessions
    # (no state provider) still run without crashing.
    tool = FeedTool()
    result = tool.run(kind="meal")
    assert "FEED_NARRATED_ONLY" in result
    assert "kind=meal" in result
    assert "pleasure=medium" in result
    assert "state unavailable" in result


def test_feed_name_and_description_populated() -> None:
    tool = FeedTool()
    assert tool.name == "feed"
    assert "food" in tool.description.lower()
