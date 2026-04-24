# Session Management

> Claude CLI subprocess → LangChain model → LangGraph StateGraph-based agent session lifecycle management

## Architecture Overview

```
AgentSessionManager (top-level manager)
        │
        ├── AgentSession (per-session instance)
        │     ├── ClaudeCLIChatModel (LangChain BaseChatModel)
        │     │     └── ClaudeProcess (CLI subprocess)
        │     ├── CompiledStateGraph (LangGraph graph)
        │     │     └── WorkflowDefinition → WorkflowExecutor
        │     ├── SessionMemoryManager (long-term + short-term memory)
        │     └── SessionFreshness (idle detection / auto-revival)
        │
        ├── SessionStore (persistent metadata — PostgreSQL + JSON)
        ├── SessionLogger (logging)
        └── Idle Monitor (background idle scan)
```

---

## Session State Machine

```
STARTING → RUNNING → IDLE → RUNNING (auto-revival)
    │          │         │
    ↓          ↓         ↓
  ERROR      ERROR    STOPPED
```

| State | Description |
|-------|-------------|
| `STARTING` | Initializing |
| `RUNNING` | Active — can receive/execute commands |
| `IDLE` | Idle — auto-revives on next invocation |
| `STOPPED` | Normal shutdown |
| `ERROR` | Error occurred |

The idle monitor runs every 60 seconds, transitioning `RUNNING` sessions that are not executing to `IDLE`. `IDLE` sessions auto-revive on the next `invoke()` call.

---

## ClaudeProcess

Individual Claude CLI subprocess manager.

### Initialization

```python
process = ClaudeProcess(
    session_id="abc123",
    session_name="Developer Session",
    working_dir="/workspace/project",
    model="claude-sonnet-4-20250514",
    max_turns=100,
    timeout=21600.0,
    mcp_config=mcp_config,
    system_prompt="You are a developer...",
    role="developer"
)
await process.initialize()
```

During initialization:
1. Create storage directory (`{STORAGE_ROOT}/{session_id}`)
2. Write session info file
3. Generate `.mcp.json` (MCP server config)
4. Discover Claude CLI (node.exe + cli.js paths)
5. Transition state to `RUNNING`

### Execution

```python
result = await process.execute(
    prompt="Create a Python web server",
    timeout=300,
    skip_permissions=True,
    resume=True  # Continue previous conversation
)
```

**Execution flow:**
1. Acquire `_execution_lock` (prevent concurrent execution)
2. Build environment variables (OS + Claude + Git auth)
3. Compose CLI arguments: `--print --verbose --output-format stream-json`
4. Auto-resume: if `_execution_count > 0`, add `--resume {conversation_id}`
5. Security flag: `--dangerously-skip-permissions`
6. Build direct node command: `[node.exe, cli.js, ...args]`
7. Start subprocess → write prompt to stdin
8. Read stdout/stderr concurrently (with timeout)
9. Parse each line with `StreamParser`
10. Record in `WORK_LOG.md`
11. Return result

### Result Format

```python
{
    "success": True,
    "output": "Final output text",
    "error": None,
    "duration_ms": 3500,
    "cost_usd": 0.0234,
    "tool_calls": [{"id": "...", "name": "Write", "input": {...}}],
    "num_turns": 3,
    "model": "claude-sonnet-4-20250514",
    "stop_reason": "end_turn"
}
```

### Git Authentication

`_setup_git_auth_env()` — Detects `GITHUB_TOKEN` environment variable and:
- Sets `GH_TOKEN`
- Sets `GIT_TERMINAL_PROMPT=0`
- Injects `https://x-access-token:<PAT>@github.com/` URL rewrite via `GIT_CONFIG_*`

---

## StreamParser

Parses Claude CLI's `--output-format stream-json` output line by line.

### Event Types

| Event | Description |
|-------|-------------|
| `SYSTEM_INIT` | Initialization (model, tools, MCP server info) |
| `ASSISTANT_MESSAGE` | Assistant message (text, tool use blocks) |
| `TOOL_USE` | Tool call start |
| `TOOL_RESULT` | Tool execution result |
| `CONTENT_BLOCK_START` / `DELTA` / `STOP` | Streaming text |
| `RESULT` | Execution complete (duration, cost, turns) |
| `ERROR` | Error |

### ExecutionSummary

