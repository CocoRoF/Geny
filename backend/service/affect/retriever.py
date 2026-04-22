"""Affect-aware retrieval re-ranking — PR-X6-2.

Provides :class:`AffectAwareRetrieverMixin`, an opt-in mixin that
subclasses of existing retrievers can inherit to blend emotional
similarity into their text-based relevance score.

Design contract
---------------

- **Opt-in.** Retrievers that do *not* subclass this mixin behave
  exactly as before (byte-identical results). Nothing in this module
  monkey-patches existing classes.
- **Null-safe.** If the query or the candidate has no emotion vector
  (``None``, empty, dim-mismatch), the affect term drops out and the
  text score flows through unchanged. A single record with a corrupt
  vector cannot poison a session's ranking.
- **Stdlib only.** No numpy dependency — this mixin is imported in
  hot paths (per-query) and sandbox / lightweight test environments
  must work. Dot products and norms are hand-rolled in Python. For
  typical ``emotion_vec`` dimensions (≤ 32) the overhead is
  negligible compared to the LLM call that triggered the retrieval.
- **Blending, not replacement.** Emotional similarity is a re-ranking
  signal, never the sole score. ``affect_weight`` controls the mix:
  ``blended = (1 - w) * text + w * affect_similarity``. Default
  ``w = 0.3`` is a conservative starting point; PR-X6-3 will tune
  based on real usage data.

Non-goals
---------

- This mixin does **not** write emotion vectors. Write-path wiring
  (emitter → memory record) is a follow-up PR — see
  ``dev_docs/20260422_2/index.md §비범위``.
- This mixin does **not** query the SQL layer. It receives
  pre-scored candidate triples and reorders them. Ingestion of
  ``emotion_vec`` from DB rows is the subclass's job.
- Dimension validation is intentionally loose: any mismatch means
  "no affect signal available" rather than a raise. Embedder
  migration (e.g. 16-dim → 32-dim) should not break retrieval.
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Tuple

__all__ = ["AffectAwareRetrieverMixin"]


Candidate = Tuple[Any, float, Optional[Sequence[float]]]


class AffectAwareRetrieverMixin:
    """Re-rank retrieval results by cosine similarity of emotion vectors.

    Subclasses produce ``(item, text_score, candidate_emotion_vec)``
    triples and call :meth:`rerank_by_affect` to blend in the affect
    signal. When either the query or the candidate has no emotion
    vector, the candidate's text score is preserved unchanged.

    Override :attr:`affect_weight` on the subclass (or an instance)
    to tune the mix without editing this module.
    """

    #: Weight of the affect term in the blended score. 0.0 disables
    #: affect entirely (text-only ranking); 1.0 ranks purely by
    #: emotion. Default 0.3 — text still dominates.
    affect_weight: float = 0.3

    @staticmethod
    def cosine_similarity(
        a: Optional[Sequence[float]],
        b: Optional[Sequence[float]],
    ) -> Optional[float]:
        """Cosine similarity of two vectors in ``[-1.0, 1.0]``.

        Returns ``None`` when the similarity is undefined:
        - either vector is ``None``
        - either vector is empty
        - dimensions differ
        - either vector is all-zero (zero norm)
        """
        if a is None or b is None:
            return None
        if len(a) == 0 or len(b) == 0:
            return None
        if len(a) != len(b):
            return None
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for x, y in zip(a, b):
            dot += x * y
            norm_a += x * x
            norm_b += y * y
        if norm_a == 0.0 or norm_b == 0.0:
            return None
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    def blend_scores(
        self,
        text_score: float,
        affect_similarity: Optional[float],
    ) -> float:
        """Combine a text relevance score with an affect similarity.

        When ``affect_similarity`` is ``None`` the text score passes
        through — this preserves the text-only ordering for records
        or queries without emotion data.
        """
        if affect_similarity is None:
            return text_score
        w = self.affect_weight
        return (1.0 - w) * text_score + w * affect_similarity

    def rerank_by_affect(
        self,
        candidates: Sequence[Candidate],
        query_emotion_vec: Optional[Sequence[float]],
    ) -> List[Tuple[Any, float]]:
        """Re-rank ``candidates`` by blending text score with affect similarity.

        :param candidates: Sequence of ``(item, text_score,
            candidate_emotion_vec)`` triples. ``candidate_emotion_vec``
            may be ``None`` for records with no emotion data.
        :param query_emotion_vec: Vector to compare candidates against.
            When ``None``, no affect signal is available and the
            function simply sorts by text score (stable).
        :returns: ``[(item, blended_score)]`` sorted by blended score
            descending.
        """
        if query_emotion_vec is None or len(query_emotion_vec) == 0:
            return [
                (item, text_score)
                for item, text_score, _ in sorted(
                    candidates, key=lambda c: c[1], reverse=True
                )
            ]

        blended: List[Tuple[Any, float]] = []
        for item, text_score, cand_vec in candidates:
            sim = self.cosine_similarity(query_emotion_vec, cand_vec)
            blended.append((item, self.blend_scores(text_score, sim)))
        blended.sort(key=lambda p: p[1], reverse=True)
        return blended
