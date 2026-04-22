"""AffectAwareRetrieverMixin — PR-X6-2.

Pins the null-safe re-ranking behavior so consumers (future follow-up
that wires a concrete retriever) can rely on:

- text-only fallback when query or candidate has no emotion vector
- dim-mismatch treated as "no signal", never a raise
- opt-in: subclasses that never call ``rerank_by_affect`` are
  untouched
"""

from __future__ import annotations

import math

import pytest

from service.affect.retriever import AffectAwareRetrieverMixin


class _Retriever(AffectAwareRetrieverMixin):
    """Minimal concrete subclass for testing — mixin has no other deps."""


# ── cosine_similarity ───────────────────────────────────────────────


def test_cosine_identical_vectors_is_one() -> None:
    r = _Retriever()
    assert r.cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero() -> None:
    r = _Retriever()
    assert r.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite_vectors_is_minus_one() -> None:
    r = _Retriever()
    assert r.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_handles_scaling_invariance() -> None:
    """Cosine is magnitude-invariant — [1,2,3] and [2,4,6] are the same direction."""
    r = _Retriever()
    assert r.cosine_similarity([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)


def test_cosine_none_returns_none() -> None:
    r = _Retriever()
    assert r.cosine_similarity(None, [1.0, 2.0]) is None
    assert r.cosine_similarity([1.0, 2.0], None) is None
    assert r.cosine_similarity(None, None) is None


def test_cosine_empty_returns_none() -> None:
    r = _Retriever()
    assert r.cosine_similarity([], [1.0]) is None
    assert r.cosine_similarity([1.0], []) is None
    assert r.cosine_similarity([], []) is None


def test_cosine_dim_mismatch_returns_none() -> None:
    """Embedder migration must not cause retrieval to raise — just drop affect signal."""
    r = _Retriever()
    assert r.cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) is None


