# Autonomous Agent Deep Analysis Report

> Purpose: Perform an in-depth analysis of the current Autonomous Agent implementation,
> identify gaps where Enhanced State fields are not actually utilized, and derive enhancement directions.

---

## 1. System Architecture Overview

### 1.1 Two Graph Modes

| Aspect | Simple Graph | Autonomous Graph |
|--------|-------------|------------------|
| **State** | `AgentState` | `AutonomousState` |
| **Purpose** | Testing / single-turn agent | **Default Agent** (difficulty-based autonomous execution) |
| **Location** | `agent_session.py` `_build_simple_graph()` | `autonomous_graph.py` `AutonomousGraph.build()` |
| **Resilience Nodes** | ✅ context_guard, completion_detect | ❌ **None** |
| **Memory Injection** | ✅ `_memory_manager` utilized | ❌ **None** |
| **Fallback** | ❌ (session-level only) | ❌ **None** |
| **Context Budget** | ✅ guard → state recording | ❌ **None** |

**Core Problem**: The default agent (Autonomous Graph) has none of the Resilience features designed and implemented in Phases 1–3 integrated into it.

### 1.2 Autonomous Graph Topology

```
START → classify_difficulty ─┬─ [easy]   → direct_answer → END
                             ├─ [medium] → answer → review ─┬─ [approved] → END
                             │                               └─ [retry]    → answer
                             └─ [hard]   → create_todos → execute_todo → check_progress
                                                           ↑                    │
                                                           └── [continue] ─────┘
                                                                [complete] → final_review → final_answer → END
```

Total: 9 nodes, 3 conditional routers, 3 execution paths.

---

## 2. AutonomousState Field Utilization Audit

### 2.1 Definition vs Actual Usage

In the table below, **"Written"** means a node writes the field to state,
and **"Read"** means a node reads from that field in state.

| State Field | Definition Location | Initial Value | Written (Write) | Read (Read) | Actual Utilization |
|------------|-----------|--------|----------------|-------------|----------------|
| `input` | `state.py:210` | User input | ❌ | ✅ All nodes | ✅ |
| `messages` | `state.py:213` | `[]` | ✅ All nodes | ❌ No node reads accumulated messages | ⚠️ **Accumulated but never read** |
| `current_step` | `state.py:214` | `"start"` | ✅ All nodes | ❌ | ⚠️ Debug only |
| `last_output` | `state.py:215` | `None` | ❌ **Never written** | ❌ | ❌ **Unused** |
| `difficulty` | `state.py:218` | `None` | ✅ classify_difficulty | ✅ _route_by_difficulty | ✅ |
| `answer` | `state.py:221` | `None` | ✅ answer, direct_answer | ✅ review | ✅ |
| `review_result` | `state.py:222` | `None` | ✅ review | ✅ _route_after_review | ✅ |
| `review_feedback` | `state.py:223` | `None` | ✅ review, final_review | ✅ answer(retry), final_answer | ✅ |
| `review_count` | `state.py:224` | `0` | ✅ review | ✅ answer, review | ✅ |
| `todos` | `state.py:227` | `[]` | ✅ create_todos, execute_todo | ✅ execute_todo, check_progress, final_review, final_answer | ✅ |
| `current_todo_index` | `state.py:228` | `0` | ✅ create_todos, execute_todo | ✅ execute_todo, check_progress, _route_after_progress_check | ✅ |
| `final_answer` | `state.py:231` | `None` | ✅ review(approved), direct_answer, final_answer | ✅ Extracted from invoke result | ✅ |
| **`completion_signal`** | `state.py:234` | `"none"` | ❌ **Never written** | ❌ | ❌ **Unused** |
| **`completion_detail`** | `state.py:235` | `None` | ❌ **Never written** | ❌ | ❌ **Unused** |
| `error` | `state.py:238` | `None` | ✅ On error | ✅ Checked from invoke | ✅ (error only) |
| `is_complete` | `state.py:239` | `False` | ✅ Multiple nodes | ❌ Not read within graph | ⚠️ External check only |
| **`context_budget`** | `state.py:242` | `None` | ❌ **Never written** | ❌ | ❌ **Unused** |
| **`fallback`** | `state.py:245` | `None` | ❌ **Never written** | ❌ | ❌ **Unused** |
| **`memory_refs`** | `state.py:248` | `[]` | ❌ **Never written** | ❌ | ❌ **Unused** |
| `metadata` | `state.py:251` | `{}` | ✅ check_progress | ⚠️ Partial | ⚠️ Minimal use |

### 2.2 Unused Fields Summary

**Completely Unused (Defined but Never Touched by Autonomous Graph)**:
1. `completion_signal` — Structured completion signal. Nodes don't parse signals from model responses
2. `completion_detail` — Completion detail information
3. `context_budget` — Context window usage tracking
4. `fallback` — Model fallback record
5. `memory_refs` — Memory reference list
6. `last_output` — Last output (input for completion_detect, but never written)

