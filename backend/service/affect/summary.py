"""Turn-level affect summary — PR-X6F-1.

Given the :class:`MutationBuffer`-style entries produced by the
:class:`AffectTagEmitter` (stage 14), this module extracts a fixed-order
6-dim emotion vector plus a scalar intensity. The vector is the shape
we store in ``SessionMemoryEntryModel.emotion_vec`` and compare in
:class:`AffectAwareRetrieverMixin` (PR-X6-2).

Why fixed order
---------------

The emitter's tag set is closed at module import time
(``AFFECT_TAGS = ("joy", "sadness", "anger", "fear", "calm",
"excitement")``). Fixing the vector dimension to the same 6 slots in
the same order means:

- A retriever can cosine-compare two records without carrying a
  schema header.
- Embedder migrations don't apply — this vector is semantic, not
  learned. If we later add a 7th tag, migration is adding a zero
  column to pre-existing vectors (or leaving them as 6-dim and relying
  on the mixin's dim-mismatch fallback).

Intensity
---------

A single scalar in ``[0.0, 1.0]`` summarising "how emotional was this
turn". Defined as ``min(1.0, max(|v_i|) / MOOD_ALPHA)`` so that a full
single-tag emit (``strength=1.0``) reaches exactly 1.0 regardless of
``MOOD_ALPHA`` scaling. Multi-tag turns can exceed 1.0 on the raw
mood-delta axis but we clamp to keep the field usable as a weight.

Design constraints (inherited from PR-X6-1/X6-2)
------------------------------------------------

- Stdlib only. No pipeline import (no ``geny_executor``, no
  ``PipelineState`` dependency) — the helper runs against anything
  that quacks like a ``MutationBuffer``.
- Null-safe. Empty buffer / no mood entries → ``(None, None)``
  (no "neutral zero" sentinel — matches X6-1 storage semantics).
- Deterministic. No randomness, no timestamp usage — given the same
  entries returns the same output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple

__all__ = [
    "AFFECT_VECTOR_TAGS",
    "AFFECT_TURN_SUMMARY_KEY",
    "AffectTurnSummary",
    "summarize_affect_mutations",
    "stash_affect_summary",
]

#: Key under which an :class:`AffectTurnSummary` is stashed on
#: ``state.shared`` by :class:`AffectTagEmitter` (PR-X6F-3).
#: Pipeline callers downstream of stage 14 read this key to forward
#: affect fields to STM writes (e.g. PR-X6F-2-extended callers).
AFFECT_TURN_SUMMARY_KEY: str = "affect_turn_summary"


@dataclass(frozen=True)
class AffectTurnSummary:
    """Per-turn affect snapshot, shaped for direct DB write.

    Consumers receive this from ``state.shared[AFFECT_TURN_SUMMARY_KEY]``
    after stage 14 and can pass its fields straight to
    :func:`service.database.memory_db_helper.db_stm_add_message`.

    The frozen dataclass makes accidental mutation loud — the value
    on ``state.shared`` is a read-only snapshot of the turn's affect,
    not a scratchpad.
    """

    emotion_vec: Tuple[float, ...]
    emotion_intensity: float

#: The canonical tag order used for the stored 6-dim emotion vector.
#: Matches :data:`service.emit.affect_tag_emitter.AFFECT_TAGS` but is
#: duplicated here to avoid importing the emit pipeline (which carries
#: an executor dependency) from this pure-stdlib helper.
AFFECT_VECTOR_TAGS: Tuple[str, ...] = (
    "joy",
    "sadness",
    "anger",
    "fear",
    "calm",
    "excitement",
)

#: Mirrors the emitter's ``MOOD_ALPHA`` — kept in sync intentionally,
#: but defined independently to keep this module stdlib-only. If the
#: emitter's alpha changes, bump this and the X6F PR-3 test will
#: catch drift via the round-trip check.
_MOOD_ALPHA: float = 0.15

_MOOD_PATH_PREFIX: str = "mood."


def summarize_affect_mutations(
    entries: Optional[Iterable[Any]],
) -> Tuple[Optional[List[float]], Optional[float]]:
    """Reduce a mutation stream into ``(emotion_vec, emotion_intensity)``.

    :param entries: Anything iterable whose elements expose ``op``,
        ``path``, and ``value`` attributes — in practice a
        :class:`MutationBuffer` or its ``items`` tuple.
    :returns: ``(vec, intensity)`` pair:
        - ``vec``: 6-dim list of floats in the order given by
          :data:`AFFECT_VECTOR_TAGS`, **or** ``None`` if no mood
          mutation was present.
        - ``intensity``: scalar in ``[0.0, 1.0]`` summarising the
          turn's emotional load, **or** ``None`` when ``vec`` is
          ``None``.

    Only ``op == "add"`` mutations on paths starting with ``mood.``
    contribute — this matches what :class:`AffectTagEmitter` emits.
    Other paths (``bond.*``, ``vitals.*``) are ignored. Multiple
    mutations on the same tag within a turn accumulate (sum).
    """
    if entries is None:
        return (None, None)

    accum: dict[str, float] = {tag: 0.0 for tag in AFFECT_VECTOR_TAGS}
    touched = False

    for m in entries:
        op = getattr(m, "op", None)
        path = getattr(m, "path", None)
        value = getattr(m, "value", None)
        if op != "add" or not isinstance(path, str):
            continue
        if not path.startswith(_MOOD_PATH_PREFIX):
            continue
        tag = path[len(_MOOD_PATH_PREFIX):]
        if tag not in accum:
            continue
        try:
            accum[tag] += float(value)
        except (TypeError, ValueError):
            continue
        touched = True

    if not touched:
        return (None, None)

    vec: List[float] = [accum[tag] for tag in AFFECT_VECTOR_TAGS]
    peak = max(abs(v) for v in vec)
    if _MOOD_ALPHA > 0.0:
        intensity = min(1.0, peak / _MOOD_ALPHA)
    else:
        intensity = min(1.0, peak)
    return (vec, intensity)


def stash_affect_summary(shared: Any, entries: Optional[Iterable[Any]]) -> Optional["AffectTurnSummary"]:
    """Compute an :class:`AffectTurnSummary` from ``entries`` and write it to ``shared``.

    Returns the stashed summary (or ``None`` when no mood mutations
    were found — in which case ``shared`` is left untouched). This
    lets the emitter decide whether to clear a stale prior-turn
    summary; the default is *not to*, so that heterogeneous emit
    chains (multiple emitters contributing mood deltas) compose
    naturally: each call accumulates into the same buffer, and the
    last caller's summary wins.
    """
    vec, intensity = summarize_affect_mutations(entries)
    if vec is None or intensity is None:
        return None
    summary = AffectTurnSummary(
        emotion_vec=tuple(vec),
        emotion_intensity=intensity,
    )
    shared[AFFECT_TURN_SUMMARY_KEY] = summary
    return summary
