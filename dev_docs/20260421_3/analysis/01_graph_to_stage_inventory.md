# Analysis 01 — Graph→STAGE log pipeline inventory

## 1. Symptom (user report)

The Geny execution log panel surfaces entries like:

```
Graph   12:13:55   execution_complete
Graph   12:13:55   node_exit: yield
Graph   12:13:55   node_enter: yield
Graph   12:13:55   node_exit: memory
Graph   12:13:51   node_enter: memory
Graph   12:13:51   node_exit: loop
Graph   12:13:51   node_enter: loop
Graph   12:13:51   node_exit: evaluate
Graph   12:13:51   node_enter: evaluate
Graph   12:13:51   node_exit: tool
```

Three things the user wants changed:

1. **Label & terminology.** The label `Graph` and the prefix
   `node_enter/node_exit` are leftovers from the LangGraph era.
   The new Environment/Stage model in geny-executor describes
   the same events as `stage.enter`/`stage.exit` with a stage
   order. The UI should follow.
2. **Step numbers.** `yield` alone conveys nothing; `Stage 16:
   yield` immediately places it in the pipeline.
3. **Richer coverage.** Many real execution events (auto-
   revival, inbox delivery, DLQ fallback, drain replay) never
   reach this panel — they live only in the backend stderr
   `logger`. The log panel feels sparse because it's missing
   half the story.

## 2. Truth source — what geny-executor actually emits

From `geny-executor/src/geny_executor/core/pipeline.py` and
`events/types.py`:

- `PipelineEvent(type, stage, iteration, timestamp, data)` —
  one dataclass covers every event (`events/types.py:10-18`).
- 16 stages, ordered 1-16, named `input, context, system, guard,
  cache, api, token, think, parse, tool, agent, evaluate, loop,
  emit, memory, yield` (`pipeline.py:216-233` `_DEFAULT_STAGE_
  NAMES`).
- Each `Stage` has `.order: int` and
  `display_name = f"s{order:02d}_{name}"` (`stages/_core/
  stage.py:31, 107-108, 301-307` — e.g., `s16_yield`).
- Stage-lifecycle events emitted by `_run_stage`
  (`pipeline.py:880-906`):
  - `stage.enter` — fires as stage starts.
  - `stage.exit` — fires as stage finishes successfully.
  - `stage.bypass` — stage registered but skipped (or slot
    empty), fires via `_try_run_stage` (`pipeline.py:867-878`).
  - `stage.error` — stage raised; recovery may follow.
  - All four carry `stage=<name>` + `iteration=<int>` (and in
    `stage.error`, also `data={"error": str}`).
- Pipeline-lifecycle events: `pipeline.start`,
  `pipeline.complete` (with `iterations`), `pipeline.error`
  (`pipeline.py:667, 673, 677`).
- Tool events from stage s10: `tool.call_start`,
  `tool.call_complete`, `tool.execute_start`,
  `tool.execute_complete` (see
  `stages/s10_tool/artifact/default/`).
- Streaming text from stage s06: `text.delta`
  (`stages/s06_api/artifact/default/stage.py:300-308`).
- Loop signals from stage s13: `loop.escalate`, `loop.error`.

## 3. Translation layer — Geny's current map

`backend/service/langgraph/agent_session.py:959-1049`
(both `_invoke_pipeline` and `_astream_pipeline` carry an
identical `async for event in self._pipeline.run_stream(...)`
switch):

| Executor event | Geny translation | Missing metadata |
|---|---|---|
| `stage.enter` | `log_graph_event(event_type="node_enter", node_name=<stage>)` (L1001-1007) | `iteration`, `stage.order`, `stage.display_name` |
| `stage.exit` | `log_graph_event(event_type="node_exit", node_name=<stage>)` (L1008-1014) | same |
| `stage.bypass` | **NOT HANDLED** | entire event dropped |
| `stage.error` | **NOT HANDLED** (caught only by outer exception handler) | entire event dropped |
| `tool.call_start` | `log_tool_use` (L965-970) | — |
| `tool.call_complete` | `log(TOOL_RESULT)` only if error (L971-984) | success case unlogged |
| `tool.execute_start` | `log(INFO)` (L985-992) | — |
| `tool.execute_complete` | `log(TOOL_RESULT)` (L993-1000) | — |
| `loop.escalate` / `loop.error` | `log_graph_event(event_type="loop_signal", node_name="s13_loop")` (L1015-1021) | ← the only place where an `s{NN}_` display_name is emitted |
| `text.delta` | `log(STREAM_EVENT)` + accumulates output (L1024-1033) | — |
| `pipeline.complete` | captured as result (L1035+) | not logged as an event entry |
| `pipeline.start` | **NOT OBSERVED** | |
| `pipeline.error` | **NOT OBSERVED** (handled elsewhere) | |

Key observation: the `loop.escalate/error` branch at L1020
already hard-codes `"s13_loop"` — someone on Geny's side
remembered loop is stage 13 and wrote it manually. That
duplication is a warning sign that the current design doesn't
carry stage order through metadata.

## 4. SessionLogger surface

`backend/service/logging/session_logger.py`:

- `LogLevel.GRAPH = "GRAPH"` (L46). Serialized into
  `LogEntry.to_dict()["level"]` (L72-79).
