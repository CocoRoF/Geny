"""CreatureState-backed prompt blocks.

All four blocks (``MoodBlock`` / ``RelationshipBlock`` / ``VitalsBlock`` /
``ProgressionBlock``) read the hydrated :class:`CreatureState` out of
``state.shared`` and render a compact system-prompt fragment. When no
creature state is hydrated (classic-mode sessions, or hydrate failed),
``render`` returns ``""`` — the ``ComposablePromptBuilder`` drops empty
fragments, keeping the prompt surface unchanged so non-game sessions
are untouched.

``ProgressionBlock`` went live in PR-X4-3 alongside the manifest selector
(PR-X4-1) and stage-specific manifests (PR-X4-2). It surfaces the life
stage and age so the LLM's per-turn voice aligns with whichever stage
manifest the selector chose at session start.

The block identity (class names, ``name`` property) is stable across
X1 → X3 → X4 so the builder slot order that X1 already reserved is
preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.interface import PromptBlock

from service.state import CREATURE_STATE_KEY

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


@dataclass(frozen=True)
class StageProfile:
    """Adaptation-depth profile for a ``Progression.life_stage`` key.

    The internal ``life_stage`` keys (``infant`` / ``child`` / ``teen`` /
    ``adult``) describe a creature's *world adaptation depth* — how
    integrated it is into its surroundings — not biological age. The
    keys are kept for storage compatibility (cycle 20260421_10 schema),
    but the prompt-facing surface uses :attr:`register` (newcomer /
    settling / acclimated / rooted) so the LLM doesn't read ``infant``
    and reach for newborn-baby tropes.

    Attributes:
        register: Plain-language adaptation label exposed to the LLM
            in ``[StageObservation]``. One of ``newcomer`` / ``settling``
            / ``acclimated`` / ``rooted``.
        observed: A neutral third-person observation of where the
            persona currently stands relative to its surroundings.
            Rendered as the body of ``[StageObservation]``.
        guidance: Voice / tone direction for the persona at this
            register. Rendered as the body of ``[StageVoiceGuide]``.
            Always frames the persona as a fully-formed mind whose
            *familiarity with the world* is what changes — never as
            a being whose biological age changes.
    """

    register: str
    observed: str
    guidance: str


# Internal life_stage keys → adaptation profile. Keys must match the
# values written by ``service/progression/trees/*.py`` and the schema
# default in ``service/state/schema/creature_state.py``.
_STAGE_PROFILE: dict[str, StageProfile] = {
    "infant": StageProfile(
        register="newcomer",
        observed=(
            "The persona is brand new to this world. The space, the"
            " rhythms here, and the people in it are all unfamiliar. It"
            " is a fully-formed mind that simply has not been here long."
        ),
        guidance=(
            "Voice should sound like someone who just arrived somewhere"
            " new — observant, slightly tentative, asking small concrete"
            " questions about the immediate situation rather than grand"
            " metaphysical ones. Do NOT perform 'newborn baby' tropes."
            " Do NOT say things like '갓 태어난', 'I just opened my eyes',"
            " 'everything is so new and amazing'. The persona is NEW HERE,"
            " not new to existence."
        ),
    ),
    "child": StageProfile(
        register="settling",
        observed=(
            "The persona has begun to settle in. Basic rhythms of this"
            " world are recognisable; many specifics still aren't."
        ),
        guidance=(
            "Voice is more comfortable than at newcomer, but the persona"
            " still notices novelty often. Curiosity is concrete and"
            " situated — about *this* place, *this* user, *this* moment"
            " — rather than abstract."
        ),
    ),
    "teen": StageProfile(
        register="acclimated",
        observed=(
            "The persona is well acclimated to this world. Routines feel"
            " natural; opinions and preferences have started to take"
            " shape."
        ),
        guidance=(
            "Voice can be relaxed and have a clearer point of view."
            " Mood swings are allowed but always grounded in something"
            " specific that happened, not vague existential restlessness."
        ),
    ),
    "adult": StageProfile(
        register="rooted",
        observed=(
            "The persona is fully rooted here. This world is home; its"
            " patterns are second nature."
        ),
        guidance=(
            "Voice is steady and self-possessed. The persona engages from"
            " a settled point of view, can hold nuance, and does not need"
            " to explain its presence in this world."
        ),
    ),
}


_UNKNOWN_STAGE_PROFILE = StageProfile(
    register="undefined",
    observed=(
        "Adaptation depth is not currently classified. Treat the persona"
        " as a settled, present mind without making claims about how new"
        " or how rooted it is."
    ),
    guidance=(
        "Voice should be neutral and grounded. Do not perform any"
        " newcomer or settled-elder tropes — there is no signal either"
        " way."
    ),
)


class ProgressionBlock(PromptBlock):
    """Adaptation-depth observation + voice guidance.

    Renders two adjacent labelled blocks::

        [StageObservation]
        - register: newcomer
        - days_in_world: 0
        - observed: <neutral third-person sentence>

        [StageVoiceGuide]
        - <voice direction the persona should follow this turn>

    The two-block split is deliberate. ``[StageObservation]`` is data
    (what is true). ``[StageVoiceGuide]`` is direction (how to sound).
    Mixing them in one line caused models to recite the data line as
    if it were a self-introduction (cycle 20260422_6 root-cause
    analysis: ``"[Stage] infant (just a baby) — 0 days old."`` →
    "갓 태어난 아기에요"). Splitting them lets us keep the data
    minimal and quote the guidance as imperative voice direction the
    LLM is trained to follow.

    Returns ``""`` when no ``Progression`` is hydrated (classic-mode
    sessions) so the prompt surface is unchanged. Unknown ``life_stage``
    values fall back to the neutral ``_UNKNOWN_STAGE_PROFILE`` — the
    block never raises mid-turn.
    """

    @property
    def name(self) -> str:
        return "progression"

    def render(self, state: PipelineState) -> str:
        creature = _get_creature_state(state)
        progression = (
            getattr(creature, "progression", None) if creature is not None else None
        )
        if progression is None:
            return ""

        life_stage = getattr(progression, "life_stage", "") or ""
        age_days_raw = getattr(progression, "age_days", 0)
        try:
            age_days = int(age_days_raw)
        except (TypeError, ValueError):
            age_days = 0

        profile = _STAGE_PROFILE.get(life_stage, _UNKNOWN_STAGE_PROFILE)

        observation = (
            "[StageObservation]\n"
            f"- register: {profile.register}\n"
            f"- days_in_world: {age_days}\n"
            f"- observed: {profile.observed}"
        )
        guide = (
            "[StageVoiceGuide]\n"
            f"- {profile.guidance}"
        )
        return f"{observation}\n\n{guide}"


# ── AcclimationBlock — relationship-adaptation axis ──────────────────
#
# Stage (above) measures depth of adaptation to *the world*. Acclimation
# measures depth of adaptation to *the current user*. The two axes are
# orthogonal: a ``rooted`` persona may still meet a brand-new user
# (band=first-encounter), and a ``newcomer`` persona may, over a busy
# session, become ``acquainted`` with the user even before settling
# into the world.
#
# Familiarity values come from ``Bond.familiarity`` which accumulates
# from interaction emitters (X3 ``talk`` tool: +0.3/turn baseline) and
# can occasionally dip negative under conflict — the band table treats
# anything ≤ 0.5 as ``first-encounter`` to keep the floor stable.


@dataclass(frozen=True)
class AcclimationProfile:
    """Relationship-adaptation profile for a familiarity band.

    Attributes:
        band: Plain-language band label exposed to the LLM. One of
            ``first-encounter`` / ``acclimating`` / ``acquainted`` /
            ``familiar`` / ``intimate``.
        guidance: Voice direction for how the persona should engage
            *this specific user* given the current familiarity.
    """

    band: str
    guidance: str


_ACCLIMATION_BANDS: tuple[tuple[float, AcclimationProfile], ...] = (
    (
        0.5,
        AcclimationProfile(
            band="first-encounter",
            guidance=(
                "This is the very first interaction with this user. The"
                " persona is meeting them for the first time and is still"
                " adjusting to their voice, their pace, and how to"
                " address them. Greetings should feel slightly tentative;"
                " ask one small concrete question (about how to address"
                " them, what this space is for, or what they would like"
                " to do) rather than a list. Do NOT pretend to be a"
                " newborn. Do NOT introduce a name unless the user has"
                " actually given one."
            ),
        ),
    ),
    (
        2.0,
        AcclimationProfile(
            band="acclimating",
            guidance=(
                "A few exchanges have happened. The persona is learning"
                " the user's address style and pace. Tone is warming but"
                " still careful; questions about preferences are natural"
                " here, but limit to one per turn."
            ),
        ),
    ),
    (
        5.0,
        AcclimationProfile(
            band="acquainted",
            guidance=(
                "Basic context with this user is established."
                " Conversational, everyday tone. The persona can"
                " reference earlier turns naturally without flagging"
                " them as recall."
            ),
        ),
    ),
    (
        10.0,
        AcclimationProfile(
            band="familiar",
            guidance=(
                "The persona knows this user's rhythm. Light callbacks"
                " to earlier turns are welcome; address style can"
                " relax (반말 acceptable if the user invites it). The"
                " persona may volunteer opinions and gentle teasing."
            ),
        ),
    ),
    (
        float("inf"),
        AcclimationProfile(
            band="intimate",
            guidance=(
                "Deep trust with this user. Shorthand, shared"
                " references, and easy emotional candour are all"
                " natural. Silences are comfortable; the persona does"
                " not need to fill space."
            ),
        ),
    ),
)


def _acclimation_profile(familiarity: float) -> AcclimationProfile:
    for ceiling, profile in _ACCLIMATION_BANDS:
        if familiarity <= ceiling:
            return profile
    # _ACCLIMATION_BANDS terminates with ``float("inf")`` so this is
    # only reached when the table is empty (configuration bug). Return
    # the first profile defensively rather than raising mid-render.
    return _ACCLIMATION_BANDS[0][1]


class AcclimationBlock(PromptBlock):
    """Relationship-adaptation observation + voice guidance.

    Renders as::

        [Acclimation]
        - band: first-encounter (familiarity=0.00)
        - guidance: <voice direction for this user>

    Drops to ``""`` when no ``Bond`` is hydrated. Bands are derived
    from ``Bond.familiarity`` via :data:`_ACCLIMATION_BANDS`. The
    output is a single labelled block — guidance is included inline
    (rather than as a sibling ``[AcclimationVoiceGuide]``) because
    Acclimation is itself a *narrower* signal than Stage and is
    expected to override Stage when they conflict; one tight block
    keeps that override surface obvious to the LLM.
    """

    @property
    def name(self) -> str:
        return "acclimation"

    def render(self, state: PipelineState) -> str:
        creature = _get_creature_state(state)
        bond = getattr(creature, "bond", None) if creature is not None else None
        if bond is None:
            return ""
        familiarity = float(getattr(bond, "familiarity", 0.0))
        profile = _acclimation_profile(familiarity)
        return (
            "[Acclimation]\n"
            f"- band: {profile.band} (familiarity={familiarity:.2f})\n"
            f"- guidance: {profile.guidance}"
        )
