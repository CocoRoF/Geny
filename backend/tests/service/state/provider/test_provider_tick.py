"""``tick`` and ``list_characters`` on both provider implementations.

Shared surface per :class:`CreatureStateProvider` Protocol (PR-X3-4):
decay applies and persists, OCC retries on contention, missing
characters raise ``KeyError``, and ``list_characters`` reflects what
was actually loaded.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.service.state.decay import (
    DEFAULT_DECAY,
    DecayPolicy,
    DecayRule,
)
from backend.service.state.provider.in_memory import (
    InMemoryCreatureStateProvider,
)
from backend.service.state.provider.interface import StateConflictError
from backend.service.state.provider.sqlite_creature import (
    SqliteCreatureStateProvider,
)


@asynccontextmanager
async def _provider(kind: str, tmp_path: Path):
    """Parametrized provider context — used by @pytest.mark.parametrize tests.

    Async fixtures would be cleaner but none of the existing state tests
    use ``pytest_asyncio.fixture`` and adopting it here would be the only
    caller. A tiny context manager keeps the pattern local.
    """
    if kind == "in_memory":
        yield InMemoryCreatureStateProvider()
        return
    prov = SqliteCreatureStateProvider(db_path=tmp_path / f"{kind}.sqlite3")
    try:
        yield prov
    finally:
        prov.close()


_PROVIDER_KINDS = pytest.mark.parametrize("kind", ["in_memory", "sqlite"])


@_PROVIDER_KINDS
@pytest.mark.asyncio
async def test_tick_on_missing_character_raises_key_error(
    kind: str, tmp_path: Path,
) -> None:
    async with _provider(kind, tmp_path) as provider:
        with pytest.raises(KeyError):
            await provider.tick("nope", DEFAULT_DECAY)


@_PROVIDER_KINDS
@pytest.mark.asyncio
async def test_tick_applies_decay_with_real_elapsed(
    kind: str, tmp_path: Path,
) -> None:
    async with _provider(kind, tmp_path) as provider:
        state = await provider.load("c1", owner_user_id="u1")
        ten_hours_ago = datetime.now(timezone.utc) - timedelta(hours=10)
        await provider.set_absolute("c1", {"last_tick_at": ten_hours_ago})

        policy = DecayPolicy(rules=(DecayRule("vitals.hunger", +1.0),))
        after = await provider.tick("c1", policy)

        start_hunger = state.vitals.hunger
        assert after.vitals.hunger == pytest.approx(start_hunger + 10.0, abs=0.5)
        assert after.last_tick_at > ten_hours_ago + timedelta(hours=9)


@_PROVIDER_KINDS
@pytest.mark.asyncio
async def test_tick_persists_so_load_returns_decayed(
    kind: str, tmp_path: Path,
) -> None:
    async with _provider(kind, tmp_path) as provider:
        await provider.load("c1", owner_user_id="u1")
        await provider.set_absolute("c1", {
            "last_tick_at": datetime.now(timezone.utc) - timedelta(hours=5),
            "vitals.hunger": 20.0,
        })
        await provider.tick(
            "c1", DecayPolicy(rules=(DecayRule("vitals.hunger", +2.0),)),
        )
        reloaded = await provider.load("c1", owner_user_id="u1")
        assert reloaded.vitals.hunger == pytest.approx(30.0, abs=0.5)


@_PROVIDER_KINDS
@pytest.mark.asyncio
async def test_tick_clamps_to_max(kind: str, tmp_path: Path) -> None:
    async with _provider(kind, tmp_path) as provider:
        await provider.load("c1", owner_user_id="u1")
        await provider.set_absolute("c1", {
            "last_tick_at": datetime.now(timezone.utc) - timedelta(hours=100),
            "vitals.hunger": 80.0,
        })
        after = await provider.tick(
            "c1", DecayPolicy(rules=(DecayRule("vitals.hunger", +2.0),)),
        )
        assert after.vitals.hunger == pytest.approx(100.0)


@_PROVIDER_KINDS
@pytest.mark.asyncio
async def test_list_characters_empty_initially(
    kind: str, tmp_path: Path,
) -> None:
    async with _provider(kind, tmp_path) as provider:
        assert await provider.list_characters() == []


@_PROVIDER_KINDS
@pytest.mark.asyncio
async def test_list_characters_after_load(kind: str, tmp_path: Path) -> None:
    async with _provider(kind, tmp_path) as provider:
        await provider.load("alpha", owner_user_id="u1")
        await provider.load("beta", owner_user_id="u1")
        await provider.load("gamma", owner_user_id="u2")
        ids = set(await provider.list_characters())
        assert ids == {"alpha", "beta", "gamma"}


@_PROVIDER_KINDS
@pytest.mark.asyncio
async def test_tick_preserves_bond_affection(kind: str, tmp_path: Path) -> None:
    async with _provider(kind, tmp_path) as provider:
        await provider.load("c1", owner_user_id="u1")
        await provider.set_absolute("c1", {
            "last_tick_at": datetime.now(timezone.utc) - timedelta(hours=50),
            "bond.affection": 42.0,
            "bond.trust": 17.0,
            "bond.dependency": 3.0,
        })
        after = await provider.tick("c1", DEFAULT_DECAY)
        assert after.bond.affection == pytest.approx(42.0)
        assert after.bond.trust == pytest.approx(17.0)
        assert after.bond.dependency == pytest.approx(3.0)


# -- OCC path (sqlite-specific) -------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_tick_bumps_row_version(tmp_path: Path) -> None:
    prov = SqliteCreatureStateProvider(db_path=tmp_path / "t.sqlite3")
    try:
        await prov.load("c1", owner_user_id="u1")
        before = await prov.row_version("c1")
        assert before == 1
        await prov.tick("c1", DEFAULT_DECAY)
        after = await prov.row_version("c1")
        assert after == 2
    finally:
        prov.close()


class _ExecProxy:
    """Thin wrapper that intercepts ``execute`` to simulate OCC misses.

    sqlite3.Connection forbids setattr on the ``execute`` method, so we
    swap the whole connection attribute on the provider with this proxy.
    Delegates every other attribute to the real connection.
    """

    def __init__(self, conn, *, misses: int) -> None:
        self._conn = conn
        self._misses_left = misses
        self.update_calls = 0

    def execute(self, sql: str, params: tuple = ()) -> Any:
        if sql.startswith("UPDATE creature_state "):
            self.update_calls += 1
            if self._misses_left > 0:
                self._misses_left -= 1
                # Lie about the row_version (last param) so WHERE misses.
                bogus = list(params)
                bogus[-1] = 99999
                return self._conn.execute(sql, tuple(bogus))
        return self._conn.execute(sql, params)

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - passthrough
        return getattr(self._conn, item)


@pytest.mark.asyncio
async def test_sqlite_tick_retries_transient_conflict(tmp_path: Path) -> None:
    """Simulate one OCC miss, then success on retry."""
    prov = SqliteCreatureStateProvider(db_path=tmp_path / "t.sqlite3")
    try:
        await prov.load("c1", owner_user_id="u1")
        proxy = _ExecProxy(prov._conn, misses=1)
        prov._conn = proxy  # type: ignore[assignment]

        after = await prov.tick("c1", DEFAULT_DECAY)
        assert proxy.update_calls >= 2  # at least one retry
        assert getattr(after, "_row_version") == 2
    finally:
        prov._conn = proxy._conn  # type: ignore[assignment]
        prov.close()


@pytest.mark.asyncio
async def test_sqlite_tick_gives_up_after_max_retries(tmp_path: Path) -> None:
    prov = SqliteCreatureStateProvider(db_path=tmp_path / "t.sqlite3")
    try:
        await prov.load("c1", owner_user_id="u1")
        proxy = _ExecProxy(prov._conn, misses=999)
        prov._conn = proxy  # type: ignore[assignment]

        with pytest.raises(StateConflictError):
            await prov.tick("c1", DEFAULT_DECAY)
    finally:
        prov._conn = proxy._conn  # type: ignore[assignment]
        prov.close()
