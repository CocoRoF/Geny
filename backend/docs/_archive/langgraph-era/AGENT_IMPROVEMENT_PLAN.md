# Geny Agent Enhancement Master Plan

> **Goal**: Referencing OpenClaw's production-grade agent execution patterns,
> enhance the Claude CLI + LangGraph-based Geny Agent to the highest level possible.

---

## 1. Current State vs Target State GAP Analysis

### 1.1 Core GAP Matrix

| Area | Current Geny Agent | OpenClaw Reference Level | GAP Severity |
|------|--------------------|--------------------|-----------|
| **System Prompts** | 5 MD files (15–150 lines), 6 inline prompts | 25+ section modular prompts, prompt modes, hook overrides | 🔴 Critical |
| **Execution Resilience** | Single attempt, MemorySaver (volatile) | Auth rotation, context overflow compaction (3-stage), model fallback | 🔴 Critical |
| **State Management** | MemorySaver (in-memory), Redis (metadata only) | File-based JSONL transcript, write locks, 45s TTL cache | 🟡 Major |
| **Tool Policy** | All tools always active | Profile-based (minimal/coding/messaging/full), owner-only, group expansion | 🟡 Major |
| **Completion Detection** | String matching ("Task completed", etc.) | SDK-level turn tracking + structured completion signals | 🟡 Major |
| **Context Management** | None (relies on CLI's --resume) | Context window guard (warn<32k, block<16k), auto compaction | 🟡 Major |
| **Session Freshness** | None | Per-channel auto-reset policies, freshness evaluation | 🟢 Minor |
| **Streaming** | Pseudo-streaming (100-char chunks) | Real-time event stream subscription, block reply chunking | 🟢 Minor |
| **Sub-agents** | Manager→Worker HTTP self-call | Gateway RPC, depth/child-count limits, session key isolation | 🟡 Major |

### 1.2 Our Differentiators (Maintain/Strengthen)

Geny Agent takes a fundamentally different approach from OpenClaw:

| Feature | Geny Agent | OpenClaw |
|---------|---------------|----------|
| **LLM Invocation** | Claude CLI subprocess | Built-in SDK API |
| **State Graph** | LangGraph StateGraph | None (while loop) |
| **Difficulty Classification** | AutonomousGraph (EASY/MED/HARD) | None |
| **Self-Review** | Built-in review loop | None |
| **TODO Tracking** | Structured TodoItem[] | None |
| **Multi-Pod** | Redis-based session routing | Single instance |

**Strategy**: Maintain our structural strengths based on LangGraph while absorbing OpenClaw's **prompt design**, **execution resilience**, **tool policy**, and **context management** patterns.

---

## 2. Improvement Roadmap

### Phase 1: System Prompt Enhancement (Top Priority)

Upgrade the current superficial role-based prompts to **OpenClaw's 25+ section modular prompt** level.

#### TODO 1.1: Build Prompt Builder System
- **File**: `service/prompt/prompt_builder.py` (new)
- **Contents**:
  - `PromptSection` dataclass (name, content, condition, priority)
  - `PromptBuilder` class — conditional assembly by section
  - `PromptMode` enum (FULL / MINIMAL / NONE)
  - Builder pattern for adding/removing/overriding sections
  - Bootstrap file injection (AGENTS.md, CLAUDE.md, etc.)

```python
# Target API:
builder = PromptBuilder(mode=PromptMode.FULL)
prompt = (builder
    .add_identity(agent_name="DevWorker", role=SessionRole.WORKER)
    .add_capabilities(tools=active_tools)
    .add_safety_guidelines()
    .add_workspace_context(working_dir="/project")
    .add_datetime()
    .add_execution_protocol(autonomous=True)
    .add_completion_protocol()
    .add_context_files(["AGENTS.md", "CLAUDE.md"])
    .add_runtime_line(model="claude-sonnet-4", session_id="abc")
    .build())
```

#### TODO 1.2: Deep Enhancement of Role-Specific Prompts
- **File**: Full redesign of the `prompts/` directory
- Convert each role's prompt into **prompt section compositions**:
  - `developer.md` → Identity + Coding Guidelines + Safety + Tool Style
  - `worker.md` → Identity + Execution Protocol + Completion Protocol + Status Reporting
  - `self-manager.md` → Identity + CPEV Cycle + Milestone Tracking + Self-Sufficiency
  - `manager.md` → Identity + Delegation Protocol + Worker Management + Progress Tracking
  - `researcher.md` → Identity + Research Protocol + Citation + Synthesis
- Extract common sections (Safety, DateTime, Workspace, etc.)

#### TODO 1.3: Add Execution Protocol Sections
- **Key**: Prompt sections that maximize Claude CLI's `--resume` utilization
- **Contents**:
  - Response termination protocol (`[CONTINUE: ...]` / `[TASK_COMPLETE]` structured format)
  - Silent Reply protocol (prevent unnecessary responses)
  - Tool usage style guide (format for tool calls explanation/results)
  - Error self-recovery protocol
  - Context efficiency guide (token-saving patterns)

### Phase 2: Execution Engine Resilience Enhancement

#### TODO 2.1: Model Fallback System
- **File**: `service/langgraph/model_fallback.py` (new)
- **Contents**:
  - `ModelFallbackRunner` — iterates through candidate model list
  - `FailoverError` exception class (401, 403, 429, overloaded)
  - Model allowlist support
  - AbortError propagates immediately without fallback

```python
class ModelFallbackRunner:
    async def run_with_fallback(self, fn, candidates, allowlist=None):
        for candidate in candidates:
            if allowlist and candidate not in allowlist:
                continue
            try:
                return await fn(candidate)
            except FailoverError:
                continue
            except AbortError:
                raise
        raise AllCandidatesFailedError(...)
```

#### TODO 2.2: Context Overflow Recovery
- **File**: `service/langgraph/context_guard.py` (new)
- **Contents**:
  - Context window size tracking
  - Overflow detection (error message pattern matching)
  - 3-stage recovery: conversation summary compaction → re-compaction → tool result truncation
  - `ContextWindowGuard` — warn/block thresholds

#### TODO 2.3: Enhanced Retry Loop
- **File**: Modify `service/langgraph/agent_session.py`
- **Contents**:
  - Add retry wrapper to `_agent_node`
  - Auth error → try different API key (env var based)
  - Timeout → exponential backoff retry
  - Context overflow → compact and retry

### Phase 3: Tool Policy System

#### TODO 3.1: Tool Policy Engine
- **File**: `service/tool_policy/policy.py` (new)
- **Contents**:
  - `ToolProfile` enum (MINIMAL / CODING / MESSAGING / FULL)
  - `ToolPolicyEngine` — compute allowed tool set based on profile
  - Default profile mapping per role
  - Group expansion (`group:fs`, `group:runtime`, etc.)
  - Per-session override support

```python
class ToolPolicyEngine:
    def resolve_allowed_tools(
        self, role: SessionRole, profile: ToolProfile,
        custom_allow: List[str] = None, custom_deny: List[str] = None
    ) -> Set[str]:
        base = PROFILE_TOOLS[profile]
        result = base | set(custom_allow or [])
        result -= set(custom_deny or [])
        return result
```

#### TODO 3.2: Dynamic MCP Configuration Filtering
- Add policy-based filtering to `MCPLoader`
- Activate only a subset of MCP servers based on role

### Phase 4: State Management Enhancement (LangGraph-Specific)

#### TODO 4.1: Persistent Checkpointer
- Replace MemorySaver → SqliteSaver or Redis-based checkpointer
- Enable graph state recovery after process crashes

#### TODO 4.2: Session Freshness Policy
- **File**: `service/langgraph/session_freshness.py` (new)
- Configurable session expiration time (default: 6 hours)
- Auto-reset or compaction on expiry

#### TODO 4.3: Enhanced Completion Detection
- String matching → structured completion protocol
- Link `[TASK_COMPLETE]` signal with prompts above
- Structurally parse `is_complete` state from CLI output in LangGraph

---

## 3. Phase 1 Detailed Execution Plan

### 3.1 Prompt Builder Implementation

```
service/prompt/
├── __init__.py
├── builder.py          # PromptBuilder main class
├── sections.py         # All prompt section definitions
├── protocols.py        # Execution/completion/error recovery protocols
└── context_loader.py   # Bootstrap file loader
```

### 3.2 Section List (OpenClaw Reference + Geny Agent Specific)

| # | Section | Condition | Description |
|---|---------|-----------|-------------|
| 1 | Identity | Always | Agent name, role, core identity |
| 2 | Role Protocol | Per role | Role-specific behavioral guidelines (developer/worker/manager...) |
| 3 | Capabilities | When tools active | Available tool list and usage |
| 4 | Tool Style | When tools active | Tool call format, result handling guide |
| 5 | Safety | Always | Safety guidelines, data protection |
| 6 | Execution Protocol | autonomous=True | CPEV cycle, self-management protocol |
| 7 | Completion Protocol | Always | [CONTINUE]/[TASK_COMPLETE] signal convention |
| 8 | Workspace | When working_dir exists | Working directory information |
| 9 | DateTime | Always | Current time (KST/UTC) |
| 10 | Error Recovery | autonomous=True | Error self-recovery protocol |
| 11 | Context Efficiency | Always | Token-efficient response guide |
| 12 | Delegation | role=MANAGER | Delegation protocol, Worker management rules |
| 13 | Status Reporting | role=WORKER | Progress status reporting format |
| 14 | Bootstrap Context | When files exist | AGENTS.md, CLAUDE.md, etc. |
| 15 | Runtime Line | Always | Model, session ID, time — single-line metadata |

### 3.3 Implementation Priority

```
1. PromptBuilder + PromptSection basic skeleton    → builder.py
2. Write content for 15 sections                   → sections.py
3. Write detailed execution/completion protocols   → protocols.py
4. Bootstrap file loader                           → context_loader.py
5. Integrate builder into existing code            → agent_session.py, process_manager.py
6. Migrate existing prompts/*.md to builder-based approach
```

---

## 4. Expected Impact Analysis

### 4.1 Prompt Enhancement Effects
- Significant improvement in agent response quality (structured behavioral protocols)
- Elimination of unnecessary questions/waiting (enhanced self-management)
- Increased error self-recovery rate (recovery protocols)
- Improved token efficiency (efficiency guide)

### 4.2 Execution Resilience Effects
- Single failure → automatic recovery (model fallback, context compaction)
- Significant stability improvement for long-running tasks
- Automatic bypass of API key expiration / rate limits

### 4.3 Tool Policy Effects
- Enhanced security (principle of least privilege)
- Appropriate tool access per role
- Prevention of Manager directly accessing the file system

---

## 5. Execution Log (updated)

### Completed Items
1. ✅ `service/prompt/` directory structure
2. ✅ `builder.py` — PromptBuilder core
3. ✅ `sections.py` — 15 prompt sections
4. ✅ `protocols.py` — Execution/completion/error recovery protocols
5. ✅ `context_loader.py` — Bootstrap file loader
6. ✅ Integration (`_build_system_prompt()` → `AgentSessionManager`)
7. ✅ Model fallback system (`service/langgraph/model_fallback.py`)
8. ✅ Context guard (`service/langgraph/context_guard.py`)
9. ✅ Enhanced completion detection (structured `CompletionSignal` enum)
10. ✅ Enhanced LangGraph State (`service/langgraph/state.py`)
    - Single source of truth for `AgentState` / `AutonomousState`
    - First-class fields: `iteration`, `max_iterations`, `completion_signal`, `completion_detail`, `context_budget`, `fallback`, `memory_refs`
    - Centralized enums: `CompletionSignal`, `Difficulty`, `ReviewResult`, `TodoStatus`, `ContextBudgetStatus`
    - Compound types: `TodoItem`, `MemoryRef`, `FallbackRecord`, `ContextBudget`
    - Custom reducers: `_add_messages`, `_merge_todos`, `_merge_memory_refs`
    - Helpers: `make_initial_agent_state()`, `make_initial_autonomous_state()`
11. ✅ Session Memory system (`service/memory/`)
    - `types.py` — `MemorySource`, `MemoryEntry`, `MemorySearchResult`, `MemoryStats`
    - `long_term.py` — `LongTermMemory` (MEMORY.md + dated + topic files, keyword+recency search)
    - `short_term.py` — `ShortTermMemory` (JSONL transcript + summary.md)
    - `manager.py` — `SessionMemoryManager` (unified facade, cross-store search, context injection, auto-flush)
12. ✅ Resilience graph nodes (`service/langgraph/resilience_nodes.py`)
    - `make_context_guard_node()` — context budget check node
    - `make_memory_inject_node()` — memory injection node
    - `make_transcript_record_node()` — post-LLM transcript recording
    - `completion_detect_node()` / `detect_completion_signal()` — structured completion parsing
13. ✅ Integrated `state.py` into `agent_session.py`
    - Removed inline `AgentState` / `add_messages` — now imports from `state.py`
    - Graph topology: `START → context_guard → agent → process_output → (continue|end)`
    - `_process_output_node` writes `iteration`, `completion_signal`, `completion_detail`
    - `_should_continue` reads structured `CompletionSignal` from state
    - Memory manager initialized on session init, records transcripts, flushes on cleanup
    - All docstrings/comments translated to English
14. ✅ Integrated `state.py` into `autonomous_graph.py`
