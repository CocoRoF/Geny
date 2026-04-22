"""Multi-language sentence splitter for streaming TTS (Phase 4).

OmniVoice's :py:meth:`omnivoice_core.models.OmniVoice.generate` is
non-streaming: a single call produces one PCM array for the whole input
text. To deliver an interactive feel for chat-style payloads (where the
LLM may emit several sentences in one response) we split the text into
sentences on the *client* side of the model and feed them through one
generation call each. The resulting PCM chunks are then framed onto
the wire in order, so the listener hears sentence #1 while the model is
still synthesising sentence #2.

Splitting rules
---------------

We segment on *terminal* punctuation common to the languages OmniVoice
ships with (English, Korean, Japanese, Chinese), keeping the punctuation
attached to the preceding clause:

* ``. ! ?`` (Latin)
* ``。 ！ ？`` (CJK fullwidth)
* ``…``      (ellipsis is treated as a soft terminator)

Newlines in the source text always end a sentence — chat models
frequently emit ``"Hello.\\n\\nHow are you?"`` and we don't want a long
silent gap from a synthesiser inferring continuity. Blank lines
(``\\n\\n``) are treated as **paragraph barriers** that the merge pass
will never cross.

Length safety
-------------

Sentences longer than ``max_chars`` are *soft-split* on whitespace at a
character budget, then on hard character cut as a last resort, so a
runaway non-stopping sentence still gets fed to the model in
manageable chunks (default 240 chars ≈ 12s of audio).

Minimum-chunk merging
---------------------

After the primary split, adjacent sentences within the **same
paragraph** are coalesced until each chunk reaches at least
``min_chars`` characters. This avoids the pathological case where the
LLM emits filler interjections like ``"음..."`` or ``"와!"`` and each
becomes its own per-sentence model invocation — on Pascal-class GPUs
the per-call setup overhead dominates, so a fragmented stream is
*slower* than a single-shot synthesis. Merging respects paragraph
breaks so the prosody of multi-paragraph replies is preserved. The
last fragment of a paragraph is allowed to fall below ``min_chars`` if
there's nothing left to merge with.

Empty / whitespace-only fragments are silently dropped.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, List

logger = logging.getLogger("server.text_split")


# Terminal punctuation: a character class of all sentence enders. The
# regex captures the terminator so we keep it attached to the segment.
_TERMINATOR = r"[.!?。！？…]"
_SENTENCE_RE = re.compile(rf"([^\n]+?{_TERMINATOR}+|[^\n]+)\s*", re.DOTALL)

# Blank-line paragraph separator (one or more empty lines, ignoring
# whitespace-only lines). Used to slice the input into paragraphs that
# the merge pass treats as hard barriers.
_PARAGRAPH_RE = re.compile(r"\n[ \t]*\n+")


def split_sentences(
    text: str,
    *,
    max_chars: int = 240,
    min_chars: int = 0,
) -> List[str]:
    """Split ``text`` into a list of sentences.

    Each returned chunk satisfies ``len(chunk) <= max_chars`` and, when
    possible, ``len(chunk) >= min_chars``. The split is greedy
    left-to-right; punctuation stays with the preceding clause.

    * ``max_chars`` controls the *upper* bound — fragments longer than
      this are soft-split on whitespace, falling back to a hard cut.
    * ``min_chars`` controls the *lower* bound — adjacent fragments
      within the same paragraph are merged together until the running
      length reaches the budget. Set to ``0`` (default) to disable the
      merge pass entirely (legacy behaviour).

    Paragraph barriers (one or more blank lines) are never crossed by
    the merge pass — multi-paragraph replies keep their natural pauses.
    The last fragment of a paragraph is emitted even if it falls below
    ``min_chars``; the goal is to amortise model setup, not to enforce
    a strict floor.
    """
    if not text or not text.strip():
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    if min_chars < 0:
        raise ValueError("min_chars must be >= 0")
    # Don't let an over-eager min swallow the upper bound — a merged
    # chunk must still respect ``max_chars``.
    effective_min = min(min_chars, max_chars)

    out: List[str] = []
    # Slice on blank lines first; these are paragraph barriers we will
    # never merge across. A single ``\n`` inside a paragraph is still
    # treated as a sentence break (chat / markdown convention).
    for paragraph in _PARAGRAPH_RE.split(text):
        if not paragraph or not paragraph.strip():
            continue
        # Per-paragraph: split on internal newlines + terminal punct.
        para_pieces: List[str] = []
        for line in paragraph.split("\n"):
            line = line.strip()
            if not line:
                continue
            for match in _SENTENCE_RE.finditer(line):
                segment = match.group(1).strip()
                if not segment:
                    continue
                if len(segment) <= max_chars:
                    para_pieces.append(segment)
                else:
                    para_pieces.extend(_soft_split(segment, max_chars=max_chars))
        # Coalesce within the paragraph.
        if effective_min > 0 and para_pieces:
            out.extend(_coalesce(para_pieces, min_chars=effective_min, max_chars=max_chars))
        else:
            out.extend(para_pieces)
    return out


def _coalesce(pieces: List[str], *, min_chars: int, max_chars: int) -> List[str]:
    """Merge adjacent pieces until each is at least ``min_chars`` long.

    Within the budget, we prefer to grow the current chunk by appending
    the next piece (with a single space) rather than emit something
    shorter than ``min_chars``. We refuse to merge if the result would
    exceed ``max_chars`` — this keeps the upper bound contract intact.

    The final piece may be shorter than ``min_chars`` if there's
    nothing left to merge with; that's intentional. Trying to backfill
    by stealing from the previous chunk would force a re-synthesis of
    audio that's already been emitted in a streaming context.
    """
    if not pieces:
        return []
    merged: List[str] = []
    cur = pieces[0]
    for nxt in pieces[1:]:
        # If current chunk is already long enough OR appending would
        # blow the upper bound, flush and start fresh.
        if len(cur) >= min_chars:
            merged.append(cur)
            cur = nxt
            continue
        # Joining cost is +1 for the separator. If that exceeds
        # max_chars we have to flush short — better a slightly short
        # chunk than violating the upper bound.
        joined_len = len(cur) + 1 + len(nxt)
        if joined_len > max_chars:
            merged.append(cur)
            cur = nxt
            continue
        cur = f"{cur} {nxt}"
    if cur:
        merged.append(cur)
    return merged


def _soft_split(segment: str, *, max_chars: int) -> List[str]:
    """Split a too-long segment on whitespace, falling back to hard cut.

    Tries to break at a space near the budget boundary; if the segment
    has no whitespace at all (e.g. a long URL or a CJK run with no
    spaces) it falls back to a fixed-width slice.
    """
    pieces: List[str] = []
    remaining = segment
    while len(remaining) > max_chars:
        # Look for the last whitespace within the budget; if none, hard cut.
        cut = remaining.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        head = remaining[:cut].strip()
        if head:
            pieces.append(head)
        remaining = remaining[cut:].lstrip()
    if remaining.strip():
        pieces.append(remaining.strip())
    return pieces


def chunked_sentences(
    text: str,
    *,
    max_chars: int = 240,
    min_chars: int = 0,
) -> Iterable[tuple[int, str]]:
    """Yield ``(seq, sentence)`` pairs, ``seq`` starting at 0.

    Convenience wrapper for the streaming endpoint, which needs the
    sequence number to label each PCM chunk on the wire.
    """
    for i, s in enumerate(
        split_sentences(text, max_chars=max_chars, min_chars=min_chars)
    ):
        yield i, s