def test_cosine_zero_norm_returns_none() -> None:
    """All-zero vectors have undefined direction."""
    r = _Retriever()
    assert r.cosine_similarity([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) is None
    assert r.cosine_similarity([1.0, 2.0, 3.0], [0.0, 0.0, 0.0]) is None


def test_cosine_is_static() -> None:
    """Can be called without an instance."""
    assert AffectAwareRetrieverMixin.cosine_similarity(
        [1.0, 0.0], [1.0, 0.0]
    ) == pytest.approx(1.0)


# ── blend_scores ────────────────────────────────────────────────────


def test_blend_none_affect_passes_text_through() -> None:
    r = _Retriever()
    assert r.blend_scores(0.7, None) == 0.7


def test_blend_with_default_weight() -> None:
    """Default weight is 0.3 → blended = 0.7*text + 0.3*affect."""
    r = _Retriever()
    assert r.blend_scores(1.0, 0.0) == pytest.approx(0.7)
    assert r.blend_scores(0.0, 1.0) == pytest.approx(0.3)
    assert r.blend_scores(0.5, 0.5) == pytest.approx(0.5)


def test_blend_respects_instance_weight_override() -> None:
    r = _Retriever()
    r.affect_weight = 0.5
    assert r.blend_scores(1.0, 0.0) == pytest.approx(0.5)


def test_blend_weight_zero_is_text_only() -> None:
    """w=0 makes the mixin opt-out without removing it from the MRO."""
    r = _Retriever()
    r.affect_weight = 0.0
    assert r.blend_scores(0.42, 0.99) == pytest.approx(0.42)


def test_blend_weight_one_is_affect_only() -> None:
    r = _Retriever()
    r.affect_weight = 1.0
    assert r.blend_scores(0.42, 0.99) == pytest.approx(0.99)


# ── rerank_by_affect ────────────────────────────────────────────────


def test_rerank_with_null_query_falls_back_to_text_order() -> None:
    """No query emotion → preserve text-only ranking."""
    r = _Retriever()
    candidates = [("a", 0.2, [1.0, 0.0]), ("b", 0.9, [0.0, 1.0]), ("c", 0.5, None)]
    out = r.rerank_by_affect(candidates, None)
    assert [item for item, _ in out] == ["b", "c", "a"]


def test_rerank_with_empty_query_falls_back_to_text_order() -> None:
    r = _Retriever()
    candidates = [("a", 0.3, [1.0]), ("b", 0.7, [0.5])]
    out = r.rerank_by_affect(candidates, [])
    assert [item for item, _ in out] == ["b", "a"]


def test_rerank_reorders_by_affect_when_text_ties() -> None:
    """Equal text scores → affect similarity breaks the tie."""
    r = _Retriever()
    query = [1.0, 0.0, 0.0]
    candidates = [
        ("match", 0.5, [1.0, 0.0, 0.0]),      # similarity 1.0
        ("orthogonal", 0.5, [0.0, 1.0, 0.0]),  # similarity 0.0
    ]
    out = r.rerank_by_affect(candidates, query)
    assert [item for item, _ in out] == ["match", "orthogonal"]


def test_rerank_mixes_text_and_affect() -> None:
    """Text winner with bad affect can be overtaken by text runner-up with good affect."""
    r = _Retriever()
    r.affect_weight = 0.5
    query = [1.0, 0.0]
    # text=1.0 but orthogonal emotion → blended 0.5
    # text=0.8 and matching emotion → blended 0.9
    candidates = [
        ("text_top", 1.0, [0.0, 1.0]),
        ("affect_top", 0.8, [1.0, 0.0]),
    ]
    out = r.rerank_by_affect(candidates, query)
    assert [item for item, _ in out] == ["affect_top", "text_top"]


def test_rerank_null_candidate_keeps_text_score() -> None:
    """Candidates without emotion_vec must not be penalized — they pass through on text."""
    r = _Retriever()
    r.affect_weight = 0.5
    query = [1.0, 0.0]
    candidates = [
        ("has_emotion_poor_match", 0.5, [0.0, 1.0]),  # blended 0.25
        ("no_emotion", 0.4, None),                      # text passthrough 0.4
    ]
    out = r.rerank_by_affect(candidates, query)
    assert [item for item, _ in out] == ["no_emotion", "has_emotion_poor_match"]


def test_rerank_dim_mismatch_candidate_keeps_text_score() -> None:
    """16-dim query against a legacy 8-dim candidate → treat as missing emotion."""
    r = _Retriever()
    query = [1.0] * 16
    candidates = [("legacy", 0.7, [1.0] * 8)]
    out = r.rerank_by_affect(candidates, query)
    # Only candidate → blended equals its text score (fallback)
    assert out == [("legacy", 0.7)]


def test_rerank_returns_blended_scores_numerically() -> None:
    r = _Retriever()
    r.affect_weight = 0.25
    query = [1.0, 0.0]
    candidates = [("x", 0.8, [1.0, 0.0])]
    out = r.rerank_by_affect(candidates, query)
    assert len(out) == 1
    item, score = out[0]
    assert item == "x"
    # blended = 0.75*0.8 + 0.25*1.0 = 0.85
    assert score == pytest.approx(0.85)


def test_rerank_empty_candidates() -> None:
    r = _Retriever()
    assert r.rerank_by_affect([], [1.0, 0.0]) == []
    assert r.rerank_by_affect([], None) == []


def test_rerank_is_opt_in_class_without_mixin_unaffected() -> None:
    """Sanity: a plain retriever that never touches this mixin has no new behavior."""

    class Plain:
        def search(self, q):
            return [("a", 0.5), ("b", 0.9)]

    plain = Plain()
    assert plain.search("q") == [("a", 0.5), ("b", 0.9)]
    # And the mixin can't accidentally interfere — it has to be mixed in explicitly.
    assert not isinstance(plain, AffectAwareRetrieverMixin)


def test_rerank_respects_weight_zero_preserves_text_order() -> None:
    """w=0 on a subclass means the mixin is opted out behaviorally."""
    r = _Retriever()
    r.affect_weight = 0.0
    query = [1.0, 0.0]
    candidates = [
        ("high_text_low_affect", 0.9, [0.0, 1.0]),
        ("low_text_high_affect", 0.1, [1.0, 0.0]),
    ]
    out = r.rerank_by_affect(candidates, query)
    assert [item for item, _ in out] == ["high_text_low_affect", "low_text_high_affect"]


def test_rerank_stable_for_equal_blended_scores() -> None:
    """When two candidates blend to the same score, Python's sort is stable."""
    r = _Retriever()
    r.affect_weight = 0.5
    query = [1.0, 0.0]
    # Both text=0.5, both perfect match → both blended 0.75; input order preserved
    candidates = [("first", 0.5, [1.0, 0.0]), ("second", 0.5, [1.0, 0.0])]
    out = r.rerank_by_affect(candidates, query)
    assert [item for item, _ in out] == ["first", "second"]


# ── integration: mixin cooperates with the X6-1 affect helpers ──────


def test_mixin_consumes_decoded_vectors_from_storage_helper() -> None:
    """End-to-end: storage roundtrip via encode/decode, then rerank via mixin."""
    from service.affect import decode_emotion_vec, encode_emotion_vec

    r = _Retriever()
    query = [1.0, 0.0, 0.0]

    stored_good = encode_emotion_vec([1.0, 0.0, 0.0])
    stored_bad = "totally not json"
    stored_null = None

    candidates = [
        ("good", 0.3, decode_emotion_vec(stored_good)),
        ("bad", 0.6, decode_emotion_vec(stored_bad)),      # → None
        ("null", 0.5, decode_emotion_vec(stored_null)),    # → None
    ]
    out = r.rerank_by_affect(candidates, query)
    # default weight 0.3: good=0.7*0.3+0.3*1.0=0.51, bad=0.6 (text), null=0.5 (text)
    assert [item for item, _ in out] == ["bad", "good", "null"]
    assert out[0][1] == pytest.approx(0.6)
    assert out[1][1] == pytest.approx(0.51)
    assert out[2][1] == pytest.approx(0.5)
