# Autonomous Graph Execution Logic — Deep Analysis

> Analysis date: 2026-03-21
> Target: `service/langgraph/autonomous_graph.py` and all related modules

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Execution Flow Full Map](#2-execution-flow-full-map)
3. [State Schema Analysis (AutonomousState)](#3-state-schema-analysis)
4. [Per-Node Deep Analysis — Input / Output / LLM Call Status](#4-per-node-deep-analysis)
5. [Routing Logic Analysis (Conditional Edges)](#5-routing-logic-analysis)
6. [LLM Call Count Analysis (Per Path)](#6-llm-call-count-analysis)
7. [Time Consumption Analysis — Bottlenecks](#7-time-consumption-analysis)
8. [Resilience Infrastructure Analysis](#8-resilience-infrastructure-analysis)
9. [Workflow Executor Integration Structure](#9-workflow-executor-integration-structure)
10. [Discovered Issues and Inefficiencies](#10-discovered-issues-and-inefficiencies)
11. [Appendix: Full Node I/O Matrix](#11-appendix-full-node-io-matrix)

---

## 1. System Architecture Overview

### Core Component Stack

```
User Input
  ↓
AgentSession.invoke() / .astream()
  ↓
WorkflowExecutor.compile() — WorkflowDefinition(JSON) → CompiledStateGraph
  ↓
LangGraph StateGraph (AutonomousState) — 30 nodes, 5 conditional routers
  ↓
Each node → ClaudeCLIChatModel.ainvoke() → ClaudeProcess(subprocess)
  ↓
Claude CLI (stdin/stdout stream-json) → Anthropic API
```

### Component Roles

| Component | File | Role |
|-----------|------|------|
| `AgentSession` | `agent_session.py` | Session lifecycle management, execution entry point |
| `WorkflowExecutor` | `workflow_executor.py` | JSON workflow → LangGraph compilation |
| `AutonomousGraph` | `autonomous_graph.py` | Difficulty-based graph definition (Legacy — currently WorkflowExecutor is used) |
| `AutonomousState` | `state.py` | 40+ field state schema |
| `ClaudeCLIChatModel` | `claude_cli_model.py` | LangChain `BaseChatModel` wrapper |
| `ContextWindowGuard` | `context_guard.py` | Token usage estimation/warning/blocking |
| `SessionFreshness` | `session_freshness.py` | Idle session detection/revival |
| `AutonomousPrompts` | `prompt/sections.py` | Prompt templates for each node |

### Execution Path: JSON Workflow First

The current system uses the **`template-autonomous.json` workflow definition → `WorkflowExecutor.compile()`** path instead of the hardcoded `build()` method in `autonomous_graph.py`.

```
AgentSession._build_graph()
  → _load_workflow_definition()
     → WorkflowStore.load("template-autonomous")
  → WorkflowExecutor(workflow, context).compile()
  → self._graph = CompiledStateGraph
```

`AutonomousGraph.build()` is effectively **dead code**, and `WorkflowExecutor` reconstructs the same topology from JSON.

---

## 2. Execution Flow Full Map

### 2.1 Topology (30 nodes, 37 edges)

```
START
  │
  ▼
[memory_inject] ─── (no-op or memory load)
  │
  ▼
[relevance_gate] ─── LLM call (chat mode) or pass-through
  │
  ├─ skip → END (irrelevant message)
  │
  ▼ continue
[guard_classify] ─── Context budget check (no LLM)
  │
  ▼
[classify_difficulty] ─── LLM call: easy/medium/hard classification
  │
  ▼
[post_classify] ─── Iteration increment, completion signal detection (no LLM)
  │
  ├── easy ──────────────────────────────┐
  ├── medium ────────────────────┐       │
  └── hard ──────┐               │       │
                 │               │       │
```

#### Easy Path (minimum 2 LLM calls)
```
guard_direct → direct_answer → post_direct → END
```

#### Medium Path (minimum 3 LLM calls, +2N on retry)
```
guard_answer → answer → post_answer → guard_review → review → post_review
   │                                                              │
   │    ┌──── approved ──────────────────────────────── END ◄──────┤
   │    │                                                          │
   │    └──── retry → iter_gate_medium ── continue ────────────────┘
   │                         │                          (loop back)
   │                         └── stop → END
   └─────────────────────────────────────────────────────────────────
```

#### Hard Path (minimum 5+N LLM calls, N=TODO count)
```
guard_create_todos → create_todos → post_create_todos → guard_execute
                                                            │
    ┌───────────────────────────────────────────────────────┘
    │
    ▼
execute_todo → post_execute → check_progress ─── continue → iter_gate_hard
    ▲                              │                              │
    │                              │                              ├─ continue (loop back)
    │                              │                              └─ stop ─┐
    │                              │                                       │
    │                              └── complete ───────────────────────────┐│
    │                                                                     ││
    └─────────────────────────────────────────────────────────────────────┘│
                                                                          │
    guard_final_review → final_review → post_final_review                 │
         ▲                                    │                           │
         │                                    ▼                           │
         └────────────────────────────────────┘                           │
                                                                          │
    guard_final_answer → final_answer → post_final_answer → END ◄────────┘
```

### 2.2 User-Provided Log-Based Execution Flow (Easy Path)

```
Time        Event                               Description
09:42:18   execution_start                     Graph execution start
09:42:18   node_enter: Memory Inject           Memory injection (no-op)
09:42:18   node_exit:  Memory Inject
09:42:18   node_enter: Relevance Gate          Relevance check
09:42:18   node_exit:  Relevance Gate          (non-chat → pass-through, 0ms)
09:42:18   edge_decision: Relevance Gate       → continue
09:42:18   node_enter: Guard (Classify)        Context budget check
09:42:18   node_exit:  Guard (Classify)
09:42:18   node_enter: Classify                ★ LLM call #1: difficulty classification
09:42:29   node_exit:  Classify                ~11s (LLM response)
09:42:29   edge_decision: Classify             → easy
09:42:29   node_enter: Guard (Direct)          Context budget check
09:42:29   node_exit:  Guard (Direct)
09:42:29   node_enter: Direct Answer           ★ LLM call #2: actual answer generation
09:42:31   STREAM: Model init                  Tools: 46
09:42:36   Tool: WebSearch query=...           Tool usage
09:43:09   node_exit: Direct Answer            ~40s (search+answer)
09:43:09   node_enter: Post Direct             Iteration/completion processing
09:43:09   node_exit: Post Direct
09:43:09   execution_complete                  ■ Total 53s

Total LLM calls: 2 (classify + direct_answer)
```

---

## 3. State Schema Analysis

### AutonomousState Full Fields (40+ fields)

| Category | Field | Type | Reducer | Initial Value | Purpose |
|----------|-------|------|---------|---------------|---------|
| **Input** | `input` | `str` | — | User input | Original question |
| **Conversation** | `messages` | `list` | `_add_messages` (append) | `[]` | LangChain message accumulation |
| | `current_step` | `str` | — | `"start"` | Current execution stage name |
| | `last_output` | `Optional[str]` | — | `None` | Last LLM output |
| **Iteration** | `iteration` | `int` | — | `0` | Global iteration counter |
| | `max_iterations` | `int` | — | `50` | Iteration cap |
| **Difficulty** | `difficulty` | `Optional[str]` | — | `None` | easy/medium/hard |
| **Medium Path** | `answer` | `Optional[str]` | — | `None` | Generated answer |
| | `review_result` | `Optional[str]` | — | `None` | approved/rejected |
| | `review_feedback` | `Optional[str]` | — | `None` | Review feedback |
| | `review_count` | `int` | — | `0` | Review count |
| **Hard Path** | `todos` | `List[TodoItem]` | `_merge_todos` | `[]` | TODO list |
| | `current_todo_index` | `int` | — | `0` | Current TODO index |
| **Final** | `final_answer` | `Optional[str]` | — | `None` | Final response |
| **Completion** | `completion_signal` | `Optional[str]` | — | `"none"` | Completion signal |
| | `completion_detail` | `Optional[str]` | — | `None` | Completion detail |
| | `error` | `Optional[str]` | — | `None` | Error message |
| | `is_complete` | `bool` | — | `False` | Completion flag |
| **Resilience** | `context_budget` | `Optional[ContextBudget]` | — | `None` | Context budget |
| | `fallback` | `Optional[FallbackRecord]` | — | `None` | Fallback record |
| **Memory** | `memory_refs` | `List[MemoryRef]` | `_merge_memory_refs` | `[]` | Injected memory refs |
| | `memory_context` | `Optional[str]` | `_last_wins` | `None` | Memory text |
| **Chat** | `is_chat_message` | `bool` | — | `False` | Chat mode flag |
| | `relevance_skipped` | `bool` | — | `False` | Relevance skip flag |
| **Meta** | `metadata` | `Dict` | — | `{}` | Additional metadata |

### ContextBudget Subtype

```python
class ContextBudget(TypedDict, total=False):
    estimated_tokens: int       # Estimated token count
    context_limit: int          # Model context limit
    usage_ratio: float          # Usage ratio (0.0~1.0)
    status: str                 # ok / warn / block / overflow
    compaction_count: int       # Compaction count
```

---

## 4. Per-Node Deep Analysis

### Legend

- ★ = LLM call occurs
- ○ = No LLM call (pure logic)
- 🔄 = Can loop

### 4.1 Common Entry Section

#### `memory_inject` ○
| Item | Description |
|------|-------------|
| **Input** | `state.messages`, `state.iteration`, `state.memory_refs` |
| **Output** | `{ memory_refs: [...] }` (or `{}`) |
| **LLM Call** | None |
| **Logic** | Currently no-op (actual memory injection performed by WorkflowExecutor's `MemoryInjectNode`). Searches long-term memory on first turn or every 10 turns and injects into state. |
| **Duration** | ~0ms |

#### `relevance_gate` ★ (chat mode) / ○ (normal mode)
| Item | Description |
|------|-------------|
| **Input** | `state.is_chat_message`, `state.input`, `state.metadata.{agent_name, agent_role}` |
| **Output** | `{ relevance_skipped: bool }` + `{ is_complete, final_answer, current_step }` (on skip) |
| **LLM Call** | 1 call in chat mode only (structured output: `RelevanceOutput`) |
| **Logic** | If `is_chat_message == False`, immediate pass-through (returns `{}`). In chat mode, evaluates message relevance based on agent role/name. Falls back to YES/NO on failure. |
| **Duration** | Normal mode: 0ms / Chat mode: 2~5s |

#### `guard_classify` ○
| Item | Description |
|------|-------------|
| **Input** | `state.messages` |
| **Output** | `{ context_budget: ContextBudget }` |
| **LLM Call** | None |
| **Logic** | Iterates message list with character-based token estimation (`len(text) / 3.0`). Checks `warn_ratio` (75%), `block_ratio` (90%) thresholds. |
| **Duration** | ~1ms |

#### `classify_difficulty` ★
| Item | Description |
|------|-------------|
| **Input** | `state.input` |
| **Output** | `{ difficulty: Difficulty, current_step, messages: [response], last_output }` |
| **LLM Call** | 1 — `AutonomousPrompts.classify_difficulty()` |
| **Prompt** | Instructs to analyze input and respond with exactly easy/medium/hard |
| **Parsing** | Searches for "easy"/"medium"/"hard" strings in response text |
| **Duration** | **~8-15s** (full LLM call for classification) |

#### `post_classify` ○
| Item | Description |
|------|-------------|
| **Input** | `state.iteration`, `state.last_output` |
| **Output** | `{ iteration: +1, current_step, completion_signal, completion_detail }` |
| **LLM Call** | None |
| **Logic** | Iteration increment, completion signal detection (here `detect_completion=False`), transcript recording |
| **Duration** | ~0ms |

### 4.2 Easy Path

#### `guard_direct` ○
(Same structure as guard_classify context guard)

#### `direct_answer` ★
| Item | Description |
|------|-------------|
| **Input** | `state.input` |
| **Output** | `{ answer, final_answer, messages: [response], last_output, is_complete: True }` |
| **LLM Call** | 1 — User input passed directly |
| **Prompt** | `input_text` as-is (no additional wrapping) |
| **Duration** | **~10-45s** (varies with question complexity/tool usage) |

#### `post_direct` ○
| Item | Description |
|------|-------------|
| **Input** | `state.iteration`, `state.last_output` |
| **Output** | `{ iteration: +1, completion_signal, completion_detail }` |
| **LLM Call** | None |
| **Duration** | ~0ms |

### 4.3 Medium Path

#### `guard_answer` ○ → Context guard
#### `answer` ★
| Item | Description |
|------|-------------|
| **Input** | `state.input`, `state.review_count`, `state.review_feedback`, `state.context_budget` |
| **Output** | `{ answer, messages: [response], last_output, current_step }` |
| **LLM Call** | 1 |
| **Prompt** | First attempt: `input_text` / Retry: `AutonomousPrompts.retry_with_feedback()` |
| **Duration** | ~10-30s |

#### `post_answer` ○ → Iteration/completion (detect_completion=False)
#### `guard_review` ○ → Context guard
#### `review` ★
| Item | Description |
|------|-------------|
| **Input** | `state.input`, `state.answer`, `state.review_count` |
| **Output** | `{ review_result, review_feedback, review_count, messages, last_output }` |
| **LLM Call** | 1 — `AutonomousPrompts.review()` |
| **Parsing** | Parses `VERDICT: approved/rejected` + `FEEDBACK:` format |
| **Special Logic** | `review_count >= max_review_retries (3)` → force approved |
| **Duration** | ~5-15s |

#### `post_review` ○ → Iteration/completion detection
#### `iter_gate_medium` ○ → Iteration limit/context/completion signal check 🔄

### 4.4 Hard Path

#### `guard_create_todos` ○ → Context guard
#### `create_todos` ★
| Item | Description |
|------|-------------|
| **Input** | `state.input` |
| **Output** | `{ todos: List[TodoItem], current_todo_index: 0, messages, last_output }` |
| **LLM Call** | 1 — `AutonomousPrompts.create_todos()` |
| **Parsing** | JSON parsing (includes markdown code block removal) |
| **Special Logic** | TODO count cap = 20, JSON failure → single TODO fallback |
| **Duration** | ~10-20s |

#### `post_create_todos` ○ → Iteration (detect_completion=False)
#### `guard_execute` ○ → Context guard 🔄
#### `execute_todo` ★ 🔄
| Item | Description |
|------|-------------|
| **Input** | `state.input`, `state.todos`, `state.current_todo_index`, `state.context_budget` |
| **Output** | `{ todos: [updated_todo], current_todo_index: +1, messages, last_output }` |
| **LLM Call** | 1 (per TODO) — `AutonomousPrompts.execute_todo()` |
| **Special Logic** | Under budget pressure, truncates previous results to 200 chars; on failure marks as FAILED and proceeds |
| **Duration** | ~10-60s per TODO |

#### `post_execute` ○ → Iteration/completion 🔄
#### `check_progress` ○ 🔄
| Item | Description |
|------|-------------|
| **Input** | `state.todos`, `state.current_todo_index` |
| **Output** | `{ current_step, metadata.{completed_todos, failed_todos, total_todos} }` |
| **LLM Call** | None — pure index/status counting |
| **Duration** | ~0ms |

#### `iter_gate_hard` ○ 🔄 → Iteration/context/completion check
#### `guard_final_review` ○ → Context guard
#### `final_review` ★
| Item | Description |
|------|-------------|
| **Input** | `state.input`, `state.todos`, `state.context_budget` |
| **Output** | `{ review_feedback, messages, last_output }` |
| **LLM Call** | 1 — `AutonomousPrompts.final_review()` |
| **Duration** | ~10-20s |

#### `post_final_review` ○
#### `guard_final_answer` ○ → Context guard
#### `final_answer` ★
| Item | Description |
|------|-------------|
| **Input** | `state.input`, `state.todos`, `state.review_feedback`, `state.context_budget` |
| **Output** | `{ final_answer, messages, last_output, is_complete: True }` |
| **LLM Call** | 1 — `AutonomousPrompts.final_answer()` |
| **Duration** | ~10-30s |

#### `post_final_answer` ○

---

## 5. Routing Logic Analysis

### 5 Conditional Routers

| # | Location | Router Function | Input Fields | Branch Results | Decision Basis |
|---|----------|----------------|-------------|----------------|----------------|
| 1 | `relevance_gate` → | `_route_after_relevance` | `relevance_skipped`, `is_complete`, `current_step` | `continue` / `skip` | Relevance result |
| 2 | `post_classify` → | `_route_by_difficulty` | `error`, `difficulty` | `easy` / `medium` / `hard` / `end` | Classification result |
| 3 | `post_review` → | `_route_after_review` | `is_complete`, `error`, `completion_signal`, `review_result` | `approved` / `retry` / `end` | Review result |
| 4 | `check_progress` → | `_route_after_progress_check` | `is_complete`, `error`, `completion_signal`, `current_todo_index`, `todos` | `continue` / `complete` | TODO progress |
| 5 | `iter_gate_{medium,hard}` → | `_route_iteration_gate` | `is_complete`, `error` | `continue` / `stop` | Iteration gate result |

### Routing Priority Pattern

All routers follow the same check pattern:
1. `error` → immediate termination
2. `is_complete` → termination
3. `completion_signal` → COMPLETE/BLOCKED → termination
4. Original business logic check

---

## 6. LLM Call Count Analysis

### Min/Max LLM Calls per Path

| Path | Min LLM Calls | Max LLM Calls | Conditions |
|------|--------------|--------------|------------|
| **Easy** (normal mode) | **2** | **2** | classify + direct_answer |
| **Easy** (chat mode) | **3** | **3** | relevance + classify + direct_answer |
| **Medium** (normal, 1st approval) | **3** | **3** | classify + answer + review |
| **Medium** (normal, retries) | **3 + 2N** | **3 + 2×3 = 9** | N = retry count (max 3) |
| **Hard** (normal, T TODOs) | **4 + T** | **4 + 20 = 24** | classify + create_todos + T×execute + final_review + final_answer |
| **Hard** (chat, T TODOs) | **5 + T** | **5 + 20 = 25** | +relevance |

### User Example Analysis (Easy Path)

```
"Who won the 2025 Korean Series?" → Easy
Total time: 53s
├── classify_difficulty: ~11s (LLM #1)
├── direct_answer: ~40s (LLM #2 + WebSearch)
├── Remaining nodes: ~2s (guards, posts, memory)
```

**Key Observation**: For a simple question, the `classify_difficulty` LLM call accounts for **21% of total time** (11s/53s).
This question is obviously EASY, so the classification LLM call is pure overhead.

---

## 7. Time Consumption Analysis — Bottlenecks

### Bottleneck #1: Difficulty Classification LLM Call (All Paths)

Every request must go through the `classify_difficulty` LLM call.
- **Duration**: 8~15s
- **Problem**: Most questions can be processed directly without classification
- **Scale**: Easy questions estimated at 60-80% of all queries, all bearing unnecessary classification cost

### Bottleneck #2: Excessive Guard Node Duplication (All Paths)

Context guard exists **before every LLM call**:
- Easy: `guard_classify` + `guard_direct` = 2 times
- Medium: `guard_classify` + `guard_answer` + `guard_review` = 3 times (+2N on retry)
- Hard: `guard_classify` + `guard_create_todos` + N×`guard_execute` + `guard_final_review` + `guard_final_answer` = 4+N times

Each guard takes ~1ms, but **node entry/exit logging** cost exceeds the guard logic itself.
LangGraph node transition overhead (state serialization/deserialization) also accumulates.

### Bottleneck #3: Excessive Post-Model Node Separation (All Paths)

`post_{position}` nodes exist **after every LLM call**:
- `post_classify`, `post_direct`, `post_answer`, `post_review`,
  `post_create_todos`, `post_execute`, `post_final_review`, `post_final_answer`

These nodes perform iteration increment, completion signal detection, and transcript recording — all lightweight operations that could be inlined into the LLM call nodes themselves, eliminating 8 node transitions.
