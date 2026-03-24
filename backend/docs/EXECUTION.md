# Execution & Real-Time Communication

> Unified execution architecture for command (1:1) and chat room broadcast (1:N), with SSE-based real-time delivery

## Core Principle

**A chat room is just multi-command.**

There is ONE execution path for all agent interactions. Whether a user sends a command to a single agent (Command tab) or broadcasts a message to a room of N agents (Messenger), every execution goes through the same `agent_executor.py` module. This guarantees identical behavior for:

- Session logging (log_command / log_response)
- Cost tracking (increment_cost)
- Auto-revival (revive dead agent processes)
- Double-execution prevention
- Timeout handling

```
                    ┌─────────────────────────┐
                    │    agent_executor.py     │
                    │                         │
                    │  execute_command()       │  ← sync (await result)
                    │  start_command_background│  ← async (fire & forget)
                    │  _execute_core()         │  ← shared lifecycle
                    └────────┬────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        Command Tab    Chat Broadcast   (Future)
        (1:1 agent)    (N agents)
```

---

## agent_executor.py

Central module that owns all agent execution. Both `agent_controller` and `chat_controller` delegate here.

### ExecutionResult

Every execution returns an `ExecutionResult`:

```python
@dataclass
class ExecutionResult:
    success: bool
    session_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0
    cost_usd: Optional[float] = None
```

### Execution Lifecycle (`_execute_core`)

The internal `_execute_core()` runs the full lifecycle for a single agent invocation:

```
1. Log command     →  session_logger.log_command(prompt, timeout, ...)
2. Invoke agent    →  asyncio.wait_for(agent.invoke(input_text=prompt), timeout)
3. Log response    →  session_logger.log_response(success, output, duration_ms, cost)
4. Persist cost    →  session_store.increment_cost(session_id, cost)
```

Error handling covers: `TimeoutError`, `CancelledError`, and generic exceptions. All paths log the result and mark the holder as `done`.

### Double-Execution Prevention

A per-session guard prevents concurrent executions:

```python
_active_executions: Dict[str, dict]  # session_id → holder

def is_executing(session_id) -> bool
```

Both `execute_command()` and `start_command_background()` check this registry before starting. If a command is already running, `AlreadyExecutingError` is raised (HTTP 409).

### Auto-Revival

`_resolve_agent()` is called before every execution:

1. Look up `AgentSession` by session_id
2. If `agent.is_alive()` is False → attempt `agent.revive()`
3. If revival fails → raise `AgentNotAliveError`

This makes execution resilient to process crashes. Callers never need to manually revive agents.

### Public API

| Function | Behavior | Used By |
|----------|----------|---------|
| `execute_command(session_id, prompt, ...)` | Awaits completion, returns `ExecutionResult`, auto-cleans holder | Command tab sync execute, Chat broadcast per-agent |
| `start_command_background(session_id, prompt, ...)` | Fires background task, returns holder dict immediately | Command tab SSE streaming |

---

## Command Tab (1:1 Execution)

The Command tab provides three execution modes, all via `agent_controller.py`:

### Mode 1: Synchronous Execute

```
Client                          Backend
  │                               │
  ├── POST /execute ─────────────►│  execute_command()
  │                               │  (blocks until done)
  │◄───── JSON {output, cost} ────┤
```

- Endpoint: `POST /api/agents/{session_id}/execute`
- Blocks until agent finishes
- Returns `ExecuteResponse` with output, cost, duration

### Mode 2: Two-Step SSE (Start + Events)

```
Client                          Backend
  │                               │
  ├── POST /execute/start ───────►│  start_command_background()
  │◄───── {status: "started"} ────┤
  │                               │
  ├── GET /execute/events ───────►│  SSE stream (EventSource)
  │◄── event: log ────────────────┤  ← real-time log entries
  │◄── event: log ────────────────┤
  │◄── event: status {completed} ─┤
  │◄── event: result {output} ────┤
  │◄── event: done ───────────────┤  ← stream ends
```

- Start: `POST /api/agents/{session_id}/execute/start`
- Stream: `GET /api/agents/{session_id}/execute/events`
- Client connects with `EventSource` (GET-based SSE)
- Useful when client needs to separate the start action from streaming

### Mode 3: Single SSE Stream

```
Client                          Backend
  │                               │
  ├── POST /execute/stream ──────►│  start_command_background()
  │                               │  + immediate SSE response
  │◄── event: status {running} ───┤
  │◄── event: log ────────────────┤  ← real-time log entries
  │◄── event: log ────────────────┤
  │◄── event: status {completed} ─┤
  │◄── event: result {output} ────┤
  │◄── event: done ───────────────┤
```

- Endpoint: `POST /api/agents/{session_id}/execute/stream`
- Single request: starts execution AND returns SSE stream
- Recommended for most use cases

### Command SSE Event Types

