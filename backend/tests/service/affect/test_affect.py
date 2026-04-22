"""Affect vector encode/decode helpers (PR-X6-1).

Pins the null/empty/malformed fallbacks so downstream retrieval code
(PR-X6-2) can rely on ``decode_emotion_vec`` never raising.
"""

from __future__ import annotations

import json

from service.affect import decode_emotion_vec, encode_emotion_vec


# ── encode ────────────────────────────────────────────────────────────


def test_encode_none_passes_through() -> None:
    assert encode_emotion_vec(None) is None


def test_encode_empty_sequence_returns_none() -> None:
    """Empty vectors carry no retrieval signal — treat as absence."""
    assert encode_emotion_vec([]) is None
    assert encode_emotion_vec(()) is None


def test_encode_round_trip_preserves_floats() -> None:
    raw = encode_emotion_vec([0.1, 0.2, 0.3, -0.4])
    assert raw is not None
    parsed = json.loads(raw)
    assert parsed == [0.1, 0.2, 0.3, -0.4]


def test_encode_coerces_ints_to_floats() -> None:
    raw = encode_emotion_vec([1, 2, 3])
    parsed = json.loads(raw)
    assert parsed == [1.0, 2.0, 3.0]
    assert all(isinstance(x, float) for x in parsed)


# ── decode ────────────────────────────────────────────────────────────


def test_decode_none_returns_none() -> None:
    assert decode_emotion_vec(None) is None


def test_decode_empty_string_returns_none() -> None:
    assert decode_emotion_vec("") is None


def test_decode_valid_round_trip() -> None:
    vec = [0.5, -0.25, 0.125]
    assert decode_emotion_vec(encode_emotion_vec(vec)) == vec


def test_decode_malformed_json_returns_none() -> None:
    assert decode_emotion_vec("not json") is None
    assert decode_emotion_vec("[1, 2,") is None


def test_decode_non_list_json_returns_none() -> None:
    assert decode_emotion_vec('"hello"') is None
    assert decode_emotion_vec("42") is None
    assert decode_emotion_vec('{"a": 1}') is None


def test_decode_non_numeric_elements_return_none() -> None:
    assert decode_emotion_vec('["a", "b"]') is None
    assert decode_emotion_vec("[1, 2, null]") is None


def test_decode_numeric_strings_are_coerced() -> None:
    """JSON numbers decode to int/float — but if someone wrote string
    numerics (e.g. from a CSV import), accept them via ``float(x)``."""
    assert decode_emotion_vec('["1.5", "2.5"]') == [1.5, 2.5]
