# Progress 01 — Cycle 20260421_3 PRs landed

**Date.** 2026-04-21

All three planned PRs for this cycle are merged to `main`. The log
panel now speaks the executor's Stage terminology, stage events
carry order + display-name + iteration metadata, previously-dropped
executor events (`stage.bypass`, `stage.error`, `pipeline.start`,
`pipeline.error`) are surfaced, and the busiest execution-side
silent paths (auto-revival, busy-inbox delivery, DLQ fallbacks,
inbox drain) are now visible in the log panel.

## PR board

| PR | Title | Status | Notes |
|---|---|---|---|
| [#203](https://github.com/CocoRoF/Geny/pull/203) | `feat(logging): rename LogLevel.GRAPH → LogLevel.STAGE` | merged | Backend enum + `log_stage_*` helpers + legacy `log_graph_*` wrappers + frontend dual-handling. `STAGE_ORDER` guardrail pins the local stage-name table to `geny_executor.core.pipeline.Pipeline._DEFAULT_STAGE_NAMES`. |
| [#204](https://github.com/CocoRoF/Geny/pull/204) | `feat(logging): surface stage metadata + bypass/error + silent paths` | merged | `stage.bypass` / `stage.error` / `pipeline.start` / `pipeline.error` translation in `_invoke_pipeline` + `_astream_pipeline`. Auto-revival / busy-inbox delivery / DLQ fallback / drain lifecycle promoted to session_logger entries. Two new test modules pin the coverage. |
| [#205](https://github.com/CocoRoF/Geny/pull/205) | `docs(cycle-20260421_3): analysis + plan + progress for stage logging` | this PR | Cycle documents. |

Merge order followed the plan (PR-1 → PR-2 → PR-3). PR-2 depends on
the `log_stage_*` helpers introduced in PR-1; opening them
sequentially against `main` (instead of stacking) avoided the
branch-deletion cascade that closed PR-200 during cycle 20260421_2.

## Behaviour changes observed

- Log panel rows previously labeled "Graph" now render as "Stage",
  with the stage display name (`s16_yield` etc.) and iteration
  suffix visible.
- Skipped executor slots no longer vanish — they show up as
  `⊘ s05_cache (skipped)` rows. Equally, stage failures surface as
  `✗ s10_tool: <error>` instead of being silently converted to
  pipeline errors downstream.
- `pipeline.start` now opens each turn with an explicit
  `execution_start` entry; before, only the complete/error events
  were ever logged.
- Auto-revived sessions emit a visible `auto_revival` entry, so a
  user confused by "why did the agent suddenly come back" can see
  the event in the panel.
- Inbox delivery to a busy VTuber writes `inbox.delivered` on the
  sender side (with `inbox.fallback_dlq` / `inbox.dlq_failed` for
  the two error paths). Drain lifecycle (`drain.start` /
  `drain.item_ok` / `drain.item_failed` / `drain.complete`)
  appears on the receiver side. Empty queues stay silent to avoid
  panel noise.

## Test coverage added

- `backend/tests/service/logging/test_stage_logging.py` (11 tests):
  enum shape, `STAGE_ORDER` monotonicity + executor-guardrail,
  `stage_display_name` format, every `log_stage_*` helper,
  graceful unknown-stage handling, legacy `log_graph_*` wrapper
  parity.
- `backend/tests/service/logging/test_stage_event_coverage.py`
  (6 tests): bypass/error/pipeline.start/pipeline.error translate,
  invoke + astream parity.
- `backend/tests/service/execution/test_execution_logging_gaps.py`
  (4 tests): auto-revival entry, busy-inbox sender-side entry,
  drain lifecycle entries, empty-drain silence.

## Follow-ups (out of scope for this cycle)

- Consider upstreaming `stage_order` to `PipelineEvent` itself so
  the local `STAGE_ORDER` mirror can be retired. Blocked on a
  geny-executor API addition; noted in plan/01 § 7.
- Frontend toggle to collapse `stage_bypass` rows — slot-empty
  bypasses can reach 6–8 per session and may clutter the panel.
  Deferred until real usage data shows it's actually noisy.
- Legacy `log_graph_error` call site in `_astream_pipeline` still
  writes at STAGE level via the deprecated wrapper. Not worth a
  cycle on its own; will be folded into any future logging
  cleanup.
