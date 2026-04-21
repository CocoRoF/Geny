"""CreatureState-backed prompt blocks — no-op stubs for X1.

Each block reads a well-known key from ``state.shared`` and renders a short
text fragment. In X1 the keys are not yet populated (X3 introduces
``SessionRuntimeRegistry.hydrate`` which writes ``state.shared['creature_state']``),
so ``render`` returns ``""`` — the ``ComposablePromptBuilder`` drops empty
fragments, keeping the prompt surface unchanged.

X3/X4 replaces each stub's ``render`` with real formatting logic; the class
identity and name property stay the same so the X1 composition already
reserves the slot order.
"""

from __future__ import annotations

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.interface import PromptBlock


class MoodBlock(PromptBlock):
    """Current mood vector. No-op in X1; X3 fills from CreatureState.mood."""

    @property
    def name(self) -> str:
        return "mood"

    def render(self, state: PipelineState) -> str:
        return ""


class RelationshipBlock(PromptBlock):
    """Bond level + owner recognition. No-op in X1; X3 fills from CreatureState.bond."""

    @property
    def name(self) -> str:
        return "relationship"

    def render(self, state: PipelineState) -> str:
        return ""


class VitalsBlock(PromptBlock):
    """Hunger / energy / cleanliness. No-op in X1; X3 fills from CreatureState.vitals."""

    @property
    def name(self) -> str:
        return "vitals"

    def render(self, state: PipelineState) -> str:
        return ""


class ProgressionBlock(PromptBlock):
    """Life-stage / manifest hints. No-op in X1; X4 fills from CreatureState.progression."""

    @property
    def name(self) -> str:
        return "progression"

    def render(self, state: PipelineState) -> str:
        return ""
