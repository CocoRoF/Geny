"""
Curation Scheduler — Background service for periodic automatic curation.

Checks the LTMConfig schedule settings and runs the curation pipeline
on uncurated User Opsidian notes when the schedule fires.

Follows the same pattern as ``thinking_trigger.py``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from logging import getLogger
from typing import Optional

logger = getLogger(__name__)

# Check interval: how often the loop wakes up to evaluate the schedule
_CHECK_INTERVAL_SECONDS = 300  # 5 minutes


class CurationScheduler:
    """Background async loop that periodically curates User Opsidian notes."""

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Curation scheduler started")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Curation scheduler stopped")

    # ── Main loop ─────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_and_run()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Curation scheduler error: {e}", exc_info=True)
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)

    async def _check_and_run(self) -> None:
        """Evaluate whether scheduled curation should fire, and run if so."""
        from service.config import get_config_manager
        from service.config.sub_config.general.ltm_config import LTMConfig

        mgr = get_config_manager()
        cfg = mgr.load_config(LTMConfig)
        if cfg is None:
            return

        # Both master toggle and schedule toggle must be on
        if not cfg.auto_curation_enabled or not cfg.auto_curation_schedule_enabled:
            return

        now = datetime.now(timezone.utc)

        # Check if enough time has elapsed since last run
        if cfg.auto_curation_last_run:
            try:
                last = datetime.fromisoformat(cfg.auto_curation_last_run)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last) < timedelta(hours=cfg.auto_curation_interval_hours):
                    return
            except ValueError:
                pass  # Invalid timestamp — proceed with curation

        logger.info("Scheduled curation triggered — starting batch curation")
        await self._run_batch(cfg)

        # Persist last_run timestamp
        try:
            mgr.update_config("ltm", {
                "auto_curation_last_run": now.isoformat(),
            })
            logger.info(f"Curation scheduler: updated last_run to {now.isoformat()}")
        except Exception as e:
            logger.error(f"Failed to update last_run: {e}")

    async def _run_batch(self, cfg) -> None:
        """Run batch curation across all users' uncurated notes."""
        try:
            from service.memory.user_opsidian import get_user_opsidian_manager
            from service.memory.curated_knowledge import get_curated_knowledge_manager
            from service.memory.curation_engine import CurationEngine

            # Use the auth fallback username (single-user deployment)
            username = "anonymous"

            opsidian_mgr = get_user_opsidian_manager(username)
            curated_mgr = get_curated_knowledge_manager(username)

            # Get all User Opsidian files
            opsidian_index = opsidian_mgr.get_index()
            if not opsidian_index or not opsidian_index.get("files"):
                logger.info("Curation scheduler: no user opsidian notes to curate")
                return

            all_files = list(opsidian_index["files"].keys())

            # Cap at max_notes_per_run
            files_to_curate = all_files[:cfg.auto_curation_max_notes_per_run]

            # Get LLM model if configured
            llm_model = None
            if cfg.auto_curation_use_llm:
                try:
                    from service.workflow.nodes.memory.memory_reflect_node import _get_memory_model
                    llm_model = _get_memory_model()
                except Exception:
                    pass

            engine = CurationEngine(
                curated_manager=curated_mgr,
                user_opsidian_manager=opsidian_mgr,
                llm_model=llm_model,
            )

            results = await engine.curate_batch(files_to_curate, use_llm=cfg.auto_curation_use_llm)

            success_count = sum(1 for r in results if r.success)
            logger.info(
                f"Curation scheduler: completed batch — "
                f"{success_count}/{len(results)} notes curated successfully"
            )

        except Exception as e:
            logger.error(f"Curation scheduler batch failed: {e}", exc_info=True)


# ── Singleton access ──────────────────────────────────────────────

_instance: Optional[CurationScheduler] = None


def get_curation_scheduler() -> CurationScheduler:
    global _instance
    if _instance is None:
        _instance = CurationScheduler()
    return _instance
