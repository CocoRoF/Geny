"""Pin tests for the display-layer text sanitizer.

Cycle 20260421_2 / plan 01: the sanitizer is the single source of
truth for how routing / emotion / think markers are stripped before
agent output reaches any user-visible surface. These tests lock
down the contract so later changes to the surface sinks
(chat_controller, agent_executor, thinking_trigger) can't
accidentally widen or narrow it.
"""

from __future__ import annotations

import pytest

from service.utils.text_sanitizer import sanitize_for_display


# ─────────────────────────────────────────────────────────────────
# Pure function — every category covered
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        # ── Empty / falsy ──
        ("", ""),
        (None, ""),
        ("   ", ""),
        # ── Plain text unchanged ──
        ("안녕하세요", "안녕하세요"),
        ("Hello, world!", "Hello, world!"),
        # ── Single emotion tag ──
        ("[joy] 안녕!", "안녕!"),
        ("안녕! [joy]", "안녕!"),
        # ── Multiple emotion tags mixed in ──
        ("[joy] 안녕 [smirk] 반가워", "안녕 반가워"),
        # Every canonical emotion should be recognised
        ("[neutral] x [anger] y [disgust] z", "x y z"),
        ("[fear] x [sadness] y [surprise] z", "x y z"),
        ("[warmth] x [curious] y [calm] z", "x y z"),
        ("[excited] x [shy] y [proud] z", "x y z"),
        ("[grateful] x [playful] y [confident] z", "x y z"),
        ("[thoughtful] x [concerned] y [amused] z [tender] w", "x y z w"),
        # ── Routing / system prefixes ──
        ("[SUB_WORKER_RESULT] 워커 답장", "워커 답장"),
        ("[THINKING_TRIGGER] 조용하네", "조용하네"),
        ("[THINKING_TRIGGER:first_idle] 조용하네", "조용하네"),
        ("[CLI_RESULT] legacy", "legacy"),
        ("[ACTIVITY_TRIGGER] hi", "hi"),
        ("[ACTIVITY_TRIGGER:user_return] hi", "hi"),
        ("[DELEGATION_REQUEST] do this", "do this"),
        ("[DELEGATION_RESULT] done", "done"),
        ("[autonomous_signal:morning_check] ping", "ping"),
        ("[SILENT] quiet", "quiet"),
        # ── Case insensitivity ──
        ("[JOY] hi", "hi"),
        ("[Sub_Worker_Result] x", "x"),
        ("[thinking_trigger:X] y", "y"),
        # ── Combined routing + emotion (the user-reported case) ──
        (
            "[SUB_WORKER_RESULT] 워케에게서 답장이 왔어요! [joy]\n\n"
            "워커가 정말 친근하게 인사해주네요~ [surprise]",
            "워케에게서 답장이 왔어요! 워커가 정말 친근하게 인사해주네요~",
        ),
        # ── <think> blocks ──
        ("<think>internal</think>Hello", "Hello"),
        ("Hi <think>a</think>there<think>b</think>", "Hi there"),
        ("Pre <think>reasoning\nacross\nlines</think> post", "Pre post"),
        # ── Unclosed <think> block — everything after is dropped ──
        ("<think>never closed", ""),
        ("visible <think>rest is dropped", "visible"),
        # ── X7: unknown lowercase single-word brackets are now STRIPPED ──
        # This is the catch-all safety net for emotion-like tags the
        # LLM invents outside the taxonomy. See taxonomy.py docstring.
        ("[random_thing] stays", "stays"),
        # Tags with colons + spaces / punctuation are NOT single-word
        # identifiers, so they remain — the narrow catch-all preserves
        # these legitimate bracketed payloads.
        ("[note: todo] also stays", "[note: todo] also stays"),
        # Input-only routing tags with spaces / capitals / punctuation
        # stay preserved — the catch-all is intentionally narrow.
        (
            "[INBOX from Alice] should stay",
            "[INBOX from Alice] should stay",
        ),
        (
            "[DM to Bob (internal)] not stripped",
            "[DM to Bob (internal)] not stripped",
        ),
        # ── Whitespace collapsing ──
        ("a   b   c", "a b c"),
        ("[joy]    안녕", "안녕"),
        ("before [joy]   after", "before after"),
        # ── Emotion tags with no following space ──
        ("[joy]hello", "hello"),
        # ── Tags at boundaries ──
        ("\n\n[joy]\n\nhello\n\n", "hello"),
    ],
)
def test_sanitize_for_display(text: str | None, expected: str) -> None:
    assert sanitize_for_display(text) == expected


# ─────────────────────────────────────────────────────────────────
# Partial / streaming input — token-boundary safety
# ─────────────────────────────────────────────────────────────────


def test_partial_tag_at_end_is_preserved() -> None:
    """Streaming accumulator: if the current buffer ends mid-tag, the
    partial tag must survive so the next appended chunk can complete
    it. The sanitizer only strips complete, recognised tags.
    """
    assert sanitize_for_display("hello [j") == "hello [j"
    assert sanitize_for_display("hello [jo") == "hello [jo"
    # Only once complete AND recognised does stripping happen.
    assert sanitize_for_display("hello [joy") == "hello [joy"
    assert sanitize_for_display("hello [joy]") == "hello"