```python
@dataclass
class ExecutionSummary:
    model: str
    available_tools: List[str]
    mcp_servers: List[str]
    tool_calls: List[Dict]
    assistant_messages: List[str]
    final_output: str
    success: bool
    is_error: bool
    error_message: str
    duration_ms: int
    total_cost_usd: float
    num_turns: int
    usage: Dict
    stop_reason: str
```

---

## ClaudeCLIChatModel

Wraps `ClaudeProcess` as a LangChain `BaseChatModel`.

```
LangGraph StateGraph
    │
    ▼
ClaudeCLIChatModel._agenerate(messages)
    │
    ▼
ClaudeProcess.execute(prompt)
    │
    ▼
Claude CLI subprocess
```

- `_agenerate(messages)`: Convert messages to prompt → `process.execute()` → wrap as `AIMessage`
- `cost_usd` is included in `AIMessage.additional_kwargs`
- `_llm_type = "claude-cli"`

---

## AgentSession

`CompiledStateGraph`-based session. Integrates ClaudeProcess + LangGraph + Memory.

### Creation

```python
agent = await AgentSession.create(
    session_id="abc123",
    session_name="Dev Session",
    working_dir="/workspace",
    model_name="claude-sonnet-4-20250514",
    workflow_id="template-autonomous",
    role="developer",
    max_iterations=50,
    mcp_config=mcp_config,
    system_prompt="..."
)
```

### Graph Build

`_build_graph()` → `_load_workflow_definition()`:

| Priority | Source | Description |
|----------|--------|-------------|
| 1 | `workflow_id` | Load explicitly by ID from WorkflowStore |
| 2 | `graph_name` | Name inference: "optimized" → `template-optimized-autonomous` etc. |
| 3 | Default | `template-simple` |

`WorkflowExecutor(workflow, ExecutionContext).compile()` → `CompiledStateGraph`

### Execution (invoke)

```python
result = await agent.invoke(
    input_text="Create a Python web server",
    max_iterations=50
)
# result = {"output": "...", "total_cost": 0.0234}
```

**invoke flow:**
1. Freshness check → auto-revive if idle, ERROR if limit exceeded
2. Verify process is alive → async revival
3. Set `_is_executing = True` (block idle monitor)
4. Create `make_initial_autonomous_state(input_text)`
5. Record input to short-term memory
6. `await self._graph.ainvoke(initial_state, config)`
7. Extract `final_answer` / `answer` / `last_output`
8. Record execution result to long-term memory
9. Return result

### Streaming (astream)

```python
async for chunk in agent.astream(input_text="..."):
    # Receive per-node execution chunks
    ...
```

### Revival (revive)

Auto-recovery when process dies:
1. Clean up dead model
2. Recreate model (new ClaudeProcess)
3. Rebuild graph
4. Restore state to `RUNNING`

---

## AgentSessionManager

Unified management of `AgentSession` + `SessionStore` + idle monitor.

### Session Creation Flow

```python
agent = await manager.create_agent_session(CreateSessionRequest(
    session_name="My Developer",
    role="developer",
    model="claude-sonnet-4-20250514",
    workflow_id="template-autonomous",
    tool_preset_id="template-all-tools"
))
```

**Creation sequence:**
1. Resolve Tool Preset → compute allowed Python tools + MCP servers
2. Assemble session MCP config (`build_session_mcp_config`)
3. Build system prompt (role + context + memory + shared folder)
4. `AgentSession.create()` — spawn ClaudeProcess + compile graph
5. Register in `_local_agents` and `_local_processes`
6. Connect DB to memory manager
7. Create shared folder symlink
8. Create SessionLogger + register in SessionStore

### Key Methods

| Method | Description |
|--------|-------------|
| `create_agent_session(request)` | Full creation flow |
| `get_agent(session_id)` | Get agent |
| `delete_session(session_id)` | Cleanup + soft delete |
| `cleanup_dead_sessions()` | Attempt revival → delete on failure |
| `start_idle_monitor()` | Start background idle scan |
| `stop_idle_monitor()` | Stop idle scan |

---

## SessionStore

Persistent session metadata registry.

### Dual Storage

- **Primary**: PostgreSQL `sessions` table
- **Backup**: `sessions.json` file
- All writes go to both; reads prioritize DB

### Soft Delete Pattern

```python
store.soft_delete(session_id)    # is_deleted=True, status=stopped
store.restore(session_id)        # is_deleted=False
store.permanent_delete(session_id)  # Permanent deletion
```

### Cost Tracking

