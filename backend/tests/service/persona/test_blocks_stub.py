"""Stub blocks render empty — prompt surface is unchanged in X1."""

from __future__ import annotations

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import (
    ComposablePromptBuilder,
    PersonaBlock,
)

from backend.service.persona import (
    MoodBlock,
    ProgressionBlock,
    RelationshipBlock,
    VitalsBlock,
)


def test_all_stub_blocks_render_empty() -> None:
    state = PipelineState()
    for block in (MoodBlock(), RelationshipBlock(), VitalsBlock(), ProgressionBlock()):
        assert block.render(state) == ""


def test_stub_names_are_stable_and_unique() -> None:
    names = [b.name for b in (MoodBlock(), RelationshipBlock(), VitalsBlock(), ProgressionBlock())]
    assert names == ["mood", "relationship", "vitals", "progression"]
    assert len(set(names)) == len(names)


def test_stubs_are_dropped_from_composed_prompt() -> None:
    """Empty blocks must not leave extra separators in the composed output."""
    builder = ComposablePromptBuilder(
        blocks=[
            PersonaBlock("persona-A"),
            MoodBlock(),
            RelationshipBlock(),
            VitalsBlock(),
            ProgressionBlock(),
            PersonaBlock("persona-B"),
        ]
    )
    out = builder.build(PipelineState())
    assert out == "persona-A\n\npersona-B"
