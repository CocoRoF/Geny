# Cycle 20260421_3 — Log pipeline STAGE migration + event enrichment

**Date.** 2026-04-21
**Trigger.** User wants the log panel's "Graph" label replaced
with the correct **STAGE** terminology (matching the
geny-executor Environment/Stage model Geny migrated to), to show
STAGE step numbers where possible, and to surface previously
silent execution events so the log panel actually reflects what
the system did.

## Background — why "Graph" in the first place?

Geny's `session_logger` was designed around an older
LangGraph-based architecture and defined `LogLevel.GRAPH`
(`backend/service/logging/session_logger.py:46`) with helper
methods `log_graph_event`, `log_graph_node_enter`,
`log_graph_node_exit`, etc. The frontend's
`LogEntryCard.tsx:30` hard-codes `label: 'Graph'` for that level.

When Geny migrated to geny-executor's 16-stage Environment
pipeline, the translation point
(`backend/service/langgraph/agent_session.py:1001-1014`)
funnelled executor `stage.enter` / `stage.exit` events into
`log_graph_event(event_type="node_enter"/"node_exit",
node_name=<stage>)`. The UI inherited the "Graph" label and
`node_enter: yield` strings even though the executor thinks in
**stages** and knows their order (1–16).

## Bug / regression summary

1. **Terminology lag.** UI says "Graph" / "node_enter: yield" —
   inconsistent with the executor's STAGE model the user reads
   about in docs.
2. **Lost metadata.** Executor emits `iteration`, `stage.name`,
   and each `Stage` has `.order` (1–16) — Geny drops all of this
   before reaching the log panel. No step numbers appear.
3. **Missing events.** `stage.bypass` and `stage.error` are
   emitted by the executor but completely ignored by the Geny
   translation layer.
4. **Silent paths.** Auto-revival, inbox delivery/DLQ, and inbox
   drain operations all call `logger.info()` (stderr-only) and
   never emit `session_logger` entries — invisible in the UI.

## Scope

**In:**
- Rename `LogLevel.GRAPH` → `LogLevel.STAGE` (backend enum +
  call sites + frontend `LEVEL_CONFIG`).
- Add `stage_order` + `stage_display_name` + `iteration` to
  every stage log entry's metadata.
- Handle `stage.bypass`, `stage.error` events.
- Promote auto-revival / inbox-delivery / DLQ / drain events to
  `session_logger` entries so they appear in the panel.
- Frontend: update label, add per-event descriptions
  (`node_bypass`, `node_error`) to `getEntryDescription`.

**Out:**
- Executor upstream changes (adding `stage_order` to
  `PipelineEvent` directly). Possible follow-up cycle; for now
  Geny maintains its own stage-name→order map.
- Restructuring the DB schema. Legacy `GRAPH` rows coexist with
  new `STAGE` rows; frontend handles both.
- Full timeline redesign. `ExecutionTimeline.tsx` continues to
  render the same entries; only label changes.

## PR plan

| PR | Branch | Scope |
|---|---|---|
| PR-1 | `feat/loglevel-stage-rename` | `LogLevel.STAGE` enum + rename `log_graph_*` → `log_stage_*` with back-compat aliases; frontend `LEVEL_CONFIG` + `LogEntryCard` dual-handling GRAPH & STAGE |
| PR-2 | `feat/stage-metadata-and-gap-closure` | Add `stage_order` / `stage_display_name` / `iteration` metadata; handle `stage.bypass` / `stage.error`; promote silent paths (auto-revival, inbox, drain) to session_logger |
| PR-3 | `docs/cycle-20260421_3-stage-logging` | Analysis + plan + progress |

Merge order: PR-1 → PR-2 → PR-3. PR-2 depends on helper
methods introduced in PR-1.

## Documents

- [analysis/01_graph_to_stage_inventory.md](analysis/01_graph_to_stage_inventory.md) — full emit / translate / consume map + gap list
- [plan/01_loglevel_stage_rename.md](plan/01_loglevel_stage_rename.md) — PR-1 design
- [plan/02_stage_metadata_and_gaps.md](plan/02_stage_metadata_and_gaps.md) — PR-2 design
- progress/01_prs_opened.md — after PRs open

## Relation to other cycles

- **20260421_2 (sanitizer).** Independent. Plan docs written,
  awaiting green-light. Touches `chat_controller.py` / `agent_
  executor.py` at different call sites (display sinks vs
  logging sinks); no merge conflicts expected.
- **20260420_8 + 20260421_1.** Prior cycles fixed STM role
  classification + DM continuity. Those logs already flow
  through `session_logger` with INFO/STAGE levels — this cycle
  strengthens rather than changes that.