```python
store.increment_cost(session_id, 0.0234)
# SQL: UPDATE sessions SET total_cost = COALESCE(total_cost, 0) + 0.0234
```

Atomic increment — safe for concurrent execution.

---

## CLI Discovery (cli_discovery)

Auto-discovers Claude CLI's `node.exe` + `cli.js` paths.

### Windows

Find `claude.cmd` → infer `node.exe` + `node_modules/@anthropic-ai/claude-code/cli.js` paths

### Unix

`claude` binary → resolve symlink → infer `cli.js` path

Result: `ClaudeNodeConfig(node_path, cli_js_path, base_dir)`

**Key insight**: Direct execution via `node.exe` bypasses `cmd.exe`/PowerShell — improved reliability.

---

## Platform Utilities

| Utility | Description |
|---------|-------------|
| `IS_WINDOWS` / `IS_MACOS` / `IS_LINUX` | Platform detection |
| `DEFAULT_STORAGE_ROOT` | Platform-specific session storage path |
| `get_claude_env_vars()` | Collect Claude-related environment variables |
| `WindowsProcessWrapper` | Workaround for Windows `SelectorEventLoop` issues |
| `create_subprocess_cross_platform()` | Cross-platform subprocess creation |

---

## API Endpoints

### Agent Sessions (`/api/agents`) — Primary API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/agents` | Create AgentSession |
| `GET` | `/api/agents` | List all agents |
| `GET` | `/api/agents/{id}` | Get agent |
| `PUT` | `/api/agents/{id}/system-prompt` | Update system prompt |
| `DELETE` | `/api/agents/{id}` | Soft delete |
| `DELETE` | `/api/agents/{id}/permanent` | Permanent delete |
| `POST` | `/api/agents/{id}/restore` | Restore |
| `POST` | `/api/agents/{id}/invoke` | LangGraph state-based execution |
| `POST` | `/api/agents/{id}/execute` | Graph execution (blocking) |
| `POST` | `/api/agents/{id}/execute/start` | Start background execution |
| `GET` | `/api/agents/{id}/execute/events` | Execution SSE log stream |
| `POST` | `/api/agents/{id}/execute/stream` | Execution + SSE combined |

### Store Queries

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agents/store/deleted` | Soft-deleted sessions |
| `GET` | `/api/agents/store/all` | All stored sessions |
| `GET` | `/api/agents/store/{id}` | Stored session metadata |

### Legacy Sessions (`/api/sessions`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sessions` | Create session |
| `GET` | `/api/sessions` | List sessions |
| `GET` | `/api/sessions/{id}` | Get session |
| `DELETE` | `/api/sessions/{id}` | Delete session |
| `POST` | `/api/sessions/{id}/execute` | Execute (blocking) |
| `POST` | `/api/sessions/{id}/execute/stream` | Execute (SSE) |
| `GET` | `/api/sessions/{id}/storage` | List storage files |
| `GET` | `/api/sessions/{id}/storage/{path}` | Read file |

### SSE Event Types

| Event | Description |
|-------|-------------|
| `log` | SessionLogger log entry |
| `status` | Status change (running/completed/error) |
| `result` | Execution result |
| `done` | Stream end |
| `error` | Error |

Auto-revival: All execution endpoints check `agent.is_alive()` → call `agent.revive()` if needed.

---

## Related Files

```
service/claude_manager/
├── __init__.py
├── models.py               # SessionStatus, CreateSessionRequest, ExecuteResponse, MCPConfig
├── session_manager.py       # SessionManager (basic session management)
├── session_store.py         # SessionStore (persistent metadata — PostgreSQL + JSON)
├── process_manager.py       # ClaudeProcess (CLI subprocess)
├── stream_parser.py         # StreamParser (stream-json parsing)
├── cli_discovery.py         # Claude CLI auto-discovery (node.exe + cli.js)
├── platform_utils.py        # Cross-platform utilities
├── storage_utils.py         # Storage file utilities
└── constants.py             # Constants

service/langgraph/
├── agent_session.py          # AgentSession (LangGraph-based session)
├── agent_session_manager.py  # AgentSessionManager (unified management)
├── claude_cli_model.py       # ClaudeCLIChatModel (LangChain wrapper)
├── state.py                  # AutonomousState TypedDict
├── autonomous_graph.py       # Legacy hardcoded graph (superseded)
├── context_guard.py          # ContextWindowGuard (token limits)
├── model_fallback.py         # ModelFallbackRunner (model switching)
└── resilience_nodes.py       # Completion signal parsing
```
