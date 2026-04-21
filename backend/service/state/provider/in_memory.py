"""In-memory ``CreatureStateProvider`` for tests and feature-flag-off paths.

Dict-backed; guarded by a per-character ``asyncio.Lock`` so concurrency
tests see the same serialization guarantees as the sqlite provider.
Deep-copies on every read so callers can't mutate the store by accident.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Dict, List, Sequence

from ..decay import DecayPolicy, apply_decay
from ..schema.creature_state import CreatureState
from ..schema.mutation import Mutation
from .mutate import apply_mutations


class InMemoryCreatureStateProvider:
    def __init__(self) -> None:
        self._store: Dict[str, CreatureState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _lock_for(self, character_id: str) -> asyncio.Lock:
        lock = self._locks.get(character_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[character_id] = lock
        return lock

    async def load(
        self,
        character_id: str,
        *,
        owner_user_id: str = "",
    ) -> CreatureState:
        async with self._lock_for(character_id):
            state = self._store.get(character_id)
            if state is None:
                state = CreatureState(
                    character_id=character_id,
                    owner_user_id=owner_user_id,
                )
                self._store[character_id] = copy.deepcopy(state)
            return copy.deepcopy(state)

    async def apply(
        self,
        snapshot: CreatureState,
        mutations: Sequence[Mutation],
    ) -> CreatureState:
        async with self._lock_for(snapshot.character_id):
            if not mutations:
                return snapshot
            new_state = apply_mutations(snapshot, mutations)
            self._store[snapshot.character_id] = copy.deepcopy(new_state)
            return copy.deepcopy(new_state)

    async def set_absolute(
        self,
        character_id: str,
        patch: Dict[str, Any],
    ) -> CreatureState:
        async with self._lock_for(character_id):
            state = self._store.get(character_id)
            if state is None:
                raise KeyError(f"character {character_id!r} not loaded")
            new_state = copy.deepcopy(state)
            for path, value in patch.items():
                _assign_path(new_state, path, value)
            self._store[character_id] = copy.deepcopy(new_state)
            return copy.deepcopy(new_state)

    async def tick(
        self,
        character_id: str,
        policy: DecayPolicy,
    ) -> CreatureState:
        async with self._lock_for(character_id):
            state = self._store.get(character_id)
            if state is None:
                raise KeyError(f"character {character_id!r} not loaded")
            new_state = apply_decay(state, policy)
            self._store[character_id] = copy.deepcopy(new_state)
            return copy.deepcopy(new_state)

    async def list_characters(self) -> List[str]:
        # Snapshot of keys — safe to read without per-key locks because
        # dict iteration under CPython is atomic for this op.
        return list(self._store.keys())


def _assign_path(state: CreatureState, path: str, value: Any) -> None:
    parts = path.split(".")
    obj: Any = state
    for p in parts[:-1]:
        obj = getattr(obj, p)
    setattr(obj, parts[-1], value)
