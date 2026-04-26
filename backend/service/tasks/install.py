"""Wire BackgroundTaskRunner into Geny's app.state.

Backend selection is env-driven so operators can switch without
code changes:

    GENY_TASK_BACKEND=memory   (default — process-lifetime)
    GENY_TASK_BACKEND=file     (durable single-process)
    GENY_TASK_STORE_PATH=...   (file backend root)

The runner ships with two executors out of the box:
    - local_bash  — shell command via subprocess
    - local_agent — sub-agent via SubagentTypeOrchestrator
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

from geny_executor.runtime import (
    BackgroundTaskRunner,
    LocalAgentExecutor,
    LocalBashExecutor,
)
from geny_executor.stages.s13_task_registry import (
    FileBackedRegistry,
    InMemoryRegistry,
)

logger = logging.getLogger(__name__)


def _build_registry():
    backend = os.getenv("GENY_TASK_BACKEND", "memory").lower()
    if backend == "file":
        path = os.getenv(
            "GENY_TASK_STORE_PATH",
            str(Path.home() / ".geny" / "tasks"),
        )
        Path(path).mkdir(parents=True, exist_ok=True)
        logger.info("task_backend=file path=%s", path)
        return FileBackedRegistry(Path(path))
    logger.info("task_backend=memory")
    return InMemoryRegistry()


def _orchestrator_factory(app_state):
    """Returns the active SubagentTypeOrchestrator, or None.

    Looked up lazily so a host that hasn't wired stage 12 yet still
    starts cleanly — LocalAgentExecutor will reject submissions at
    execute() time with a clear error message.
    """
    def _factory():
        return getattr(app_state, "subagent_orchestrator", None)
    return _factory


def install_task_runtime(app_state) -> Dict[str, Any]:
    registry = _build_registry()
    runner = BackgroundTaskRunner(
        registry,
        executors={
            "local_bash": LocalBashExecutor(),
            "local_agent": LocalAgentExecutor(_orchestrator_factory(app_state)),
        },
        max_concurrent=int(os.getenv("GENY_TASK_MAX_CONCURRENT", "8")),
    )
    # start() is sync-safe to call from a sync context; lifespan
    # will see the runner ready by the time it yields.
    import asyncio
    asyncio.get_event_loop().create_task(runner.start())
    return {"registry": registry, "runner": runner}


__all__ = ["install_task_runtime"]
