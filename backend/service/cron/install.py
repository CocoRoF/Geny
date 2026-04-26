"""Wire CronRunner into Geny's app.state.

Backend selection mirrors the task runtime:
    GENY_CRON_BACKEND=memory   (default)
    GENY_CRON_BACKEND=file
    GENY_CRON_STORE_PATH=...   (file backend path)

D.1 (cycle 20260426_1): the executor's :class:`CronRunner` doesn't
expose an audit-callback hook. We subclass and override ``_submit`` so
every scheduled fire is recorded into Geny's
``service.telemetry.cron_history`` ring buffer alongside the adhoc
fires the cron controller already records. Without this the AdminPanel
"recent fires" panel stays empty even when scheduled jobs run.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from geny_executor.cron import (
    CronRunner,
    FileBackedCronJobStore,
    InMemoryCronJobStore,
)
from geny_executor.cron.types import CronJob

logger = logging.getLogger(__name__)


class _RecordingCronRunner(CronRunner):
    """:class:`CronRunner` subclass that records every scheduled fire
    into ``service.telemetry.cron_history``.

    The executor base class fires by calling ``self._submit`` from
    inside ``_fire_due_jobs``; we override ``_submit`` so the recording
    happens regardless of whether submit succeeded (records
    ``status="submit_failed"`` when the executor returns ``None``).
    Any failure inside the recording call is swallowed — telemetry must
    never break the cron loop.
    """

    async def _submit(
        self,
        job: CronJob,
        fire_time: datetime,
    ) -> Optional[str]:
        task_id = await super()._submit(job, fire_time)
        try:
            from service.telemetry.cron_history import record_fire

            record_fire(
                job.name,
                task_id=task_id,
                status="fired" if task_id else "submit_failed",
                fired_at=fire_time,
            )
        except Exception:  # noqa: BLE001 — telemetry must not break cron
            logger.debug(
                "cron_record_fire_failed for job %s",
                job.name,
                exc_info=True,
            )
        return task_id


def _build_store(app_state=None):
    backend = os.getenv("GENY_CRON_BACKEND", "memory").lower()
    if backend == "postgres":
        # PR-D.1.2 — multi-host shared cron registry.
        db_manager = getattr(app_state, "app_db", None) if app_state else None
        if db_manager is None:
            logger.warning(
                "cron_backend=postgres requested but app_state.app_db not "
                "available; falling back to memory",
            )
            return InMemoryCronJobStore()
        try:
            from service.cron.store_postgres import PostgresCronJobStore
        except ImportError as exc:
            logger.warning(
                "cron_backend=postgres requested but store_postgres unavailable "
                "(%s); falling back to memory", exc,
            )
            return InMemoryCronJobStore()
        logger.info("cron_backend=postgres")
        return PostgresCronJobStore(db_manager)
    if backend == "file":
        path = Path(os.getenv(
            "GENY_CRON_STORE_PATH",
            str(Path.home() / ".geny" / "cron.json"),
        ))
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("cron_backend=file path=%s", path)
        return FileBackedCronJobStore(path)
    logger.info("cron_backend=memory")
    return InMemoryCronJobStore()


def install_cron_runtime(app_state) -> Dict[str, Any]:
    task_runner = getattr(app_state, "task_runner", None)
    if task_runner is None:
        raise RuntimeError("install_cron_runtime: task_runner must be wired first")
    store = _build_store(app_state)
    cycle = int(os.getenv("GENY_CRON_CYCLE_SECONDS", "60"))
    runner = _RecordingCronRunner(store, task_runner, cycle_seconds=cycle)
    asyncio.get_event_loop().create_task(runner.start())
    return {"store": store, "runner": runner}


__all__ = ["install_cron_runtime"]