- `log_graph_event(event_type, message, node_name, state_
  snapshot, data)` (L706-741) — single generic emit.
- Typed helpers: `log_graph_execution_start` (L743-763),
  `log_graph_node_enter` (L765-779), `log_graph_node_exit`
  (L781-804), `log_graph_state_update` (L806-822),
  `log_graph_edge_decision` (L824-845),
  `log_graph_execution_complete` (L847-876), `log_graph_error`
  (L878+).
- **Typed helpers are defined but not used** — the translation
  layer calls generic `log_graph_event` directly, skipping
  specialized signatures. Migration can consolidate.

## 5. Frontend consumers

Everything hangs off `entry.level.value` sent from backend.

### 5.1. `LogEntryCard.tsx`

- Line 30: `LEVEL_CONFIG.GRAPH = { icon: Zap, color: '#8b5cf6',
  label: 'Graph' }` — this is where the "Graph" label text
  comes from.
- Line 86-88: if `entry.level === 'GRAPH' && meta?.event_type`,
  render `"{event_type}: {node_name}"` → produces
  `"node_enter: yield"` string.
- Line 157: `hasDetail` includes `'GRAPH'` — expand-on-click
  behavior depends on this.

### 5.2. Other frontend files referencing `GRAPH` / `'Graph'` / `node_enter` / `node_exit`

Per grep (Geny/frontend/src):

- `lib/i18n/en.ts` — user-facing i18n strings (likely "Graph
  events" labels).
- `components/tabs/LogsTab.tsx` — tab label / filter.
- `components/execution/ExecutionTimeline.tsx` — timeline
  markers.
- `components/execution/StepDetailPanel.tsx` — step detail.
- `components/live2d/VTuberChatPanel.tsx` — mentions in chat
  panel (likely indirect — not in the log rendering pipeline).
- `components/messenger/MessageList.tsx` — similar.
- `components/obsidian/obsidian.css` — possibly CSS class
  `.log-graph` styling.

Each needs a look during PR-1 to add `STAGE` alongside `GRAPH`
(keep the latter for DB-persisted legacy rows).

## 6. Silent paths that should surface

Places in `backend/service/execution/agent_executor.py` where
execution drama happens but only `logger.info/warning/debug`
fires (never reaches the UI panel):

| L# | Function | Event | Why users want it visible |
|---|---|---|---|
| 461-467 | `_ensure_alive_or_revive` | Auto-revival triggered / succeeded | User sees "why did my session skip a beat?" |
| 217-219 | `_notify_linked_vtuber._trigger_vtuber` | VTuber busy → SUB_WORKER_RESULT inbox'd | Explains the 2-min delay between sub-worker finish and VTuber narration |
| 222-225 | same | Inbox delivery failed → falling back to DLQ | High-severity, absolutely should show |
| 237-240 | same | DLQ fallback also failed | Ditto |
| 845, 857, 863 | `_drain_inbox` | Drain start / item processed / item failed | Users see queued DMs being replayed |
| 872 | same | Drain complete (N items processed) | Summary for the turn |

All these are candidates for `session_logger.log(LogLevel.INFO,
...)` with structured metadata. Not STAGE events — they're not
from the executor — but they are *execution* events the panel
should cover.

## 7. The stage-order lookup problem

The executor emits `stage=<name>` (e.g., `"yield"`) but does
NOT include `stage_order` on the `PipelineEvent`. Geny has two
options:

1. **Local map in Geny.** Duplicate the 16-name table into a
   constant in `session_logger.py` or a new `stage_registry.py`
   module. Zero coordination cost, risk: the table drifts if
   the executor ever renames a stage. Mitigation: the executor
   versions its package; a rename would come with a floor bump,
   which this cycle's PR could catch.
2. **Upstream PR to the executor.** Add `order: int` (and
   optionally `display_name: str`) to `PipelineEvent`. Cleaner
   long-term; adds one more executor release coordinating
   dance.

Recommendation: do (1) now, file (2) as a follow-up if the
duplication bites.

## 8. Verification plan (post-merge)

1. Start a VTuber session, issue a command that triggers tool
   use + loop + memory stages.
2. Open the log panel. Confirm:
   - Entries are labelled **"Stage"** (not "Graph"). Old rows
     from prior sessions still render as "Graph" with the same
     visual treatment.
   - Each stage log shows `s{NN}_{name}` (e.g., `s16_yield`)
     with iteration index.
   - `node_bypass` entries appear for any stage registered but
     skipped (e.g., `s05_cache` when cache is empty).
3. Force a busy-path scenario (VTuber busy when Sub-Worker
   finishes) — log panel shows "Sub-Worker result queued to
   inbox (will deliver on drain)" and later "Drain replayed 1
   queued message".
4. Kill the executor process mid-session → confirm "Auto-
   revival succeeded" entry appears in the log panel.

## 9. Out-of-scope (explicitly)

- Full UI redesign / new log view — the new data is rendered in
  the existing card component.
- Retroactive migration of old DB `GRAPH` rows to `STAGE`.
- Any change to TTS, sanitizer, or STM behavior.
- Executor package changes (deferred per § 7).
