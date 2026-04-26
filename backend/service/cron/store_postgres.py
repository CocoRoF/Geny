"""PostgresCronJobStore — multi-host shared cron registry (PR-D.1.2).

Implements ``geny_executor.cron.CronJobStore`` against Geny's psycopg3
DatabaseManager. Same shape as PostgresTaskRegistryStore (sync DB
calls wrapped in asyncio.to_thread).

Use this when:

- multiple backend instances need a shared cron view (a single
  daemon should run, but a leader-election pattern out of scope here)
- operators want to query cron history with SQL (last_fired_at,
  last_task_id audit trail)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from geny_executor.cron.store_abc import CronJobStore
from geny_executor.cron.types import CronJob, CronJobStatus

logger = logging.getLogger(__name__)


_TABLE = "cron_jobs"


def _row_to_job(row: Dict[str, Any]) -> CronJob:
    payload_raw = row.get("payload") or ""
    try:
        payload = json.loads(payload_raw) if payload_raw else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    return CronJob(
        name=row["name"],
        cron_expr=row.get("cron_expr") or "",
        target_kind=row.get("target_kind") or "",
        payload=payload,
        description=row.get("description") or None,
        status=CronJobStatus(row.get("status") or CronJobStatus.ENABLED.value),
        created_at=_parse_dt(row.get("created_at")),
        last_fired_at=_parse_dt(row.get("last_fired_at")),
        last_task_id=row.get("last_task_id") or None,
    )


def _parse_dt(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


class PostgresCronJobStore(CronJobStore):
    """Postgres-backed CronJobStore.

    The runner stays single-process (no built-in leader election); this
    store is mostly useful for shared visibility + persistence across
    restarts. If two daemons race against the same row, the
    ``mark_fired`` upsert keeps last_fired_at consistent but doesn't
    prevent both from submitting the same task.
    """

    def __init__(self, db_manager: Any) -> None:
        self._db = self._unwrap(db_manager)

    @staticmethod
    def _unwrap(db_manager):
        if db_manager is None:
            return None
        if hasattr(db_manager, "db_manager"):
            return db_manager.db_manager
        return db_manager

    def _execute(self, query: str, params: tuple = ()):
        if self._db is None:
            raise RuntimeError("PostgresCronJobStore: db_manager not bound")
        return self._db.execute_query(query, params)

    def _execute_one(self, query: str, params: tuple = ()):
        if self._db is None:
            raise RuntimeError("PostgresCronJobStore: db_manager not bound")
        return self._db.execute_query_one(query, params)

    def _execute_modify(self, query: str, params: tuple = ()) -> Optional[int]:
        if self._db is None:
            raise RuntimeError("PostgresCronJobStore: db_manager not bound")
        return self._db.execute_update_delete(query, params)

    # ── CronJobStore protocol ────────────────────────────────────────

    async def put(self, job: CronJob) -> None:
        payload_blob = json.dumps(job.payload or {}, ensure_ascii=False, default=str)
        await asyncio.to_thread(
            self._execute_modify,
            f"""
            INSERT INTO {_TABLE}
                (name, cron_expr, target_kind, payload, description,
                 status, last_fired_at, last_task_id, extra_data,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (name) DO UPDATE SET
                cron_expr = EXCLUDED.cron_expr,
                target_kind = EXCLUDED.target_kind,
                payload = EXCLUDED.payload,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            (
                job.name,
                job.cron_expr,
                job.target_kind,
                payload_blob,
                job.description or "",
                job.status.value,
                job.last_fired_at.isoformat() if job.last_fired_at else "",
                job.last_task_id or "",
                "",
            ),
        )

    async def get(self, name: str) -> Optional[CronJob]:
        row = await asyncio.to_thread(
            self._execute_one,
            f"SELECT * FROM {_TABLE} WHERE name = %s LIMIT 1",
            (name,),
        )
        return _row_to_job(row) if row else None

    async def list(self, *, only_enabled: bool = False) -> List[CronJob]:
        if only_enabled:
            query = f"SELECT * FROM {_TABLE} WHERE status = %s ORDER BY name"
            params: tuple = (CronJobStatus.ENABLED.value,)
        else:
            query = f"SELECT * FROM {_TABLE} ORDER BY name"
            params = ()
        rows = await asyncio.to_thread(self._execute, query, params)
        return [_row_to_job(r) for r in (rows or [])]

    async def delete(self, name: str) -> bool:
        affected = await asyncio.to_thread(
            self._execute_modify,
            f"DELETE FROM {_TABLE} WHERE name = %s",
            (name,),
        )
        return bool(affected and affected > 0)

    async def mark_fired(
        self,
        name: str,
        when: datetime,
        task_id: Optional[str] = None,
    ) -> Optional[CronJob]:
        existing = await self.get(name)
        if existing is None:
            return None
        existing.last_fired_at = when
        existing.last_task_id = task_id
        await asyncio.to_thread(
            self._execute_modify,
            f"""
            UPDATE {_TABLE}
            SET last_fired_at = %s,
                last_task_id = %s,
                updated_at = NOW()
            WHERE name = %s
            """,
            (
                when.isoformat() if when else "",
                task_id or "",
                name,
            ),
        )
        return existing

    async def update_status(
        self,
        name: str,
        status: CronJobStatus,
    ) -> Optional[CronJob]:
        existing = await self.get(name)
        if existing is None:
            return None
        existing.status = status
        await asyncio.to_thread(
            self._execute_modify,
            f"""
            UPDATE {_TABLE}
            SET status = %s, updated_at = NOW()
            WHERE name = %s
            """,
            (status.value, name),
        )
        return existing


__all__ = ["PostgresCronJobStore"]