def test_partial_think_open_drops_everything_after() -> None:
    """Conservative choice: if we see <think> but no </think>, treat
    the remainder as in-progress reasoning that must not be shown.
    A later chunk closing the block also produces empty (or the
    pre-think portion), which is fine — reasoning stays hidden.
    """
    assert sanitize_for_display("visible <think>partial") == "visible"


# ─────────────────────────────────────────────────────────────────
# Back-compat shim — tts_controller.sanitize_tts_text
# ─────────────────────────────────────────────────────────────────


def test_tts_shim_matches_sanitize_for_display() -> None:
    from controller.tts_controller import sanitize_tts_text
    sample = "[SUB_WORKER_RESULT] hi [joy] there"
    assert sanitize_tts_text(sample) == sanitize_for_display(sample)
    assert sanitize_tts_text(sample) == "hi there"


# ─────────────────────────────────────────────────────────────────
# X7 (cycle 20260422_5): expanded taxonomy + unknown-tag catch-all
# ─────────────────────────────────────────────────────────────────


def test_new_taxonomy_tags_are_stripped() -> None:
    """Tags that were added in X7 (wonder, amazement, satisfaction,
    curiosity) must now be recognized by the sanitizer whitelist."""
    for tag in ("wonder", "amazement", "satisfaction", "curiosity"):
        assert sanitize_for_display(f"[{tag}] hi") == "hi", (
            f"tag {tag!r} should be stripped after X7"
        )


def test_unknown_lowercase_tag_stripped_by_catch_all() -> None:
    """User-reported leak: `[bewildered]` / `[melancholy]` were not in
    the old whitelist; the X7 catch-all strips any unseen lowercase
    bracket identifier (3-20 chars)."""
    assert sanitize_for_display("[bewildered] thinking") == "thinking"
    assert sanitize_for_display("mid [melancholy] sentence") == "mid sentence"


def test_catch_all_preserves_routing_tags() -> None:
    """The narrow catch-all must not eat uppercase routing tags — those
    are handled by SYSTEM_TAG_PATTERN separately with precise matches."""
    # SUB_WORKER_RESULT is uppercase_underscore → routing path strips it;
    # the catch-all would ignore it regardless. The assertion here is
    # about ordering + pattern narrowness.
    assert sanitize_for_display("[SUB_WORKER_RESULT] done") == "done"
    assert sanitize_for_display("[THINKING_TRIGGER] ok") == "ok"


def test_catch_all_preserves_short_or_numeric_brackets() -> None:
    """`[a]`, `[1]`, `[to]`, `[x1]` stay — legitimate user text
    (footnote refs, numbers, list markers)."""
    assert sanitize_for_display("footnote [a] and [1]") == "footnote [a] and [1]"
    assert sanitize_for_display("word [to] word") == "word [to] word"
    # Even 2-char lowercase stays (below min length 3)
    assert sanitize_for_display("tag [hi]") == "tag [hi]"


# ─────────────────────────────────────────────────────────────────
# X7-follow-up (cycle 20260422_5): ``:strength`` suffix coverage
# ─────────────────────────────────────────────────────────────────
# User reported raw ``[excitement:0.7]`` leaking to the VTuber chat —
# the display sanitizer regexes were missing optional-strength support.
# Pin both the whitelisted path AND the catch-all here.


def test_recognized_tag_with_strength_is_stripped() -> None:
    """Tags decorated with ``:N`` or ``:N.N`` strength still strip."""
    assert sanitize_for_display("[excitement:0.7] 좋아") == "좋아"
    assert sanitize_for_display("[joy:1.5] hi") == "hi"
    assert sanitize_for_display("mid [fear:2] end") == "mid end"
    # Negative strength + no fraction
    assert sanitize_for_display("[calm:-1] sedated") == "sedated"


def test_recognized_tag_with_whitespace_inside_bracket() -> None:
    """Slightly sloppy LLM output — spaces inside the bracket — strips."""
    assert sanitize_for_display("[ joy ] yo") == "yo"
    assert sanitize_for_display("[joy : 0.5] yo") == "yo"
    assert sanitize_for_display("[ excitement:0.7 ] 좋아") == "좋아"


def test_unknown_tag_with_strength_is_stripped() -> None:
    """Catch-all must also tolerate ``:strength`` on unknown tags."""
    assert sanitize_for_display("[bewildered:0.3] thinking") == "thinking"
    assert sanitize_for_display("[melancholy:1.5] mood") == "mood"


def test_strength_does_not_unlock_routing_tags() -> None:
    """Uppercase routing tags must stay bypassed even with a colon
    payload — the catch-all is narrow on the identifier side."""
    # Routing tags already strip via SYSTEM_TAG_PATTERN; strength should
    # still land on the existing cases (THINKING_TRIGGER:first_idle).
    assert sanitize_for_display("[THINKING_TRIGGER:x] ok") == "ok"


def test_recognized_tags_imported_from_taxonomy() -> None:
    """Canonical list must be the taxonomy, not an in-file duplicate."""
    from service.affect.taxonomy import RECOGNIZED_TAGS as canonical
    from service.utils.text_sanitizer import EMOTION_TAGS
    assert EMOTION_TAGS is canonical
