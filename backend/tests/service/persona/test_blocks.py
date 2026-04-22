"""CreatureState-backed prompt blocks — stub + live rendering.

PR-X3-1 introduced stub blocks. PR-X3-8 (cycle 20260421_9) gave
MoodBlock / RelationshipBlock / VitalsBlock live ``render`` logic that
reads from ``state.shared[CREATURE_STATE_KEY]``. PR-X4-3 (cycle
20260421_10) fills in ProgressionBlock so the LLM gets a narrative
anchor (life stage + age) aligned with the manifest the selector
chose. These tests pin:

1. The classic-mode contract (no creature state in shared → empty
   fragment, composed prompt unchanged). X1's original guarantee.
2. The live-mode output shape for all four blocks: band adjective +
   raw value per axis (Mood/Rel/Vitals), stage + descriptor + age
   (Progression), graceful fall-through when fields are missing.
"""

from __future__ import annotations

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import (
    ComposablePromptBuilder,
    PersonaBlock,
)

from service.persona import (
    AcclimationBlock,
    MoodBlock,
    ProgressionBlock,
    RelationshipBlock,
    VitalsBlock,
)
from service.state import CREATURE_STATE_KEY
from service.state.schema.creature_state import (
    Bond,
    CreatureState,
    Progression,
    Vitals,
)
from service.state.schema.mood import MoodVector


def _state_with_creature(creature: CreatureState) -> PipelineState:
    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = creature
    return state


def _creature(
    *,
    mood: MoodVector | None = None,
    bond: Bond | None = None,
    vitals: Vitals | None = None,
    progression: Progression | None = None,
) -> CreatureState:
    kwargs = dict(
        character_id="c1",
        owner_user_id="u1",
        mood=mood or MoodVector(),
        bond=bond or Bond(),
        vitals=vitals or Vitals(),
    )
    if progression is not None:
        kwargs["progression"] = progression
    return CreatureState(**kwargs)


# ── Classic-mode (no hydrated state) ───────────────────────────────


def test_all_blocks_render_empty_when_no_creature_state() -> None:
    state = PipelineState()
    for block in (
        MoodBlock(),
        RelationshipBlock(),
        VitalsBlock(),
        ProgressionBlock(),
        AcclimationBlock(),
    ):
        assert block.render(state) == ""


def test_names_are_stable_and_unique() -> None:
    names = [
        b.name
        for b in (
            MoodBlock(),
            RelationshipBlock(),
            VitalsBlock(),
            ProgressionBlock(),
            AcclimationBlock(),
        )
    ]
    assert names == ["mood", "relationship", "vitals", "progression", "acclimation"]
    assert len(set(names)) == len(names)


def test_empty_blocks_are_dropped_from_composed_prompt() -> None:
    builder = ComposablePromptBuilder(
        blocks=[
            PersonaBlock("persona-A"),
            MoodBlock(),
            RelationshipBlock(),
            VitalsBlock(),
            ProgressionBlock(),
            AcclimationBlock(),
            PersonaBlock("persona-B"),
        ]
    )
    out = builder.build(PipelineState())
    assert out == "persona-A\n\npersona-B"


def test_progression_block_empty_when_creature_has_no_progression_attr() -> None:
    """Defensive: a programmatic corruption (progression set to None on
    the creature) must not crash render — other live blocks follow the
    same attr-none fall-through."""

    creature = _creature()
    creature.progression = None  # type: ignore[assignment]
    state = _state_with_creature(creature)
    assert ProgressionBlock().render(state) == ""


# ── MoodBlock — live ───────────────────────────────────────────────


def test_mood_block_reports_dominant_emotion_with_value() -> None:
    mood = MoodVector(joy=0.7, calm=0.2)
    out = MoodBlock().render(_state_with_creature(_creature(mood=mood)))
    assert out == "[Mood] joy (0.70)."


def test_mood_block_includes_secondary_when_above_threshold() -> None:
    mood = MoodVector(joy=0.6, excitement=0.4, calm=0.1)
    out = MoodBlock().render(_state_with_creature(_creature(mood=mood)))
    assert out == "[Mood] joy (0.60) with excitement (0.40)."


def test_mood_block_omits_secondary_below_threshold() -> None:
    mood = MoodVector(joy=0.6, excitement=0.1)
    out = MoodBlock().render(_state_with_creature(_creature(mood=mood)))
    assert out == "[Mood] joy (0.60)."


def test_mood_block_reports_calm_when_no_basic_emotion_clears_threshold() -> None:
    mood = MoodVector(joy=0.05, calm=0.9)
    out = MoodBlock().render(_state_with_creature(_creature(mood=mood)))
    assert out == "[Mood] calm."


def test_mood_block_empty_when_creature_has_no_mood_attr() -> None:
    """Defensive: a partially-hydrated creature (mood=None somehow) must
    not blow the block up — return empty so the prompt surface is
    unchanged."""

    class _Partial:
        mood = None

    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _Partial()
    assert MoodBlock().render(state) == ""


