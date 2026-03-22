# Geny Platform — Cost & Session Logging Flow Reference

> Generated 2026-03-21 · End-to-end trace of cost data and session logging

---

## 1. Cost Data Origin

**Ultimate source:** The Claude CLI. When executed with
`--output-format stream-json`, Claude CLI emits a final JSON event:

```json
{"type": "result", "total_cost_usd": 0.003421, "duration_ms": 9234, ...}
```

This per-invocation cost is calculated by the CLI itself based on
token usage and model pricing.

---

## 2. StreamParser — First Extraction Point

**File:** `service/claude_manager/stream_parser.py`

### StreamEvent (dataclass)
```python
@dataclass
class StreamEvent:
    total_cost_usd: Optional[float] = None  # from result event
    ...
```

### ExecutionSummary (dataclass)
```python
@dataclass
class ExecutionSummary:
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    tool_calls: List[Dict] = field(default_factory=list)
    usage: Dict = field(default_factory=dict)
    model: str = ""
    final_output: str = ""
    ...
```

### Parsing chain:
```
_parse_result(data) → StreamEvent(total_cost_usd=data["total_cost_usd"])
_update_summary(event) → self.summary.total_cost_usd = event.total_cost_usd
```

---

## 3. ProcessManager — Cost Propagation Hub

**File:** `service/claude_manager/process_manager.py`

### execute() method
After `stream_parser.get_summary()`, returns a result dict:

```python
return {
    "success": True,
    "output": summary.final_output,
    "cost_usd": summary.total_cost_usd,     # ← HERE
    "duration_ms": duration_ms,
    "tool_calls": summary.tool_calls,
    "num_turns": summary.num_turns,
    "usage": summary.usage,
    "model": summary.model,
    "execution_count": self._execution_count,
    ...
}
```

### Side effects in execute():
1. **Logs cost** to terminal: `Cost: ${summary.total_cost_usd:.6f}`
2. **Writes WORK_LOG.md:** `_append_work_log(cost_usd=summary.total_cost_usd)`
3. **Returns cost** in result dict to caller

---

## 4. WORK_LOG.md — File-based Cost Record

**File:** `{storage_path}/WORK_LOG.md`

Written by `ProcessManager._append_work_log()`. Format:

```markdown
# Work Log - Session {session_id}
**Session Name:** {name}
**Created:** {ISO timestamp}
**Model:** {model}

---
## [✅] Execution #1 — 2026-03-21 10:51:51
**Duration:** 9234ms
**Cost:** $0.030541

### Prompt
```
{prompt_preview}
```

### Output
```
{output_preview}
```
```

**Key limitation:** Cost is written as markdown text. No aggregation.
Each execution appends a new entry. The file grows indefinitely.

---

## 5. Three Execution Paths — Cost Propagation Analysis

### Path 1: Claude Controller (Direct CLI Execute)
**File:** `controller/claude_controller.py`

```
User → POST /api/claude/{id}/execute
     → ProcessManager.execute()
     → result["cost_usd"] = X.XX  ✅ PROPAGATED
     → ExecuteResponse(cost_usd=X.XX) → Frontend  ✅
```

**Status:** Cost fully propagated.

### Path 2: Command Controller (Batch/Broadcast)
**File:** `controller/command_controller.py`

```
User → POST /api/commands/batch
     → ProcessManager.execute()
     → result["cost_usd"] = X.XX  ✅
     → session_logger.log_response(cost_usd=X.XX)  ✅ in metadata
     → BatchCommandResult → Frontend  ❌ cost NOT in response model
```

**Status:** Cost logged but not returned to frontend.

### Path 3: Agent Controller (Graph Execute) ⚠️ BROKEN
**File:** `controller/agent_controller.py`

```
User → POST /api/agents/{id}/execute/start
     → agent.invoke(input_text=prompt)
       → AgentSession.invoke()
         → graph.ainvoke(initial_state)
           → Node.execute() → context.resilient_invoke()
             → ClaudeCLIChatModel._agenerate()
               → ProcessManager.execute() → cost_usd available ✅
               → AIMessage(additional_kwargs={...})  ❌ cost NOT included
             → Node returns state update (no cost field)
           → Final state (AutonomousState) — NO cost fields ❌
         → Returns text only (final_answer | answer | last_output) ❌
     → result_text (string, no cost) ❌
     → session_logger.log_response(cost_usd=None) ❌
     → ExecuteResponse(cost_usd=None) → Frontend ❌
```

**Status:** Cost is LOST at multiple points:
1. `ClaudeCLIChatModel._agenerate()` drops `cost_usd` from result dict
2. `AutonomousState` has no cost fields
3. `AgentSession.invoke()` returns only text
4. `agent_controller._run()` never receives cost

---

## 6. ClaudeCLIChatModel — Where Cost Is Dropped

**File:** `service/langgraph/claude_cli_model.py`

The `_agenerate()` method calls `self._process.execute()` which returns
a dict with `cost_usd`. But the AIMessage only includes:

