"""STM affect-aware retriever — PR-X6F-4.

Concrete consumer of :class:`AffectAwareRetrieverMixin` (PR-X6-2) that
queries short-term memory via :func:`db_stm_search` (extended in this
PR to return decoded ``emotion_vec`` / ``emotion_intensity`` per row)
and blends the turn's affect summary into the keyword score.

Null-safe composition
---------------------

This class is the first place the three X6 pieces meet:

- **Storage** (X6-1 / X6F-2): rows may or may not carry an
  ``emotion_vec``. Most legacy rows won't until the pipeline last-mile
  lands.
- **Ranking** (X6-2 mixin): handles null / empty / dim-mismatch by
  falling back to text-only.
- **Query side** (X6F-3 stash): the caller supplies the *current
  turn's* emotion vector so "retrieve memories with a matching mood"
  works even before the write-path is hot.

The retriever therefore has three graceful-degradation paths:

1. No query vector supplied → text-only ordering (stable sort by
   score desc).
2. Query vector supplied, all candidates have NULL ``emotion_vec`` →
   behaves as if no query vector was supplied — mixin returns text
   score unchanged via ``blend_scores(text, None)``.
3. Partial affect coverage (some rows have vectors, some don't) →
   rows with vectors get a blended score; rows without pass through
   on their text score. Comparability across the two groups is
   acceptable because the mixin's ``blend_scores`` collapses to the
   text score when ``affect_similarity`` is ``None`` — both groups
   share the same scale.

Why a separate class rather than extending ``ShortTermMemory``
-------------------------------------------------------------

``ShortTermMemory`` lives in ``service.memory`` which eagerly imports
numpy-heavy modules (``vector_memory``). Keeping the affect retriever
in ``service.affect`` preserves the stdlib-only import discipline we
set in X6-1 — the mixin, the summary helper, and this class all stay
importable without the executor/numpy stack.

A later PR can wrap ``ShortTermMemory.search_affect_aware`` around
this retriever when the write-path wiring is live.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from service.affect.retriever import AffectAwareRetrieverMixin

logger = logging.getLogger(__name__)

__all__ = ["STMAffectAwareRetriever"]


class STMAffectAwareRetriever(AffectAwareRetrieverMixin):
    """Affect-aware keyword search over ``session_memory_entries``.

    Usage::

        retriever = STMAffectAwareRetriever(db_manager)
        ranked = retriever.search(
            session_id="sess-42",
            query_text="how did the pet react yesterday",
            query_emotion_vec=[0.15, 0, 0, 0, 0, 0],  # current turn joy
            max_results=5,
        )
        for row, blended_score in ranked:
            ...

    ``db_manager`` may be any object accepted by
    :func:`service.database.memory_db_helper.db_stm_search` (typically
    an :class:`AppDatabaseManager`).
    """

    def __init__(
        self,
        db_manager: Any,
        *,
        affect_weight: Optional[float] = None,
    ) -> None:
        self._db_manager = db_manager
        if affect_weight is not None:
            self.affect_weight = affect_weight

    def search(
        self,
        session_id: str,
        query_text: str,
        *,
        query_emotion_vec: Optional[Sequence[float]] = None,
        max_results: int = 10,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Run STM keyword search and re-rank by blended affect similarity.

        :param session_id: Session whose STM to search.
        :param query_text: Keyword query (same contract as
            :func:`db_stm_search`).
        :param query_emotion_vec: Optional emotion vector to re-rank
            by. When ``None``, results are ordered by raw text score
            only (the mixin's text-only fallback path).
        :param max_results: Upper bound on rows pulled from the DB.
            Re-ranking happens on this candidate pool only — the
            final output length equals the DB return size.
        :returns: ``[(row_dict, blended_score), ...]`` sorted by
            blended score descending. ``row_dict`` has the same shape
            as :func:`db_stm_search` rows, with ``emotion_vec`` decoded
            to ``list[float]`` or ``None``. Empty list on any failure
            or empty search space — never raises into the caller.
        """
        from service.database.memory_db_helper import db_stm_search

        try:
            rows = db_stm_search(
                self._db_manager,
                session_id,
                query_text=query_text,
                max_results=max_results,
            )
        except Exception as exc:
            logger.debug(
                "STMAffectAwareRetriever: db_stm_search raised: %s", exc
            )
            return []

        if not rows:
            return []

        # db_stm_search rows come back sorted by id DESC (recency); we
        # synthesize a descending-rank text score in [0, 1] so the
        # mixin has something to blend against. This preserves the
        # existing "most recent match first" behavior when no affect
        # signal is available.
        n = len(rows)
        candidates: List[Tuple[Dict[str, Any], float, Optional[Sequence[float]]]] = []
        for idx, row in enumerate(rows):
            text_score = 1.0 - (idx / n) if n > 0 else 1.0
            candidates.append(
                (row, text_score, row.get("emotion_vec"))
            )

        return self.rerank_by_affect(candidates, query_emotion_vec)
