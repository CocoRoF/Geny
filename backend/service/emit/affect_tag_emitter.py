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
from geny_executor.stages.s14_emit.interface import Emitter
from geny_executor.stages.s14_emit.types import EmitResult

from service.affect.summary import stash_affect_summary
from service.affect.taxonomy import RECOGNIZED_TAGS, coefficients_for
from service.state import MUTATION_BUFFER_KEY

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

DEFAULT_MAX_TAG_MUTATIONS_PER_TURN: Final[int] = 3

#: Base scale for ``bond.affection`` coefficients from the taxonomy —
#: a coefficient of 1.0 reproduces the pre-X7 joy/calm magnitude.
_BOND_AFFECTION_SCALE: Final[float] = 0.5

#: Base scale for ``bond.trust`` coefficients. Negative because the
#: original behavior was "anger/fear decrements trust"; the taxonomy
#: encodes magnitudes as positive coefficients and the emitter applies
#: the sign here, keeping the mapping table visually direction-neutral.
_BOND_TRUST_SCALE: Final[float] = -0.3


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

        applied = 0
        dropped = 0
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

            self._apply_tag(buf, tag, strength)
            applied += 1

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

    def _apply_tag(self, buf: Any, tag: str, strength: float) -> None:
        """Emit mutations for every coefficient in the tag's taxonomy entry.

        Unknown tags (absent from ``AFFECT_TAG_MAPPING``) produce no
        mutations — they're still stripped from ``final_text`` by the
        regex match, but contribute nothing to creature state. This
        mirrors the design intent: display cleanliness first, mutation
        correctness second.
        """
        coeffs = coefficients_for(tag)
        if not coeffs:
            return
        source = f"emit:affect_tag/{tag}"
        for path, coeff in coeffs.items():
            # Scale depends on the axis family. Mood axes use MOOD_ALPHA
            # so a coefficient of 1.0 matches the historical delta; bond
            # axes use their own scale and carry the sign in
            # _BOND_TRUST_SCALE so taxonomy magnitudes stay positive.
            if path.startswith("mood."):
                delta = strength * coeff * MOOD_ALPHA
            elif path == "bond.affection":
                delta = strength * coeff * _BOND_AFFECTION_SCALE
            elif path == "bond.trust":
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
            buf.append(
                op="add",
                path=path,
                value=delta,
                source=source,
            )
