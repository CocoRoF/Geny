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

Manifest transition (plan/04 §7.4, PR-X4-5)
-------------------------------------------

When a :class:`~backend.service.progression.selector.ManifestSelector`
and a matching :class:`CharacterLike` are supplied, hydrate also runs
the selector against the freshly loaded snapshot. A selector decision
that differs from the stored ``progression.manifest_id`` produces three
mutations on the turn's buffer:

- ``set progression.manifest_id = <new_id>``
- ``set progression.life_stage = <stage-from-new_id>`` (when parseable)
- ``append progression.milestones = "enter:<new_id>"``

The registry also stamps ``session_meta["new_milestone"] =
"enter:<new_id>"`` so the :class:`EventSeedBlock`'s
``milestone_just_hit`` trigger (weight 3.0) fires on the *same* turn the
transition lands — the prompt feels the milestone the moment it
happens, not only on the next session. The pipeline itself isn't
rebuilt mid-session (plan/04 §7.4 makes that a session-start-only
action); the persisted mutations take effect on the next session.
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

_SELECTOR_SOURCE = "selector:transition"

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
        manifest_selector: Any = None,
        character: Any = None,
    ) -> None:
        self.session_id = session_id
        self.character_id = character_id
        self.owner_user_id = owner_user_id
        self._provider = provider
        self._catchup_policy = catchup_policy
        self._manifest_selector = manifest_selector
        self._character = character
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
        # PR-X5F-3: also expose the registry on the typed
        # ``state.session_runtime`` slot (geny-executor >= 0.30.0), so
        # stages and third-party plugins can reach ``snapshot`` /
        # ``session_id`` / ``character_id`` via attribute access instead
        # of the stringly-typed ``state.shared`` bag. Coexists with the
        # shared-dict writes above — existing consumers unchanged.
        _put_session_runtime(state, self)
        _emit(state, "state.hydrated", {
            "character_id": self.character_id,
            "session_id": self.session_id,
            "row_version": getattr(snap, "_row_version", None),
            "last_tick_at": snap.last_tick_at.isoformat(),
        })

        await self._maybe_apply_manifest_transition(state, snap)
        return snap

    async def _maybe_apply_manifest_transition(
        self, state: Any, snap: CreatureState,
    ) -> None:
        """Run the selector and stage transition mutations when warranted.

        Plan/04 §7.4 runs the selector at session start. The registry is
        the only component that has (a) the hydrated snapshot, (b) the
        mutation buffer, and (c) the shared session_meta dict, so it's
        the natural home — placing the call here also means test
        harnesses that exercise hydrate get selector coverage for free.

        Silent on every failure mode (missing selector, missing
        character, selector exception, non-parseable id): a
        misconfigured growth tree must not cost a turn.
        """
        if self._manifest_selector is None or self._character is None:
            return
        try:
            new_id = await self._manifest_selector.select(snap, self._character)
        except Exception:
            logger.debug(
                "manifest selector raised during hydrate — keeping current id",
                exc_info=True,
            )
            return

        current_id = self._current_manifest_id(snap)
        if not isinstance(new_id, str) or not new_id or new_id == current_id:
            return

        buf = _get_shared(state, MUTATION_BUFFER_KEY)
        if not isinstance(buf, MutationBuffer):
            logger.debug(
                "selector transition: mutation buffer missing — skipping",
            )
            return

        buf.append(
            op="set",
            path="progression.manifest_id",
            value=new_id,
            source=_SELECTOR_SOURCE,
        )
        new_stage = _stage_from_manifest_id(new_id)
        if new_stage:
            buf.append(
                op="set",
                path="progression.life_stage",
                value=new_stage,
                source=_SELECTOR_SOURCE,
            )
        milestone = f"enter:{new_id}"
        buf.append(
            op="append",
            path="progression.milestones",
            value=milestone,
            source=_SELECTOR_SOURCE,
        )

        meta = _get_shared(state, SESSION_META_KEY)
        if isinstance(meta, dict):
            meta["new_milestone"] = milestone

        _emit(state, "state.manifest_transition", {
            "character_id": self.character_id,
            "session_id": self.session_id,
            "from_manifest_id": current_id,
            "to_manifest_id": new_id,
            "new_life_stage": new_stage,
        })

    @staticmethod
    def _current_manifest_id(snap: CreatureState) -> str:
        progression = getattr(snap, "progression", None)
        if progression is None:
            return ""
        manifest_id = getattr(progression, "manifest_id", "")
        return manifest_id if isinstance(manifest_id, str) else ""

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


_KNOWN_LIFE_STAGES: frozenset[str] = frozenset(
    {"infant", "child", "teen", "adult"}
)


def _stage_from_manifest_id(manifest_id: str) -> str:
    """Parse a manifest id's leading stage keyword.

    Accepts both bare (``"child"``) and archetype-suffixed (``"child_curious"``)
    forms — mirrors :func:`~backend.service.progression.selector.default_manifest_naming`.
    Returns ``""`` for unparseable ids (``"base"``, future stages, empty);
    the caller treats empty as "don't mutate life_stage" so a custom-named
    manifest doesn't flip the creature into a bogus stage.
    """
    if not manifest_id:
        return ""
    head = manifest_id.split("_", 1)[0]
    return head if head in _KNOWN_LIFE_STAGES else ""


def _put_shared(state: Any, key: str, value: Any) -> None:
    shared = getattr(state, "shared", None)
    if shared is None:
        raise AttributeError("state has no 'shared' mapping")
    shared[key] = value


def _put_session_runtime(state: Any, runtime: Any) -> None:
    """Best-effort write of the registry onto ``state.session_runtime``.

    Tolerates state objects that refuse arbitrary attribute writes
    (``__slots__`` without the field, frozen dataclasses, unusual
    hosts). The shared-dict path remains authoritative in that case;
    this attribute is an *ergonomic* alias, not the storage source.
    """
    try:
        state.session_runtime = runtime
    except (AttributeError, TypeError):
        logger.debug(
            "state %r rejected session_runtime attribute write; "
            "falling back to shared-dict only",
            type(state).__name__,
        )


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
