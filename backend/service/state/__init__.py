"""Creature state layer — long-lived per-character game state (X3).

Cycle 20260421_9 introduces ``CreatureState`` as an **external wrapper**
around the pipeline — hydrated before ``pipeline.run`` and persisted after.
Stages mutate state by appending ``Mutation`` entries to a buffer on
``state.shared``; the wrapper commits them atomically through a
``CreatureStateProvider``.

See ``dev_docs/20260421_6/plan/02_creature_state_contract.md`` for the
full contract; this package is layered as:

- ``schema/`` — pure dataclasses (PR-X3-1).
- ``provider/`` — storage protocol + sqlite impl (PR-X3-2).
- ``registry`` / ``hydrator`` — pipeline integration (PR-X3-3).
- ``decay`` + ``decay_service`` — time-based drift + tick engine
  registration (PR-X3-4).
"""

from __future__ import annotations

from .decay import (
    CATCHUP_THRESHOLD,
    DEFAULT_DECAY,
    DecayPolicy,
    DecayRule,
    apply_decay,
)
from .decay_service import (
    DEFAULT_DECAY_INTERVAL_SECONDS,
    DEFAULT_DECAY_JITTER_SECONDS,
    CreatureStateDecayService,
)
from .flags import (
    KNOWN_TURN_KINDS,
    TURN_KIND_SYSTEM,
    TURN_KIND_TOOL,
    TURN_KIND_TRIGGER,
    TURN_KIND_USER,
    get_turn_kind,
    is_user_turn,
    is_vtuber_role,
    is_vtuber_state,
    role_of,
)
from .hydrator import hydrate_state, persist_state
from .provider import (
    CreatureStateProvider,
    InMemoryCreatureStateProvider,
    RECENT_EVENTS_MAX,
    SqliteCreatureStateProvider,
    StateConflictError,
    apply_mutations,
)
from .registry import (
    CREATURE_STATE_KEY,
    MUTATION_BUFFER_KEY,
    SESSION_META_KEY,
    SessionRuntimeRegistry,
)
from .schema import (
    SCHEMA_VERSION,
    Bond,
    CHARACTER_ROLE_OTHER,
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
    CreatureState,
    KNOWN_CHARACTER_ROLES,
    MoodVector,
    Mutation,
    MutationBuffer,
    MutationOp,
    Progression,
    Vitals,
)
from .tool_context import (
    bind_creature_role,
    bind_mutation_buffer,
    current_creature_role,
    current_mutation_buffer,
    reset_creature_role,
    reset_mutation_buffer,
)

__all__ = [
    "CATCHUP_THRESHOLD",
    "CHARACTER_ROLE_OTHER",
    "CHARACTER_ROLE_VTUBER",
    "CHARACTER_ROLE_WORKER",
    "CREATURE_STATE_KEY",
    "CreatureStateDecayService",
    "DEFAULT_DECAY",
    "DEFAULT_DECAY_INTERVAL_SECONDS",
    "DEFAULT_DECAY_JITTER_SECONDS",
    "DecayPolicy",
    "DecayRule",
    "KNOWN_CHARACTER_ROLES",
    "KNOWN_TURN_KINDS",
    "MUTATION_BUFFER_KEY",
    "SCHEMA_VERSION",
    "SESSION_META_KEY",
    "TURN_KIND_SYSTEM",
    "TURN_KIND_TOOL",
    "TURN_KIND_TRIGGER",
    "TURN_KIND_USER",
    "Bond",
    "CreatureState",
    "CreatureStateProvider",
    "InMemoryCreatureStateProvider",
    "MoodVector",
    "Mutation",
    "MutationBuffer",
    "MutationOp",
    "Progression",
    "RECENT_EVENTS_MAX",
    "SessionRuntimeRegistry",
    "SqliteCreatureStateProvider",
    "StateConflictError",
    "Vitals",
    "apply_decay",
    "apply_mutations",
    "bind_creature_role",
    "bind_mutation_buffer",
    "current_creature_role",
    "current_mutation_buffer",
    "get_turn_kind",
    "hydrate_state",
    "is_user_turn",
    "is_vtuber_role",
    "is_vtuber_state",
    "persist_state",
    "reset_creature_role",
    "reset_mutation_buffer",
    "role_of",
]
