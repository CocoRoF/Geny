"""GiftTool behaviour (cycle 20260421_9 PR-X3-6)."""

from __future__ import annotations

from backend.service.game.tools import GiftTool
from backend.service.game.tools.rules import GIFT_RULES

from ._helpers import bound_buffer, by_path


def test_gift_flower_hits_affection_trust_joy_and_event() -> None:
    with bound_buffer() as buf:
        result = GiftTool().run(kind="flower")
    rule = GIFT_RULES["flower"]

    assert "GIFT_OK kind=flower pleasure=medium" in result
    assert by_path(buf, "bond.affection")[0].value == rule.affection_delta
    assert by_path(buf, "bond.trust")[0].value == rule.trust_delta
    assert by_path(buf, "mood.joy")[0].value == rule.joy_delta
    assert by_path(buf, "recent_events")[0].value == "gift:flower"


def test_gift_letter_bumps_trust_most_of_all_gifts() -> None:
    with bound_buffer() as buf:
        GiftTool().run(kind="letter")
    trust_mutation = by_path(buf, "bond.trust")[0]
    assert trust_mutation.value == GIFT_RULES["letter"].trust_delta


def test_gift_default_is_flower() -> None:
    with bound_buffer() as buf:
        GiftTool().run()
    assert by_path(buf, "recent_events")[0].value == "gift:flower"


def test_gift_unknown_falls_back_to_flower() -> None:
    with bound_buffer() as buf:
        GiftTool().run(kind="diamond_ring")
    assert by_path(buf, "recent_events")[0].value == "gift:diamond_ring"
    assert by_path(buf, "bond.affection")[0].value == GIFT_RULES["flower"].affection_delta


def test_gift_sources_are_tool_gift() -> None:
    with bound_buffer() as buf:
        GiftTool().run(kind="toy")
    for m in buf.items:
        assert m.source == "tool:gift"


def test_gift_without_buffer_returns_narrated_only() -> None:
    result = GiftTool().run(kind="accessory")
    assert "GIFT_NARRATED_ONLY" in result
    assert "kind=accessory" in result
    assert "state unavailable" in result
