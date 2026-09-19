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


class TestTheAccumulationIsTheTurn:
    """``state.final_text`` is NOT the turn.

    Stage 9 overwrites it on every loop iteration, so it holds the last
    message. An agent that narrates, calls a tool, then answers has written
    two messages; preferring ``final_text`` keeps only the second. I shipped
    exactly that for one deploy and a three-step turn came back as 34
    characters, with the agent's first sentence gone.
    """

    @staticmethod
    def _resolve(accumulated: str, final_text: str) -> str:
        """The rule both call sites now use."""
        return sanitize_for_display(accumulated or final_text)

    def test_prose_written_before_a_tool_call_survives(self) -> None:
        accumulated = "STEP-ONE 시작합니다\n\nSTEP-THREE 끝났습니다"
        final_text = "STEP-THREE 끝났습니다"
        out = self._resolve(accumulated, final_text)
        assert "STEP-ONE" in out and "STEP-THREE" in out

    def test_preferring_the_final_text_would_have_lost_it(self) -> None:
        """The shape of the regression, kept as its own assertion so the
        reason this rule exists cannot be refactored away."""
        accumulated = "STEP-ONE 시작합니다\n\nSTEP-THREE 끝났습니다"
        final_text = "STEP-THREE 끝났습니다"
        assert "STEP-ONE" not in (final_text or accumulated)

    def test_nothing_streamed_falls_back_to_the_final_text(self) -> None:
        assert self._resolve("", "only answer") == "only answer"

    def test_the_boundary_is_where_the_cleaning_happens(self) -> None:
        assert self._resolve("[joy:0.6] 축하해!", "") == "축하해!"

    def test_the_real_source_follows_this_rule(self) -> None:
        """The three above reproduce the rule; this one reads the code.

        Without it they are decorative — I reverted the source and all three
        still passed, which is the exact failure mode this session has been
        finding everywhere else.
        """
        import inspect

        from service.executor.agent_session import AgentSession

        source = inspect.getsource(AgentSession)
        # the accumulation wins; `result` is the empty-case fallback
        assert "if not accumulated_output:\n                    accumulated_output = streamed_result" in source, (
            "the turn's output no longer prefers the streamed accumulation"
        )
        assert "if streamed_result:\n                    accumulated_output = streamed_result" not in source, (
            "the last message is being preferred over the turn again"
        )
        # …and the cleaning happens once, at the boundary
        assert '"output": sanitize_for_display(accumulated_output)' in source
        assert "result_text = sanitize_for_display(" in source


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


class TestTheLoopSignalsAreNotForReaders:
    """``[TASK_COMPLETE]`` is how the model tells the pipeline a turn is over.
    Nothing stripped it, so every answer ended with it visible — in chat, in
    the API response, and in whatever TTS read aloud."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("답변입니다.\n\n[TASK_COMPLETE]", "답변입니다."),
            ("[BLOCKED: 권한 없음] 못 했어", "못 했어"),
            ("[CONTINUE:next] 이어서", "이어서"),
        ],
    )
    def test_they_are_stripped(self, raw: str, expected: str) -> None:
        assert sanitize_for_display(raw) == expected

    def test_a_turn_that_was_only_a_signal_becomes_empty(self) -> None:
        """Which is what the narration check downstream reads as "it said
        nothing" — the same answer it gave when the marker was still there."""
        assert sanitize_for_display("[TASK_COMPLETE]") == ""

    def test_the_narration_check_still_agrees(self) -> None:
        from service.execution.agent_executor import _strip_only_loop_signals

        # tool-only turn → no narration, before and after the boundary strip
        assert not (_strip_only_loop_signals(sanitize_for_display("[TASK_COMPLETE]")) or "")
        assert not (_strip_only_loop_signals("[TASK_COMPLETE]") or "")
        # a real answer → narration either way
        assert _strip_only_loop_signals(sanitize_for_display("했어요.\n[TASK_COMPLETE]"))


class TestABudgetTheOwnerCleared:
    """A blank number field arrives as 0. It must mean "automatic" for the
    budgets that have an automatic, and be refused for the one that does not."""

    def test_clearing_the_context_window_removes_the_declaration(self) -> None:
        from service.harness.overlay import merge_overlay

        merged = merge_overlay({"budgets": {"contextWindow": 32768}},
                               {"budgets": {"contextWindow": 0}})
        assert "contextWindow" not in merged["budgets"]

    def test_clearing_the_ceiling_removes_it(self) -> None:
        from service.harness.overlay import merge_overlay

        merged = merge_overlay({"budgets": {"costCeiling": 2.5}},
                               {"budgets": {"costCeiling": 0}})
        assert "costCeiling" not in merged["budgets"]

    def test_zero_turns_is_refused_rather_than_stored(self) -> None:
        """There is no automatic number of steps, and zero would read as
        "stop before the first one"."""
        from service.harness.overlay import HarnessRejected, validate_overlay
        from types import SimpleNamespace

        with pytest.raises(HarnessRejected):
            validate_overlay({"budgets": {"maxIterations": 0}},
                             pipeline=SimpleNamespace(stages=[]))
