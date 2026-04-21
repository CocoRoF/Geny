"""``SessionRuntimeRegistry`` — pipeline ↔ ``CreatureState`` bridge.

Holds the snapshot for a single turn and injects ``creature_state`` /
``creature_state_mut`` into ``state.shared`` so stages can read/write
without touching the provider directly.

Sequencing per turn (see ``plan/02 §4``):

1. AgentSession instantiates one registry with the caller's identities + provider.
2. ``await registry.hydrate(state)`` before ``pipeline.run`` — loads the
   latest snapshot, installs buffer, emits ``state.hydrated``.
3. Pipeline stages read via ``state.shared['creature_state']`` and append
   to ``state.shared['creature_state_mut']``.
4. ``await registry.persist(state)`` after ``pipeline.run`` — commits
   mutations, emits ``state.persisted`` or ``state.conflict``.

Hydrate also performs **catch-up decay** (plan/02 §5.4): if the stored
``last_tick_at`` is older than :data:`~backend.service.state.decay.CATCHUP_THRESHOLD`
(typically because the owner has been offline), the registry calls
``provider.tick`` once before stages see the snapshot so drifted vitals
are reflected in this turn's prompt. Catch-up failures do not block the
turn — stages fall back to the stale snapshot and the scheduled decay
service will correct on its next run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .decay import CATCHUP_THRESHOLD, DEFAULT_DECAY, DecayPolicy
from .provider.interface import CreatureStateProvider, StateConflictError
from .schema.creature_state import CreatureState
from .schema.mutation import MutationBuffer

logger = logging.getLogger(__name__)

# Keys we write into ``state.shared`` — exported as constants so stages
# don't fight over spelling.
CREATURE_STATE_KEY = "creature_state"
MUTATION_BUFFER_KEY = "creature_state_mut"
SESSION_META_KEY = "session_meta"


class SessionRuntimeRegistry:
    def __init__(
        self,
        *,
        session_id: str,
        character_id: str,
        owner_user_id: str,
        provider: CreatureStateProvider,
        catchup_policy: DecayPolicy = DEFAULT_DECAY,
    ) -> None:
        self.session_id = session_id
        self.character_id = character_id
        self.owner_user_id = owner_user_id
        self._provider = provider
        self._catchup_policy = catchup_policy
        self._snapshot: Optional[CreatureState] = None

    @property
    def snapshot(self) -> Optional[CreatureState]:
        return self._snapshot

    async def hydrate(self, state: Any) -> CreatureState:
        snap = await self._provider.load(
            self.character_id, owner_user_id=self.owner_user_id,
        )
        snap = await self._maybe_catchup(state, snap)
        self._snapshot = snap
        _put_shared(state, CREATURE_STATE_KEY, snap)
        _put_shared(state, MUTATION_BUFFER_KEY, MutationBuffer())
        _put_shared(state, SESSION_META_KEY, {
            "session_id": self.session_id,
            "character_id": self.character_id,
            "owner_user_id": self.owner_user_id,
        })
        _emit(state, "state.hydrated", {
            "character_id": self.character_id,
            "session_id": self.session_id,
            "row_version": getattr(snap, "_row_version", None),
            "last_tick_at": snap.last_tick_at.isoformat(),
        })
        return snap

    async def _maybe_catchup(
        self, state: Any, snap: CreatureState,
    ) -> CreatureState:
        """Tick once if ``last_tick_at`` is older than the threshold.

        Returns the decayed snapshot, or the original on any failure.
        """
        now = datetime.now(timezone.utc)
        last_tick = snap.last_tick_at
        if last_tick.tzinfo is None:
            # Defensive: serialized states should round-trip with tzinfo,
            # but guard against a legacy row sneaking through naive.
            last_tick = last_tick.replace(tzinfo=timezone.utc)
        if now - last_tick < CATCHUP_THRESHOLD:
            return snap

        tick = getattr(self._provider, "tick", None)
        if not callable(tick):
            # Provider pre-dates PR-X3-4 — no catch-up available, ship
            # the stale snapshot rather than fail the turn.
            return snap

        try:
            caught_up = await tick(self.character_id, self._catchup_policy)
        except Exception as e:
            # Catch-up must never block a turn. Stages see the stale
            # snapshot; the scheduled decay service will correct.
            logger.warning(
                "state catchup failed for %s: %s", self.character_id, e
            )
            _emit(state, "state.catchup_failed", {
                "character_id": self.character_id,
                "session_id": self.session_id,
                "reason": str(e),
            })
            return snap

        _emit(state, "state.catchup", {
            "character_id": self.character_id,
            "session_id": self.session_id,
            "from_last_tick_at": snap.last_tick_at.isoformat(),
            "to_last_tick_at": caught_up.last_tick_at.isoformat(),
        })
        return caught_up

    async def persist(self, state: Any) -> CreatureState:
        if self._snapshot is None:
            raise RuntimeError("persist called without hydrate")
        buf = _get_shared(state, MUTATION_BUFFER_KEY)
        if not isinstance(buf, MutationBuffer):
            raise RuntimeError(
                f"expected MutationBuffer at state.shared[{MUTATION_BUFFER_KEY!r}], "
                f"got {type(buf).__name__}"
            )
        try:
            new_state = await self._provider.apply(self._snapshot, buf.items)
        except StateConflictError as e:
            _emit(state, "state.conflict", {
                "character_id": self.character_id,
                "session_id": self.session_id,
                "mutations": len(buf),
                "reason": str(e),
            })
            raise

        self._snapshot = new_state
        _put_shared(state, CREATURE_STATE_KEY, new_state)
        _emit(state, "state.persisted", {
            "character_id": self.character_id,
            "session_id": self.session_id,
            "mutations": len(buf),
            "row_version": getattr(new_state, "_row_version", None),
        })
        return new_state


def _put_shared(state: Any, key: str, value: Any) -> None:
    shared = getattr(state, "shared", None)
    if shared is None:
        raise AttributeError("state has no 'shared' mapping")
    shared[key] = value


def _get_shared(state: Any, key: str) -> Any:
    shared = getattr(state, "shared", None)
    if shared is None:
        raise AttributeError("state has no 'shared' mapping")
    return shared.get(key)


def _emit(state: Any, event: str, payload: dict[str, Any]) -> None:
    """Best-effort ``state.add_event`` — silently skip if unavailable.

    PipelineState (geny_executor) exposes ``add_event``. Test stubs may
    not; the registry should not crash for lack of observability.
    """
    add_event = getattr(state, "add_event", None)
    if callable(add_event):
        try:
            add_event(event, payload)
        except Exception:
            # Event sink failures must never break hydrate/persist.
            pass
