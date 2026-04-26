"""D.1 (cycle 20260426_1) — _RecordingCronRunner tests.

Verifies that ``_RecordingCronRunner._submit`` records every scheduled
fire into ``service.telemetry.cron_history``. The base ``CronRunner``
fires by calling ``_submit`` from inside its loop; intercepting that
method is the simplest non-invasive hook.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

# The runner imports geny_executor.cron.types — skip when executor isn't
# importable (bare test venv). CI installs everything.
pytest.importorskip("geny_executor")
pytest.importorskip("croniter")

from service.cron.install import _RecordingCronRunner  # noqa: E402
from service.telemetry import cron_history  # noqa: E402

from geny_executor.cron import InMemoryCronJobStore  # noqa: E402
from geny_executor.cron.types import CronJob  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_history():
    cron_history.clear()
    yield
    cron_history.clear()


def _job(name: str = "j1") -> CronJob:
    return CronJob(
        name=name,
        cron_expr="* * * * *",
        target_kind="noop",
        payload={},
    )


@pytest.mark.asyncio
async def test_record_fire_called_on_successful_submit() -> None:
    """A scheduled fire that submits successfully must produce a
    ``status='fired'`` entry with the returned task_id."""
    store = InMemoryCronJobStore()
    task_runner = AsyncMock()
    task_runner.submit = AsyncMock(return_value="task-abc")

    runner = _RecordingCronRunner(store, task_runner, cycle_seconds=1)

    job = _job("scheduled-test")
    fire_time = datetime.now(timezone.utc)
    task_id = await runner._submit(job, fire_time)

    assert task_id == "task-abc"
    rows = cron_history.history("scheduled-test", limit=10)
    assert len(rows) == 1
    assert rows[0]["task_id"] == "task-abc"
    assert rows[0]["status"] == "fired"


@pytest.mark.asyncio
async def test_record_fire_records_submit_failure() -> None:
    """When the executor returns ``None`` (submit_failed branch), we
    still record the attempt with ``status='submit_failed'`` so the
    operator can see attempted-but-failed fires."""
    store = InMemoryCronJobStore()
    task_runner = AsyncMock()
    task_runner.submit = AsyncMock(side_effect=RuntimeError("boom"))

    runner = _RecordingCronRunner(store, task_runner, cycle_seconds=1)

    job = _job("failing-test")
    fire_time = datetime.now(timezone.utc)
    task_id = await runner._submit(job, fire_time)

    # Base CronRunner._submit catches the exception and returns None.
    assert task_id is None
    rows = cron_history.history("failing-test", limit=10)
    assert len(rows) == 1
    assert rows[0]["task_id"] is None
    assert rows[0]["status"] == "submit_failed"


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_break_cron() -> None:
    """A bug in record_fire must not crash the cron loop — the runner's
    overridden _submit swallows telemetry exceptions."""
    store = InMemoryCronJobStore()
    task_runner = AsyncMock()
    task_runner.submit = AsyncMock(return_value="task-xyz")

    runner = _RecordingCronRunner(store, task_runner, cycle_seconds=1)

    # Patch record_fire to raise.
    import service.telemetry.cron_history as ch_mod

    real_record_fire = ch_mod.record_fire

    def boom(*_a, **_kw):
        raise RuntimeError("telemetry busted")

    ch_mod.record_fire = boom
    try:
        task_id = await runner._submit(_job("telemetry-bug"), datetime.now(timezone.utc))
    finally:
        ch_mod.record_fire = real_record_fire

    # Must still return the upstream task_id.
    assert task_id == "task-xyz"
