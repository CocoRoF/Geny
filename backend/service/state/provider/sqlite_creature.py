"""File-backed SQLite ``CreatureStateProvider`` — MVP persistence.

Geny's main persistence layer is PostgreSQL (``service/database``), but
the X3 MVP intentionally uses a self-contained SQLite file so the state
module can be rolled out / reverted without touching PG migrations. Once
the shape is stable, PR-X5 or later can mirror this provider onto the PG
helper pattern.

Synchronous stdlib ``sqlite3`` is wrapped in ``asyncio.to_thread`` so the
Protocol stays ``async``. One connection per provider instance; thread
safety comes from sqlite's own serialization (``check_same_thread=False``
+ single writer via ``BEGIN IMMEDIATE``).
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..decay import DecayPolicy, apply_decay
from ..schema.creature_state import CreatureState
from ..schema.mutation import Mutation
from .interface import StateConflictError
from .mutate import apply_mutations
from .serialize import dumps, loads


# Decay tick contends with pipeline ``apply`` for the same row. One
# internal retry absorbs the common case of "pipeline committed while
# decay was computing"; further contention escalates as a conflict so
# the decay service can skip to the next scheduled tick rather than
# spinning.
_TICK_MAX_RETRIES = 3


_MIGRATION = (Path(__file__).parent / "migrations" / "0001_initial.sql").read_text()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteCreatureStateProvider:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        # ``check_same_thread=False`` because we dispatch through
        # ``asyncio.to_thread`` from potentially different worker threads.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._conn.executescript(_MIGRATION)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- sync internals (run via to_thread) --------------------------------

    def _load_sync(self, character_id: str, owner_user_id: str) -> CreatureState:
        """Return hydrated state with ``_row_version`` attached for OCC."""
        cur = self._conn.execute(
            "SELECT data_json, row_version FROM creature_state WHERE character_id = ?",
            (character_id,),
        )
        row = cur.fetchone()
        if row is not None:
            state = loads(row["data_json"])
            setattr(state, "_row_version", int(row["row_version"]))
            return state

        # First-touch — create a default row so apply() has something to OCC against.
        default = CreatureState(
            character_id=character_id,
            owner_user_id=owner_user_id,
        )
        blob = dumps(default)
        now = _utcnow_iso()
        self._conn.execute(
            "INSERT INTO creature_state "
            "(character_id, owner_user_id, schema_version, data_json, "
            " last_tick_at, last_interaction_at, updated_at, row_version) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, 1)",
            (
                character_id,
                owner_user_id,
                default.schema_version,
                blob,
                default.last_tick_at.isoformat(),
                now,
            ),
        )
        self._conn.commit()
        setattr(default, "_row_version", 1)
        return default

    def _apply_sync(
        self,
        snapshot: CreatureState,
        mutations: Sequence[Mutation],
    ) -> CreatureState:
        if not mutations:
            # Nothing to persist — preserve snapshot identity / row_version.
            return snapshot
        new_state = apply_mutations(snapshot, mutations)
        blob = dumps(new_state)
        last_interaction_iso = (
            new_state.last_interaction_at.isoformat()
            if new_state.last_interaction_at is not None
            else None
        )

        # OCC: use the row_version the caller saw at load time. Missing attr
        # means the caller fabricated a state without going through load() —
        # we fall back to a re-read so tests / admin paths still work, but
        # they forfeit the stale-snapshot guarantee.
        expected = getattr(snapshot, "_row_version", None)
        if expected is None:
            row = self._conn.execute(
                "SELECT row_version FROM creature_state WHERE character_id = ?",
                (snapshot.character_id,),
            ).fetchone()
            if row is None:
                raise KeyError(
                    f"character {snapshot.character_id!r} not loaded before apply"
                )
            expected = int(row["row_version"])

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            result = self._conn.execute(
                "UPDATE creature_state "
                "   SET data_json = ?, schema_version = ?, "
                "       last_tick_at = ?, last_interaction_at = ?, "
                "       updated_at = ?, row_version = row_version + 1 "
                " WHERE character_id = ? AND row_version = ?",
                (
                    blob,
                    new_state.schema_version,
                    new_state.last_tick_at.isoformat(),
                    last_interaction_iso,
                    _utcnow_iso(),
                    snapshot.character_id,
                    expected,
                ),
            )
            if result.rowcount == 0:
                self._conn.execute("ROLLBACK")
                raise StateConflictError(
                    f"row_version mismatch on {snapshot.character_id!r} "
                    f"(expected {expected})"
                )
            self._conn.execute("COMMIT")
        except StateConflictError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        setattr(new_state, "_row_version", expected + 1)
        return new_state

    def _set_absolute_sync(
        self, character_id: str, patch: Dict[str, Any],
    ) -> CreatureState:
        cur = self._conn.execute(
            "SELECT data_json, row_version FROM creature_state WHERE character_id = ?",
            (character_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"character {character_id!r} not loaded")
        state = loads(row["data_json"])
        expected = int(row["row_version"])
        # set_absolute has no caller snapshot, so it always re-reads the
        # version — concurrent admin writes are the caller's problem.

        for path, value in patch.items():
            _assign_path(state, path, value)

        blob = dumps(state)
        last_interaction_iso = (
            state.last_interaction_at.isoformat()
            if state.last_interaction_at is not None
            else None
        )

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            result = self._conn.execute(
                "UPDATE creature_state "
                "   SET data_json = ?, schema_version = ?, "
                "       last_tick_at = ?, last_interaction_at = ?, "
                "       updated_at = ?, row_version = row_version + 1 "
                " WHERE character_id = ? AND row_version = ?",
                (
                    blob,
                    state.schema_version,
                    state.last_tick_at.isoformat(),
                    last_interaction_iso,
                    _utcnow_iso(),
                    character_id,
                    expected,
                ),
            )
            if result.rowcount == 0:
                self._conn.execute("ROLLBACK")
                raise StateConflictError(
                    f"row_version mismatch on {character_id!r} (expected {expected})"
                )
            self._conn.execute("COMMIT")
        except StateConflictError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        setattr(state, "_row_version", expected + 1)
        return state

    def _row_version_sync(self, character_id: str) -> Optional[int]:
        row = self._conn.execute(
            "SELECT row_version FROM creature_state WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        return int(row["row_version"]) if row is not None else None

    def _tick_sync(
        self, character_id: str, policy: DecayPolicy,
    ) -> CreatureState:
        """Load → apply_decay → OCC UPDATE, with bounded retry on conflict."""
        last_err: Optional[StateConflictError] = None
        for _ in range(_TICK_MAX_RETRIES):
            cur = self._conn.execute(
                "SELECT data_json, row_version FROM creature_state "
                "WHERE character_id = ?",
                (character_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"character {character_id!r} not loaded")
            snap = loads(row["data_json"])
            expected = int(row["row_version"])
            setattr(snap, "_row_version", expected)

            new_state = apply_decay(snap, policy)
            blob = dumps(new_state)
            last_interaction_iso = (
                new_state.last_interaction_at.isoformat()
                if new_state.last_interaction_at is not None
                else None
            )

            self._conn.execute("BEGIN IMMEDIATE")
            try:
                result = self._conn.execute(
                    "UPDATE creature_state "
                    "   SET data_json = ?, schema_version = ?, "
                    "       last_tick_at = ?, last_interaction_at = ?, "
                    "       updated_at = ?, row_version = row_version + 1 "
                    " WHERE character_id = ? AND row_version = ?",
                    (
                        blob,
                        new_state.schema_version,
                        new_state.last_tick_at.isoformat(),
                        last_interaction_iso,
                        _utcnow_iso(),
                        character_id,
                        expected,
                    ),
                )
                if result.rowcount == 0:
                    self._conn.execute("ROLLBACK")
                    last_err = StateConflictError(
                        f"tick: row_version mismatch on {character_id!r} "
                        f"(expected {expected})"
                    )
                    continue  # re-read + retry
                self._conn.execute("COMMIT")
            except StateConflictError:
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

            setattr(new_state, "_row_version", expected + 1)
            return new_state

        assert last_err is not None  # loop always sets on retry branch
        raise last_err

    def _list_characters_sync(self) -> List[str]:
        rows = self._conn.execute(
            "SELECT character_id FROM creature_state"
        ).fetchall()
        return [str(r["character_id"]) for r in rows]

    # -- async Protocol surface -------------------------------------------

    async def load(
        self,
        character_id: str,
        *,
        owner_user_id: str = "",
    ) -> CreatureState:
        async with self._lock:
            return await asyncio.to_thread(
                self._load_sync, character_id, owner_user_id
            )

    async def apply(
        self,
        snapshot: CreatureState,
        mutations: Sequence[Mutation],
    ) -> CreatureState:
        async with self._lock:
            return await asyncio.to_thread(self._apply_sync, snapshot, mutations)

    async def set_absolute(
        self,
        character_id: str,
        patch: Dict[str, Any],
    ) -> CreatureState:
        async with self._lock:
            return await asyncio.to_thread(
                self._set_absolute_sync, character_id, patch
            )

    async def row_version(self, character_id: str) -> Optional[int]:
        """Peek at the OCC version — diagnostic / test helper."""
        async with self._lock:
            return await asyncio.to_thread(self._row_version_sync, character_id)

    async def tick(
        self,
        character_id: str,
        policy: DecayPolicy,
    ) -> CreatureState:
        async with self._lock:
            return await asyncio.to_thread(self._tick_sync, character_id, policy)

    async def list_characters(self) -> List[str]:
        async with self._lock:
            return await asyncio.to_thread(self._list_characters_sync)


def _assign_path(state: CreatureState, path: str, value: Any) -> None:
    parts = path.split(".")
    obj: Any = state
    for p in parts[:-1]:
        obj = getattr(obj, p)
    setattr(obj, parts[-1], value)
