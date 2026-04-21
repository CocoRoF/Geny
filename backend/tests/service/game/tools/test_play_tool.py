"""PlayTool behaviour (cycle 20260421_9 PR-X3-6)."""

from __future__ import annotations

from backend.service.game.tools import PlayTool
from backend.service.game.tools.rules import PLAY_RULES

from ._helpers import bound_buffer, by_path


def test_play_cuddle_pushes_stress_energy_affection_and_event() -> None:
    with bound_buffer() as buf:
        result = PlayTool().run(kind="cuddle")

    assert "PLAY_OK kind=cuddle pleasure=medium" in result
    rule = PLAY_RULES["cuddle"]
    assert by_path(buf, "vitals.stress")[0].value == rule.stress_delta
    assert by_path(buf, "vitals.energy")[0].value == rule.energy_delta
    assert by_path(buf, "bond.affection")[0].value == rule.affection_delta
    assert by_path(buf, "recent_events")[0].value == "played:cuddle"


def test_play_tease_raises_stress_and_drops_affection() -> None:
    with bound_buffer() as buf:
        PlayTool().run(kind="tease")
    assert by_path(buf, "vitals.stress")[0].value > 0
    assert by_path(buf, "bond.affection")[0].value < 0


def test_play_default_is_cuddle() -> None:
    with bound_buffer() as _:
        result = PlayTool().run()
    assert "kind=cuddle" in result


def test_play_unknown_falls_back_to_cuddle() -> None:
    with bound_buffer() as buf:
        result = PlayTool().run(kind="parkour")
    assert by_path(buf, "recent_events")[0].value == "played:parkour"
    rule = PLAY_RULES["cuddle"]
    assert by_path(buf, "vitals.stress")[0].value == rule.stress_delta
    assert "pleasure=medium" in result


def test_play_all_sources_are_tool_play() -> None:
    with bound_buffer() as buf:
        PlayTool().run(kind="game")
    for m in buf.items:
        assert m.source == "tool:play"


def test_play_without_buffer_returns_narrated_only() -> None:
    result = PlayTool().run(kind="fetch")
    assert "PLAY_NARRATED_ONLY" in result
    assert "kind=fetch" in result
    assert "state unavailable" in result
