"""AffectTagEmitter — turns LLM ``[emotion:strength]`` tags into mutations.

LLMs tend to intersperse affect cues into their prose. This emitter
harvests those cues at stage 14 time and:

1. Pushes an EMA-scaled delta onto ``mood.<axis>`` in the current-turn
   :class:`MutationBuffer` (via ``state.shared[MUTATION_BUFFER_KEY]``)
   for every coefficient of the matched tag in the canonical taxonomy
   (:mod:`service.affect.taxonomy`). A single ``[wonder]`` now pushes
   contributions to three axes at once (excitement + calm + joy),
   matching the richer tag set the VTuber prompt allows.
2. Layers bond deltas (``bond.affection`` / ``bond.trust``) when the
   tag's taxonomy entry declares them. Scaling uses the emitter's
   per-axis base constants so the old 6-tag numerical behavior is
   preserved at coefficient 1.0.
3. Rewrites ``state.final_text`` with *all* emotion-like bracketed
   tags stripped — both the recognized-taxonomy set and a narrow
   lowercase-identifier safety net for tags that slip past the
   taxonomy (new expressive words the model tries). The user-visible
   text never carries raw ``[something]`` markers.

The emitter is intentionally forgiving — if the buffer isn't present
(classic mode, no provider) or the text has no tags, it returns a
no-op :class:`EmitResult`. Never raises into the chain; the wrapping
:class:`EmitterChain` catches exceptions too, but the emitter itself
tries to be boring on all negative paths.

See ``dev_docs/20260421_6/plan/04_tamagotchi_interaction_layering.md §4.2``
for the original contract; cycle 20260422_5 (X7) extends the
taxonomy to ~25 tags without changing the emit pipeline shape.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from geny_executor.core.state import PipelineState
from geny_executor.stages.s17_emit.interface import Emitter
from geny_executor.stages.s17_emit.types import EmitResult

from service.affect.summary import stash_affect_summary
from service.affect.taxonomy import RECOGNIZED_TAGS, coefficients_for
from service.state import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    SESSION_META_KEY,
    TURN_KIND_USER,
    get_turn_kind,
    is_vtuber_role,
    is_vtuber_state,
)

logger = logging.getLogger(__name__)

#: Re-exported for backwards compatibility with existing callers and
#: tests that reference ``AFFECT_TAGS`` directly. Source of truth is
#: :data:`service.affect.taxonomy.RECOGNIZED_TAGS`.
AFFECT_TAGS: Final[tuple[str, ...]] = RECOGNIZED_TAGS

#: Matches ``[tag]`` / ``[tag:strength]`` where ``tag`` is a name the
#: taxonomy knows about. Case-insensitive — ``[Joy]`` and ``[JOY]`` both
#: normalize to ``joy`` when looked up in the taxonomy.
AFFECT_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"\[(" + "|".join(AFFECT_TAGS) + r")\s*(?::(-?\d+(?:\.\d+)?))?\s*\]",
    flags=re.IGNORECASE,
)

#: Safety net: matches *any* bracketed lowercase identifier that looks
#: like an emotion tag (3–20 chars, alphabetic + underscore only),
#: with an optional *numeric* ``:strength`` suffix so entries like
#: ``[bewildered:0.7]`` get stripped. Non-numeric payloads like
#: ``[note: todo]`` don't match and stay (protects legitimate text).
#: Used only for stripping — never for mutation. Uppercase-only routing
#: tokens like ``[THINKING_TRIGGER]`` / ``[SUB_WORKER_RESULT]`` do NOT
#: match by design; they stay for the downstream router / sanitizer.
UNKNOWN_EMOTION_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"\[\s*([a-z][a-z_]{2,19})(?:\s*:\s*-?\d+(?:\.\d+)?)?\s*\]"
)

MOOD_ALPHA: Final[float] = 0.15

# Plan/Phase03 §3.7 — lowered from 3 → 2 so a single LLM turn can move
# at most two affect axes meaningfully. Combined with §3.2 coalescing
# (same-path tags sum to one mutation) and §3.3 saturation, this caps
# total per-turn mood movement to roughly 0.30 in any one direction.
DEFAULT_MAX_TAG_MUTATIONS_PER_TURN: Final[int] = 2

#: Base scale for ``bond.affection`` coefficients from the taxonomy —
#: a coefficient of 1.0 reproduces the pre-X7 joy/calm magnitude.
_BOND_AFFECTION_SCALE: Final[float] = 0.5

#: Base scale for ``bond.trust`` coefficients. Negative because the
#: original behavior was "anger/fear decrements trust"; the taxonomy
#: encodes magnitudes as positive coefficients and the emitter applies
#: the sign here, keeping the mapping table visually direction-neutral.
_BOND_TRUST_SCALE: Final[float] = -0.3


_MOOD_PATH_PREFIX: Final[str] = "mood."


def _saturation_factor(current: float) -> float:
    """Plan/Phase03 §3.3 — diminishing returns near the [0,1] cap.

    Returns a multiplier in ``[0.0, 1.0]`` for an incoming positive
    delta on a mood axis, based on the *current* value of that axis.
    The factor is identity (1.0) below 0.5, ramps linearly to 0.5 at
    current=0.8, then linearly to 0.0 at current=1.0. Above 1.0 the
    delta is fully suppressed — the clamp in ``_clamp_for_path``
    would clip it anyway, but we want the *upstream* signal to be
    near-zero so the saturating axis doesn't waste a coalesce slot.

    Negative deltas (regressing toward neutral) are not saturated by
    this function — the caller checks ``delta > 0`` before applying
    the factor. That asymmetry is intentional: it should always be
    *easy* for an axis to come down from saturation, so the system
    doesn't get stuck.
    """
    if current < 0.5:
        return 1.0
    if current < 0.8:
        return 1.0 - (current - 0.5) / 0.3 * 0.5
    if current < 1.0:
        return 0.5 - (current - 0.8) / 0.2 * 0.5
    return 0.0


def _read_mood_axis(snap: Any, path: str) -> float:
    """Best-effort read of a ``mood.<axis>`` value off a hydrated
    snapshot. Returns 0.0 when the snapshot is missing the axis (so
    a fresh creature with no mood block doesn't blow up the emitter).
    """
    if snap is None or not path.startswith(_MOOD_PATH_PREFIX):
        return 0.0
    axis = path[len(_MOOD_PATH_PREFIX):]
    mood = getattr(snap, "mood", None)
    if mood is None:
        return 0.0
    val = getattr(mood, axis, 0.0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


class AffectTagEmitter(Emitter):
    """Parse ``[emotion[:strength]]`` tags out of final_text into mutations.

    Args:
        max_tags_per_turn: Cap on how many tag hits translate into
            mutations within one call. Extra matches are dropped (with
            a debug log) so a confused LLM can't spam mood +N in one
            turn. Stripping from ``final_text`` still applies to all
            matches — the cap only gates mutation emission.
    """

    def __init__(
        self,
        *,
        max_tags_per_turn: int = DEFAULT_MAX_TAG_MUTATIONS_PER_TURN,
    ) -> None:
        if max_tags_per_turn < 0:
            raise ValueError(
                f"max_tags_per_turn must be >= 0, got {max_tags_per_turn}"
            )
        self._max_tags_per_turn = max_tags_per_turn

    @property
    def name(self) -> str:
        return "affect_tag"

    async def emit(self, state: PipelineState) -> EmitResult:
        # Plan/Phase04 §4.1 — VTuber-only gate. Worker / planner
        # pipelines may use the same emitter chain but must not have
        # their `final_text` carrying mood/bond mutations. We still
        # strip recognized tags from the visible text below; the gate
        # only suppresses mutation emission. Two sources of truth are
        # consulted (snapshot + session_meta) so a mis-wired hydrate
        # path can't accidentally bypass the guard.
        snap = state.shared.get(CREATURE_STATE_KEY)
        meta = state.shared.get(SESSION_META_KEY)
        meta_role = meta.get("character_role") if isinstance(meta, dict) else None
        role_is_vtuber = is_vtuber_state(snap) and (
            meta_role is None or is_vtuber_role(meta_role)
        )
        # When *no* CreatureState was hydrated at all (classic mode),
        # we still want to strip tags from the visible text — but
        # there's no buffer to mutate either, so the existing buf-None
        # branch handles that case cleanly. Only set the suppress flag
        # for the explicit "hydrated state, but not VTuber" case.
        suppress_mutations = snap is not None and not role_is_vtuber

        text = state.final_text or ""
        matches = AFFECT_TAG_RE.findall(text)

        cleaned = AFFECT_TAG_RE.sub("", text) if matches else text
        # Safety net: strip any remaining lowercase bracketed identifier
        # that wasn't in the taxonomy. Counts unknown hits so we can
        # surface them via metadata for telemetry / prompt-tuning.
        unknown_hits = UNKNOWN_EMOTION_TAG_RE.findall(cleaned)
        if unknown_hits:
            cleaned = UNKNOWN_EMOTION_TAG_RE.sub("", cleaned)
            logger.debug(
                "AffectTagEmitter: stripped %d unknown emotion-like tag(s): %r",
                len(unknown_hits),
                unknown_hits[:5],
            )
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

        if not matches and not unknown_hits:
            return EmitResult(
                emitted=False,
                channels=["affect_tag"],
                metadata={"matches": 0},
            )

        state.final_text = cleaned

        if not matches:
            # Only unknown tags — nothing to mutate, but we did clean
            # the display text. Surface that for observability.
            return EmitResult(
                emitted=False,
                channels=["affect_tag"],
                metadata={
                    "matches": 0,
                    "unknown_stripped": len(unknown_hits),
                    "stripped": True,
                    "reason": "no_recognized_tags",
                },
            )

        buf: Any = state.shared.get(MUTATION_BUFFER_KEY)
        if buf is None:
            return EmitResult(
                emitted=False,
                channels=["affect_tag"],
                metadata={
                    "matches": len(matches),
                    "unknown_stripped": len(unknown_hits),
                    "applied": 0,
                    "stripped": True,
                    "reason": "no_mutation_buffer",
                },
            )

        if suppress_mutations:
            # Plan/Phase04 §4.1 — non-VTuber turn: tags were stripped
            # from the visible text above, but no mood/bond mutations
            # are emitted. Surfaced via metadata for telemetry.
            return EmitResult(
                emitted=False,
                channels=["affect_tag"],
                metadata={
                    "matches": len(matches),
                    "unknown_stripped": len(unknown_hits),
                    "applied": 0,
                    "stripped": True,
                    "reason": "non_vtuber_role",
                },
            )

        applied = 0
        dropped = 0
        # Plan/Phase02 §3.1 — read the current turn kind. Defaults to
        # USER when the classifier didn't run (legacy tests / classic
        # mode), preserving today's behavior of "always count bond".
        turn_kind = get_turn_kind(meta) if isinstance(meta, dict) else TURN_KIND_USER

        # Plan/Phase03 §3.2 — coalesce per path within a turn so
        # ``[joy] [joy] [joy]`` produces *one* mood.joy mutation
        # whose value is the sum of the three contributions, not
        # three independent appends. ``deltas`` is the running sum,
        # ``sources`` records up to three contributing tags per path
        # so the audit log retains provenance.
        deltas: dict[str, float] = {}
        sources: dict[str, list[str]] = {}

        for tag_raw, strength_raw in matches:
            if applied >= self._max_tags_per_turn:
                dropped += 1
                continue

            tag = tag_raw.lower()
            try:
                strength = float(strength_raw) if strength_raw else 1.0
            except ValueError:
                logger.debug(
                    "AffectTagEmitter: bad strength %r for tag %r; defaulting to 1.0",
                    strength_raw,
                    tag,
                )
                strength = 1.0

            contributions = self._compute_tag_deltas(
                tag, strength, turn_kind=turn_kind,
            )
            if not contributions:
                # Tag known to taxonomy but every coefficient was
                # gated out (e.g. only bond.* contributions on a
                # non-user turn). Don't count toward applied — we
                # didn't actually move the state.
                continue

            for path, delta in contributions.items():
                if delta == 0.0:
                    continue
                deltas[path] = deltas.get(path, 0.0) + delta
                bucket = sources.setdefault(path, [])
                if tag not in bucket and len(bucket) < 3:
                    bucket.append(tag)
            applied += 1

        # Plan/Phase03 §3.3 — apply saturation per mood axis using
        # the hydrated snapshot's *current* value. Done after
        # coalescing so the saturation factor reflects the pre-turn
        # state, not a half-applied accumulator. Bond / vitals axes
        # are not saturated here (they have their own clamp policies
        # in ``_clamp_for_path``).
        for path, total in deltas.items():
            if total == 0.0:
                continue
            if total > 0.0 and path.startswith(_MOOD_PATH_PREFIX):
                current = _read_mood_axis(snap, path)
                sat = _saturation_factor(current)
                total *= sat
                if total == 0.0:
                    continue
            tags_used = sources.get(path) or ["unknown"]
            src = "emit:affect_tag/" + "+".join(tags_used)
            buf.append(op="add", path=path, value=total, source=src)

        if dropped:
            logger.debug(
                "AffectTagEmitter: dropped %d tag(s) past per-turn cap %d",
                dropped,
                self._max_tags_per_turn,
            )

        # PR-X6F-3: stash a turn-level affect summary on state.shared so
        # downstream STM writers can persist it via the emotion_vec /
        # emotion_intensity kwargs from PR-X6F-2. ``stash_affect_summary``
        # is null-safe — if no mood mutations accumulated (e.g. tags
        # matched but the buffer op filtering dropped them), shared is
        # left untouched.
        stashed = stash_affect_summary(state.shared, buf)

        return EmitResult(
            emitted=True,
            channels=["affect_tag"],
            metadata={
                "matches": len(matches),
                "unknown_stripped": len(unknown_hits),
                "applied": applied,
                "dropped": dropped,
                "stripped": True,
                "summary_stashed": stashed is not None,
            },
        )

    def _compute_tag_deltas(
        self,
        tag: str,
        strength: float,
        *,
        turn_kind: str = TURN_KIND_USER,
    ) -> dict[str, float]:
        """Return ``{path: delta}`` contributions for a single tag.

        Pure helper — no buffer side effects. Lets ``emit()`` coalesce
        same-path deltas across multiple tags before flushing them as
        one mutation each.

        Unknown tags (absent from ``AFFECT_TAG_MAPPING``) return an
        empty dict — they're still stripped from ``final_text`` by the
        regex match, but contribute nothing to creature state.

        ``turn_kind`` (Plan/Phase02 §3.1) gates bond contributions: on
        autonomous (TRIGGER) turns ``bond.affection`` and ``bond.trust``
        are skipped entirely so the character only earns relational
        deltas from real user interaction. Mood deltas land on every
        turn — the inner emotional life is allowed to drift even when
        no one is watching.
        """
        coeffs = coefficients_for(tag)
        if not coeffs:
            return {}
        is_user_turn = turn_kind == TURN_KIND_USER
        out: dict[str, float] = {}
        for path, coeff in coeffs.items():
            # Scale depends on the axis family. Mood axes use MOOD_ALPHA
            # so a coefficient of 1.0 matches the historical delta; bond
            # axes use their own scale and carry the sign in
            # _BOND_TRUST_SCALE so taxonomy magnitudes stay positive.
            if path.startswith("mood."):
                delta = strength * coeff * MOOD_ALPHA
            elif path == "bond.affection":
                if not is_user_turn:
                    continue  # Plan/Phase02 §3.1 — autonomous turns can't grow affection.
                delta = strength * coeff * _BOND_AFFECTION_SCALE
            elif path == "bond.trust":
                if not is_user_turn:
                    continue  # Plan/Phase02 §3.1 — autonomous turns can't move trust either.
                delta = strength * coeff * _BOND_TRUST_SCALE
            else:
                # Unknown bond / vitals path in the taxonomy — fall back
                # to mood-style scaling so a typo in the table doesn't
                # silently produce a huge delta. Logged for awareness.
                logger.debug(
                    "AffectTagEmitter: taxonomy tag %r targets unrecognized "
                    "path %r; applying MOOD_ALPHA scale as a safe default",
                    tag, path,
                )
                delta = strength * coeff * MOOD_ALPHA
            out[path] = delta
        return out
