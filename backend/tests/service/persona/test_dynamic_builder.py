"""DynamicPersonaSystemBuilder — per-turn resolve is reflected in build()."""

from __future__ import annotations

from typing import List

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import (
    DateTimeBlock,
    PersonaBlock,
)

from backend.service.persona import (
    DynamicPersonaSystemBuilder,
    PersonaResolution,
)


class _MutatingProvider:
    """Returns a different persona text on each call."""

    def __init__(self, texts: List[str]):
        self._texts = list(texts)
        self._i = 0

    def resolve(self, state, *, session_meta):
        text = self._texts[self._i]
        self._i = min(self._i + 1, len(self._texts) - 1)
        return PersonaResolution(persona_blocks=[PersonaBlock(text)])


def test_build_calls_provider_each_turn_and_reflects_change() -> None:
    provider = _MutatingProvider(["turn1", "turn2", "turn3"])
    builder = DynamicPersonaSystemBuilder(
        provider, session_meta={"session_id": "s1"}
    )
    state = PipelineState()
    t1 = builder.build(state)
    t2 = builder.build(state)
    t3 = builder.build(state)
    assert isinstance(t1, str) and "turn1" in t1
    assert "turn2" in t2
    assert "turn3" in t3
    assert t1 != t2 != t3


def test_tail_blocks_appended_after_persona() -> None:
    provider = _MutatingProvider(["PERSONA"])
    builder = DynamicPersonaSystemBuilder(
        provider,
        session_meta={"session_id": "s"},
        tail_blocks=[DateTimeBlock()],
    )
    out = builder.build(PipelineState())
    assert isinstance(out, str)
    assert out.index("PERSONA") < out.index("Current date:")


def test_system_tail_text_rendered_last() -> None:
    class _P:
        def resolve(self, state, *, session_meta):
            return PersonaResolution(
                persona_blocks=[PersonaBlock("A")],
                system_tail="ZZ-TAIL",
            )

    builder = DynamicPersonaSystemBuilder(
        _P(),
        session_meta={"session_id": "s"},
        tail_blocks=[DateTimeBlock()],
    )
    out = builder.build(PipelineState())
    assert isinstance(out, str)
    # tail after date block
    assert out.index("Current date:") < out.index("ZZ-TAIL")


def test_content_blocks_mode_returns_list() -> None:
    provider = _MutatingProvider(["HELLO"])
    builder = DynamicPersonaSystemBuilder(
        provider,
        session_meta={"session_id": "s"},
        use_content_blocks=True,
    )
    out = builder.build(PipelineState())
    assert isinstance(out, list)
    assert out[0]["type"] == "text"
    assert out[0]["text"] == "HELLO"


def test_session_meta_is_passed_to_provider() -> None:
    seen: dict = {}

    class _P:
        def resolve(self, state, *, session_meta):
            seen.update(session_meta)
            return PersonaResolution()

    builder = DynamicPersonaSystemBuilder(
        _P(),
        session_meta={"session_id": "abc", "is_vtuber": True, "character_id": "c42"},
    )
    builder.build(PipelineState())
    assert seen == {"session_id": "abc", "is_vtuber": True, "character_id": "c42"}


def test_session_meta_is_isolated_from_caller_mutation() -> None:
    """Builder must copy its session_meta so later caller edits don't leak in."""
    sm = {"session_id": "orig"}
    builder = DynamicPersonaSystemBuilder(
        _MutatingProvider(["x"]),
        session_meta=sm,
    )
    sm["session_id"] = "mutated"
    assert builder.session_meta["session_id"] == "orig"


def test_empty_resolution_produces_empty_prompt_with_no_tail() -> None:
    class _Empty:
        def resolve(self, state, *, session_meta):
            return PersonaResolution()

    out = DynamicPersonaSystemBuilder(_Empty(), session_meta={}).build(PipelineState())
    assert out == ""
