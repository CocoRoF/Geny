# B.1 — Session-param enforcement (max_iterations bridge)

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/executor/agent_session.py` — `_apply_session_limits_to_pipeline` helper + call site at end of `_build_pipeline`; updated docstrings on `max_turns` / `timeout` properties to record actual enforcement layer.
- `backend/tests/service/executor/test_session_param_enforcement.py` (new) — 7 cases.

## What it changes

`_apply_session_limits_to_pipeline` mutates the bound Pipeline's `_config.max_iterations` to the session-supplied value. Called once at the tail of `_build_pipeline` (right after `attach_runtime`), so every subsequent `pipeline.run_stream` call inherits the override via `Pipeline._init_state` → `PipelineConfig.apply_to_state` → `state.max_iterations`.

Without this hook:
- UI sets `max_iterations=3`.
- Backend stores it in `AgentSession._max_iterations`.
- Pipeline's `_config.max_iterations` keeps the manifest default (typically 50).
- Executor enforces 50 — UI control is cosmetic.

With this hook the executor's iteration guards (`s04_guard.IterationGuard`, `s16_loop.LoopController`) see the user's cap.

## What it does NOT change

- `timeout` — already enforced at the chat-execution layer via `asyncio.wait_for(agent.invoke(...), timeout=...)` in `service/execution/agent_executor.py:_execute_core`. Property docstring updated to record this.
- `max_turns` — with env-driven pipelines, "turn" reduces to "one chat message", which is governed by the chat layer not the executor pipeline. Field is currently advisory only. Property docstring updated; no behavior change.

## Tests

`test_session_param_enforcement.py` (7 cases):
- `test_max_iterations_overrides_pipeline_default` — happy path: 50 → 3.
- `test_no_pipeline_is_silent_noop` — pre-init sessions don't raise.
- `test_pipeline_without_config_is_silent_noop` — older executor builds tolerated.
- `test_zero_max_iterations_leaves_manifest_default` — falsy session value defers to manifest.
- `test_negative_max_iterations_is_rejected` — bogus negative values defer to manifest.
- `test_invalid_max_iterations_is_logged_and_ignored` — non-numeric value logs warning + leaves manifest default.
- `test_idempotent_when_value_unchanged` — re-applying same value emits no log.
- `test_change_logged_when_value_overridden` — single info line on transition.

Local: skipped (pytest.importorskip("pydantic") since the bare test venv lacks pydantic). CI installs the full backend requirements and runs all 8 cases.

## Caller-side behavior

`_build_pipeline` now calls `self._apply_session_limits_to_pipeline()` after `attach_runtime`. This is a one-line call site; correctness is covered by the helper unit tests. Existing manager-level tests (e.g. `test_agent_session_manager_state.py`) exercise the call path implicitly.

## Follow-ups identified during sprint

- `max_turns` field can probably be removed from the UI given it has no enforcement path. Defer to a separate UX-cleanup PR (out of cycle scope).
- Adaptive evaluator (s14) may DROP `state.max_iterations` further when classified as easy/not-easy. User's value is treated as the cap, not the floor — correct semantics, but worth documenting in the UI tooltip for `max_iterations`. Defer to C.3.
