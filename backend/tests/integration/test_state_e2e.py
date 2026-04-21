"""Creature-state end-to-end regression — cycle 20260421_9 PR-X3-10.

The X3 cycle built a chain of components, each covered by its own unit
suite:

- PR-X3-1/2  schema + ``InMemoryCreatureStateProvider``
- PR-X3-3    ``SessionRuntimeRegistry.hydrate`` / ``persist``
- PR-X3-4    ``apply_decay`` + catch-up on hydrate
- PR-X3-6    game tools (``TalkTool`` / ``FeedTool``) via
             ``current_mutation_buffer`` ContextVar
- PR-X3-7    ``AffectTagEmitter`` writes into
             ``state.shared[MUTATION_BUFFER_KEY]``
- PR-X3-8    ``MoodBlock`` / ``RelationshipBlock`` / ``VitalsBlock``
             rendering from the hydrated snapshot
- PR-X3-9    ``EmotionExtractor.resolve_emotion`` honours
             ``CreatureState.mood``

Each of those works in isolation, but the cycle's contract is that the
whole chain is *live* — tool mutation → persist → hydrate next turn →
prompt block reflects → avatar picks the right emotion. If one hand-off
silently regresses (a wrong ContextVar bind, a missed
``state.shared`` key, a mood that isn't handed to the extractor) the
integration breaks even though every unit test stays green.

This module drives the four scenarios from ``plan/04 §10.3`` end-to-end
against the **real** components (no component is mocked; the provider
is the in-memory one to keep the test fast and deterministic). Each
scenario asserts the observable cross-component contract, not the
intermediate mutations.

Scenarios
---------
- **S1 첫 만남** (first meeting): a new ``TalkTool(kind="greet")`` lifts
  ``bond.familiarity`` from 0 → 0.3, surfacing as the ``nascent``
  band in ``RelationshipBlock`` on the next turn.
- **S2 포만→굶주림** (sated → hungry): ~20h elapsed between turns
  pushes ``vitals.hunger`` past 80 via catch-up decay, and
  ``VitalsBlock`` renders the ``starving`` band.
- **S3 재접속** (24h away): the hydrate catch-up fires exactly once,
  emits ``state.catchup``, and the next turn's vitals prompt + avatar
  resolution use the caught-up snapshot (not the stale one).
- **S4 감정 태그 학습** (affect-tag accumulation): three turns of
  ``[joy]`` outputs accumulate ``mood.joy`` past the threshold, so the
  next turn's ``MoodBlock`` reports joy and
  ``EmotionExtractor.resolve_emotion`` returns the ``"joy"`` slot for
  the Live2D avatar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

import pytest
from geny_executor.core.state import PipelineState

from service.emit.affect_tag_emitter import AffectTagEmitter
from service.game.tools.talk import FAMILIARITY_DELTA, TalkTool
from service.persona.blocks import (
    MoodBlock,
    RelationshipBlock,
    VitalsBlock,
)
from service.state import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    InMemoryCreatureStateProvider,
    SessionRuntimeRegistry,
    bind_mutation_buffer,
    reset_mutation_buffer,
)
from service.vtuber.emotion_extractor import EmotionExtractor

_EMOTION_MAP: Dict[str, int] = {
    "neutral": 0,
    "joy": 1,
    "sadness": 2,
    "anger": 3,
    "fear": 4,
    "surprise": 5,
}


def _registry(
    provider: InMemoryCreatureStateProvider,
    *,
    character_id: str = "rico",
    session_id: str = "sess-e2e",
) -> SessionRuntimeRegistry:
    return SessionRuntimeRegistry(
        session_id=session_id,
        character_id=character_id,
        owner_user_id="player-1",
        provider=provider,
    )


async def _run_turn_with_tool(
    registry: SessionRuntimeRegistry,
    tool_call,
) -> PipelineState:
    """One full turn: hydrate → bind buffer → run tool → persist.

    ``tool_call`` is a zero-arg callable that invokes the tool of
    interest. It runs *inside* the context where
    ``MUTATION_BUFFER_KEY`` from ``state.shared`` is bound onto the
    ContextVar — exactly like ``AgentSession`` does in production.
    """
    state = PipelineState()
    await registry.hydrate(state)

    buf = state.shared[MUTATION_BUFFER_KEY]
    token = bind_mutation_buffer(buf)
    try:
        tool_call()
    finally:
        reset_mutation_buffer(token)

    await registry.persist(state)
    return state


# ── S1 — 첫 만남 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s1_first_meeting_greet_bumps_familiarity_band_to_nascent() -> None:
    """Fresh character → TalkTool greet → next turn sees ``nascent`` bond.

    Contract: the LLM opens the session with a ``greet``; on the next
    turn the RelationshipBlock's prompt fragment reports familiarity
    has left ``none`` and entered the first positive band. This is what
    the character persona uses to decide greeting tone.
    """
    provider = InMemoryCreatureStateProvider()
    registry = _registry(provider)

    # Turn 1 — greet.
    await _run_turn_with_tool(
        registry, lambda: TalkTool().run(kind="greet", topic="opening"),
    )

    # Turn 2 — observe the block output driven by the hydrated snapshot.
    turn2 = PipelineState()
    snap = await registry.hydrate(turn2)

    assert snap.bond.familiarity == pytest.approx(FAMILIARITY_DELTA)
    rendered = RelationshipBlock().render(turn2)
    assert "[Bond with Owner]" in rendered
    assert "familiarity: nascent" in rendered
    # And it's reflected back out of the provider too — not just the
    # in-flight snap.
    persisted = await provider.load("rico", owner_user_id="player-1")
    assert persisted.bond.familiarity == pytest.approx(FAMILIARITY_DELTA)
    assert "talk:greet:opening" in persisted.recent_events


@pytest.mark.asyncio
async def test_s1_greet_twice_accumulates_familiarity() -> None:
    """Bond is durable — a second greet on a returning session lifts
    familiarity past the ``nascent`` cap into ``budding``."""
    provider = InMemoryCreatureStateProvider()
    registry = _registry(provider)

    # Four greets worth of contact so we clearly cross the 0.5 → 2.0
    # band boundary without sitting on the edge.
    for _ in range(4):
        await _run_turn_with_tool(
            registry, lambda: TalkTool().run(kind="greet"),
        )

    final = await provider.load("rico", owner_user_id="player-1")
    assert final.bond.familiarity == pytest.approx(FAMILIARITY_DELTA * 4)

    turn = PipelineState()
    await registry.hydrate(turn)
    assert "familiarity: budding" in RelationshipBlock().render(turn)


# ── S2 — 포만 → 굶주림 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s2_long_gap_drives_vitals_block_to_starving() -> None:
    """~20h between turns pushes hunger past the ``hungry`` band.

    The in-process catch-up is what makes time-of-day storytelling
    possible: the LLM didn't have to call a decay tool, yet the next
    prompt reflects the creature has grown hungry while the user was
    away. If hydrate silently skipped catch-up we'd render ``peckish``
    off the stale snapshot and the narration would sound off.
    """
    provider = InMemoryCreatureStateProvider()
    registry = _registry(provider)

    # First, materialize the character so we can pin its state.
    await provider.load("rico", owner_user_id="player-1")
    # Arrange: fed yesterday, last_tick pushed ~20h into the past so
    # DEFAULT_DECAY's +2.5/h hunger drift saturates past the ``hungry``
    # band (80) even from a comfortable starting hunger.
    stale_tick = datetime.now(timezone.utc) - timedelta(hours=20)
    await provider.set_absolute(
        "rico",
        {
            "last_tick_at": stale_tick,
            "vitals.hunger": 50.0,
            "vitals.energy": 80.0,
            "vitals.cleanliness": 80.0,
            "vitals.stress": 20.0,
        },
    )

    # Turn: hydrate runs catch-up → VitalsBlock reflects it.
    state = PipelineState()
    snap = await registry.hydrate(state)
    assert snap.vitals.hunger > 80.0, snap.vitals.hunger

    rendered = VitalsBlock().render(state)
    assert "[Vitals]" in rendered
    assert ("hunger: hungry" in rendered) or ("hunger: starving" in rendered)


# ── S3 — 재접속 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s3_reconnect_after_24h_triggers_single_catchup_event() -> None:
    """24h absence → one catch-up tick + ``state.catchup`` event.

    Pins: (1) the tick fires exactly once per hydrate (not twice, not
    zero — a regression here hides behind decay working anyway on
    the next scheduled service tick), (2) the vitals prompt on the
    comeback turn reflects the gap, (3) the avatar resolver picks up
    the caught-up mood (still calm here) and falls through to agent
    state as designed.
    """
    provider = _CountingProvider()
    registry = _registry(provider)

    await provider.load("rico", owner_user_id="player-1")
    stale_tick = datetime.now(timezone.utc) - timedelta(hours=24)
    await provider.set_absolute(
        "rico",
        {
            "last_tick_at": stale_tick,
            "vitals.hunger": 30.0,
            "vitals.cleanliness": 50.0,
            "vitals.energy": 60.0,
        },
    )

    state = _RecordingState()
    snap = await registry.hydrate(state)

    # Exactly one catch-up tick fired for this hydrate.
    assert provider.tick_calls == ["rico"]

    # State.catchup event was observed.
    catchup_events = [p for n, p in state.events if n == "state.catchup"]
    assert len(catchup_events) == 1
    assert catchup_events[0]["character_id"] == "rico"

    # Observable on the next turn's prompt: vitals are drifted.
    vitals_rendered = VitalsBlock().render(state)
    # Hunger climbed from 30 by +2.5*24=60 → 90 → ``starving``.
    assert "hunger: starving" in vitals_rendered
    # Energy dropped from 60 by -1.5*24=-36 → 24 → ``tired``.
    assert "energy: tired" in vitals_rendered

    # Avatar path: no mood pressure + no agent state → neutral.
    extractor = EmotionExtractor(_EMOTION_MAP)
    emotion, index = extractor.resolve_emotion(None, None, mood=snap.mood)
    assert emotion == "neutral"
    assert index == _EMOTION_MAP["neutral"]


@pytest.mark.asyncio
async def test_s3_fresh_reconnect_does_not_trigger_catchup() -> None:
    """Negative control for S3 — a short-away session must *not* catch
    up (or we'd be double-ticking on every turn and vitals would
    saturate in minutes)."""
    provider = _CountingProvider()
    registry = _registry(provider)

    # Default InMemory provider load stamps ``last_tick_at`` = now.
    await provider.load("rico", owner_user_id="player-1")
    state = _RecordingState()
    await registry.hydrate(state)

    assert provider.tick_calls == []
    assert not any(n == "state.catchup" for n, _ in state.events)


# ── S4 — 감정 태그 자동 학습 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_s4_repeated_joy_tags_accumulate_and_surface_through_mood_block_and_avatar() -> None:
    """Three turns of ``[joy]`` lift ``mood.joy`` past the MoodBlock
    threshold, and the mood-aware avatar path maps it to the joy slot.

    This pins the full affect loop:

    1. Stage 14 ``AffectTagEmitter`` parses the LLM's text tag into a
       mutation on ``state.shared[MUTATION_BUFFER_KEY]``.
    2. ``registry.persist`` commits that mutation — ``mood.joy`` is
       durable across turns (not wiped on next hydrate).
    3. The next turn's hydrate returns the accumulated mood, and
       ``MoodBlock`` surfaces ``joy`` in the system prompt.
    4. The VTuber emitter path asks the extractor with the same mood
       and gets ``(joy, emotion_map["joy"])``.
    """
    provider = InMemoryCreatureStateProvider()
    registry = _registry(provider)
    emitter = AffectTagEmitter()

    for i in range(3):
        state = PipelineState()
        await registry.hydrate(state)
        # Simulate an LLM answer that includes an affect tag. ``emit``
        # reads final_text, writes into state.shared[MUTATION_BUFFER_KEY],
        # and rewrites final_text with tags stripped — same as it
        # behaves inside the real pipeline.
        state.final_text = f"That's wonderful! [joy] (turn {i + 1})"
        result = await emitter.emit(state)
        assert result.emitted is True
        assert "[joy]" not in state.final_text  # stripped for downstream
        await registry.persist(state)

    # Fresh hydrate — the durable side.
    observe = PipelineState()
    snap = await registry.hydrate(observe)

    # Three `[joy]` tags × MOOD_ALPHA (0.15) = 0.45 — well above the
    # 0.15 dominant threshold so MoodBlock surfaces it.
    assert snap.mood.joy == pytest.approx(0.45, rel=1e-6)

    mood_rendered = MoodBlock().render(observe)
    assert mood_rendered.startswith("[Mood] joy")
    assert "(0.45)" in mood_rendered

    # Avatar side — mood wins over the completed default (joy here
    # happens to agree, but the contract is mood-driven).
    extractor = EmotionExtractor(_EMOTION_MAP)
    emotion, index = extractor.resolve_emotion(
        "plain answer with no tag", "completed", mood=snap.mood,
    )
    assert emotion == "joy"
    assert index == _EMOTION_MAP["joy"]

    # Bond.affection also climbed (joy = +0.5 per tag via the
    # emitter's secondary bond rule) — proves the *secondary* effect
    # is surviving the round-trip, not just the mood channel.
    assert snap.bond.affection == pytest.approx(1.5, rel=1e-6)


@pytest.mark.asyncio
async def test_s4_anger_mood_overrides_completed_default_on_avatar_path() -> None:
    """Sanity: a *negative* accumulated mood also reaches the avatar.

    If the mood wiring only happened to work for joy (because
    ``completed → joy`` agrees) a joy-only test would pass vacuously.
    Anger disagrees with the completed default, so this guards
    against that kind of false green."""
    provider = InMemoryCreatureStateProvider()
    registry = _registry(provider)
    emitter = AffectTagEmitter()

    for _ in range(3):
        state = PipelineState()
        await registry.hydrate(state)
        state.final_text = "You again?? [anger:2]"
        await emitter.emit(state)
        await registry.persist(state)

    observe = PipelineState()
    snap = await registry.hydrate(observe)
    # 3 turns × 2.0 strength × 0.15 MOOD_ALPHA = 0.9
    assert snap.mood.anger == pytest.approx(0.9, rel=1e-6)

    extractor = EmotionExtractor(_EMOTION_MAP)
    emotion, _ = extractor.resolve_emotion(None, "completed", mood=snap.mood)
    assert emotion == "anger"


# ── Full cycle (hits every X3 hand-off) ────────────────────────────


@pytest.mark.asyncio
async def test_full_cycle_tool_mutation_then_affect_tag_then_persist() -> None:
    """One turn where both paths contribute: a TalkTool call (through
    ContextVar) AND an AffectTagEmitter match (through state.shared)
    must both land in the same buffer and commit atomically."""
    provider = InMemoryCreatureStateProvider()
    registry = _registry(provider)
    emitter = AffectTagEmitter()

    state = PipelineState()
    await registry.hydrate(state)
    buf = state.shared[MUTATION_BUFFER_KEY]

    token = bind_mutation_buffer(buf)
    try:
        TalkTool().run(kind="greet")
    finally:
        reset_mutation_buffer(token)

    state.final_text = "Nice to meet you! [joy]"
    await emitter.emit(state)

    # Both paths appended into the same buffer.
    paths = {m.path for m in buf.items}
    assert "bond.familiarity" in paths
    assert "mood.joy" in paths
    assert "bond.affection" in paths

    await registry.persist(state)

    persisted = await provider.load("rico", owner_user_id="player-1")
    assert persisted.bond.familiarity == pytest.approx(FAMILIARITY_DELTA)
    assert persisted.mood.joy == pytest.approx(0.15, rel=1e-6)
    assert persisted.bond.affection == pytest.approx(0.5, rel=1e-6)


# ── Helpers local to this module ───────────────────────────────────


class _CountingProvider(InMemoryCreatureStateProvider):
    """Counts ``tick`` invocations so tests can assert catch-up fired
    exactly the expected number of times."""

    def __init__(self) -> None:
        super().__init__()
        self.tick_calls: list[str] = []

    async def tick(self, character_id, policy):  # type: ignore[override]
        self.tick_calls.append(character_id)
        return await super().tick(character_id, policy)


class _RecordingState:
    """Minimal ``PipelineState`` analog for event-assertion tests.

    Registry only touches ``shared`` + ``add_event``; keeping this
    local saves the registry tests' stub from leaking across the
    integration-test boundary but stays isomorphic to it.
    """

    def __init__(self) -> None:
        self.shared: dict = {}
        self.events: list = []

    def add_event(self, name: str, payload: dict) -> None:
        self.events.append((name, payload))
