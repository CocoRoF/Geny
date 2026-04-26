"""PostgresCronJobStore tests (PR-D.1.2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

pytest.importorskip("geny_executor")

from geny_executor.cron.types import CronJob, CronJobStatus  # noqa: E402

from service.cron.store_postgres import PostgresCronJobStore  # noqa: E402


class _FakeDB:
    """Minimal fake matching PostgresCronJobStore's SQL surface."""

    def __init__(self):
        self.rows: Dict[str, Dict[str, Any]] = {}

    def execute_query(self, query: str, params: tuple = ()):
        if "FROM cron_jobs" not in query:
            return []
        rows = list(self.rows.values())
        if "WHERE status = %s" in query:
            rows = [r for r in rows if r.get("status") == params[0]]
        rows.sort(key=lambda r: r.get("name") or "")
        return rows

    def execute_query_one(self, query: str, params: tuple = ()):
        if "FROM cron_jobs" in query and "WHERE name = %s" in query:
            return self.rows.get(params[0])
        return None

    def execute_update_delete(self, query: str, params: tuple = ()):
        if "INSERT INTO cron_jobs" in query:
            (name, cron_expr, target_kind, payload, description,
             status, last_fired, last_task_id, _extra) = params
            self.rows[name] = {
                "name": name, "cron_expr": cron_expr,
                "target_kind": target_kind, "payload": payload,
                "description": description, "status": status,
                "last_fired_at": last_fired, "last_task_id": last_task_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            return 1
        if "UPDATE cron_jobs" in query:
            name = params[-1]
            if name not in self.rows:
                return 0
            if "last_fired_at" in query:
                self.rows[name].update({
                    "last_fired_at": params[0], "last_task_id": params[1],
                })
            elif "status = %s" in query:
                self.rows[name]["status"] = params[0]
            return 1
        if "DELETE FROM cron_jobs" in query:
            name = params[0]
            return 1 if self.rows.pop(name, None) is not None else 0
        return 0


@pytest.fixture
def store() -> PostgresCronJobStore:
    return PostgresCronJobStore(_FakeDB())


# ── Round-trip ───────────────────────────────────────────────────────


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_put_then_get(self, store):
        job = CronJob(
            name="nightly", cron_expr="0 3 * * *",
            target_kind="local_bash", payload={"cmd": "echo hi"},
        )
        await store.put(job)
        got = await store.get("nightly")
        assert got is not None
        assert got.name == "nightly"
        assert got.cron_expr == "0 3 * * *"
        assert got.payload == {"cmd": "echo hi"}

    @pytest.mark.asyncio
    async def test_put_overwrites(self, store):
        await store.put(CronJob(name="x", cron_expr="* * * * *", target_kind="bash"))
        await store.put(CronJob(name="x", cron_expr="0 9 * * *", target_kind="bash"))
        got = await store.get("x")
        assert got.cron_expr == "0 9 * * *"

    @pytest.mark.asyncio
    async def test_get_unknown_returns_none(self, store):
        assert await store.get("ghost") is None

    @pytest.mark.asyncio
    async def test_delete_removes(self, store):
        await store.put(CronJob(name="x", cron_expr="* * * * *", target_kind="b"))
        assert await store.delete("x") is True
        assert await store.get("x") is None

    @pytest.mark.asyncio
    async def test_delete_unknown_returns_false(self, store):
        assert await store.delete("ghost") is False


# ── List + filtering ─────────────────────────────────────────────────


class TestList:
    @pytest.mark.asyncio
    async def test_list_all_sorted_by_name(self, store):
        await store.put(CronJob(name="b", cron_expr="* * * * *", target_kind="x"))
        await store.put(CronJob(name="a", cron_expr="* * * * *", target_kind="x"))
        out = await store.list()
        assert [j.name for j in out] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_only_enabled_filter(self, store):
        await store.put(CronJob(
            name="on", cron_expr="* * * * *", target_kind="x",
            status=CronJobStatus.ENABLED,
        ))
        await store.put(CronJob(
            name="off", cron_expr="* * * * *", target_kind="x",
            status=CronJobStatus.DISABLED,
        ))
        out = await store.list(only_enabled=True)
        assert [j.name for j in out] == ["on"]


# ── mark_fired / update_status ───────────────────────────────────────


class TestMutations:
    @pytest.mark.asyncio
    async def test_mark_fired(self, store):
        await store.put(CronJob(name="x", cron_expr="* * * * *", target_kind="b"))
        when = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
        out = await store.mark_fired("x", when, task_id="t-1")
        assert out is not None
        assert out.last_task_id == "t-1"
        # Verify persisted (re-fetch from store).
        got = await store.get("x")
        assert got.last_fired_at == when

    @pytest.mark.asyncio
    async def test_mark_fired_unknown_returns_none(self, store):
        assert await store.mark_fired("ghost", datetime.now(timezone.utc)) is None

    @pytest.mark.asyncio
    async def test_update_status_disable(self, store):
        await store.put(CronJob(name="x", cron_expr="* * * * *", target_kind="b"))
        out = await store.update_status("x", CronJobStatus.DISABLED)
        assert out.status == CronJobStatus.DISABLED

    @pytest.mark.asyncio
    async def test_update_status_unknown_returns_none(self, store):
        assert await store.update_status("ghost", CronJobStatus.DISABLED) is None


# ── ABC / unwrap ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_db_manager_raises_on_use():
    s = PostgresCronJobStore(None)
    with pytest.raises(RuntimeError):
        await s.put(CronJob(name="x", cron_expr="*", target_kind="b"))


def test_unwrap_inner_db_manager():
    class Outer:
        def __init__(self):
            self.db_manager = _FakeDB()
    s = PostgresCronJobStore(Outer())
    assert s._db is not None