```python
additional_kwargs = {
    "execution_count": result.get("execution_count", 0),
    "duration_ms": result.get("duration_ms", 0),
    "session_id": self._process.session_id,
    "conversation_id": self._process._conversation_id,
    # ❌ "cost_usd" is NOT included
    # ❌ "tool_calls" is NOT included
    # ❌ "usage" is NOT included
}
```

**Fix needed:** Include `cost_usd`, `tool_calls`, and `usage` in
`additional_kwargs`.

---

## 7. AutonomousState — No Cost Tracking

**File:** `service/langgraph/state.py`

The `AutonomousState` TypedDict has **zero cost-related fields**:
- No `total_cost` accumulator
- No per-iteration cost tracker
- No cost reducer function

During graph execution, each node calls the LLM, incurs cost, but the
cost is invisible to the state machine.

---

## 8. SessionLogger — Cost in Metadata

**File:** `service/logging/session_logger.py`

### log_response()
Records `cost_usd` in metadata of RESPONSE-level log entries:
```python
metadata = {
    "type": "response",
    "cost_usd": cost_usd,      # ← from caller
    "duration_ms": duration_ms,
    ...
}
```

### log_iteration_complete()
Has `cost_usd` parameter but is **NEVER CALLED** anywhere in the codebase.
Dead code.

### log_stream_event()
For `event_type == "result"`:
```python
cost = data.get("total_cost_usd", 0)
preview = f"Duration: {duration}ms, Cost: ${cost:.6f}"
```
Display-only in log.

### Storage:
- In-memory `_log_cache` (volatile, max 1000 entries)
- File: `logs/{session_id}.log`
- DB: `session_logs` table (best-effort via `db_insert_log_entry`)

---

## 9. Memory Manager — Cost Not Recorded

**File:** `service/memory/manager.py`

### record_execution()
Called after each graph invoke. Receives `result_state` (AutonomousState)
and `duration_ms`. Builds a markdown entry with:
- Duration
- Difficulty
- Iterations
- TODOs
- Final output preview

**Does NOT include cost** — because AutonomousState has no cost fields,
and the method doesn't receive cost as a parameter.

---

## 10. Frontend — Where Cost Appears Today

### ExecuteResponse (`types/index.ts`)
```typescript
export interface ExecuteResponse {
  cost_usd?: number;  // always null from Agent path
  ...
}
```

### Log Entry Metadata
The frontend reads `cost_usd` from log entry metadata and displays it:

| Component | Display | Source |
|-----------|---------|--------|
| `StepDetailPanel.tsx` | `$X.XXXXXX` per iteration | `meta.cost_usd` |
| `LogEntryCard.tsx` | `$X.XXXX` inline | `meta.cost_usd` |

### No Cumulative Display
No component shows total/cumulative cost per session. The InfoTab
shows session metadata but has no cost field.

---

## 11. Summary of All Cost-Related Locations

| File | What | Status |
|------|------|--------|
| `stream_parser.py` | Extract `total_cost_usd` from CLI | ✅ Working |
| `process_manager.py execute()` | Return `cost_usd` in result | ✅ Working |
| `process_manager.py _append_work_log()` | Write cost to WORK_LOG.md | ✅ Working |
| `claude_cli_model.py _agenerate()` | Pass cost in AIMessage | ❌ DROPS cost |
| `state.py AutonomousState` | Track cost across nodes | ❌ NO cost fields |
| `agent_session.py invoke()` | Return cost from graph | ❌ Returns text only |
| `agent_controller.py _run()` | Log/return cost | ❌ Always None |
| `session_logger.py log_response()` | Record cost in metadata | ⚠️ Receives None from Agent path |
| `session_logger.py log_iteration_complete()` | Record iteration cost | ❌ Dead code |
| `memory/manager.py record_execution()` | Record cost in LTM | ❌ Not included |
| `models.py SessionInfo` | Return cost in session info | ❌ No cost field |
| `session.py SessionModel` | Store cost in DB | ❌ No cost column |
| `session_db_helper.py` | Persist cost | ❌ No cost writes |
| Frontend InfoTab | Display cumulative cost | ❌ Not implemented |
| Frontend CommandTab | Display execution cost | ⚠️ Shows from log metadata only |

---

## 12. What Needs to Change

### A. Fix Cost Propagation (Agent Path)

1. **`claude_cli_model.py`:** Include `cost_usd` in `AIMessage.additional_kwargs`
2. **`state.py`:** Add `total_cost: float` accumulator field with add-reducer
3. **LLM nodes:** After `resilient_invoke()`, extract cost from
   `response.additional_kwargs["cost_usd"]` and write to state
4. **`agent_session.py`:** Extract `total_cost` from final state and pass
   to logger/caller

### B. Persistent Cost Storage

5. **`session.py SessionModel`:** Add `total_cost` column (DOUBLE PRECISION DEFAULT 0)
6. **`session_db_helper.py`:** Add `total_cost` to `_COLUMN_FIELDS`
7. **`models.py SessionInfo`:** Add `total_cost` field
8. **After each execution:** `db_update_session(session_id, {"total_cost": cumulative})`

### C. Frontend Display

9. **`types/index.ts SessionInfo`:** Add `total_cost?: number`
10. **`InfoTab.tsx`:** Display total cost field
11. **`CommandTab.tsx`:** Show per-execution cost from result event
