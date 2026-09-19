"""A VTuber's emotion cues drive the avatar. They must not be read aloud.

The model is asked for inline cues — ``[joy:0.6] 축하해!`` — and three
different things want three different versions of that sentence:

* the **avatar** wants the tag (it picks the expression),
* the **reader** and **TTS** want it gone,
* the **mood** wants it counted.

All three worked except the second, on two surfaces, for one reason: the
pipeline strips the tags into ``state.final_text`` and Geny threw that value
away whenever it was SHORTER than what it had streamed — which is precisely
what stripping makes it. The guard existed for executor ≤ 0.20.0, which sent
a 500-char preview in that field.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from service.affect.taxonomy import RECOGNIZED_TAGS
from service.utils.text_sanitizer import sanitize_for_display


class TestTheFinalTextIsTheCleanedOne:
    """Reproduces the guard at the two call sites that had it."""

    @staticmethod
    def _resolve(streamed_result: str, accumulated: str) -> str:
        """The rule both call sites now use."""
        return streamed_result or accumulated

    def test_a_shorter_final_text_is_accepted(self) -> None:
        """Stripping is the one thing that makes it legitimately shorter, so
        the old ``>=`` guard rejected exactly the correction it should take."""
        streamed = "[joy:0.6] 발표 대성공했다니 정말 잘됐다!"
        cleaned = "발표 대성공했다니 정말 잘됐다!"
        assert len(cleaned) < len(streamed)
        assert self._resolve(cleaned, streamed) == cleaned

    def test_an_empty_final_text_falls_back_to_the_stream(self) -> None:
        """A turn can end with no final text; streamed tokens beat nothing."""
        assert self._resolve("", "partial answer") == "partial answer"

    def test_the_guard_it_replaced_would_have_failed_this(self) -> None:
        streamed, cleaned = "[joy:0.6] hi", "hi"
        old_rule = cleaned if len(cleaned) >= len(streamed) else streamed
        assert old_rule == streamed, "the old guard kept the tagged text"
        assert self._resolve(cleaned, streamed) == cleaned


class TestWhatReachesAReader:
    @pytest.mark.parametrize(
        "raw",
        [
            "[joy] 축하해!",
            "[joy:0.6] 축하해!",
            "[joy : 0.7] 축하해!",
            "[wonder:1.5] 축하해!",
            "첫 문장. [curious:0.5] 축하해!",
        ],
    )
    def test_every_shape_the_prompt_offers_is_stripped(self, raw: str) -> None:
        """``prompts/vtuber.md`` offers inline placement and strength
        suffixes, so both have to strip."""
        cleaned = sanitize_for_display(raw)
        assert "[" not in cleaned, cleaned
        assert "축하해!" in cleaned

    def test_ordinary_bracketed_prose_survives(self) -> None:
        """A strict numeric payload is what keeps ``[note: todo]`` alive."""
        assert "[note: todo]" in sanitize_for_display("see [note: todo] please")


class TestTheTwoTaxonomiesCannotDrift:
    """The backend strips what it recognises and leaves the rest on screen;
    the client colours what IT recognises. Six tags were in one list and not
    the other, including ``wonder`` — the emitter's own worked example."""

    @staticmethod
    def _frontend_emotions() -> set[str]:
        source = (
            Path(__file__).resolve().parents[3]
            / ".." / "frontend" / "src" / "components" / "chat" / "chat-utils.ts"
        ).resolve()
        text = source.read_text(encoding="utf-8")
        block = re.search(r"export const EMOTIONS = \[(.*?)\] as const;", text, re.S)
        assert block, "EMOTIONS list not found in chat-utils.ts"
        return set(re.findall(r"'([a-z_]+)'", block.group(1)))

    def test_the_client_knows_every_tag_the_server_does(self) -> None:
        missing = set(RECOGNIZED_TAGS) - self._frontend_emotions()
        assert not missing, f"the client cannot recognise: {sorted(missing)}"

    def test_the_client_invents_none(self) -> None:
        extra = self._frontend_emotions() - set(RECOGNIZED_TAGS)
        assert not extra, f"the client recognises tags the server does not: {sorted(extra)}"

    def test_the_client_understands_the_strength_suffix(self) -> None:
        """Without it, most of what the model actually writes reads as no tag
        at all — the prompt explicitly offers ``[joy:0.7]``."""
        source = (
            Path(__file__).resolve().parents[3]
            / ".." / "frontend" / "src" / "components" / "chat" / "chat-utils.ts"
        ).resolve()
        text = source.read_text(encoding="utf-8")
        assert "const STRENGTH" in text
        assert "EMOTION_REGEX" in text and "${STRENGTH}" in text


class TestTheAvatarStillSeesThem:
    """Stripping for the reader must not blind the avatar — it reads the raw
    message, and the sanitised copy is made after that."""

    def test_the_extractor_reads_a_strength_suffix(self) -> None:
        from service.vtuber.emotion_extractor import EmotionExtractor

        extractor = EmotionExtractor({"joy": 3, "neutral": 0})
        emotion, index = extractor.resolve_emotion("[joy:0.6] 축하해!", None)
        assert (emotion, index) == ("joy", 3)

    def test_the_send_path_emits_before_it_sanitises(self) -> None:
        """Order matters and is easy to reverse by accident: sanitise first
        and the avatar goes permanently neutral."""
        import inspect

        import ws.execute_stream as stream

        source = inspect.getsource(stream)
        body = source[source.index("for entry in new_entries:"):]
        emit_at = body.index("_emit_avatar_state_for_log")
        clean_at = body.index('entry_dict["message"] = sanitize_for_display')
        assert emit_at < clean_at, "the display copy is made before the avatar reads it"