---

## 3. Per-Node Detailed Analysis

### 3.1 Common Pattern: Model Invocation Method Across All Nodes

```python
# All 9 nodes use the same pattern:
messages = [HumanMessage(content=prompt)]    # ← New single message each time
response = await self._model.ainvoke(messages)  # ← Bare call, no protection
```

**Problem List**:

| # | Problem | Description |
|---|---------|-------------|
| P1 | **Stateless Context** | Each node creates a new `[HumanMessage]`. Accumulated messages are not utilized. Previous node results exist only within prompt text and don't form a LangChain message chain |
| P2 | **No Context Budget Check** | In long hard tasks with 15 TODO items, model is called 15 times. No prompt length check per call |
| P3 | **No Model Fallback** | When `self._model.ainvoke()` fails, it's caught with except and sets `error + is_complete=True`. Immediate termination without retry or alternative model attempt |
| P4 | **No Completion Signal Parsing** | Model responses are not parsed for `[TASK_COMPLETE]`, `[BLOCKED]`, `[ERROR]`, etc. No call to `detect_completion_signal()` anywhere |
| P5 | **No Memory Injection** | Related information from long-term/short-term memory is not retrieved and included in prompts |
| P6 | **No Transcript Recording** | Model responses are not recorded in short-term memory |
| P7 | **No Iteration Counter** | No overall execution iteration counter (review_count is medium path only) |
| P8 | **No Error Recovery** | In the hard path, when 1 TODO fails it proceeds to the next, but basic errors immediately terminate the entire graph |

### 3.2 Per-Node Details

#### `classify_difficulty` (Classification)
- **Does**: Sends input to model, parses easy/medium/hard
- **Missing**:
  - No fallback strategy on classification failure (defaults to medium, but immediate termination on model call failure itself)
  - Reference to memory at this stage could enable more accurate classification using previous conversation context

#### `direct_answer` (Easy Path)
- **Does**: Passes input directly to model, response = final answer
- **Missing**:
  - No completion signal parsing
  - No context budget check (potential issue with long inputs)

#### `answer` → `review` Loop (Medium Path)
- **Does**: answer generates response, review parses VERDICT/FEEDBACK, retry if rejected
- **Well done**: Retry logic, max_review_retries check, feedback-included retry
- **Missing**:
  - Only counts review_count. No overall iteration tracking
  - Messages from previous responses not utilized in each retry (feedback only passed via prompt text)
  - No model fallback

#### `create_todos` → `execute_todo` → `check_progress` Loop (Hard Path)
- **Does**: JSON TODO parsing → sequential execution → progress check → final_review → final_answer
- **Well done**: Previous TODO results included in next TODO's prompt
- **Missing**:
  - Potential infinite loop regardless of TODO count (check_progress → execute_todo repeat) — no max iteration cap
  - No model fallback per execute_todo
  - When execute_todo fails it skips to next, but no circuit breaker for 3 consecutive failures
  - No context budget check during total TODO execution
  - previous_results grows with each TODO → no compaction available

---

## 4. Comparison with Simple Graph: Resilience Gap

### 4.1 Simple Graph's Resilience Stack

```
START → context_guard → agent → process_output → [continue/end]
                                                       ↑
                                                  completion_detect (built-in)
```

Simple Graph in `agent_session.py`:
1. **`context_guard` node** — Estimates message tokens each iteration, requests compaction on BLOCK
2. **`_agent_node`** — Records to transcript via `_memory_manager.record_message()` after model call
3. **`_process_output_node`** — Calls `detect_completion_signal()`, increments iteration, records completion_signal/detail
4. **`_should_continue`** — Structured routing based on completion_signal

### 4.2 Resilience Gap Matrix

| Resilience Feature | Simple Graph | Autonomous Graph | Gap |
|-------------------|-------------|------------------|------|
| Context Guard (Token Budget) | ✅ Every iteration | ❌ | **CRITICAL** |
| Completion Signal Detection | ✅ `detect_completion_signal()` | ❌ | **HIGH** |
| Memory Injection | ✅ record + search | ❌ | **HIGH** |
| Transcript Recording | ✅ `record_message()` | ❌ | **MEDIUM** |
| Model Fallback | ❌ (not integrated) | ❌ | MEDIUM |
| Iteration Cap (overall) | ✅ max_iterations | ❌ (path-specific only) | **HIGH** |
| Error Recovery / Retry | ❌ (simple termination) | ❌ (simple termination) | MEDIUM |
| Session Freshness | ✅ `_check_freshness()` | ✅ (session level) | OK |
| Checkpointing | ✅ Supported | ✅ Supported | OK |

