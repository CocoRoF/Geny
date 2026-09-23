"""The emotion cues are for the avatar and the voice — and they stopped
getting them.

On 2026-09-19 the turn's text became the reader's copy: ``[joy:0.6]`` and
friends stripped, which is right for anyone READING. But that copy was then
the only text a turn handed on, and two consumers act on the cues: the
avatar's expression (``_emit_avatar_state``) and the voice's emotional
reference (the web panel's auto-TTS). Both went flat — the avatar showed the
same "completed" face for every reply, and every reply was spoken neutral.
Production, before this fix: ``[calm:0.3] 안녕, 연결 확인됐어.`` in memory,
``emotion=neutral`` on every OmniVoice request.

A turn now carries two texts: ``output`` for people, ``spoken`` for them.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from service.execution import agent_executor
from service.execution.agent_executor import ExecutionResult
from service.utils.text_sanitizer import (
    sanitize_for_display,
    sanitize_for_speech,
    spoken_if_different,
)


class TestTwoTexts:
    RAW = "[calm:0.4] 사장님.\n\n[fear:0.4] 오늘따라 좀 버거워.\n\n[TASK_COMPLETE]"

    def test_the_spoken_text_keeps_the_cues(self) -> None:
        spoken = sanitize_for_speech(self.RAW)
        assert spoken.startswith("[calm:0.4] 사장님.")
        assert "[fear:0.4]" in spoken

    def test_but_not_the_protocol(self) -> None:
        """Loop signals and reasoning are for the pipeline, not for anyone."""
        spoken = sanitize_for_speech("<think>hmm</think>[joy] 좋아! [TASK_COMPLETE]")
        assert spoken == "[joy] 좋아!"

    def test_the_display_text_has_neither(self) -> None:
        assert sanitize_for_display(self.RAW) == "사장님.\n\n오늘따라 좀 버거워."

    def test_a_reply_without_cues_is_not_stored_twice(self) -> None:
        assert spoken_if_different("안녕 [TASK_COMPLETE]", "안녕") is None
        assert spoken_if_different("[joy] 안녕", "안녕") == "[joy] 안녕"


class _Model:
    emotionMap = {"neutral": 0, "joy": 1, "fear": 4, "sadness": 2}


class _Avatar:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def update_state(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def avatar(monkeypatch):
    rec = _Avatar()
    app_state = MagicMock()
    app_state.avatar_state_manager = rec
    app_state.live2d_model_manager.get_agent_model = lambda _sid: _Model()
    monkeypatch.setattr(agent_executor, "_app_state", app_state)

    async def _no_mood(_sid):
        return None

    monkeypatch.setattr(agent_executor, "_load_mood_for_session", _no_mood)
    return rec


class TestTheAvatarReadsTheCues:
    @pytest.mark.asyncio
    async def test_the_expression_comes_from_the_spoken_text(self, avatar) -> None:
        result = ExecutionResult(
            success=True,
            session_id="s",
            output="오늘따라 좀 버거워.",
            spoken="[fear:0.4] 오늘따라 좀 버거워.",
        )
        await agent_executor._emit_avatar_state("s", result)
        assert avatar.calls[-1]["emotion"] == "fear"

    @pytest.mark.asyncio
    async def test_without_cues_it_is_what_it_was(self, avatar) -> None:
        """No ``spoken`` means the output is all there is — the old path."""
        result = ExecutionResult(success=True, session_id="s", output="[joy] hi")
        await agent_executor._emit_avatar_state("s", result)
        assert avatar.calls[-1]["emotion"] == "joy"


class TestTheRoomKeepsThem:
    """The web panel's TTS reads the message the room socket replays — from
    the database — so the cues and the message's origin must be columns."""

    def test_they_are_written(self, monkeypatch) -> None:
        from service.database import chat_db_helper as h

        seen: Dict[str, Any] = {}

        class _Mgr:
            def execute_insert(self, query, params):
                seen["query"], seen["params"] = query, params
                return 1

        monkeypatch.setattr(h, "_get_db_manager", lambda db: _Mgr())
        monkeypatch.setattr(h, "_is_db_available", lambda db: True)
        h.db_add_message(object(), "room", {
            "type": "agent", "content": "안녕", "spoken": "[joy] 안녕",
            "source": "thinking_trigger",
        })
        assert "spoken, source" in seen["query"]
        assert seen["params"][-2:] == ("[joy] 안녕", "thinking_trigger")

    def test_and_read_back(self, monkeypatch) -> None:
        from service.database import chat_db_helper as h

        class _Mgr:
            def execute_query(self, query, params=None):
                return [{
                    "message_id": "m1", "type": "agent", "content": "안녕",
                    "timestamp": "t", "spoken": "[joy] 안녕", "source": "thinking_trigger",
                }, {
                    "message_id": "m2", "type": "user", "content": "hi", "timestamp": "t",
                }]

        monkeypatch.setattr(h, "_get_db_manager", lambda db: _Mgr())
        monkeypatch.setattr(h, "_is_db_available", lambda db: True)
        cued, plain = h.db_get_messages(object(), "room")
        assert cued["spoken"] == "[joy] 안녕" and cued["source"] == "thinking_trigger"
        assert "spoken" not in plain and "source" not in plain

    def test_the_schema_has_the_columns(self) -> None:
        from service.database.models.chat_message import ChatMessageModel

        schema = ChatMessageModel().get_schema()
        assert schema["spoken"].startswith("TEXT") and schema["source"].startswith("VARCHAR")


class TestHistoryKeepsThemToo:
    """The live socket sends the stored dict; the REST history goes through a
    response model that ignores unknown keys — and dropped both fields on
    production while the socket carried them."""

    def test_the_history_model_carries_them(self) -> None:
        from controller.chat_controller import MessageResponse

        row = {
            "id": "m1", "type": "agent", "content": "안녕", "timestamp": "t",
            "spoken": "[joy] 안녕", "source": "user_shared_trigger",
        }
        out = MessageResponse(**row).model_dump()
        assert out["spoken"] == "[joy] 안녕"
        assert out["source"] == "user_shared_trigger"
