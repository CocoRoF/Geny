"""``_emit_avatar_state`` honours hydrated ``CreatureState.mood`` — PR-X3-9.

The executor-side avatar emission path is the single call site that
turns an LLM response (or an error state) into a Live2D expression
update. With ``CreatureState`` in play it must prefer the creature's
mood over the keyword fallback, matching the in-process mood extractor
contract pinned by ``test_emotion_extractor_mood.py``.

These tests patch the module-level ``_app_state``, the
``_get_agent_manager`` shim, and the Live2D model manager so we can
drive the real ``_emit_avatar_state`` with a fake world and observe
what ``AvatarStateManager.update_state`` was called with.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from service.execution import agent_executor
from service.execution.agent_executor import ExecutionResult
from service.state.schema.creature_state import CreatureState
from service.state.schema.mood import MoodVector


_EMOTION_MAP: Dict[str, int] = {
    "neutral": 0,
    "joy": 1,
    "sadness": 2,
    "anger": 3,
    "fear": 4,
    "surprise": 5,
}


class _FakeModel:
    def __init__(self) -> None:
        self.emotionMap = _EMOTION_MAP


class _FakeModelManager:
    def get_agent_model(self, _sid: str) -> Optional[_FakeModel]:
        return _FakeModel()


class _RecordingAvatarManager:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def update_state(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _FakeAgent:
    def __init__(
        self,
        session_id: str,
        character_id: Optional[str] = "char-1",
    ) -> None:
        self.session_id = session_id
        self.character_id = character_id


class _FakeProvider:
    def __init__(self, mood: Optional[MoodVector]) -> None:
        self._mood = mood
        self.load_calls: List[str] = []

    async def load(self, character_id: str, **_: Any) -> CreatureState:
        self.load_calls.append(character_id)
        return CreatureState(
            character_id=character_id,
            owner_user_id="u",
            mood=self._mood or MoodVector(),
        )


class _FakeManager:
    def __init__(
        self,
        agent: Optional[_FakeAgent],
        provider: Optional[_FakeProvider],
    ) -> None:
        self._agent = agent
        self.state_provider = provider

    def get_agent(self, session_id: str) -> Optional[_FakeAgent]:
        if self._agent and self._agent.session_id == session_id:
            return self._agent
        return None


@pytest.fixture
def world(monkeypatch):
    avatar = _RecordingAvatarManager()
    models = _FakeModelManager()
    app_state = MagicMock()
    app_state.avatar_state_manager = avatar
    app_state.live2d_model_manager = models
    monkeypatch.setattr(agent_executor, "_app_state", app_state)

    state = {
        "manager": None,
    }

    def _install_manager(
        *,
        mood: Optional[MoodVector],
        provider: Optional[_FakeProvider] = None,
        character_id: Optional[str] = "char-1",
    ) -> _FakeManager:
        prov = provider if provider is not None else _FakeProvider(mood)
        agent = _FakeAgent("sess-1", character_id=character_id)
        manager = _FakeManager(agent, prov)
        state["manager"] = manager
        monkeypatch.setattr(
            agent_executor, "_get_agent_manager", lambda: manager
        )
        return manager

    return {"avatar": avatar, "install_manager": _install_manager, "state": state}


# ── happy path: mood beats agent_state=completed (which would map to joy) ─


@pytest.mark.asyncio
async def test_success_path_mood_overrides_completed_default(world) -> None:
    world["install_manager"](mood=MoodVector(sadness=0.7))
    result = ExecutionResult(
        success=True, session_id="sess-1", output="Plain reply text."
    )

    await agent_executor._emit_avatar_state("sess-1", result)

    assert len(world["avatar"].calls) == 1
    call = world["avatar"].calls[0]
    assert call["emotion"] == "sadness"
    assert call["expression_index"] == _EMOTION_MAP["sadness"]
    assert call["trigger"] == "agent_output"


@pytest.mark.asyncio
async def test_success_path_calm_mood_keeps_completed_default(world) -> None:
    """Calm / unset mood must defer so ``completed`` still maps to joy."""
    world["install_manager"](mood=MoodVector())
    result = ExecutionResult(
        success=True, session_id="sess-1", output="Hi."
    )

    await agent_executor._emit_avatar_state("sess-1", result)

    call = world["avatar"].calls[0]
    assert call["emotion"] == "joy"


@pytest.mark.asyncio
async def test_text_tag_still_wins_over_mood(world) -> None:
    world["install_manager"](mood=MoodVector(joy=0.9))
    result = ExecutionResult(
        success=True, session_id="sess-1", output="[fear] something lurks"
    )

    await agent_executor._emit_avatar_state("sess-1", result)

    call = world["avatar"].calls[0]
    assert call["emotion"] == "fear"


# ── error path: mood shapes error-side expression too ─────────────


@pytest.mark.asyncio
async def test_error_path_mood_overrides_error_default(world) -> None:
    """anger mood > the default ``error → fear`` mapping."""
    world["install_manager"](mood=MoodVector(anger=0.6))
    result = ExecutionResult(
        success=False, session_id="sess-1", error="boom"
    )

    await agent_executor._emit_avatar_state("sess-1", result)

    call = world["avatar"].calls[0]
    assert call["emotion"] == "anger"
    assert call["trigger"] == "state_change"


# ── classic mode: no state_provider → no mood read, no crash ─────


@pytest.mark.asyncio
async def test_classic_mode_no_provider_uses_completed_mapping(world) -> None:
    world["install_manager"](mood=None, provider=None, character_id=None)
    world["state"]["manager"].state_provider = None

    result = ExecutionResult(
        success=True, session_id="sess-1", output="Hi."
    )
    await agent_executor._emit_avatar_state("sess-1", result)

    call = world["avatar"].calls[0]
    assert call["emotion"] == "joy"


@pytest.mark.asyncio
async def test_missing_character_id_skips_mood_lookup(world) -> None:
    provider = _FakeProvider(MoodVector(anger=0.9))
    world["install_manager"](mood=None, provider=provider, character_id=None)

    result = ExecutionResult(
        success=True, session_id="sess-1", output="Hi."
    )
    await agent_executor._emit_avatar_state("sess-1", result)

    # Provider was never asked, because no character_id mapped:
    assert provider.load_calls == []
    call = world["avatar"].calls[0]
    assert call["emotion"] == "joy"


@pytest.mark.asyncio
async def test_provider_raise_is_swallowed(world) -> None:
    class _Boom:
        async def load(self, *_: Any, **__: Any) -> CreatureState:
            raise RuntimeError("provider down")

    world["install_manager"](mood=None, provider=_Boom())  # type: ignore[arg-type]

    result = ExecutionResult(
        success=True, session_id="sess-1", output="Hello"
    )
    # Must not raise — avatar still updates with fallback emotion.
    await agent_executor._emit_avatar_state("sess-1", result)
    assert world["avatar"].calls, "update_state should still have been called"
    assert world["avatar"].calls[0]["emotion"] == "joy"


# ── _load_mood_for_session in isolation ────────────────────────────


@pytest.mark.asyncio
async def test_load_mood_returns_mood_when_everything_wired(world) -> None:
    world["install_manager"](mood=MoodVector(joy=0.4))
    mood = await agent_executor._load_mood_for_session("sess-1")
    assert isinstance(mood, MoodVector)
    assert mood.joy == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_load_mood_returns_none_for_unknown_session(world) -> None:
    world["install_manager"](mood=MoodVector(joy=0.4))
    assert await agent_executor._load_mood_for_session("no-such") is None
