"""Display-layer sanitization for agent output.

Strips the three kinds of special markers that agents emit but that
should never reach a user-visible surface (chat room, TTS, UI):

* Routing / system prefixes — ``[THINKING_TRIGGER]``,
  ``[SUB_WORKER_RESULT]``, ``[DELEGATION_REQUEST|RESULT]``, and the loop
  signals ``[TASK_COMPLETE]`` / ``[BLOCKED]`` / ``[CONTINUE]``. These are
  protocol tags consumed by the classifier / router / loop.
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
    r"SILENT|"
    # Loop signals. The pipeline reads these to decide whether a turn is
    # over (``prompts`` teaches them; ``agent_executor`` reads them to tell
    # narration from a tool-only turn) and a reader has no use for them —
    # but until now nothing stripped them, so every answer ended in a
    # visible ``[TASK_COMPLETE]`` on every surface, chat and TTS included.
    r"TASK_COMPLETE|"
    r"BLOCKED(?::[^]]*)?|"
    r"CONTINUE(?::[^]]*)?)"
    # Trailing horizontal whitespace only — never newlines, so stripping a
    # tag can't swallow the blank line that separates markdown blocks.
    r"\][^\S\n]*",
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
    # Trailing ``[^\S\n]*`` (not ``\s*``) so removing an inline emotion tag
    # keeps any following newline — the paragraph break between blocks.
    r"\[\s*(?:" + "|".join(EMOTION_TAGS) + r")" + _STRENGTH_RE + r"\s*\][^\S\n]*",
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
    r"\[\s*[a-z][a-z_]{2,19}" + _STRENGTH_RE + r"\s*\][^\S\n]*",
)

THINK_BLOCK_PATTERN = re.compile(
    # Trailing horizontal whitespace only, so a reasoning block wedged
    # between two paragraphs doesn't glue them when removed.
    r"<think>.*?</think>[^\S\n]*", re.DOTALL | re.IGNORECASE
)
# Open-ended <think> with no closer (the LLM didn't emit </think>
# yet, e.g. mid-stream). Everything from <think> onward is dropped.
THINK_OPEN_PATTERN = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)

# Display whitespace tidy — collapse runs of *horizontal* whitespace but
# KEEP newlines, so markdown block structure (the blank lines that separate
# headings / tables / block quotes / fenced code) survives into the chat
# renderer. Collapsing newlines here — as an earlier ``\s{2,}`` pass did —
# glued every block onto one line, so tables and headings stopped rendering.
_DISPLAY_HORIZONTAL_WS = re.compile(r"[^\S\n]+")
_DISPLAY_WS_AROUND_NL = re.compile(r"[^\S\n]*\n[^\S\n]*")
_DISPLAY_BLANK_LINE_RUN = re.compile(r"\n{3,}")
# Fenced code is copied verbatim so its indentation isn't flattened.
_FENCED_CODE_SPAN = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)


def _tidy_display_whitespace(chunk: str) -> str:
    chunk = _DISPLAY_HORIZONTAL_WS.sub(" ", chunk)   # space/tab runs → 1 space
    chunk = _DISPLAY_WS_AROUND_NL.sub("\n", chunk)   # trim spaces hugging \n
    chunk = _DISPLAY_BLANK_LINE_RUN.sub("\n\n", chunk)  # cap blank-line runs
    return chunk


def _collapse_display_whitespace(text: str) -> str:
    """Tidy whitespace for display while preserving newlines and leaving
    fenced code blocks byte-for-byte intact."""
    out: list[str] = []
    last = 0
    for m in _FENCED_CODE_SPAN.finditer(text):
        out.append(_tidy_display_whitespace(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_tidy_display_whitespace(text[last:]))
    return "".join(out).strip()

# ──────────────────────────────────────────────────────────────────
# TTS-specific stripping — emoji + textual emoticon
# ──────────────────────────────────────────────────────────────────
#
# TTS engines transliterate emoji to whatever the configured locale
# pronounces them as — frequently producing the wrong-language
# spoken output the user reported (😊 read aloud as
# "smiling-face-with-smiling-eyes" in English mid-sentence). Strip
# them before audio synthesis. Display surfaces (chat UI) keep them.
#
# The pattern covers the SMP emoji blocks plus the BMP misc-symbols
# / dingbats / variation-selector / ZWJ / keycap range. Arrow blocks
# (U+2190-U+21FF) are deliberately excluded — they're plain
# directional symbols that frequently appear in legitimate Korean
# text (→ ←) and pronounce fine.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # Misc Symbols & Pictographs
    "\U0001F600-\U0001F64F"  # Emoticons (😀-🙏)
    "\U0001F680-\U0001F6FF"  # Transport & Map
    "\U0001F700-\U0001F77F"  # Alchemical Symbols
    "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols & Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols & Pictographs Extended-A
    "\U00002600-\U000026FF"  # Misc Symbols (☀⚡⚠)
    "\U00002700-\U000027BF"  # Dingbats (✨✅✂)
    "\U00002B00-\U00002BFF"  # Misc Symbols & Arrows (⭐⭕⬛⬜⬅⬆⬇)
    "\U00002300-\U000023FF"  # Misc Technical (⌚⌛⏰⏳)
    "\U0001F1E6-\U0001F1FF"  # Regional Indicator (flags)
    "\U0001F3FB-\U0001F3FF"  # Skin tone modifiers
    "\U0000FE00-\U0000FE0F"  # Variation Selectors
    "\U0000200D"             # Zero Width Joiner
    "\U000020E3"             # Combining Enclosing Keycap
    "]+",
    flags=re.UNICODE,
)

# Common textual emoticons. Conservative whitelist — only the
# unambiguously-emoticon shapes that TTS would render as character
# sequences ("colon dash D" etc.). Word-boundary-anchored so we
# don't accidentally chew up legitimate text like ":-)". The shapes
# are case-sensitive on the letter parts.
_EMOTICON_PATTERN = re.compile(
    r"(?<!\w)"
    r"(?:"
    r":-?[\)\(DP/o\\\|]"   # :)  :(  :D  :P  :/  :o  :\  :|
    r"|;-?[\)D]"            # ;)  ;D
    r"|XD|xD|=\)|=\("
    r"|T_T|T\.T|ㅠㅠ|ㅜㅜ|ㅎㅎ|ㅋㅋ+"
    r"|>_<|\^_\^|\^\^|\^o\^"
    r")"
    r"(?!\w)",
)

# ──────────────────────────────────────────────────────────────────
# Markdown stripping for TTS
# ──────────────────────────────────────────────────────────────────
#
# Agents frequently format their replies with markdown — headings
# (``#`` / ``##``), emphasis (``**bold**``, ``*italic*``), lists,
# block quotes, fenced code, links, and Obsidian-style wikilinks
# (``[[target]]``). When the unprocessed text reaches TTS, the
# engine reads the punctuation literally ("hash hash hello",
# "asterisk asterisk asterisk asterisk strong", etc.). The user's
# captured failure mode included ``# 안녕하세요!`` and ``**굵은
# 글씨**`` being voiced verbatim.
#
# These patterns operate on the post-display-sanitised text, so
# routing tags / emotion tags / think blocks are already gone by
# the time we run them. We strip the markup *but keep the visible
# words*.
#
# Order of application matters:
#   1. Fenced code blocks → unwrap to inner text (don't lose the
#      content; agents sometimes put speakable explanations inside)
#   2. Inline code (``...``) → strip backticks, keep contents
#   3. Images ``![alt](url)`` → drop entirely (alt text is rarely
#      worth speaking and ``alt`` text often duplicates surrounding
#      prose)
#   4. Links ``[text](url)`` → keep ``text``, drop URL
#   5. Wikilinks ``[[target|alias]]`` → keep alias if present, else
#      target — same convention as our memory writers
#   6. Emphasis (``**``, ``__``, ``*``, ``_``) → strip markers,
#      keep wrapped text
#   7. Headings (``#`` at line start) → strip the ``#`` run + space
#   8. Block quotes (``>`` at line start) → strip
#   9. List markers (``-`` / ``*`` / ``+`` / ``1.`` at line start)
#      → strip
#  10. Horizontal rules (``---``, ``***``, ``___`` on their own
#      line) → drop
#  11. HTML tags (``<br>``, ``<b>foo</b>``) → strip tags, keep text
#  12. Stray punctuation cleanup (multiple consecutive separators)

_MD_FENCED_CODE = re.compile(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", re.DOTALL)
_MD_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_WIKILINK = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")
_MD_BOLD_ITALIC_STAR = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}")
_MD_BOLD_ITALIC_UNDER = re.compile(r"(?<![A-Za-z0-9_])_{1,3}([^_\n]+?)_{1,3}(?![A-Za-z0-9_])")
_MD_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_MD_BLOCKQUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE)
_MD_LIST_MARKER = re.compile(r"^[ \t]*(?:[-*+]|\d{1,3}[.)])[ \t]+", re.MULTILINE)
_MD_HRULE = re.compile(r"^[ \t]{0,3}(?:[-*_][ \t]?){3,}[ \t]*$", re.MULTILINE)
_MD_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
# Inline separator runs that AREN'T a full-line horizontal rule — topic
# dividers the persona drops between same-line text: ``a --- b``, ``a — b``,
# ``~~~``, ``***``, ``•••``. The run (or a lone em/en/hyphen dash) must be
# whitespace-delimited on BOTH sides, so word-internal hyphens (``e-mail``,
# ``2-3``, ``test_file``) and arrows survive. Replacing with the captured
# leading boundary keeps the surrounding spacing; the final whitespace
# collapse tidies the rest.
_MD_INLINE_SEP = re.compile(r"(^|\s)(?:[-–—~·•*_]{2,}|[—–-])(?=\s|$)")


def _strip_markdown_for_tts(text: str) -> str:
    """Strip markdown formatting from ``text`` while preserving the
    spoken words. Order-sensitive — see the comment block above.
    """
    if not text:
        return ""
    # 1. Fenced code blocks → inner content
    text = _MD_FENCED_CODE.sub(lambda m: m.group(1) or "", text)
    # 2. Inline code → unwrap
    text = _MD_INLINE_CODE.sub(r"\1", text)
    # 3. Images → drop
    text = _MD_IMAGE.sub("", text)
    # 4. Links → keep visible text
    text = _MD_LINK.sub(r"\1", text)
    # 5. Wikilinks → alias if present, else target
    text = _MD_WIKILINK.sub(lambda m: m.group(2) or m.group(1), text)
    # 6. Emphasis — apply twice so triple stars (``***x***``) collapse
    #    cleanly through the bold-then-italic passes.
    for _ in range(2):
        text = _MD_BOLD_ITALIC_STAR.sub(r"\1", text)
        text = _MD_BOLD_ITALIC_UNDER.sub(r"\1", text)
    # 7. Headings — strip leading ``#`` runs
    text = _MD_HEADING.sub("", text)
    # 8. Block quotes — strip leading ``>``
    text = _MD_BLOCKQUOTE.sub("", text)
    # 9. List markers — strip leading bullet / number
    text = _MD_LIST_MARKER.sub("", text)
    # 10. Horizontal rules — drop the whole line
    text = _MD_HRULE.sub("", text)
    # 11. HTML tags
    text = _MD_HTML_TAG.sub("", text)
    # 12. Inline separator runs — drop dividers used between same-line text
    #     (``a --- b``, ``a — b``, ``~~~``), keeping word-internal hyphens.
    #     Apply twice so back-to-back dividers (``a --- b --- c``) fully clear.
    text = _MD_INLINE_SEP.sub(r"\1", text)
    text = _MD_INLINE_SEP.sub(r"\1", text)
    return text


def sanitize_for_display(text: str | None) -> str:
    """Strip routing / emotion / think markers; tidy whitespace.

    Safe on ``None`` and empty input — returns ``""`` so callers can
    concatenate / length-check without guarding.

    Unknown bracketed tokens (e.g. ``[note]``, ``[INBOX from X]``)
    are preserved; only the whitelisted routing prefixes and canonical
    emotion labels are removed. This keeps legitimate user text that
    happens to contain brackets intact.

    Newlines are **preserved** (only horizontal whitespace runs collapse,
    blank-line runs cap at one, and fenced code is left intact). The chat
    UI renders this text as markdown, so the blank lines separating
    headings / tables / block quotes / code fences must survive — an
    earlier ``\\s{2,} → " "`` pass collapsed them and glued every block
    onto one line, which stopped tables and headings from rendering.

    Note — emoji and textual emoticons survive this pass because chat
    UIs render them correctly. Use :func:`sanitize_for_tts` for the
    audio synthesis path; that pass also strips emoji and flattens
    newlines for continuous speech.
    """
    if not text:
        return ""
    text = THINK_BLOCK_PATTERN.sub("", text)
    text = THINK_OPEN_PATTERN.sub("", text)
    text = SYSTEM_TAG_PATTERN.sub("", text)
    text = EMOTION_TAG_PATTERN.sub("", text)
    text = UNKNOWN_EMOTION_TAG_PATTERN.sub("", text)
    return _collapse_display_whitespace(text)


def sanitize_for_tts(text: str | None) -> str:
    """Display-sanitised + emoji / emoticon / markdown stripped.

    TTS engines fail in three distinct ways on raw agent output:

      * emoji are transliterated to their Unicode-name word forms
        (😊 → "smiling-face-with-smiling-eyes") in whatever the
        engine's primary locale is, wrecking Korean / Japanese audio
        with mid-sentence English fragments;
      * common textual emoticons (``:)`` ``ㅋㅋ`` ``^_^``) are voiced
        as character sequences;
      * **markdown formatting is read literally** — agents that
        reply with headings (``# 안녕하세요!``), emphasis
        (``**굵은 글씨**``), wikilinks (``[[target]]``), or fenced
        code make the TTS engine speak the punctuation ("hash hash
        hello", "asterisk asterisk strong asterisk asterisk").

    This pass handles all three. Output is plain prose ready for the
    audio engine. Display surfaces (chat UI) should keep using
    :func:`sanitize_for_display` so the visible transcript still
    shows the emoji and markdown the agent wrote.

    Order is load-bearing: the markdown stripper relies on
    line-anchored patterns (headings, blockquotes, list markers,
    horizontal rules), so line structure is kept intact through the
    routing/think/emotion strips and the markdown unwrap, and only
    *then* is every newline flattened into a space so the TTS engine
    reads continuously. (Unlike :func:`sanitize_for_display`, which
    now preserves newlines for the markdown-rendering chat UI, the
    TTS output must end up single-line.)
    """
    if not text:
        return ""
    # Reasoning blocks first — ``<think>``/``</think>`` payloads are
    # never speakable and can contain anything (including markdown
    # we'd otherwise unwrap).
    text = THINK_BLOCK_PATTERN.sub("", text)
    text = THINK_OPEN_PATTERN.sub("", text)
    # Markdown next — runs *before* the bracket-tag strippers so
    # constructs like ``[[wikilink]]``, ``[link text](url)``, and
    # ``![alt](url)`` get unwrapped without
    # ``UNKNOWN_EMOTION_TAG_PATTERN`` clobbering the inner
    # ``[wikilink]`` / ``[alt]`` and leaving an orphan ``[]`` /
    # ``!(image.png)`` behind.
    text = _strip_markdown_for_tts(text)
    # Routing prefixes + emotion tags + unknown bracketed tags —
    # whatever brackets remain after markdown unwrap are real
    # routing/emotion noise and get cleaned up here.
    text = SYSTEM_TAG_PATTERN.sub("", text)
    text = EMOTION_TAG_PATTERN.sub("", text)
    text = UNKNOWN_EMOTION_TAG_PATTERN.sub("", text)
    # Emoji + textual emoticons — pure character-level passes.
    text = _EMOJI_PATTERN.sub("", text)
    text = _EMOTICON_PATTERN.sub("", text)
    # Final whitespace collapse — newlines and runs of spaces
    # become single spaces so the TTS engine reads continuously.
    text = re.sub(r"\s+", " ", text)
    return text.strip()
