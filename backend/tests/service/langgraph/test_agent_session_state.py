"""AgentSession × CreatureState integration (cycle 20260421_9 PR-X3-5).

When a ``state_provider`` + ``character_id`` pair is wired on the session,
``_invoke_pipeline`` / ``_astream_pipeline`` must:

1. Hydrate the creature state before the pipeline loop — ``state.shared``
   receives the snapshot, mutation buffer, and session meta keys.
2. Let stages mutate via the buffer during the loop.
3. Persist the buffer through ``provider.apply`` after the loop.

When the provider is ``None`` the session stays in classic mode — no
hydrate, no persist, no crashes. Failures in hydrate/persist must never
propagate and break the turn.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import pytest

from service.langgraph.agent_session import AgentSession

from backend.service.state import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    SESSION_META_KEY,
    CreatureState,
    InMemoryCreatureStateProvider,
    SessionRuntimeRegistry,
)
from backend.service.state.provider.interface import StateConflictError


# --- Shared scaffolding ----------------------------------------------------


class _FakeMemoryManager:
    def __init__(self) -> None:
        self.messages: List[Tuple[str, str]] = []
        self.executions: List[Dict[str, Any]] = []

    def record_message(self, role: str, content: str) -> None:
        self.messages.append((role, content))

    async def record_execution(self, **kwargs: Any) -> None:
        self.executions.append(kwargs)


class _FakeEvent:
    def __init__(self, event_type: str, data: Dict[str, Any]) -> None:
        self.type = event_type
        self.data = data


class _RecordingPipeline:
    """Captures the ``state`` it sees and optionally pushes a mutation.

    Simulates a stage that appends to the mutation buffer mid-turn so the
    persist path has something to commit. The snapshot we see at run
    time is recorded so tests can assert hydrate actually reached
    ``state.shared``.
    """

    def __init__(
        self,
        events: List[_FakeEvent],
        *,
        mutations_to_append=None,
    ) -> None:
        self._events = events
        self._mutations = mutations_to_append or []
        self.seen_shared: Dict[str, Any] = {}

    async def run_stream(self, input_text: str, state: Any):
        self.seen_shared = dict(state.shared)
        buf = state.shared.get(MUTATION_BUFFER_KEY)
        if buf is not None:
            for m in self._mutations:
                buf.append(**m)
        for evt in self._events:
            yield evt


def _make_session(
    pipeline: _RecordingPipeline,
    *,
    state_provider=None,
    character_id: str | None = None,
) -> Tuple[AgentSession, _FakeMemoryManager]:
    session = AgentSession(
        session_id="s-state",
        session_name="T",
        state_provider=state_provider,
        character_id=character_id,
    )
    mem = _FakeMemoryManager()
    session._memory_manager = mem  # type: ignore[assignment]
    session._pipeline = pipeline  # type: ignore[assignment]
    session._execution_count = 0
    return session, mem


def _success_events(output: str = "ok") -> List[_FakeEvent]:
    return [
        _FakeEvent("text.delta", {"text": output}),
        _FakeEvent(
            "pipeline.complete",
            {"result": output, "total_cost_usd": 0.0, "iterations": 1},
        ),
    ]


# --- Classic mode (no state_provider) --------------------------------------


@pytest.mark.asyncio
async def test_classic_mode_leaves_state_shared_untouched() -> None:
    """No state_provider → hydrate/persist are never invoked and the
    pipeline state contains no creature_state keys."""
    pipe = _RecordingPipeline(_success_events())
    session, _ = _make_session(pipe)  # state_provider=None

    result = await session._invoke_pipeline(
        "hi", start_time=0.0, session_logger=None,
    )

    assert result["output"] == "ok"
    assert CREATURE_STATE_KEY not in pipe.seen_shared
    assert MUTATION_BUFFER_KEY not in pipe.seen_shared
    assert SESSION_META_KEY not in pipe.seen_shared


@pytest.mark.asyncio
async def test_classic_mode_build_state_registry_returns_none() -> None:
    session = AgentSession(session_id="s-c", session_name="T")
    assert session._build_state_registry() is None


# --- With state_provider: happy paths --------------------------------------


@pytest.mark.asyncio
async def test_hydrate_installs_creature_state_into_shared() -> None:
    prov = InMemoryCreatureStateProvider()
    pipe = _RecordingPipeline(_success_events())
    session, _ = _make_session(
        pipe, state_provider=prov, character_id="c1",
    )

    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    assert CREATURE_STATE_KEY in pipe.seen_shared
    assert MUTATION_BUFFER_KEY in pipe.seen_shared
    assert SESSION_META_KEY in pipe.seen_shared
    snap = pipe.seen_shared[CREATURE_STATE_KEY]
    assert isinstance(snap, CreatureState)
    assert snap.character_id == "c1"


@pytest.mark.asyncio
async def test_character_id_defaults_to_session_id() -> None:
    """With state_provider but no character_id, the session_id is used."""
    prov = InMemoryCreatureStateProvider()
    pipe = _RecordingPipeline(_success_events())
    session, _ = _make_session(pipe, state_provider=prov)  # no character_id

    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    snap = pipe.seen_shared[CREATURE_STATE_KEY]
    assert snap.character_id == session._session_id


@pytest.mark.asyncio
async def test_persist_applies_mutations_and_bumps_state() -> None:
    prov = InMemoryCreatureStateProvider()
    # Seed with a known starting hunger so the mutation is observable.
    await prov.load("c1", owner_user_id="u1")
    await prov.set_absolute("c1", {"vitals.hunger": 10.0})

    mutation = {
        "op": "add",
        "path": "vitals.hunger",
        "value": 5.0,
        "source": "test",
    }
    pipe = _RecordingPipeline(_success_events(), mutations_to_append=[mutation])
    session, _ = _make_session(
        pipe, state_provider=prov, character_id="c1",
    )

    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    # Reload and check the mutation was persisted.
    after = await prov.load("c1", owner_user_id="u1")
    assert after.vitals.hunger == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_astream_also_hydrates_and_persists() -> None:
    """Streaming path mirrors invoke — hydrate before, persist after."""
    prov = InMemoryCreatureStateProvider()
    await prov.load("c1", owner_user_id="u1")
    await prov.set_absolute("c1", {"vitals.hunger": 20.0})

    mutation = {
        "op": "add",
        "path": "vitals.hunger",
        "value": 3.0,
        "source":"stream",
    }
    pipe = _RecordingPipeline(_success_events(), mutations_to_append=[mutation])
    session, _ = _make_session(
        pipe, state_provider=prov, character_id="c1",
    )

    async for _ in session._astream_pipeline(
        "hi", start_time=0.0, session_logger=None,
    ):
        pass

    assert CREATURE_STATE_KEY in pipe.seen_shared
    after = await prov.load("c1", owner_user_id="u1")
    assert after.vitals.hunger == pytest.approx(23.0)


# --- Catch-up behaviour through hydrate ------------------------------------


@pytest.mark.asyncio
async def test_stale_snapshot_triggers_catchup_in_hydrate() -> None:
    """When last_tick_at is past the catch-up threshold the registry
    ticks once on hydrate — stages see the decayed state, not the raw."""
    prov = InMemoryCreatureStateProvider()
    await prov.load("c1", owner_user_id="u1")
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    await prov.set_absolute("c1", {
        "last_tick_at": stale,
        "vitals.hunger": 10.0,
    })

    pipe = _RecordingPipeline(_success_events())
    session, _ = _make_session(
        pipe, state_provider=prov, character_id="c1",
    )

    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    snap = pipe.seen_shared[CREATURE_STATE_KEY]
    assert snap.vitals.hunger > 10.0


# --- Error isolation -------------------------------------------------------


class _ExplodingHydrateProvider:
    """Provider that raises on ``load`` — hydrate must swallow it."""

    async def load(self, character_id: str, *, owner_user_id: str = "") -> CreatureState:
        raise RuntimeError("storage on fire")

    async def apply(self, snapshot, mutations):
        raise AssertionError("apply should not be reached when hydrate failed")


@pytest.mark.asyncio
async def test_hydrate_failure_does_not_break_the_turn() -> None:
    prov = _ExplodingHydrateProvider()
    pipe = _RecordingPipeline(_success_events("still works"))
    session, _ = _make_session(
        pipe, state_provider=prov, character_id="c1",
    )

    result = await session._invoke_pipeline(
        "hi", start_time=0.0, session_logger=None,
    )

    assert result["output"] == "still works"
    # Hydrate failed → shared has no creature_state
    assert CREATURE_STATE_KEY not in pipe.seen_shared


class _ExplodingPersistProvider(InMemoryCreatureStateProvider):
    async def apply(self, snapshot, mutations):  # type: ignore[override]
        raise RuntimeError("apply on fire")


@pytest.mark.asyncio
async def test_persist_failure_does_not_break_the_turn() -> None:
    prov = _ExplodingPersistProvider()
    mutation = {
        "op": "add",
        "path": "vitals.hunger",
        "value": 1.0,
        "source":"t",
    }
    pipe = _RecordingPipeline(_success_events(), mutations_to_append=[mutation])
    session, _ = _make_session(
        pipe, state_provider=prov, character_id="c1",
    )

    result = await session._invoke_pipeline(
        "hi", start_time=0.0, session_logger=None,
    )

    # Error during persist must not surface to the caller.
    assert result["output"] == "ok"


class _ConflictingPersistProvider(InMemoryCreatureStateProvider):
    async def apply(self, snapshot, mutations):  # type: ignore[override]
        raise StateConflictError("raced with decay")


@pytest.mark.asyncio
async def test_persist_conflict_is_downgraded_to_debug() -> None:
    """StateConflictError is a routine race — must not propagate."""
    prov = _ConflictingPersistProvider()
    mutation = {
        "op": "add",
        "path": "vitals.hunger",
        "value": 1.0,
        "source":"t",
    }
    pipe = _RecordingPipeline(_success_events(), mutations_to_append=[mutation])
    session, _ = _make_session(
        pipe, state_provider=prov, character_id="c1",
    )

    result = await session._invoke_pipeline(
        "hi", start_time=0.0, session_logger=None,
    )
    assert result["output"] == "ok"


# --- Persist-on-error sanity -----------------------------------------------


@pytest.mark.asyncio
async def test_persist_runs_even_when_pipeline_errors() -> None:
    """A pipeline.error shouldn't drop already-buffered mutations on the
    floor — persist runs anyway (plan/02 §4.3 — "user response already
    accepted; state must reflect what happened")."""
    prov = InMemoryCreatureStateProvider()
    await prov.load("c1", owner_user_id="u1")
    await prov.set_absolute("c1", {"vitals.hunger": 0.0})

    mutation = {
        "op": "add",
        "path": "vitals.hunger",
        "value": 7.0,
        "source":"mid-turn",
    }
    events = [
        _FakeEvent("text.delta", {"text": "partial"}),
        _FakeEvent(
            "pipeline.error", {"error": "boom", "total_cost_usd": 0.0},
        ),
    ]
    pipe = _RecordingPipeline(events, mutations_to_append=[mutation])
    session, _ = _make_session(
        pipe, state_provider=prov, character_id="c1",
    )

    await session._invoke_pipeline("hi", start_time=0.0, session_logger=None)

    after = await prov.load("c1", owner_user_id="u1")
    assert after.vitals.hunger == pytest.approx(7.0)


# --- Build helper ----------------------------------------------------------


def test_build_state_registry_returns_fresh_instance_per_call() -> None:
    """The registry is turn-scoped — a fresh one per build."""
    prov = InMemoryCreatureStateProvider()
    session = AgentSession(
        session_id="s-x",
        state_provider=prov,
        character_id="c1",
    )
    r1 = session._build_state_registry()
    r2 = session._build_state_registry()
    assert isinstance(r1, SessionRuntimeRegistry)
    assert isinstance(r2, SessionRuntimeRegistry)
    assert r1 is not r2


def test_build_state_registry_uses_owner_username_when_present() -> None:
    prov = InMemoryCreatureStateProvider()
    session = AgentSession(
        session_id="s-x",
        state_provider=prov,
        character_id="c1",
        owner_username="alice",
    )
    reg = session._build_state_registry()
    assert reg is not None
    assert reg.owner_user_id == "alice"