| Event | Data | Description |
|-------|------|-------------|
| `status` | `{status, message}` | `"running"`, `"completed"`, or `"error"` |
| `log` | LogEntry dict | Real-time log entry from session logger in-memory cache |
| `result` | ExecuteResponse dict | Final execution result (output, cost, duration) |
| `error` | `{error}` | Top-level execution error |
| `done` | `{}` | Stream complete sentinel |

### Log Streaming Mechanism

The SSE stream reads from the session logger's **in-memory cache** (not the log file):

```python
while not holder["done"]:
    new_entries, cursor = session_logger.get_cache_entries_since(cursor)
    for entry in new_entries:
        yield sse_event("log", entry)
    await asyncio.sleep(0.15)  # 150ms poll interval
```

This gives near-real-time log delivery (~150ms latency) while the agent executes.

---

## Chat Room (1:N Broadcast)

The Messenger provides multi-agent communication via `chat_controller.py`.

### Broadcast Flow

```
Client                              Backend
  │                                    │
  ├── POST /rooms/{id}/broadcast ─────►│
  │                                    ├── 1. Save user message
  │                                    ├── 2. Create BroadcastState
  │                                    ├── 3. asyncio.create_task(_run_broadcast)
  │◄── {broadcast_id, target_count} ───┤  ← immediate response
  │                                    │
  │  (SSE stream — already connected)  │
  │◄── event: message (user msg) ──────┤  ← user's own message via SSE
  │◄── event: broadcast_status ────────┤  ← progress: 0/3 completed
  │◄── event: message (agent reply) ───┤  ← agent 1 response
  │◄── event: broadcast_status ────────┤  ← progress: 1/3 completed
  │◄── event: message (agent reply) ───┤  ← agent 2 response
  │◄── event: message (agent reply) ───┤  ← agent 3 response
  │◄── event: broadcast_status ────────┤  ← progress: 3/3 completed
  │◄── event: message (system) ────────┤  ← "3/3 sessions responded (5.2s)"
  │◄── event: broadcast_done ──────────┤  ← broadcast complete
```

### _run_broadcast

Background task that executes the same `execute_command()` for each agent in the room:

```python
async def _invoke_one(session_id):
    result = await execute_command(session_id=session_id, prompt=message)
    store.add_message(room_id, {type: "agent", content: result.output, ...})
    _notify_room(room_id)   # wake SSE listeners

tasks = [asyncio.create_task(_invoke_one(sid)) for sid in session_ids]
await asyncio.gather(*tasks, return_exceptions=True)
```

Key properties:
- All agents execute **concurrently** (asyncio.gather)
- Each agent uses `execute_command()` — identical path to Command tab
- Results are persisted immediately as they arrive (not batched)
- SSE listeners are notified after each message is saved

### BroadcastState

Tracks progress of a single broadcast:

```python
@dataclass
class BroadcastState:
    broadcast_id: str
    room_id: str
    total: int          # number of target agents
    completed: int      # finished (success or failure)
    responded: int      # produced output
    finished: bool
    started_at: float
```

- Stored in `_active_broadcasts: Dict[str, BroadcastState]` (room_id → state)
- Auto-cleaned 30 seconds after completion

### Chat Room SSE Event Stream

```
GET /api/chat/rooms/{room_id}/events?after={last_msg_id}
```

Long-lived SSE connection for real-time room updates. This is the **sole channel** for receiving new messages — the frontend does not poll.

#### Connection & Reconnection

```python
EventSource connects to:
  {BACKEND_URL}/api/chat/rooms/{room_id}/events?after={last_msg_id}
```

- `after` parameter: resume from the last received message ID
- On initial connect (no `after`): anchors to latest existing message, streams only new messages going forward
- On reconnect: `after=<last_msg_id>` replays any messages missed during disconnection
- Frontend auto-reconnects with 3-second delay on connection loss

#### Notification Mechanism

```python
_room_new_msg_events: Dict[str, asyncio.Event]   # room_id → Event

def _notify_room(room_id):
    event.set()   # wakes all SSE listeners for this room
```

1. Message saved to store → `_notify_room(room_id)` called
2. `asyncio.Event.set()` wakes the SSE generator
3. Generator queries `_get_messages_after(last_seen_id)` for new messages
4. New messages yielded as `message` SSE events

No polling — the SSE generator sleeps on `asyncio.Event.wait()` and wakes immediately when notified.

#### Chat SSE Event Types

| Event | Data | When |
|-------|------|------|
| `message` | Full message object | New message saved (user, agent, or system) |
| `broadcast_status` | `{broadcast_id, total, completed, responded, finished}` | Broadcast progress update |
| `broadcast_done` | `{broadcast_id, total, responded}` | All agents finished |
| `heartbeat` | `{ts}` | Every 5 seconds (keep-alive, only when idle) |

#### Message Object (via SSE)

