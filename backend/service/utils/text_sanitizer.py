"""Display-layer sanitization for agent output.

Strips the three kinds of special markers that agents emit but that
should never reach a user-visible surface (chat room, TTS, UI):

* Routing / system prefixes — ``[THINKING_TRIGGER]``,
  ``[SUB_WORKER_RESULT]``, ``[DELEGATION_REQUEST|RESULT]``, etc.
  These are protocol tags consumed by the classifier / router.
* Emotion tags — ``[joy]``, ``[surprise]``, ``[smirk]``, …
  emitted deliberately by VTuber prompts and consumed by the
  avatar layer (``EmotionExtractor``). Not for humans.
* Reasoning blocks — ``<think>...</think>`` emitted by reasoning
  models.

Kept free of agent/session state so it's safe to call from any
display sink, including streaming accumulation where the input may
be a partial, still-growing string (a regex ``sub`` over the whole
accumulated buffer correctly strips complete tags and leaves an
incomplete trailing tag in place until the next token completes it).

Governance: the emotion-tag vocabulary lives in
:mod:`service.affect.taxonomy` (cycle 20260422_5 X7). Both this
module and :class:`service.emit.affect_tag_emitter.AffectTagEmitter`
import ``RECOGNIZED_TAGS`` from there, and a second narrow
catch-all strips any lowercase-bracketed identifier that slips past
the whitelist — so a newly-invented tag name the LLM tries never
reaches the user-visible surface, even if the taxonomy hasn't been
updated yet.
"""

from __future__ import annotations

import re

from service.affect.taxonomy import RECOGNIZED_TAGS

# Exported so consumers (TTS sanitizer, future plugins) can extend
# the routing-prefix set without duplicating the master list.
SYSTEM_TAG_PATTERN = re.compile(
    r"\["
    r"(?:THINKING_TRIGGER(?::\w+)?|"
    r"autonomous_signal:[^]]*|"
    r"DELEGATION_REQUEST|"
    r"DELEGATION_RESULT|"
    r"SUB_WORKER_RESULT|"
    r"CLI_RESULT|"
    r"ACTIVITY_TRIGGER(?::\w+)?|"
    r"SILENT)"
    r"\]\s*",
    re.IGNORECASE,
)

# Canonical emotion labels. Imported from the single source of truth
# in ``service.affect.taxonomy`` so the sanitizer, the emitter, and
# the prompt instruction can't drift apart. See the taxonomy module
# docstring for the governance rule.
EMOTION_TAGS = RECOGNIZED_TAGS
# The optional ``:strength`` suffix matches the grammar documented in
# ``backend/prompts/vtuber.md`` — a decimal number (optional leading
# ``-``, optional fractional part). Strict numeric payload on purpose:
# legitimate bracketed text like ``[note: todo]`` or ``[DM to Bob]``
# must survive this pass (the router / catch-all below handle other
# cases). Allow whitespace inside the bracket (``[joy : 0.7]``,
# ``[joy:1.5 ]``) so lightly malformed LLM output still strips.
_STRENGTH_RE = r"(?:\s*:\s*-?\d+(?:\.\d+)?)?"

EMOTION_TAG_PATTERN = re.compile(
    r"\[\s*(?:" + "|".join(EMOTION_TAGS) + r")" + _STRENGTH_RE + r"\s*\]\s*",
    re.IGNORECASE,
)

# Narrow catch-all mirroring ``AffectTagEmitter.UNKNOWN_EMOTION_TAG_RE``
# — any *remaining* lowercase single-word bracket tag that isn't on the
# canonical list is also stripped from display, including an optional
# ``:strength`` numeric suffix. Matches the emitter's safety-net so
# user-facing text never carries raw ``[something]`` or ``[something:0.7]``.
# Uppercase routing tags (already handled above) don't match. Non-numeric
# payloads like ``[note: todo]`` are preserved by the strict numeric
# strength rule.
UNKNOWN_EMOTION_TAG_PATTERN = re.compile(
    r"\[\s*[a-z][a-z_]{2,19}" + _STRENGTH_RE + r"\s*\]\s*",
)

THINK_BLOCK_PATTERN = re.compile(
    r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE
)
# Open-ended <think> with no closer (the LLM didn't emit </think>
# yet, e.g. mid-stream). Everything from <think> onward is dropped.
THINK_OPEN_PATTERN = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)

_WHITESPACE_COLLAPSE = re.compile(r"\s{2,}")


def sanitize_for_display(text: str | None) -> str:
    """Strip routing / emotion / think markers; collapse whitespace.

    Safe on ``None`` and empty input — returns ``""`` so callers can
    concatenate / length-check without guarding.

    Unknown bracketed tokens (e.g. ``[note]``, ``[INBOX from X]``)
    are preserved; only the whitelisted routing prefixes and canonical
    emotion labels are removed. This keeps legitimate user text that
    happens to contain brackets intact.
    """
    if not text:
        return ""
    text = THINK_BLOCK_PATTERN.sub("", text)
    text = THINK_OPEN_PATTERN.sub("", text)
    text = SYSTEM_TAG_PATTERN.sub("", text)
    text = EMOTION_TAG_PATTERN.sub("", text)
    text = UNKNOWN_EMOTION_TAG_PATTERN.sub("", text)
    return _WHITESPACE_COLLAPSE.sub(" ", text).strip()