---

## 5. Structural Issues Deep Analysis

### 5.1 Underutilization of Message Accumulation

`AutonomousState.messages` is designed as **append-only** using the `Annotated[list, _add_messages]` reducer.
In practice, all nodes return `"messages": [response]` or `"messages": [HumanMessage(...)]` to accumulate in the messages list.

**However, no node reads `state.get("messages")`.**

Each node crafts an independent `[HumanMessage]` using `state.get("input")` and a prompt template.
This means messages accumulate, but what's actually sent to the model is always a single HumanMessage — the model has no awareness of the conversation flow.

#### Impact

- In the hard path with 10 TODOs, 20+ items accumulate in messages, but each execute_todo sends only an independent prompt
- The next node cannot directly see the quality of the model's previous response (manual insertion of partial results into prompt strings)
- The only use of messages: reading `_invoke_autonomous` results externally

### 5.2 Absence of Overall Iteration Cap

Simple Graph prevents infinite loops with `max_iterations`.
Autonomous Graph:
- Medium path: `max_review_retries` (default 3) — limits only review count
- Hard path: TODO count is the upper bound — but if model creates 50 TODOs in create_todos, it runs 50 times

**There is no timeout or iteration cap for entire execution.**

### 5.3 Error Handling Fragility

```python
except Exception as e:
    return {
        "error": str(e),
        "is_complete": True,  # ← Immediate termination
    }
```

Same pattern across all nodes. Problems:
- Rate limit → terminated without retry
- Transient network errors → terminated without retry
- `ModelFallbackRunner` exists but is used nowhere

### 5.4 Hard Path Prompt Bloating

In `execute_todo`, previous results are included in the prompt:

```python
for i, t in enumerate(todos):
    if i < current_index and t.get("result"):
        previous_results += f"\n[{t['title']}]: {t['result'][:500]}...\n"
```

On the 10th TODO, the prompt includes ~4500 characters of previous results.
In `final_review` and `final_answer`, **all TODO results are included in full**, potentially making prompts very large.
**Without a context guard, this bloating cannot be detected or prevented.**

---

## 6. Components That Exist but Are Not Integrated

The following components are already implemented but not connected to the Autonomous Graph:

### 6.1 `resilience_nodes.py`

| Function | Purpose | Autonomous Integration |
|----------|---------|---------------------|
| `make_context_guard_node()` | Messages token budget check, compaction request | ❌ |
| `make_memory_inject_node()` | Long/short-term memory search → `memory_refs` recording | ❌ |
| `make_transcript_record_node()` | Record model response to JSONL transcript | ❌ |
| `completion_detect_node()` | Parse `[TASK_COMPLETE]` etc. from output → record `completion_signal` | ❌ |
| `detect_completion_signal()` | Pure function — extract signal from text | ❌ |

### 6.2 `model_fallback.py`

`ModelFallbackRunner` class:
- Automatically switches to candidate model when preferred model fails
- Can generate `FallbackRecord` to record in state
- `classify_error()`: Classifies error type (rate_limit, overloaded, timeout, etc.)
- `is_recoverable()`: Determines if fallback is possible

**Current status**: `model_fallback.py` is imported/used nowhere.

### 6.3 `context_guard.py`

`ContextWindowGuard` class:
- Token estimation (character-based heuristic)
- 2-stage warning: Warn(75%) / Block(90%)
- `compact()` method to remove old messages

**Current status**: Used only in Simple Graph's `make_context_guard_node()`.

### 6.4 `service/memory/`

`SessionMemoryManager`:
- `record_message()`: Save conversation history
- `search()`: Search for similar memories
- `build_memory_context()`: Build string for prompt injection

**Current status**: Only record is used in Simple Graph's `_agent_node()`. Unused in Autonomous Graph.

---

## 7. Autonomous Graph's Design Intent vs Reality

### 7.1 Original Design Intent (state.py comments)

```python
"""
Design principles (referencing OpenClaw patterns):
- Every resilience concern lives IN state, not in ad-hoc instance vars
- Completion detection via structured signal enum, not string matching
- Context budget tracked as first-class state field
- Model fallback state recorded so nodes can react to degraded mode
- Memory references surfaced in state for traceability
"""
```

### 7.2 Reality

| Design Principle | Reality |
|-----------------|---------|
| Resilience lives in state | State fields are only defined. Nodes don't use them |
| Structured completion signals | Only `is_complete` boolean is used. CompletionSignal not parsed |
| Context budget tracking | `context_budget` field exists but never written/read |
| Model fallback recording | `fallback` field exists but never written/read |
| Memory reference tracking | `memory_refs` field exists but never written/read |

**Conclusion: The State schema is correctly designed, but Graph nodes have not been implemented to utilize it.**

---

## 8. Enhancement Direction (Improvement Candidates)