```json
{
  "id": "uuid",
  "type": "user | agent | system",
  "content": "message text",
  "timestamp": "ISO 8601",
  "session_id": "sender session",
  "session_name": "display name",
  "role": "developer",
  "duration_ms": 3500,
  "cost_usd": 0.0557
}
```

---

## Cost Tracking

Cost flows through the entire execution pipeline:

```
Claude CLI output
  → StreamParser (parses cost from stream-json)
  → ProcessManager
  → ClaudeCLIChatModel (AIMessage.additional_kwargs.cost_usd)
  → AutonomousState.total_cost (_add_floats reducer)
  → agent.invoke() returns {output, total_cost}
  → _execute_core() reads total_cost
  → session_store.increment_cost(session_id, cost)    ← DB atomic UPDATE
  → ExecutionResult.cost_usd                          ← returned to caller
```

**Command tab**: `cost_usd` in `ExecuteResponse` and `result` SSE event
**Chat room**: `cost_usd` in each message object (via SSE `message` event)

DB schema:
- Sessions table: `total_cost DOUBLE PRECISION DEFAULT 0` (cumulative per session)
- Chat messages table: `cost_usd DOUBLE PRECISION DEFAULT NULL` (per message)

---

## Frontend Architecture

### Command Tab

The frontend uses `EventSource` to connect to `/execute/stream` or the two-step `/execute/start` + `/execute/events`:

- Real-time log entries displayed as they arrive
- Final result shown when `done` event received
- Connection managed by the command execution component

### Messenger (Chat Room)

The frontend uses a Zustand store (`useMessengerStore`) with pure SSE communication:

```
┌─────────────────────────────────────────────┐
│  useMessengerStore (Zustand)                │
│                                             │
│  selectRoom(roomId)                         │
│    ├── fetchMessages(roomId)   ← HTTP GET   │
│    └── _subscribeToEvents(roomId)           │
│         └── EventSource → backend SSE       │
│              ├── message → append to store   │
│              ├── broadcast_status → update   │
│              └── broadcast_done → clear      │
│                                             │
│  sendMessage(content)                       │
│    └── POST /broadcast          ← HTTP POST │
│         (response arrives via SSE, not poll) │
└─────────────────────────────────────────────┘
```

Key design decisions:
- **No polling**: All new messages arrive via SSE. No HTTP polling timers exist.
- **Direct backend SSE**: Frontend connects directly to `{BACKEND_URL}/api/chat/rooms/{roomId}/events`, bypassing the Next.js proxy (which buffers SSE streams).
- **Deduplication**: `messages.some(m => m.id === msg.id)` prevents duplicate messages on reconnect.
- **Reconnection**: On SSE error, auto-reconnect after 3 seconds with `after=<lastMsgId>`.
- **Room list**: Refreshed on broadcast completion + 30-second interval (separate from room message SSE).

---

## API Reference

### Command Execution (agent_controller)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/agents/{id}/execute` | Synchronous execute (blocks until done) |
| `POST` | `/api/agents/{id}/execute/start` | Start background execution |
| `GET` | `/api/agents/{id}/execute/events` | SSE stream for running execution |
| `POST` | `/api/agents/{id}/execute/stream` | Start + SSE stream in one request |
| `POST` | `/api/agents/{id}/stop` | Cancel running execution |

### Chat Room (chat_controller)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/chat/rooms` | List all rooms |
| `POST` | `/api/chat/rooms` | Create room |
| `GET` | `/api/chat/rooms/{id}` | Get room details |
| `PATCH` | `/api/chat/rooms/{id}` | Update room (name, sessions) |
| `DELETE` | `/api/chat/rooms/{id}` | Delete room + message history |
| `GET` | `/api/chat/rooms/{id}/messages` | Message history (initial load) |
| `POST` | `/api/chat/rooms/{id}/broadcast` | Broadcast message (fire-and-forget) |
| `GET` | `/api/chat/rooms/{id}/events` | SSE stream (reconnectable) |

---

## Error Handling

| Error | HTTP Status | Cause |
|-------|-------------|-------|
| `AgentNotFoundError` | 404 | Session ID does not exist |
| `AgentNotAliveError` | 400 | Process dead, auto-revival failed |
| `AlreadyExecutingError` | 409 | Another command is already running on this session |
| Timeout | — | Execution exceeded timeout (default: 21600s / 6h) |

---

## Source Files

| File | Purpose |
|------|---------|
| `service/execution/agent_executor.py` | Unified execution module |
| `controller/agent_controller.py` | Command tab endpoints + SSE streaming |
| `controller/chat_controller.py` | Chat room CRUD + broadcast + room SSE |
| `service/chat/conversation_store.py` | Message persistence (PostgreSQL + JSON) |
| `service/logging/session_logger.py` | Session log recording + in-memory cache |
| `service/claude_manager/session_store.py` | Session metadata + cost persistence |
