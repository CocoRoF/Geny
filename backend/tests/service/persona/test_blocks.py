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

from backend.service.persona import (
    MoodBlock,
    ProgressionBlock,
    RelationshipBlock,
    VitalsBlock,
)
from backend.service.state import CREATURE_STATE_KEY
from backend.service.state.schema.creature_state import (
    Bond,
    CreatureState,
    Progression,
    Vitals,
)
from backend.service.state.schema.mood import MoodVector


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
    for block in (MoodBlock(), RelationshipBlock(), VitalsBlock(), ProgressionBlock()):
        assert block.render(state) == ""


def test_names_are_stable_and_unique() -> None:
    names = [b.name for b in (MoodBlock(), RelationshipBlock(), VitalsBlock(), ProgressionBlock())]
    assert names == ["mood", "relationship", "vitals", "progression"]
    assert len(set(names)) == len(names)


def test_empty_blocks_are_dropped_from_composed_prompt() -> None:
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


def test_progression_block_renders_infant_default_creature() -> None:
    """Default creature is infant at 0 days — the selector starts here
    before any transition fires (PR-X4-1 default tree)."""
    state = _state_with_creature(_creature())
    out = ProgressionBlock().render(state)
    assert out == "[Stage] infant (just a baby) — 0 days old."


def test_progression_block_pluralises_day_correctly() -> None:
    """``age_days == 1`` uses the singular 'day'; everything else uses
    'days'. Bad English in prompts nudges LLMs toward mimicking the
    same mistake in their output."""
    one_day = _creature(
        progression=Progression(life_stage="infant", age_days=1)
    )
    zero_days = _creature(
        progression=Progression(life_stage="infant", age_days=0)
    )
    many_days = _creature(
        progression=Progression(life_stage="child", age_days=4)
    )

    assert "1 day old" in ProgressionBlock().render(_state_with_creature(one_day))
    assert "0 days old" in ProgressionBlock().render(_state_with_creature(zero_days))
    assert "4 days old" in ProgressionBlock().render(_state_with_creature(many_days))


def test_progression_block_renders_each_documented_stage() -> None:
    """All four plan/04 §7.3 stages have a descriptor. The descriptor
    is what differentiates turns once the manifest (PR-X4-2) has
    picked its knobs — block is the narrative counterpart."""
    cases = [
        ("infant", 2, "just a baby"),
        ("child", 5, "curious and learning"),
        ("teen", 18, "emotionally in flux"),
        ("adult", 60, "mature"),
    ]
    for stage, age, descriptor in cases:
        creature = _creature(
            progression=Progression(life_stage=stage, age_days=age)
        )
        out = ProgressionBlock().render(_state_with_creature(creature))
        assert out == f"[Stage] {stage} ({descriptor}) — {age} days old.", (
            f"{stage}: got {out!r}"
        )


def test_progression_block_unknown_stage_falls_back_to_bare_keyword() -> None:
    """Future stages (e.g. ``"elder"``) or drift-corrupted values must
    not crash render — the block should degrade to the bare keyword
    without a descriptor. Same "never raises in render" stance the
    selector itself takes."""
    creature = _creature(
        progression=Progression(life_stage="elder", age_days=120)
    )
    out = ProgressionBlock().render(_state_with_creature(creature))
    assert out == "[Stage] elder — 120 days old."
    # Descriptor parens explicitly absent — don't leak an empty " ()".
    assert "()" not in out


def test_progression_block_blank_life_stage_reports_unknown() -> None:
    """Creature hydrated with empty ``life_stage`` (pre-seed legacy row):
    render carries an explicit ``unknown`` anchor so the LLM isn't
    silently told it has no stage at all."""
    creature = _creature(
        progression=Progression(life_stage="", age_days=3)
    )
    out = ProgressionBlock().render(_state_with_creature(creature))
    assert out == "[Stage] unknown — 3 days old."


def test_progression_block_tolerates_non_int_age_days() -> None:
    """Guard against schema drift / storage coercion returning
    something odd (None, a string). Block renders ``0 days old``
    rather than propagating TypeError into the turn."""
    creature = _creature()
    # Bypass dataclass typing on purpose — the guard is the point.
    creature.progression.age_days = None  # type: ignore[assignment]
    state = _state_with_creature(creature)
    assert ProgressionBlock().render(state) == (
        "[Stage] infant (just a baby) — 0 days old."
    )


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
    assert "[Stage] child (curious and learning) — 4 days old." in out
    # No run of three+ newlines (triple-blank from accidental stray ""):
    assert "\n\n\n" not in out
