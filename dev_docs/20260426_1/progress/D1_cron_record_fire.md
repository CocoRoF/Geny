# D.1 — Cron record_fire wired

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/cron/install.py` — new `_RecordingCronRunner(CronRunner)` subclass + swap in for the bare CronRunner.
- `backend/tests/service/cron/test_recording_runner.py` (new) — 3 cases.

## What it changes

The executor's `CronRunner` (geny-executor 1.3.0) doesn't expose an audit-callback hook — `service/telemetry/cron_history.py`'s docstring assumed one existed. As a result every scheduled fire flowed through `_submit` → `task_runner.submit` without being recorded into the Geny-side history ring. Only adhoc fires (via `cron_controller.run_now`) got recorded.

This PR introduces `_RecordingCronRunner` which overrides `_submit`. After delegating to the base implementation, it calls `record_fire(job.name, task_id=…, status=…)`. Failures inside the recording call are swallowed (telemetry must not break the cron loop).

`install_cron_runtime` now instantiates `_RecordingCronRunner` instead of `CronRunner`.

## Why

Audit (cycle 20260426_1, analysis/02 §C.1) — admin "recent fires" panel was always empty for scheduled jobs. The Integration Health card from C.2 also surfaced this as an amber-ringed pill before this fix landed.

## Tests

3 cases in `test_recording_runner.py`:
- `test_record_fire_called_on_successful_submit` — happy path, status="fired", task_id stored.
- `test_record_fire_records_submit_failure` — base CronRunner returns None on submit failure; recorder logs status="submit_failed" with task_id=None.
- `test_telemetry_failure_does_not_break_cron` — patches record_fire to raise; runner._submit still returns the upstream task_id.

Local: skipped (importorskip on geny_executor + croniter — neither in the bare test venv). CI runs them.

## Out of scope

- Backporting fires from before this lands (in-memory ring; nothing to backport).
- Persisting fires to disk (file/Postgres backend) — current ring is process-wide in-memory; deliberate per cron_history.py docstring.
