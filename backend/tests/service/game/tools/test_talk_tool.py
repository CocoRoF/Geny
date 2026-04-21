"""TalkTool behaviour (cycle 20260421_9 PR-X3-6)."""

from __future__ import annotations

from backend.service.game.tools import TalkTool
from backend.service.game.tools.talk import FAMILIARITY_DELTA

from ._helpers import bound_buffer, by_path


def test_talk_greet_bumps_familiarity_and_records_event() -> None:
    with bound_buffer() as buf:
        result = TalkTool().run(kind="greet")

    assert "TALK_OK kind=greet" in result
    fam = by_path(buf, "bond.familiarity")
    events = by_path(buf, "recent_events")
    assert len(fam) == 1 and fam[0].value == FAMILIARITY_DELTA
    assert events[0].value == "talk:greet"


def test_talk_topic_shift_includes_topic_in_tag_when_given() -> None:
    with bound_buffer() as buf:
        TalkTool().run(kind="topic_shift", topic="weather")
    events = by_path(buf, "recent_events")
    assert events[0].value == "talk:topic_shift:weather"


def test_talk_topic_is_optional() -> None:
    with bound_buffer() as buf:
        TalkTool().run(kind="farewell")
    events = by_path(buf, "recent_events")
    assert events[0].value == "talk:farewell"


def test_talk_unknown_kind_coerces_to_check_in() -> None:
    with bound_buffer() as buf:
        result = TalkTool().run(kind="scream_at_stars")
    assert "kind=check_in" in result
    events = by_path(buf, "recent_events")
    assert events[0].value == "talk:check_in"


def test_talk_sources_are_tool_talk() -> None:
    with bound_buffer() as buf:
        TalkTool().run(kind="greet", topic="opening")
    for m in buf.items:
        assert m.source == "tool:talk"


def test_talk_mutates_bond_not_vitals() -> None:
    with bound_buffer() as buf:
        TalkTool().run(kind="greet")
    assert by_path(buf, "vitals.hunger") == []
    assert by_path(buf, "vitals.energy") == []
    assert by_path(buf, "vitals.stress") == []


def test_talk_without_buffer_returns_narrated_only() -> None:
    result = TalkTool().run(kind="greet")
    assert "TALK_NARRATED_ONLY" in result
    assert "state unavailable" in result
