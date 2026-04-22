"""Affect serialization helpers for memory records.

Cycle 20260422_2 PR-X6-1 introduces nullable :attr:`emotion_vec` /
:attr:`emotion_intensity` columns on :class:`SessionMemoryEntryModel`.
Writers encode a Python ``list[float]`` to JSON for storage; readers
decode back. ``emotion_intensity`` is a plain scalar so it needs no
helper, but we keep both sides here for symmetry and one consistent
place to evolve the encoding if we switch to ``pgvector`` /
``FLOAT8[]`` later.

Design notes
------------

- **JSON rather than native array type.** PostgreSQL has ``FLOAT8[]`` /
  ``vector`` (pgvector) and SQLite has none — using a TEXT column with
  JSON keeps the migration story simple: one ``ALTER TABLE ADD COLUMN``
  regardless of backend. X6-3/X6-4 "real data" follow-ups can switch to
  a typed column if profiling proves it needed.
- **Permissive decode.** Corrupt or malformed JSON decodes to
  ``None`` — not an exception — so a single poisoned row doesn't kill
  retrieval for the rest of the session.
- **No shape enforcement here.** The vector's dimension is set by
  whichever embedder wrote it; the retriever mixin (PR-X6-2) is
  responsible for dimension-mismatch handling when comparing two
  vectors. Keeping this helper oblivious to shape means swapping
  embedders doesn't require touching persistence code.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = ["encode_emotion_vec", "decode_emotion_vec"]


def encode_emotion_vec(vec: Optional[Sequence[float]]) -> Optional[str]:
    """Serialize an emotion vector for the ``emotion_vec`` TEXT column.

    ``None`` passes through — NULL storage means "no emotion captured".
    An empty sequence is treated as absence (returns ``None``), not as
    "zero-dimensional vector", because an empty vector has no retrieval
    utility and downstream ranking would skip it anyway.
    """
    if vec is None:
        return None
    floats = [float(x) for x in vec]
    if not floats:
        return None
    return json.dumps(floats)


def decode_emotion_vec(raw: Optional[str]) -> Optional[List[float]]:
    """Parse a stored ``emotion_vec`` TEXT value back to a Python list.

    Returns ``None`` for NULL / empty / malformed input — the retriever
    mixin treats missing and corrupt vectors identically (fall back to
    text-only ranking).
    """
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("emotion_vec decode failed for value %r", raw)
        return None
    if not isinstance(parsed, list):
        logger.debug("emotion_vec decoded to non-list %r", type(parsed).__name__)
        return None
    try:
        return [float(x) for x in parsed]
    except (TypeError, ValueError):
        logger.debug("emotion_vec elements not all numeric: %r", parsed)
        return None
