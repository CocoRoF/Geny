# Autonomous Difficulty-Based Graph — Deep Analysis Document

> **Target**: CompiledStateGraph based on `template-autonomous.json`
> **Node count**: 26 (24 execution nodes excluding START/END)
> **Edge count**: 35
> **State schema**: `AutonomousState(TypedDict)`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [AutonomousState State Schema](#2-autonomousstate-state-schema)
3. [Per-Path Detailed Analysis](#3-per-path-detailed-analysis)
   - 3.1 [Common Entry: Memory Inject → Guard → Classify](#31-common-entry)
   - 3.2 [EASY Path: Direct Answer](#32-easy-path)
   - 3.3 [MEDIUM Path: Answer → Review Loop](#33-medium-path)
   - 3.4 [HARD Path: TODO Decomposition Execution](#34-hard-path)
4. [LLM Call Node Detailed Analysis](#4-llm-call-node-detailed-analysis)
   - 4.1 [ClassifyNode — Difficulty Classification](#41-classifynode--difficulty-classification)
   - 4.2 [ReviewNode — Self-Routing Quality Gate](#42-reviewnode--self-routing-quality-gate)
   - 4.3 [CreateTodosNode — JSON Parsing Dependency](#43-createtodosnode--json-parsing-dependency)
   - 4.4 [AnswerNode / DirectAnswerNode](#44-answernode--directanswernode)
   - 4.5 [FinalReviewNode / FinalAnswerNode](#45-finalreviewnode--finalanswernode)
5. [Infrastructure Node Detailed Analysis](#5-infrastructure-node-detailed-analysis)
   - 5.1 [ContextGuardNode](#51-contextguardnode)
   - 5.2 [PostModelNode](#52-postmodelnode)
   - 5.3 [IterationGateNode](#53-iterationgatenode)
   - 5.4 [CheckProgressNode](#54-checkprogressnode)
   - 5.5 [MemoryInjectNode](#55-memoryinjectnode)
6. [Routing Logic Complete Analysis](#6-routing-logic-complete-analysis)
7. [Current System Vulnerability Analysis](#7-current-system-vulnerability-analysis)
8. [Structured JSON Output Implementation Strategy](#8-structured-json-output-implementation-strategy)
9. [Robustness Improvement Proposals Summary](#9-robustness-improvement-proposals-summary)

---

## 1. Architecture Overview

```
START
  │
  ▼
mem_inject ─── guard_cls ─── classify
                                │
                 ┌──────────────┼──────────────┐
                 │              │              │
                easy         medium          hard
                 │              │              │
                 ▼              ▼              ▼
             guard_dir      guard_ans      guard_todo
                 │              │              │
                 ▼              ▼              ▼
              dir_ans        answer         mk_todos
                 │              │              │
                 ▼              ▼              ▼
             post_dir       post_ans      post_todos
                 │              │              │
                 ▼              ▼              ▼
                END         guard_rev      guard_exec
                                │              │
                                ▼              ▼
                             review        exec_todo
                               │              │
                    ┌──────────┤              ▼
                    │          │          post_exec
                 approved    retry            │
                    │          │              ▼
                    ▼          ▼          chk_prog
                   END     gate_med          │
                               │        ┌────┴────┐
                        ┌──────┤      continue  complete
                     continue stop       │        │
                        │      │         ▼        ▼
                        ▼      ▼     gate_hard  guard_fr
                    guard_ans END        │        │
                                    ┌────┤        ▼
                                 cont. stop    fin_rev
                                    │    │        │
                                    ▼    ▼        ▼
                              guard_exec guard_fr post_fr
                                                  │
                                                  ▼
                                              guard_fa
                                                  │
                                                  ▼
                                               fin_ans
                                                  │
                                                  ▼
                                               post_fa
                                                  │
                                                  ▼
                                                 END
```

The graph branches into **3 execution paths** (Easy / Medium / Hard), each with a processing pipeline suited to the task complexity.

### Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Guard before every LLM call** | `ContextGuardNode` checks token budget |
| **Post after every LLM call** | `PostModelNode` handles iteration++, completion signal detection, transcript recording |
| **Gate on every loop** | `IterationGateNode` prevents infinite loops |
| **State-based routing** | Conditional node's `get_routing_function()` reads state fields to determine port |

---

## 2. AutonomousState State Schema

```python
class AutonomousState(TypedDict, total=False):
    # ── Input ──
    input: str                                     # Original user request

    # ── Conversation History ──
    messages: Annotated[list, _add_messages]        # LangChain message list (reducer: accumulate)
    current_step: str                               # Current execution stage name
    last_output: Optional[str]                      # Last LLM response text

    # ── Iteration Management ──
    iteration: int                                  # Global iteration counter (incremented by PostModel)
    max_iterations: int                             # Maximum allowed iterations

    # ── Difficulty ──
    difficulty: Optional[str]                       # "easy" | "medium" | "hard"

    # ── Answer & Review (MEDIUM path) ──
    answer: Optional[str]                           # Generated answer
    review_result: Optional[str]                    # "approved" | "retry" etc.
    review_feedback: Optional[str]                  # Reviewer feedback text
    review_count: int                               # Review count counter

    # ── TODO (HARD path) ──
    todos: Annotated[List[TodoItem], _merge_todos]  # TODO item list (reducer: merge)
    current_todo_index: int                         # Currently executing TODO index

    # ── Final Result ──
    final_answer: Optional[str]                     # Final synthesized answer

    # ── Completion Signal ──
    completion_signal: Optional[str]                # CompletionSignal enum value
    completion_detail: Optional[str]                # Signal detail content

    # ── Error ──
    error: Optional[str]                            # Error message
    is_complete: bool                               # Workflow completion flag

    # ── Context Budget ──
    context_budget: Optional[ContextBudget]         # Token usage tracking

    # ── Model Fallback ──
    fallback: Optional[FallbackRecord]              # Model fallback history

    # ── Memory ──
    memory_refs: Annotated[List[MemoryRef], _merge_memory_refs]  # Loaded memory references

    # ── Metadata ──
    metadata: Dict[str, Any]                        # Additional metadata
```

### Reducer Behavior

- `messages`: `_add_messages` — LangChain's message accumulation reducer. New messages are **appended** to the existing list.
- `todos`: `_merge_todos` — **Overwrite-merge** TODOs with the same `id`. New items are appended.
- `memory_refs`: `_merge_memory_refs` — Deduplicate by `filename` then merge.
- Other scalar fields: **last-write-wins** — the last written value overwrites previous values.

---

## 3. Per-Path Detailed Analysis

### 3.1 Common Entry

```
START → mem_inject → guard_cls → classify → [branch]
```

| Step | Node | Action |
|------|------|--------|
| 1 | `mem_inject` | Search `input`-related memories from SessionMemoryManager (max 5). Record input in short-term transcript. |
| 2 | `guard_cls` | Estimate token count of accumulated messages → update `context_budget` state |
| 3 | `classify` | **LLM call** — difficulty classification. Keyword matching `easy`/`medium`/`hard` from response |

### 3.2 EASY Path

```
classify[easy] → guard_dir → dir_ans → post_dir → END
```

The simplest path. Calls LLM once and terminates immediately without review.

| Step | Node | State Changes |
|------|------|---------------|
| 1 | `guard_dir` | Update `context_budget` |
| 2 | `dir_ans` | Set `answer`, `final_answer`, `is_complete=True` |
| 3 | `post_dir` | `iteration++`, completion signal detection, transcript recording |

### 3.3 MEDIUM Path

```
classify[medium] → guard_ans → answer → post_ans → guard_rev → review
                       ▲                                         │
                       │                               ┌────────┼────────┐
                       │                            approved   retry    end
                       │                               │        │        │
                       │                              END    gate_med   END
                       │                                        │
                       │                                ┌───────┤
                       │                             continue  stop
                       │                                │       │
                       └────────────────────────────────┘      END
```

**Core**: Answer → Review → (if approved → END / if retry → gate → answer loop)

| Step | Node | State Changes |
|------|------|---------------|
| 1 | `guard_ans` | Update `context_budget` |
| 2 | `answer` | If `review_count == 0` use primary prompt, if >0 use retry prompt + feedback. Set `answer`, `last_output` |
| 3 | `post_ans` | `iteration++`. **`detect_completion=false`** — no completion signal detection (intent: must proceed to review after answer) |
| 4 | `guard_rev` | Update `context_budget` |
| 5 | `review` | **LLM call** — structured parsing of `VERDICT:` / `FEEDBACK:`. Set `review_result` |
| 6 | `gate_med` | (on retry) iteration ≥ 5 or `is_complete` → stop, otherwise continue |

**Review loop max iterations**: `review.max_retries=3` (force approved after 3) × `gate_med.max_iterations=5` (iteration gate). Effectively force-terminates at review_count 3.

### 3.4 HARD Path

```
classify[hard] → guard_todo → mk_todos → post_todos → guard_exec → exec_todo
                                                          ▲            │
                                                          │         post_exec
                                                          │            │
                                                          │         chk_prog
                                                          │            │
                                                     ┌────┤      ┌────┤
                                                  continue│   continue│
                                                     │  stop   │  complete
                                                     │    │    │     │
                                                 gate_hard │  (above) guard_fr
                                                     │    │         │
                                                  ┌──┤    │      fin_rev → post_fr → guard_fa → fin_ans → post_fa → END
                                               cont. stop │
                                                  │    │  │
                                              guard_exec guard_fr
```

**Core**: TODO creation → individual execution loop → progress check → final review → final answer

| Step | Node | State Changes |
|------|------|---------------|
| 1 | `guard_todo` | Update `context_budget` |
| 2 | `mk_todos` | **LLM call** — JSON array parsing → create `todos` list, `current_todo_index=0` |
| 3 | `post_todos` | `iteration++`, **`detect_completion=false`** |
| 4 | `guard_exec` | Update `context_budget` |
| 5 | `exec_todo` | **LLM call** — execute current TODO. `todos[index].status=completed`, `current_todo_index++` |
| 6 | `post_exec` | `iteration++`, completion signal detection, transcript recording |
| 7 | `chk_prog` | `current_todo_index >= len(todos)` → complete, otherwise continue |
| 8 | `gate_hard` | iteration ≥ 5 → stop(→guard_fr), otherwise continue(→guard_exec loop) |
| 9 | `guard_fr` | Update `context_budget` |
| 10 | `fin_rev` | **LLM call** — comprehensive review of all TODO results |
| 11 | `post_fr` | `iteration++`, signal detection |
| 12 | `guard_fa` | Update `context_budget` |
| 13 | `fin_ans` | **LLM call** — synthesize final answer, `is_complete=True` |
| 14 | `post_fa` | `iteration++`, signal detection |

---

## 4. LLM Call Node Detailed Analysis

### 4.1 ClassifyNode — Difficulty Classification

**File**: `model_nodes.py` / **Type**: `classify`

#### Prompt

```
You are a task difficulty classifier. Analyze the given input and classify its difficulty level.

Classification criteria:
- EASY: Simple questions, factual lookups, basic calculations, straightforward requests
- MEDIUM: Moderate complexity, requires some reasoning or multi-step thinking
- HARD: Complex tasks requiring multiple steps, research, planning, or iterative execution

IMPORTANT: Respond with ONLY one of these exact words: easy, medium, hard

Input to classify:
{input}
```

#### LLM Response Parsing Logic

```python
response_text = response.content.strip().lower()

matched = default_cat  # "medium"
for cat in categories:  # ["easy", "medium", "hard"]
    if cat.lower() in response_text:
        matched = cat
        break
```

#### Vulnerability Analysis

| Issue | Severity | Description |
|-------|----------|-------------|
| **Simple substring matching** | HIGH | `"This is not easy"` → matches `easy`! The `in` operator checks substrings, ignoring context |
| **Order dependency** | MEDIUM | `for ... break` structure favors first match. `"medium-hard"` → `medium` |
| **Default bias** | MEDIUM | Always defaults to `medium` on match failure. If LLM gives completely unrelated response, medium path is taken |
| **Free-form response** | HIGH | `"ONLY one of these exact words"` instruction exists but LLM compliance cannot be guaranteed |

#### Routing Function (Edge Decision)

```python
def _route(state):
    if state.get("error"):
        return "end"
    value = state.get("difficulty")      # Difficulty enum or string
    if hasattr(value, "value"):
        value = value.value              # enum → string
    value = value.strip().lower()
    if value in {"easy", "medium", "hard"}:
        return value
    return "medium"                      # default
```

On error → `end` port → END (immediate termination).
If difficulty parsing result is valid, route to corresponding port.

---

### 4.2 ReviewNode — Self-Routing Quality Gate

**File**: `model_nodes.py` / **Type**: `review`

#### Prompt

```
You are a quality reviewer. Review the following answer for accuracy and completeness.

Original Question:
{question}

Answer to Review:
{answer}

Review the answer and determine:
1. Is the answer accurate and correct?
2. Does it fully address the question?
3. Is there anything missing or incorrect?

Respond in this exact format:
VERDICT: approved OR rejected
FEEDBACK: (your detailed feedback)
```

#### LLM Response Parsing Logic (Detailed)

```python
matched_verdict = default_verdict  # "retry"
feedback = ""

if verdict_prefix in review_text:     # "VERDICT:" exists?
    lines = review_text.split("\n")
    for line in lines:
        if line.startswith("VERDICT:"):
            verdict_str = line.replace("VERDICT:", "").strip().lower()
            for v in verdicts:         # ["approved", "retry"]
                if v.lower() in verdict_str:
                    matched_verdict = v
                    break
        elif line.startswith("FEEDBACK:"):
            feedback = line.replace("FEEDBACK:", "").strip()
            idx = lines.index(line)
            feedback = "\n".join([feedback] + lines[idx + 1:])
            break
else:
    # No structured prefix → treat entire response as feedback
    feedback = review_text
    review_lower = review_text.lower()
    for v in verdicts:
        if v.lower() in review_lower:
            matched_verdict = v
            break
```

#### Vulnerability Analysis

| Issue | Severity | Description |
|-------|----------|-------------|
| **Prompt says `rejected` but verdicts has `retry`** | HIGH | Default prompt instructs `"VERDICT: approved OR rejected"` but actual configured verdicts are `["approved", "retry"]`. If LLM outputs `rejected`, it **matches neither verdict** and defaults to `retry`. Works coincidentally but LLM intent parsing is unreliable |
| **Substring matching** | MEDIUM | `"not approved"` → matches `approved`. `"I'd say approve rather than retry"` → `approved` (first match) |
| **FEEDBACK parsing fragile** | MEDIUM | If FEEDBACK exists without VERDICT line, entire response becomes feedback and verdict falls back to keyword search |
| **Force approve logic** | LOW | `review_count >= max_retries(3)` → force first verdict (approved). Infinite retry prevention works well |

#### Routing Function (Edge Decision)

```python
def _route(state):
    if state.get("error"):
        return "end"                     # → END

    if state.get("is_complete"):
        # approved + max_retries reached → is_complete==True
        value = state.get("review_result", "").lower()
        if value in {"approved", "retry"}:
            return value
        return "approved"                # force

    # completion signal check
    signal = state.get("completion_signal")
    if signal in ("complete", "blocked"):
        return "approved"                # force

    value = state.get("review_result", "").lower()
    if value in {"approved", "retry"}:
        return value
    return "retry"                       # default
```

**Routing map**:
- `approved` → **END** (review passed)
- `retry` → **gate_med** (retry gate)
- `end` → **END** (error termination)

---

### 4.3 CreateTodosNode — JSON Parsing Dependency

**File**: `task_nodes.py` / **Type**: `create_todos`

#### Prompt

```
You are a task planner. Break down the following complex task into smaller, manageable TODO items.

Task:
{input}

Create a list of TODO items that, when completed in order, will fully accomplish the task.
Each TODO should be:
- Specific and actionable
- Self-contained (can be executed independently)
- Ordered logically (dependencies respected)

Respond in this exact JSON format only (no markdown, no explanation):
[
  {"id": 1, "title": "Short title", "description": "Detailed description of what to do"},
  {"id": 2, "title": "Short title", "description": "Detailed description of what to do"}
]
```

#### LLM Response Parsing Logic

```python
response_text = response.content.strip()

# Step 1: Remove markdown code blocks
if "```json" in response_text:
    response_text = response_text.split("```json")[1].split("```")[0]
elif "```" in response_text:
    response_text = response_text.split("```")[1].split("```")[0]

# Step 2: JSON parsing
try:
    todos_raw = json.loads(response_text.strip())
except json.JSONDecodeError:
    # Fallback to single item on failure
    todos_raw = [{"id": 1, "title": "Execute task", "description": input_text}]

# Step 3: Convert to TodoItem format
todos = []
for item in todos_raw:
    todos.append({
        "id": item.get("id", len(todos) + 1),
        "title": item.get("title", f"Task {len(todos) + 1}"),
        "description": item.get("description", ""),
        "status": "pending",
        "result": None,
    })

# Step 4: Count limit
if len(todos) > max_todos:  # default: 20
    todos = todos[:max_todos]
```

#### Vulnerability Analysis

| Issue | Severity | Description |
|-------|----------|-------------|
| **JSON parse failure → single item fallback** | HIGH | If LLM prepends explanation text, markdown block removal may be insufficient. Fallback creates one TODO with entire input, completely losing the Hard path's decomposition benefit |
| **Markdown block parsing uses simple split** | MEDIUM | Nested or multiple code blocks may extract the wrong section |
| **No handling when items aren't dicts** | MEDIUM | `item.get("id")` call raises `AttributeError` if item is a string |
| **Empty array response** | MEDIUM | `[]` parses successfully → `todos=[]` → `chk_prog` immediately completes → no work done |

---

### 4.4 AnswerNode / DirectAnswerNode

#### AnswerNode (Medium Path)

| Situation | Prompt Used | Condition |
|-----------|-------------|-----------|
| First attempt | `prompt_template` (default: `{input}`) | `review_count == 0` |
| Retry | `retry_template` | `review_count > 0 && review_feedback exists` |

**Retry prompt**:
```
Previous attempt was rejected with this feedback:
{previous_feedback}

Please try again with the following request, addressing the feedback:
{input_text}
```

Under budget pressure, feedback is truncated to 500 characters.

#### DirectAnswerNode (Easy Path)

Simple LLM call. Copies response to all state fields specified in `output_fields`.
Default: `["answer", "final_answer"]` + `mark_complete=True`.

**DirectAnswerNode vulnerability**: `prompt_template` default is `{input}` — passes input directly without system prompt or role instructions. Effectively depends on model's default behavior.

---

### 4.5 FinalReviewNode / FinalAnswerNode

#### FinalReviewNode

Formats all TODO results as markdown and requests comprehensive review:

```python
def _format_list_items(items, max_chars):
    text = ""
    for item in items:
        status = item.get("status", "pending")
        result = item.get("result", "No result")
        if result and len(result) > max_chars:
            result = result[:max_chars] + "... (truncated)"
        text += f"\n### {item.get('title', 'Item')} [{status}]\n{result}\n"
    return text
```

Budget-aware: `context_budget.status in ("block", "overflow")` → truncate to 500 chars per item.

#### FinalAnswerNode

Synthesizes review feedback + TODO results + original request. Sets `is_complete=True`.
Even on error, returns partial results with `is_complete=True` (graceful degradation).

---

## 5. Infrastructure Node Detailed Analysis

### 5.1 ContextGuardNode

**Purpose**: Token budget check before LLM calls

```python
result = context.context_guard.check(msg_dicts)

budget = {
    "estimated_tokens": result.estimated_tokens,
    "context_limit": result.context_limit,
    "usage_ratio": result.usage_ratio,
    "status": result.status.value,     # "ok" | "warn" | "block" | "overflow"
    "compaction_count": prev_budget.get("compaction_count", 0),
}
```

**Status levels**:
| Status | Meaning | Subsequent Action |
|--------|---------|-------------------|
| `ok` | Plenty of room | Normal execution |
| `warn` | Declining trend | Model node may reduce prompt |
| `block` | Critical level | Perform context compaction, `compaction_count++` |
| `overflow` | Exceeded | IterationGate decides to stop |

### 5.2 PostModelNode

**Purpose**: Handle 3 concerns after every LLM call

```python
# 1. Iteration increment
updates["iteration"] = iteration + 1

# 2. Completion signal detection (only when detect_completion=True)
signal, detail = detect_completion_signal(last_output)
# Regex-based:
#   [TASK_COMPLETE]        → CompletionSignal.COMPLETE
#   [BLOCKED: reason]      → CompletionSignal.BLOCKED
#   [ERROR: description]   → CompletionSignal.ERROR
#   [CONTINUE: next_action] → CompletionSignal.CONTINUE

# 3. Transcript recording
context.memory_manager.record_message("assistant", last_output[:5000])
```

**Critical configuration differences**:
| Node Instance | `detect_completion` | Reason |
|--------------|---------------------|--------|
| `post_dir` (after Easy) | `True` (default) | Final output, completion detection meaningful |
| `post_ans` (after Answer) | **`False`** | Must proceed to Review, completion detection blocked |
| `post_todos` (after CreateTodos) | **`False`** | TODO list itself is output, completion detection meaningless |
| `post_exec` (after ExecuteTodo) | `True` (default) | Error/completion detection meaningful during TODO execution |
| `post_fr`, `post_fa` | `True` (default) | Completion detection needed in final stages |

### 5.3 IterationGateNode

**Purpose**: Prevent infinite loop execution

```python
# 4 stop conditions (evaluated in order)
stop_reason = None

# 1. Iteration upper bound
if check_iteration and iteration >= max_iterations:
    stop_reason = "Iteration limit"

# 2. Context budget
if check_budget and budget.status in ("block", "overflow"):
    stop_reason = "Context budget"

# 3. Completion signal
if check_completion and signal in ("complete", "blocked", "error"):
    stop_reason = "Completion signal"

# 4. Custom stop field
if custom_stop_field and state.get(custom_stop_field):
    stop_reason = "Custom stop"
```

**Routing function**:
```python
def _route(state):
    if state.get("is_complete") or state.get("error"):
        return "stop"
    return "continue"
```

> Note: `execute()` sets `is_complete=True`, and the routing function reads it.
> Execute → state update → routing order guarantees consistency.

### 5.4 CheckProgressNode

**Purpose**: Check TODO list progress

```python
def _route(state):
    if state.get("is_complete") or state.get("error"):
        return "complete"
    signal = state.get("completion_signal")
    if signal in ("complete", "blocked"):
        return "complete"
    current_index = state.get("current_todo_index", 0)
    items = state.get("todos", [])
    if current_index >= len(items):
        return "complete"               # All items processed
    return "continue"                   # Remaining items exist
```

### 5.5 MemoryInjectNode

**Purpose**: Load relevant context from session memory

```python
# Record user input in short-term transcript
context.memory_manager.record_message("user", input_text[:5000])

# Search related memories (vector/keyword based)
results = context.memory_manager.search(
    input_text[:search_chars],    # default: 500 chars
    max_results=max_results,      # default: 5
)
```

Returns: `MemoryRef` list → stored in state for tracking. Actual memory content is not injected into messages, only references are kept.

---

## 6. Routing Logic Complete Analysis

### Conditional Node List

| Node | Ports | Basis | Type |
|------|-------|-------|------|
| `classify` | easy, medium, hard, end | `difficulty` field (LLM classification) | LLM-dependent |
| `review` | approved, retry, end | `review_result` field (LLM judgment) | LLM-dependent |
| `gate_med` | continue, stop | `is_complete` / `iteration >= 5` | Pure state-based |
| `chk_prog` | continue, complete | `current_todo_index >= len(todos)` | Pure state-based |
| `gate_hard` | continue, stop | `is_complete` / `iteration >= 5` | Pure state-based |

### Routing Reliability Classification

```
┌──────────────────────────────────────────────────────────┐
│  High reliability (pure state-based)                      │
│  ├─ gate_med:  iteration counter comparison               │
│  ├─ gate_hard: iteration counter comparison               │
│  └─ chk_prog:  index vs list length comparison            │
│                                                          │
│  Low reliability (depends on LLM response parsing)        │
│  ├─ classify:  keyword substring matching from free-form  │
│  └─ review:    VERDICT: prefix parsing + keyword matching │
└──────────────────────────────────────────────────────────┘
```

---

## 7. Current System Vulnerability Analysis

### 7.1 Structural Issues in LLM Response Parsing

#### Issue 1: Classify's substring matching

```python
# Current code
for cat in categories:
    if cat.lower() in response_text:  # ← substring!
        matched = cat
        break
```

**Failure cases**:
- `"The task is not easy, it requires medium effort"` → matches `easy` (first match priority)
- `"This requires some easygoing meditation"` → matches `easy`
- `"I cannot determine the difficulty"` → default `medium`
- `"It's a HARD task but could be medium depending on context"` → `hard` won't match (`hard` is uppercase), matches after `.lower()` applied

#### Issue 2: Review's VERDICT parsing mismatch

```
Prompt: "VERDICT: approved OR rejected"
Verdicts setting: ["approved", "retry"]
```

When LLM follows instructions and outputs `"VERDICT: rejected"`:
1. Search `"rejected"` string for `"approved"` → no match
2. Search `"rejected"` string for `"retry"` → no match
3. **Default verdict `"retry"` applied** — coincidentally works correctly, but not because LLM was accurately parsed

#### Issue 3: CreateTodos' JSON dependency

LLM adds explanation text around JSON:
```
Here are the TODO items:
```json
[{"id": 1, ...}]
```
Some additional notes...
```

Current split logic can handle this, but:
```
I'll break this down into tasks:

1. First, we need to...
[{"id": 1, ...}]
```
In this case neither `"```json"` nor `"```"` exists, so the entire text goes to `json.loads()` → failure → fallback.

### 7.2 State Consistency Issues

| Issue | Impact |
|-------|--------|
| `review_count` is incremented by ReviewNode but checked by AnswerNode | Depends on state synchronization between two nodes |
| `is_complete` is set by multiple nodes | Unintended early completion possible |
| `error` field set → all routers terminate immediately | No mechanism to recover from errors |
| `iteration` is a global counter | In HARD path, 4 TODOs + guard/post repetitions can exhaust it quickly |

### 7.3 Iteration Exhaustion Analysis (HARD Path)

Iterations consumed per TODO item execution:
```
guard_exec(0) → exec_todo(0) → post_exec(+1) → chk_prog(0) → gate_hard(0)
```
= **1 iteration per TODO item**

Additionally:
```
guard_todo(0) → mk_todos(0) → post_todos(+1)  = 1 iteration
fin_rev → post_fr(+1)                         = 1 iteration
fin_ans → post_fa(+1)                         = 1 iteration
No post after classify                         = 0 iterations
```

**Total iteration consumption**: `1(create) + N(todos) + 1(final_review) + 1(final_answer)` = **N + 3**

With `gate_hard`'s default `max_iterations=5`:
- Stops when `iteration ≥ 5`
- Already at iteration=1 after TODO creation (no post in classify path, first post_todos makes it 1)
- Effectively only about **2-3 TODOs** can execute before the gate stops

> **In practice, when `max_iterations_override` is 0 (default), `state.max_iterations` (default 50-100) is used, so this is less of an issue in production. However, if the template sets override to 5, it becomes limiting.**

---

## 8. Structured JSON Output Implementation Strategy

### 8.1 Current Problem Summary

| Node | Expected LLM Output | Current Parsing Method | Failure Probability |
|------|---------------------|----------------------|---------------------|
| `classify` | Single word (`easy`/`medium`/`hard`) | Substring matching | Medium |
| `review` | `VERDICT: {v}\nFEEDBACK: {f}` | Line split + prefix matching | High |
| `create_todos` | JSON array | `json.loads()` + code block removal | High |
| `execute_todo` | Free-form | None (entire response is result) | None |
| `answer`, `direct_answer` | Free-form | None (entire response is result) | None |
| `final_review`, `final_answer` | Free-form | None (entire response is result) | None |

**Nodes requiring Structured Output**: `classify`, `review`, `create_todos` (3 total)

### 8.2 Structured JSON Output Implementation Strategies

#### Strategy A: Prompt-Level JSON Enforcement (Soft Enforcement)

Explicitly present JSON schema in prompts and strengthen parsing logic:

**ClassifyNode improved prompt example:**
```
Analyze the input and classify its difficulty.

You MUST respond with EXACTLY this JSON format, nothing else:
{"classification": "<easy|medium|hard>"}

Input: {input}
```

**ReviewNode improved prompt example:**
```
Review the answer for quality.

You MUST respond with EXACTLY this JSON format, nothing else:
{"verdict": "<approved|retry>", "feedback": "<your detailed feedback>"}

Question: {question}
Answer: {answer}
```

**Advantages**: Minimal existing architecture changes
**Disadvantages**: LLM may still output text outside JSON

#### Strategy B: Robust Parsing Layer

JSON extraction → validation → retry as a unified common utility:

```python
# Proposed: new utility module
# service/workflow/nodes/structured_output.py

import json
import re
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass

@dataclass
class FieldSpec:
    """JSON field schema definition."""
    name: str
    type: type                  # str, int, list, etc.
    required: bool = True
    allowed_values: Optional[List[str]] = None
    default: Any = None

@dataclass
class ParseResult:
    """Parsing result."""
    success: bool
    data: Dict[str, Any]
    raw_text: str
    method: str                 # "direct_json" | "code_block" | "regex" | "fallback"

def extract_structured_output(
    text: str,
    fields: List[FieldSpec],
    *,
    strict: bool = False,
) -> ParseResult:
    """Extract structured data from LLM response.

    Attempt order:
    1. Parse entire text as JSON
    2. Extract from ```json code block
    3. Extract JSON portion via {} or [] pattern
    4. Per-field regex extraction
    5. Use defaults if strict=False
    """
    ...

def validate_against_schema(
    data: Dict[str, Any],
    fields: List[FieldSpec],
) -> tuple[bool, Dict[str, Any], List[str]]:
    """Schema validation + normalization.

    Returns:
        (valid, normalized_data, errors)
    """
    ...
```

**Usage example — ClassifyNode:**

```python
CLASSIFY_SCHEMA = [
    FieldSpec(
        name="classification",
        type=str,
        required=True,
        allowed_values=None,  # Dynamic: determined from config's categories
    ),
]

async def execute(self, state, context, config):
    categories = _parse_categories(config.get("categories", ...))
    schema = [
        FieldSpec(
            name="classification",
            type=str,
            required=True,
            allowed_values=categories,
            default=config.get("default_category", "medium"),
        ),
    ]

    prompt = f"""...

    You MUST respond with this exact JSON format:
    {{"classification": "<{'|'.join(categories)}>"}}
    """

    response = await context.resilient_invoke(messages, "classify")

    result = extract_structured_output(
        response.content,
        schema,
        strict=False,
    )

    matched = result.data.get("classification", default_cat)
    ...
```

**Usage example — ReviewNode:**

```python
REVIEW_SCHEMA = [
    FieldSpec(
        name="verdict",
        type=str,
        required=True,
        allowed_values=None,  # Dynamic: determined from config's verdicts
    ),
    FieldSpec(
        name="feedback",
        type=str,
        required=True,
        default="No feedback provided",
    ),
]
```

**Usage example — CreateTodosNode:**

```python
TODO_ITEM_SCHEMA = [
    FieldSpec(name="id", type=int, required=True),
    FieldSpec(name="title", type=str, required=True),
    FieldSpec(name="description", type=str, required=True, default=""),
]

# Array schema
TODO_LIST_SCHEMA = FieldSpec(
    name="todos",
    type=list,
    required=True,
    # Each element follows TODO_ITEM_SCHEMA
)
```

#### Strategy C: LLM Tool Use / Function Calling (Hard Enforcement)

Leverage Claude API's `tool_use` feature to enforce JSON schema:

```python
# Claude API tool definition
classify_tool = {
    "name": "classify_difficulty",
    "description": "Classify the task difficulty",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["easy", "medium", "hard"],
            }
        },
        "required": ["classification"],
    },
}
```

> **Note**: The source KO document is truncated at this point. Strategy C would describe using Claude's native tool calling to guarantee structured output, which provides the strongest enforcement but requires changes to the LLM call interface.

---

## 9. Robustness Improvement Proposals Summary

Based on the vulnerabilities identified in this analysis:

| Priority | Area | Proposal | Expected Impact |
|----------|------|----------|----------------|
| P1 | LLM parsing | Implement Strategy B (robust parsing layer) for classify, review, create_todos | Eliminate parsing failures |
| P2 | VERDICT mismatch | Align prompt instructions with actual verdict values (`retry` not `rejected`) | Fix silent misparse |
| P3 | Iteration exhaustion | Use `state.max_iterations` as default instead of hardcoded override | Allow HARD path to complete |
| P4 | State consistency | Add `error` recovery mechanism (retry node instead of immediate termination) | Improve resilience |
| P5 | Empty TODO fallback | Validate `todos` length > 0 after parsing, retry LLM if empty | Prevent no-op HARD path |
