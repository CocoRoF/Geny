# Progress 02 — executor v0.23.0: per-call tool events

| Field | Value |
|-------|-------|
| Plan ref | `plan/01_immediate_fixes.md` → **PR II** |
| Master ref | `plan/00_overview.md` → **Phase 1 / PR #3** |
| Repo | `geny-executor` (sibling, not this one) |
| PR | [CocoRoF/geny-executor#29](https://github.com/CocoRoF/geny-executor/pull/29) |
| Branch | `feat/tool-call-events` (squashed + deleted) |
| Merge commit | `456d686` on `geny-executor/main` |
| Tag | `v0.23.0` |
| Release | [v0.23.0 — per-call tool events](https://github.com/CocoRoF/geny-executor/releases/tag/v0.23.0) |
| Status | **Merged, tagged, released** |

---

## What shipped

One additive release to the **executor** repo. No Geny code change
in this PR (that's PR #5 in the master sequence).

### Event vocabulary extension

Two new events on the Stage 10 (`ToolStage`) event stream, emitted
by the default `SequentialExecutor` and `ParallelExecutor`:

| Event | Fires at | Payload |
|-------|---------|---------|
| `tool.call_start` | before each individual dispatch | `{tool_use_id, name, input}` |
| `tool.call_complete` | after each individual dispatch | `{tool_use_id, name, is_error, duration_ms}` |

Pairing between `call_start` and `call_complete` is by
`tool_use_id` (Anthropic-provided, stable per call). This is
important for the parallel executor where event ordering across
calls is not guaranteed.

### API surface changes (all additive)

- `ToolExecutor.execute_all(...)` gains a keyword-only
  `on_event: Optional[ToolEventCallback]` parameter. Default
  `None` matches 0.22.1 semantics exactly — no events, identical
  behavior.
- `ToolEventCallback` type alias exported from
  `geny_executor.stages.s10_tool.interface`.
- `ToolStage.execute` wires `on_event=state.add_event` so the new
  events flow through the existing `state._event_listener` path
  without any extra host-side wiring.

### What is explicitly *not* in the payload

- **No full output.** `tool.call_complete` carries `is_error` and
  `duration_ms` only. Full tool results stay on the message bus
  (`state.tool_results`) — the event stream should not transport
  unbounded-size payloads. Host logging reads content from the
  `tool_result` message when it needs the full body.
- **No tracing IDs / spans.** `tool_use_id` + `duration_ms` is
  the minimum for rendering a per-call detail pane. A proper
  tracing layer is a separate concern.

## Verification done

### Test suite

`tests/unit/test_tool_call_events.py` (new, 6 tests):

| Test | Assertion |
|------|-----------|
| `test_sequential_emits_start_and_complete_per_call` | Events fire in correct order per call; payload shape is `{tool_use_id, name, input}` / `{tool_use_id, name, is_error, duration_ms}`; `duration_ms` is a non-negative int |
| `test_sequential_reports_is_error_true_for_failing_tool` | Router returning `ToolResult(is_error=True)` → `call_complete.is_error == True` |
| `test_sequential_on_event_is_optional` | Omitting `on_event` runs without error; matches pre-0.23.0 behavior |
| `test_parallel_emits_paired_events_per_call` | All 3 pairs fire; `tool_use_id` values match start-set to complete-set; inter-pair ordering not asserted |
| `test_parallel_on_event_is_optional` | Parallel path also honors `on_event=None` |
| `test_stage_wraps_call_events_inside_execute_events` | `tool.execute_start` is first event, `tool.execute_complete` is last, per-call events nest strictly between them — the existing outer bracket contract is preserved |

### Full suite + lint

```
pytest tests/                     → 1015 passed, 18 skipped
ruff check src/ tests/            → All checks passed
ruff format --check src/ tests/   → 313 files already formatted
```

The 18 skips are all pre-existing (missing optional `yaml`, Phase 3
gates awaiting separate work) — same count of relevant skips as
0.22.1, with 12 additional tests now passing (6 new + the existing
6 that validate 0.22.x behavior is unchanged).

### Backwards compatibility check

- `SequentialExecutor()` and `ParallelExecutor()` can still be
  called with the 3-positional form `(tool_calls, router, context)`
  — tests in `test_phase2_agent_loop.py` and others exercise this
  and all pass.
- `ToolStage(registry=...)` constructor unchanged.
- Consumers that listen only to `tool.execute_start` /
  `tool.execute_complete` see identical events; no payload or
  ordering change to those.

## Release artifacts

- **Tag**: `v0.23.0` pushed to `CocoRoF/geny-executor`.
- **GitHub release**: published with CHANGELOG-matched notes at
  <https://github.com/CocoRoF/geny-executor/releases/tag/v0.23.0>.
- **PyPI publish**: triggered by the `release: published` event;
  workflow `publish.yml` handles sdist + wheel build, `twine check`,
  and PyPI upload.

## What Geny needs next

PR #5 in the master sequence bumps the Geny pin and swaps the
log-handler branch:

```python
# backend/service/langgraph/agent_session.py (before)
elif event_type == "tool.execute_start":
    session_logger.log_tool_use(
        tool_name=...,
        tool_input=str(event_data["count"]),  # ← bug
    )

# (after)
if event_type == "tool.call_start":
    session_logger.log_tool_use(
        tool_name=event_data.get("name", "unknown"),
        tool_input=event_data.get("input") or {},
    )
elif event_type == "tool.execute_start":
    # summary line only — no log_tool_use call anymore
    session_logger.log(level=LogLevel.INFO, message=...)
```

Pin change: `backend/pyproject.toml` and `backend/requirements.txt`
move from `geny-executor>=0.22.1,<0.23.0` to
`geny-executor>=0.23.0,<0.24.0`.

## Risk

Low. The executor release is strictly additive. Existing Geny code
(which only consumes `tool.execute_*`) will run unchanged against
0.23.0 — it simply won't benefit from the new per-call rendering
until PR #5 lands. This means PR #5 can ship at any time after
PyPI has the 0.23.0 artifact; there is no forced coupling to a
specific merge order beyond that dependency.

## Next PR in sequence

**P1-PR4** — this progress doc itself, as its own documentation PR.
Then:

- P1-PR5: Geny pin `>=0.23.0,<0.24.0` + `tool.call_start` consumer
  swap + per-call error logging.
- P1-PR6: progress doc for PR5 (closes Phase 1).

Phase 1 exits when the user can run a VTuber session without
`env_id` and see both (a) `news_search` actually executing
(PR #1) and (b) the per-call input rendered correctly in the log
UI (PRs #3 + #5).
