"""Wire CronRunner into Geny's app.state.

Backend selection mirrors the task runtime:
    GENY_CRON_BACKEND=memory   (default)
    GENY_CRON_BACKEND=file
    GENY_CRON_STORE_PATH=...   (file backend path)
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict

from geny_executor.cron import (
    CronRunner,
    FileBackedCronJobStore,
    InMemoryCronJobStore,
)

logger = logging.getLogger(__name__)


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
    runner = CronRunner(store, task_runner, cycle_seconds=cycle)
    asyncio.get_event_loop().create_task(runner.start())
    return {"store": store, "runner": runner}


__all__ = ["install_cron_runtime"]