# ── RelationshipBlock — live ───────────────────────────────────────


def test_relationship_block_bands_each_axis() -> None:
    bond = Bond(affection=6.5, trust=3.0, familiarity=0.3, dependency=0.0)
    out = RelationshipBlock().render(_state_with_creature(_creature(bond=bond)))
    lines = out.splitlines()
    assert lines[0] == "[Bond with Owner]"
    assert "affection: deep (+6.50)" in lines[1]
    assert "trust: growing (+3.00)" in lines[2]
    assert "familiarity: nascent (+0.30)" in lines[3]
    assert "dependency: none (+0.00)" in lines[4]


def test_relationship_block_band_labels_cover_range() -> None:
    samples = [
        (0.0, "none"),
        (0.3, "nascent"),
        (1.5, "budding"),
        (3.5, "growing"),
        (8.0, "deep"),
        (25.0, "profound"),
    ]
    for value, expected_label in samples:
        bond = Bond(affection=value)
        out = RelationshipBlock().render(_state_with_creature(_creature(bond=bond)))
        assert f"affection: {expected_label}" in out, (value, expected_label, out)


def test_relationship_block_negative_bond_clamps_to_none_label() -> None:
    bond = Bond(affection=-2.0, trust=-0.5)
    out = RelationshipBlock().render(_state_with_creature(_creature(bond=bond)))
    assert "affection: none (-2.00)" in out
    assert "trust: none (-0.50)" in out


# ── VitalsBlock — live ─────────────────────────────────────────────


def test_vitals_block_uses_per_axis_band_semantics() -> None:
    """hunger low = good (sated); energy low = bad (exhausted) — band
    adjective must reflect *felt* state, not raw magnitude."""
    vitals = Vitals(hunger=5.0, energy=15.0, stress=10.0, cleanliness=95.0)
    out = VitalsBlock().render(_state_with_creature(_creature(vitals=vitals)))
    lines = out.splitlines()
    assert lines[0] == "[Vitals]"
    assert "hunger: sated (5/100)" in lines[1]
    assert "energy: exhausted (15/100)" in lines[2]
    assert "stress: calm (10/100)" in lines[3]
    assert "cleanliness: pristine (95/100)" in lines[4]


def test_vitals_block_extreme_highs_use_right_labels() -> None:
    vitals = Vitals(hunger=95.0, energy=95.0, stress=95.0, cleanliness=5.0)
    out = VitalsBlock().render(_state_with_creature(_creature(vitals=vitals)))
    assert "hunger: starving" in out
    assert "energy: peak" in out
    assert "stress: overwhelmed" in out
    assert "cleanliness: filthy" in out


def test_vitals_block_empty_when_creature_has_no_vitals_attr() -> None:
    class _Partial:
        vitals = None

    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _Partial()
    assert VitalsBlock().render(state) == ""


# ── ProgressionBlock — live ────────────────────────────────────────


def test_progression_block_renders_newcomer_register_for_default_creature() -> None:
    """Default creature has ``life_stage="infant"`` (storage key) which
    must surface to the LLM as ``register: newcomer`` — NEVER as
    ``infant`` — so the model doesn't recite newborn-baby tropes
    (cycle 20260422_6 root-cause)."""
    state = _state_with_creature(_creature())
    out = ProgressionBlock().render(state)

    assert "[StageObservation]" in out
    assert "[StageVoiceGuide]" in out
    assert "register: newcomer" in out
    assert "days_in_world: 0" in out
    # The internal storage key must NOT leak to the prompt surface.
    assert "infant" not in out
    # The voice guide must explicitly forbid newborn-baby tropes.
    assert "NEW HERE" in out
    assert "newborn" in out.lower()


def test_progression_block_days_in_world_reflects_age_days() -> None:
    """``days_in_world`` is a neutral counter — not a biological age.
    The render passes the integer through but never frames it as
    'X days old' (which a model can map onto biological age)."""
    cases = [(0, "days_in_world: 0"), (1, "days_in_world: 1"), (4, "days_in_world: 4")]
    for age, expected in cases:
        creature = _creature(progression=Progression(life_stage="infant", age_days=age))
        out = ProgressionBlock().render(_state_with_creature(creature))
        assert expected in out
        # Never 'X day(s) old' — that phrasing implies biological age.
        assert " old." not in out
        assert " days old" not in out


def test_progression_block_each_stage_maps_to_adaptation_register() -> None:
    """All four storage stages must surface as adaptation registers, not
    as biological labels. The mapping is the contract the persona
    files (``vtuber.md``, ``vtuber_characters/*.md``) rely on."""
    cases = [
        ("infant", "newcomer"),
        ("child", "settling"),
        ("teen", "acclimated"),
        ("adult", "rooted"),
    ]
    for stage, expected_register in cases:
        creature = _creature(progression=Progression(life_stage=stage, age_days=2))
        out = ProgressionBlock().render(_state_with_creature(creature))
        assert f"register: {expected_register}" in out, (stage, out)
        # Internal key never leaks.
        assert stage not in out, (stage, out)


