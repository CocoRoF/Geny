"""``CreatureStateProvider`` Protocol + shared error types.

PR-X3-2 defined ``load`` / ``apply`` / ``set_absolute``. PR-X3-4 adds
``tick`` (decay) and ``list_characters`` (enumeration for the decay
service). Protocol extension is structural — existing implementations
that add these methods automatically satisfy it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Protocol, Sequence, runtime_checkable

from ..schema.creature_state import CreatureState
from ..schema.mutation import Mutation

if TYPE_CHECKING:
    from ..decay import DecayPolicy

# Hard cap on ``CreatureState.recent_events`` ring buffer.
# Values beyond this get trimmed on ``apply`` (oldest first).
RECENT_EVENTS_MAX = 20


class StateConflictError(Exception):
    """Raised when optimistic concurrency rejects an ``apply`` write."""


@runtime_checkable
class CreatureStateProvider(Protocol):
    async def load(
        self,
        character_id: str,
        *,
        owner_user_id: str = "",
    ) -> CreatureState:
        """Return the ``CreatureState`` for ``character_id``.

        If no row exists yet, a fresh default state is created with the
        given ``owner_user_id`` and returned. Providers MAY persist that
        default immediately (so follow-up ``apply`` has a row to OCC
        against) or lazily on first ``apply`` — both are allowed.
        """
        ...

    async def apply(
        self,
        snapshot: CreatureState,
        mutations: Sequence[Mutation],
    ) -> CreatureState:
        """Atomically replay ``mutations`` on ``snapshot`` and persist.

        Must be all-or-nothing: a failure partway through mutations leaves
        storage as it was before the call. Implementations that detect
        concurrent writes raise :class:`StateConflictError`.
        """
        ...

    async def set_absolute(
        self,
        character_id: str,
        patch: Dict[str, Any],
    ) -> CreatureState:
        """Administrative override — progression transitions, migrations.

        ``patch`` uses the same dotted paths as mutations. Equivalent to
        an ``apply`` that consists solely of ``set`` ops but skips the
        usual mutation bookkeeping so admin changes don't pollute the
        event audit.
        """
        ...

    async def tick(
        self,
        character_id: str,
        policy: "DecayPolicy",
    ) -> CreatureState:
        """Apply time-based decay to ``character_id`` and persist.

        Called by :class:`CreatureStateDecayService` on a schedule and
        by :class:`SessionRuntimeRegistry` catch-up. Raises ``KeyError``
        if the character has no row — tick does not bring new characters
        into existence. May raise :class:`StateConflictError` if a
        concurrent ``apply`` raced; callers decide whether to retry
        (decay service just skips to next tick).
        """
        ...

    async def list_characters(self) -> List[str]:
        """Return character_ids with a stored row.

        Used by the decay service to enumerate targets. Order is not
        guaranteed. An empty list is valid (no characters yet).
        """
        ...
