"""AffectTagEmitter — turns LLM ``[emotion:strength]`` tags into mutations.

LLMs tend to intersperse affect cues into their prose. This emitter
harvests those cues at stage 14 time and:

1. Pushes an EMA-scaled delta onto ``mood.<tag>`` in the current-turn
   :class:`MutationBuffer` (via ``state.shared[MUTATION_BUFFER_KEY]``).
2. Layers a *secondary* bond delta for joy/calm (affection +) and
   anger/fear (trust −).
3. Rewrites ``state.final_text`` with the tags stripped so downstream
   emitters (text, tts, vtuber) never show them to the user.

The emitter is intentionally forgiving — if the buffer isn't present
(classic mode, no provider) or the text has no tags, it returns a
no-op :class:`EmitResult`. Never raises into the chain; the wrapping
:class:`EmitterChain` catches exceptions too, but the emitter itself
tries to be boring on all negative paths.

See ``dev_docs/20260421_6/plan/04_tamagotchi_interaction_layering.md §4.2``
for the full contract; numbers below match that spec.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final, Tuple

from geny_executor.core.state import PipelineState
from geny_executor.stages.s14_emit.interface import Emitter
from geny_executor.stages.s14_emit.types import EmitResult

from service.state import MUTATION_BUFFER_KEY

logger = logging.getLogger(__name__)

AFFECT_TAGS: Final[Tuple[str, ...]] = (
    "joy",
    "sadness",
    "anger",
    "fear",
    "calm",
    "excitement",
)

AFFECT_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"\[(" + "|".join(AFFECT_TAGS) + r")\s*(?::(-?\d+(?:\.\d+)?))?\s*\]",
    flags=re.IGNORECASE,
)

MOOD_ALPHA: Final[float] = 0.15

DEFAULT_MAX_TAG_MUTATIONS_PER_TURN: Final[int] = 3

_JOY_CALM_BOND_AFFECTION: Final[float] = 0.5
_ANGER_FEAR_BOND_TRUST: Final[float] = -0.3


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

        if not matches:
            return EmitResult(
                emitted=False,
                channels=["affect_tag"],
                metadata={"matches": 0},
            )

        cleaned = AFFECT_TAG_RE.sub("", text).strip()
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        state.final_text = cleaned

        buf: Any = state.shared.get(MUTATION_BUFFER_KEY)
        if buf is None:
            return EmitResult(
                emitted=False,
                channels=["affect_tag"],
                metadata={
                    "matches": len(matches),
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

        return EmitResult(
            emitted=True,
            channels=["affect_tag"],
            metadata={
                "matches": len(matches),
                "applied": applied,
                "dropped": dropped,
                "stripped": True,
            },
        )

    def _apply_tag(self, buf: Any, tag: str, strength: float) -> None:
        source = f"emit:affect_tag/{tag}"
        buf.append(
            op="add",
            path=f"mood.{tag}",
            value=strength * MOOD_ALPHA,
            source=source,
        )
        if tag in ("joy", "calm"):
            buf.append(
                op="add",
                path="bond.affection",
                value=strength * _JOY_CALM_BOND_AFFECTION,
                source=source,
            )
        elif tag in ("anger", "fear"):
            buf.append(
                op="add",
                path="bond.trust",
                value=strength * _ANGER_FEAR_BOND_TRUST,
                source=source,
            )