def test_progression_block_unknown_stage_falls_back_to_neutral_profile() -> None:
    """Future stages (``"elder"``) or drift-corrupted values must not
    crash render and must NOT leak the unknown key. They fall back to
    the neutral ``undefined`` profile that makes no register claim."""
    creature = _creature(progression=Progression(life_stage="elder", age_days=120))
    out = ProgressionBlock().render(_state_with_creature(creature))
    assert "register: undefined" in out
    assert "days_in_world: 120" in out
    # Internal key must not appear as a register or in the observed line.
    assert "register: elder" not in out
    assert "life_stage: elder" not in out
    assert "[StageVoiceGuide]" in out


def test_progression_block_blank_life_stage_uses_undefined_profile() -> None:
    """Empty ``life_stage`` (pre-seed legacy row) is treated identically
    to an unknown key — neutral profile, no register claim."""
    creature = _creature(progression=Progression(life_stage="", age_days=3))
    out = ProgressionBlock().render(_state_with_creature(creature))
    assert "register: undefined" in out
    assert "days_in_world: 3" in out


def test_progression_block_tolerates_non_int_age_days() -> None:
    """Guard against schema drift / storage coercion returning
    something odd (None, a string). Block must render with
    ``days_in_world: 0`` rather than propagating TypeError into the
    turn."""
    creature = _creature()
    # Bypass dataclass typing on purpose — the guard is the point.
    creature.progression.age_days = None  # type: ignore[assignment]
    state = _state_with_creature(creature)
    out = ProgressionBlock().render(state)
    assert "register: newcomer" in out
    assert "days_in_world: 0" in out


# ── Composition ────────────────────────────────────────────────────


def test_live_blocks_compose_in_order_without_extra_blank_lines() -> None:
    """With a live creature, all four live blocks contribute non-empty
    fragments plus any persona bookends; ComposablePromptBuilder must not
    emit stray double-blank separators."""
    creature = _creature(
        mood=MoodVector(joy=0.8),
        bond=Bond(affection=4.0, trust=1.0),
        vitals=Vitals(hunger=50.0, energy=60.0, stress=20.0, cleanliness=80.0),
        progression=Progression(life_stage="child", age_days=4),
    )
    state = _state_with_creature(creature)

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
    out = builder.build(state)
    assert "persona-A" in out and "persona-B" in out
    assert "[Mood] joy" in out
    assert "[Bond with Owner]" in out
    assert "[Vitals]" in out
    assert "[StageObservation]" in out
    assert "[StageVoiceGuide]" in out
    assert "register: settling" in out
    # No run of three+ newlines (triple-blank from accidental stray ""):
    assert "\n\n\n" not in out


# ── AcclimationBlock — live ────────────────────────────────────────


def test_acclimation_block_first_encounter_band_at_zero_familiarity() -> None:
    """Default Bond (familiarity=0) sits in the ``first-encounter`` band.
    The render must include the band label and the anti-newborn guard
    so the LLM has a concrete instruction to avoid the 갓-태어난 trope."""
    creature = _creature(bond=Bond(familiarity=0.0))
    out = AcclimationBlock().render(_state_with_creature(creature))
    assert "[Acclimation]" in out
    assert "band: first-encounter" in out
    assert "familiarity=0.00" in out
    assert "newborn" in out.lower()
    assert "tentative" in out.lower()


def test_acclimation_block_band_boundaries() -> None:
    """Boundary values land in the *lower* band (≤ ceil)."""
    cases = [
        (0.5, "first-encounter"),
        (0.51, "acclimating"),
        (2.0, "acclimating"),
        (2.01, "acquainted"),
        (5.0, "acquainted"),
        (5.01, "familiar"),
        (10.0, "familiar"),
        (10.01, "intimate"),
        (100.0, "intimate"),
    ]
    for familiarity, expected_band in cases:
        creature = _creature(bond=Bond(familiarity=familiarity))
        out = AcclimationBlock().render(_state_with_creature(creature))
        assert f"band: {expected_band}" in out, (familiarity, expected_band, out)


def test_acclimation_block_negative_familiarity_clamps_to_first_encounter() -> None:
    """Conflict can drive familiarity briefly negative — must not crash
    or fall through to ``unknown``; treat as ``first-encounter`` so the
    safety guidance still applies."""
    creature = _creature(bond=Bond(familiarity=-1.5))
    out = AcclimationBlock().render(_state_with_creature(creature))
    assert "band: first-encounter" in out
    assert "familiarity=-1.50" in out


def test_acclimation_block_empty_when_creature_has_no_bond_attr() -> None:
    """Defensive: bond=None must not blow render up — return empty so
    the prompt surface stays unchanged."""

    class _Partial:
        bond = None

    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _Partial()
    assert AcclimationBlock().render(state) == ""


def test_acclimation_block_empty_when_no_creature_state() -> None:
    """Classic-mode (no creature in shared) returns empty string."""
    assert AcclimationBlock().render(PipelineState()) == ""
