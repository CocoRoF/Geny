"""STMAffectAwareRetriever — PR-X6F-4.

Pins that:

- ``db_stm_search`` now selects and decodes ``emotion_vec`` /
  ``emotion_intensity`` alongside existing columns.
- The concrete :class:`STMAffectAwareRetriever` feeds those rows into
  :class:`AffectAwareRetrieverMixin` and re-ranks correctly.
- All three graceful-degradation paths hold: no query vector, all-NULL
  candidate vectors, partial coverage.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import pytest

from service.affect.stm_retriever import STMAffectAwareRetriever
from service.database.memory_db_helper import db_stm_search


class _FakeDBManager:
    """Test double matching the duck-typed contract of AppDatabaseManager."""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows
        self._last_query: str = ""
        self._last_params: Tuple[Any, ...] = ()
        self.db_manager = self
        self._healthy = True

    def _is_pool_healthy(self) -> bool:
        return self._healthy

    def execute_query(self, query: str, params: Tuple[Any, ...]):
        self._last_query = query
        self._last_params = params
        return list(self._rows)


# ── db_stm_search: new columns flow through ─────────────────────────


def test_db_stm_search_selects_emotion_columns() -> None:
    db = _FakeDBManager([])
    db_stm_search(db, "sess-1", "hello world", max_results=5)
    assert "emotion_vec" in db._last_query
    assert "emotion_intensity" in db._last_query


def test_db_stm_search_decodes_emotion_vec_per_row() -> None:
    raw_vec = json.dumps([0.15, 0.0, 0.0, 0.0, 0.0, 0.0])
    db = _FakeDBManager([
        {
            "entry_id": "e1",
            "content": "hello joy",
            "role": "assistant",
            "metadata_json": "{}",
            "entry_timestamp": "",
            "emotion_vec": raw_vec,
            "emotion_intensity": 1.0,
        },
    ])
    rows = db_stm_search(db, "s", "hello", max_results=5)
    assert rows is not None and len(rows) == 1
    assert rows[0]["emotion_vec"] == [0.15, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert rows[0]["emotion_intensity"] == 1.0


def test_db_stm_search_handles_null_emotion_vec() -> None:
    db = _FakeDBManager([
        {
            "entry_id": "e1",
            "content": "legacy row",
            "role": "user",
            "metadata_json": "{}",
            "entry_timestamp": "",
            "emotion_vec": None,
            "emotion_intensity": None,
        },
    ])
    rows = db_stm_search(db, "s", "legacy", max_results=5)
    assert rows is not None and len(rows) == 1
    assert rows[0]["emotion_vec"] is None
    assert rows[0]["emotion_intensity"] is None


def test_db_stm_search_corrupt_vec_decodes_to_none() -> None:
    """Corrupt vector must not poison the row — X6-1 contract."""
    db = _FakeDBManager([
        {
            "entry_id": "e1",
            "content": "corrupt",
            "role": "user",
            "metadata_json": "{}",
            "entry_timestamp": "",
            "emotion_vec": "not-json",
            "emotion_intensity": 0.5,
        },
    ])
    rows = db_stm_search(db, "s", "corrupt", max_results=5)
    assert rows is not None and len(rows) == 1
    assert rows[0]["emotion_vec"] is None
    # Intensity is a scalar — not gated by the vec decode
    assert rows[0]["emotion_intensity"] == 0.5


def test_db_stm_search_preserves_existing_dict_shape() -> None:
    """Existing keys must remain — entry_id, content, role, metadata,
    entry_timestamp. Only new keys were added."""
    db = _FakeDBManager([
        {
            "entry_id": "e1",
            "content": "hi",
            "role": "assistant",
            "metadata_json": '{"k": "v"}',
            "entry_timestamp": "2026-04-22T00:00:00",
            "emotion_vec": None,
            "emotion_intensity": None,
        },
    ])
    rows = db_stm_search(db, "s", "hi", max_results=5)
    assert rows is not None and len(rows) == 1
    r = rows[0]
    assert r["entry_id"] == "e1"
    assert r["content"] == "hi"
    assert r["role"] == "assistant"
    assert r["metadata"] == {"k": "v"}
    assert r["entry_timestamp"] == "2026-04-22T00:00:00"


# ── STMAffectAwareRetriever: no query vector = text-only ─────────────


def test_retriever_no_query_vec_preserves_recency_order() -> None:
    db = _FakeDBManager([
        {"entry_id": "a", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": None, "emotion_intensity": None},
        {"entry_id": "b", "content": "hi there", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": None, "emotion_intensity": None},
    ])
    r = STMAffectAwareRetriever(db)
    ranked = r.search("s", "hi", query_emotion_vec=None, max_results=5)
    assert [row["entry_id"] for row, _ in ranked] == ["a", "b"]


def test_retriever_empty_query_vec_treated_as_none() -> None:
    db = _FakeDBManager([
        {"entry_id": "a", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": [0.15, 0, 0, 0, 0, 0], "emotion_intensity": 1.0},
    ])
    # An empty sequence is "no signal" by mixin contract.
    db._rows[0]["emotion_vec"] = json.dumps([0.15, 0, 0, 0, 0, 0])
    r = STMAffectAwareRetriever(db)
    ranked = r.search("s", "hi", query_emotion_vec=[], max_results=5)
    assert len(ranked) == 1
    assert ranked[0][0]["entry_id"] == "a"


# ── STMAffectAwareRetriever: affect re-rank promotes similar rows ────


def test_retriever_promotes_affect_matching_row() -> None:
    """Row with matching emotion_vec should rise in the ranking."""
    joy_vec = json.dumps([0.15, 0.0, 0.0, 0.0, 0.0, 0.0])
    anger_vec = json.dumps([0.0, 0.0, 0.15, 0.0, 0.0, 0.0])
    db = _FakeDBManager([
        # Row 0: more recent (higher text score), but wrong affect
        {"entry_id": "recent_anger", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": anger_vec, "emotion_intensity": 1.0},
        # Row 1: older but matches current-turn joy
        {"entry_id": "older_joy", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": joy_vec, "emotion_intensity": 1.0},
    ])
    r = STMAffectAwareRetriever(db, affect_weight=0.9)
    ranked = r.search(
        "s", "hi",
        query_emotion_vec=[0.15, 0.0, 0.0, 0.0, 0.0, 0.0],
        max_results=5,
    )
    # With weight 0.9, joy match dominates recency → older_joy first
    assert ranked[0][0]["entry_id"] == "older_joy"


def test_retriever_partial_coverage_null_vec_rows_fall_back_to_text() -> None:
    """Mixed null/non-null candidate vectors both rank sensibly."""
    joy_vec = json.dumps([0.15, 0.0, 0.0, 0.0, 0.0, 0.0])
    db = _FakeDBManager([
        {"entry_id": "legacy", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": None, "emotion_intensity": None},
        {"entry_id": "with_affect", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": joy_vec, "emotion_intensity": 1.0},
    ])
    r = STMAffectAwareRetriever(db, affect_weight=0.5)
    ranked = r.search(
        "s", "hi",
        query_emotion_vec=[0.15, 0.0, 0.0, 0.0, 0.0, 0.0],
        max_results=5,
    )
    # Both present; no crash; at least the matching row is returned
    ids = [row["entry_id"] for row, _ in ranked]
    assert set(ids) == {"legacy", "with_affect"}


def test_retriever_all_null_candidate_vecs_yields_text_only_order() -> None:
    db = _FakeDBManager([
        {"entry_id": "a", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": None, "emotion_intensity": None},
        {"entry_id": "b", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": None, "emotion_intensity": None},
    ])
    r = STMAffectAwareRetriever(db, affect_weight=0.9)
    ranked = r.search(
        "s", "hi",
        query_emotion_vec=[0.15, 0, 0, 0, 0, 0],
        max_results=5,
    )
    # Recency order preserved — first row comes first (text score 1.0)
    assert ranked[0][0]["entry_id"] == "a"


def test_retriever_dim_mismatch_falls_back_to_text_score() -> None:
    """Row with 4-dim vector + 6-dim query → affect term drops out."""
    four_dim = json.dumps([0.1, 0.2, 0.3, 0.4])
    db = _FakeDBManager([
        {"entry_id": "mismatch", "content": "hi", "role": "u",
         "metadata_json": "{}", "entry_timestamp": "",
         "emotion_vec": four_dim, "emotion_intensity": 0.5},
    ])
    r = STMAffectAwareRetriever(db)
    ranked = r.search(
        "s", "hi",
        query_emotion_vec=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        max_results=5,
    )
    assert len(ranked) == 1
    # No raise — just returns blended score where affect_similarity was None
    assert ranked[0][0]["entry_id"] == "mismatch"


# ── STMAffectAwareRetriever: plumbing edge cases ────────────────────


def test_retriever_empty_search_returns_empty_list() -> None:
    db = _FakeDBManager([])
    r = STMAffectAwareRetriever(db)
    ranked = r.search("s", "nothing_matches", max_results=5)
    assert ranked == []


def test_retriever_swallows_db_errors_into_empty_list() -> None:
    class _Boom(_FakeDBManager):
        def execute_query(self, query: str, params: Tuple[Any, ...]):
            raise RuntimeError("db down")
    r = STMAffectAwareRetriever(_Boom([]))
    # db_stm_search itself catches and returns None → retriever returns []
    assert r.search("s", "x") == []


def test_retriever_honors_affect_weight_override() -> None:
    r = STMAffectAwareRetriever(_FakeDBManager([]), affect_weight=0.7)
    assert r.affect_weight == 0.7
    r2 = STMAffectAwareRetriever(_FakeDBManager([]))
    # Default from the mixin is 0.3
    assert r2.affect_weight == 0.3
