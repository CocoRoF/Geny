"""CreatureState-backed prompt blocks.

Three of these (``MoodBlock`` / ``RelationshipBlock`` / ``VitalsBlock``)
read the hydrated :class:`CreatureState` out of ``state.shared`` and
render a compact system-prompt fragment. When no creature state is
hydrated (classic-mode sessions, or hydrate failed), ``render`` returns
``""`` — the ``ComposablePromptBuilder`` drops empty fragments, keeping
the prompt surface unchanged so non-game sessions are untouched.

``ProgressionBlock`` remains a no-op; X4 fills it from
``CreatureState.progression`` when manifest selection goes live.

The block identity (class names, ``name`` property) is stable across
X1 → X3 so the builder slot order that X1 already reserved is preserved.
"""

from __future__ import annotations

from typing import Any, Iterable

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.interface import PromptBlock

from backend.service.state import CREATURE_STATE_KEY

_MOOD_DOMINANT_THRESHOLD: float = 0.15
_MOOD_SECONDARY_THRESHOLD: float = 0.25

_BOND_BANDS: tuple[tuple[float, str], ...] = (
    (0.5, "nascent"),
    (2.0, "budding"),
    (5.0, "growing"),
    (10.0, "deep"),
    (float("inf"), "profound"),
)

_HUNGER_BANDS: tuple[tuple[float, str], ...] = (
    (20.0, "sated"),
    (40.0, "satisfied"),
    (60.0, "peckish"),
    (80.0, "hungry"),
    (float("inf"), "starving"),
)

_ENERGY_BANDS: tuple[tuple[float, str], ...] = (
    (20.0, "exhausted"),
    (40.0, "tired"),
    (60.0, "steady"),
    (80.0, "rested"),
    (float("inf"), "peak"),
)

_STRESS_BANDS: tuple[tuple[float, str], ...] = (
    (20.0, "calm"),
    (40.0, "tense"),
    (60.0, "strained"),
    (80.0, "distressed"),
    (float("inf"), "overwhelmed"),
)

_CLEANLINESS_BANDS: tuple[tuple[float, str], ...] = (
    (20.0, "filthy"),
    (40.0, "grimy"),
    (60.0, "okay"),
    (80.0, "clean"),
    (float("inf"), "pristine"),
)


def _band(value: float, bands: Iterable[tuple[float, str]]) -> str:
    for ceiling, label in bands:
        if value <= ceiling:
            return label
    return "unknown"


def _bond_band(value: float) -> str:
    # Bond values can be negative (conflicts); treat everything <= 0 as
    # the weakest band so the prompt never implies a backwards direction
    # of trust/affection via a positive-only label.
    if value <= 0.0:
        return "none"
    return _band(value, _BOND_BANDS)


def _get_creature_state(state: PipelineState) -> Any:
    shared = getattr(state, "shared", None)
    if not isinstance(shared, dict):
        return None
    return shared.get(CREATURE_STATE_KEY)


class MoodBlock(PromptBlock):
    """Current mood vector → single-line summary.

    Uses :meth:`MoodVector.dominant` to pick the strongest emotion
    above ``_MOOD_DOMINANT_THRESHOLD``; when no basic emotion clears
    the threshold the creature is reported as ``calm``. A secondary
    emotion (second-strongest basic key above a higher threshold) is
    appended so the LLM has texture, e.g. ``joy with excitement``.
    """

    @property
    def name(self) -> str:
        return "mood"

    def render(self, state: PipelineState) -> str:
        creature = _get_creature_state(state)
        mood = getattr(creature, "mood", None) if creature is not None else None
        if mood is None:
            return ""

        dominant = mood.dominant(threshold=_MOOD_DOMINANT_THRESHOLD)
        dominant_val = getattr(mood, dominant, 0.0)

        basic_keys = ("joy", "sadness", "anger", "fear", "excitement")
        secondary = None
        secondary_val = 0.0
        for key in basic_keys:
            if key == dominant:
                continue
            val = getattr(mood, key, 0.0)
            if val > secondary_val and val >= _MOOD_SECONDARY_THRESHOLD:
                secondary = key
                secondary_val = val

        if dominant == "calm":
            return "[Mood] calm."
        if secondary is None:
            return f"[Mood] {dominant} ({dominant_val:.2f})."
        return (
            f"[Mood] {dominant} ({dominant_val:.2f}) "
            f"with {secondary} ({secondary_val:.2f})."
        )


class RelationshipBlock(PromptBlock):
    """Bond snapshot toward the owner.

    Emits one line per bond axis with a qualitative band label *and* the
    raw value. Bands compress well (the LLM can act on "profound trust"
    at a glance) while the number stays present so tonal edge-cases
    don't collapse — e.g. the LLM can still distinguish 5.1 from 9.9 if
    it needs to.
    """

    @property
    def name(self) -> str:
        return "relationship"

    def render(self, state: PipelineState) -> str:
        creature = _get_creature_state(state)
        bond = getattr(creature, "bond", None) if creature is not None else None
        if bond is None:
            return ""

        lines = ["[Bond with Owner]"]
        for axis in ("affection", "trust", "familiarity", "dependency"):
            val = float(getattr(bond, axis, 0.0))
            lines.append(f"- {axis}: {_bond_band(val)} ({val:+.2f})")
        return "\n".join(lines)


class VitalsBlock(PromptBlock):
    """Physical vitals snapshot.

    Per-axis semantics intentionally differ — low *hunger* is good
    (sated) but low *energy* is bad (exhausted). Each axis therefore
    has its own band table so the adjective reflects the creature's
    lived experience, not the raw number.
    """

    @property
    def name(self) -> str:
        return "vitals"

    def render(self, state: PipelineState) -> str:
        creature = _get_creature_state(state)
        vitals = getattr(creature, "vitals", None) if creature is not None else None
        if vitals is None:
            return ""

        hunger = float(getattr(vitals, "hunger", 0.0))
        energy = float(getattr(vitals, "energy", 0.0))
        stress = float(getattr(vitals, "stress", 0.0))
        cleanliness = float(getattr(vitals, "cleanliness", 0.0))

        return (
            "[Vitals]\n"
            f"- hunger: {_band(hunger, _HUNGER_BANDS)} ({hunger:.0f}/100)\n"
            f"- energy: {_band(energy, _ENERGY_BANDS)} ({energy:.0f}/100)\n"
            f"- stress: {_band(stress, _STRESS_BANDS)} ({stress:.0f}/100)\n"
            f"- cleanliness: {_band(cleanliness, _CLEANLINESS_BANDS)} ({cleanliness:.0f}/100)"
        )


class ProgressionBlock(PromptBlock):
    """Life-stage / manifest hints. No-op in X3; X4 fills from CreatureState.progression."""

    @property
    def name(self) -> str:
        return "progression"

    def render(self, state: PipelineState) -> str:
        return ""
