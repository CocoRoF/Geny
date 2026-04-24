# Logging System

> Structured logging system that triple-records per-session logs to file + DB + in-memory

## Architecture Overview

```
SessionLogger (per-session instance)
    │
    ├── File       ── logs/{session_id}.log (permanent)
    ├── PostgreSQL ── session_logs table (permanent)
    └── In-memory  ── _log_cache (max 1000 entries, for SSE streaming)
```

All log entries are simultaneously recorded in all three locations. DB writes are best-effort (non-blocking).

---

## LogLevel (11 types)

| Level | Enum | Description |
|-------|------|-------------|
| `DEBUG` | `DEBUG` | Debug messages |
| `INFO` | `INFO` | Session events, informational messages |
| `WARNING` | `WARNING` | Warnings |
| `ERROR` | `ERROR` | Errors |
| `COMMAND` | `COMMAND` | User prompt sent to Claude |
| `RESPONSE` | `RESPONSE` | Claude's response (success/failure) |
| `GRAPH` | `GRAPH` | `geny-executor` Stage transitions (legacy `Graph` key preserved for DB row compatibility) |
| `TOOL` | `TOOL_USE` | Tool call events |
| `TOOL_RES` | `TOOL_RESULT` | Tool execution results |
| `STREAM` | `STREAM_EVENT` | Claude CLI stream-json events |
| `ITER` | `ITERATION` | Autonomous execution iteration complete |

---

## LogEntry

```python
@dataclass
class LogEntry:
    level: LogLevel
    message: str
    timestamp: datetime = now_kst()
    metadata: Dict[str, Any] = {}
```

- `to_dict()` → `{timestamp, level, message, metadata}`
- `to_line()` → `[KST-timestamp] [LEVEL   ] message | {json-metadata}\n`

---

## SessionLogger

### Creation

```python
logger = SessionLogger(
    session_id="abc-123",
    session_name="My Session",
    logs_dir="backend/logs/"    # default
)
```

- Log file: `logs/{session_id}.log`
- Thread-safe with `threading.Lock`
- In-memory cache: max **1000** entries (oldest evicted first)

### Basic Logging

| Method | Level | Description |
|--------|-------|-------------|
| `log(level, message, metadata)` | Specified | General log |
| `debug(message)` | DEBUG | Debug |
| `info(message)` | INFO | Info |
| `warning(message)` | WARNING | Warning |
| `error(message)` | ERROR | Error |

### Specialized Logging

#### `log_command(prompt, timeout, system_prompt, max_turns)`

Level: **COMMAND** — Records user prompt.

| Metadata | Description |
|----------|-------------|
| `prompt_length` | Prompt length |
| `preview` | First 200 character preview |
| `system_prompt_preview` | First 100 chars of system prompt |
| `timeout`, `max_turns` | Execution settings |

#### `log_response(success, output, error, duration_ms, cost_usd, tool_calls, num_turns)`

Level: **RESPONSE** — Records Claude response. Automatically calls `log_tool_use()` for each `tool_call`.

| Metadata | Description |
|----------|-------------|
| `success` | Success flag |
| `duration_ms`, `cost_usd` | Execution time, cost |
| `output_length`, `preview` | Output length, first 200 chars |
| `tool_call_count`, `num_turns` | Tool call count, turn count |

#### `log_iteration_complete(iteration, success, output, ...)`

Level: **ITERATION** — Autonomous execution iteration complete. 500-char preview.

#### `log_tool_use(tool_name, tool_input, tool_id)`

Level: **TOOL_USE** — Tool call. Auto-performs structured extraction (see below).

#### `log_tool_result(tool_name, tool_id, result, is_error, duration_ms)`

Level: **TOOL_RESULT** — Tool result. File tools get 5000-char preview, others 500-char.

### Pipeline Event Logging

All levels: **GRAPH**. UUID event IDs generated (8 chars).

| Method | Event Type | Description |
|--------|-----------|-------------|
| `log_graph_execution_start(input, thread_id, ...)` | `execution_start` | Graph execution start |
| `log_graph_node_enter(node_name, iteration, ...)` | `node_enter` | Node entry |
| `log_graph_node_exit(node_name, iteration, duration_ms, ...)` | `node_exit` | Node exit |
| `log_graph_state_update(update_type, changes, ...)` | `state_update` | State update |
| `log_graph_edge_decision(from_node, decision, reason, ...)` | `edge_decision` | Edge decision |
| `log_graph_execution_complete(success, total_iterations, ...)` | `execution_complete` | Execution complete |
| `log_graph_error(error_message, node_name, ...)` | `error` | Graph error |

---

## Structured Extraction

Automatically extracts structured information from metadata during tool calls.

### File Change Extraction (`_extract_file_changes`)

Detected tools: `write_file`, `create_file`, `edit_file`, `str_replace_editor`, `multi_edit`, etc.

```python
{
    "file_path": "src/main.py",
    "operation": "edit",          # create / write / edit / multi_edit
    "changes": [
        {"old_str": "old code", "new_str": "new code"}
    ],
    "lines_added": 5,
    "lines_removed": 2
}
```

`multi_edit` supports up to 20 changes. Content fields max 50KB (truncated if exceeded).

### Command Extraction (`_extract_command_data`)

Detected tools: `bash`, `shell`, `execute`, `terminal`, `run`.

```python
{
    "command": "npm test",       # max 10KB
    "working_dir": "/project"
}
```

### File Read Extraction (`_extract_file_read_data`)

Detected tools: `read_file`, `view`, `cat`.

```python
{
    "file_path": "src/main.py",
    "start_line": 1,
    "end_line": 50
}
```

### Tool Formatting (`_format_tool_detail`)

Concise summary for log messages:
- bash: `` `npm test` `` (100 chars)
- read: `main.py (L1-50)`
- write: `main.py (+25 lines, 1024 chars)`
- grep: `"pattern" in src/`
- web/fetch: URL (60 chars)
- MCP tools: first relevant parameter (`query`, `path`, etc.)

---

## Log Query

### In-Memory (for SSE streaming)

```python
# Cursor-based incremental query
entries, new_cursor = logger.get_cache_entries_since(cursor=0)
```

### General Query

```python
logs = logger.get_logs(
    limit=100,
    level="INFO",            # Single or set
    from_cache=True,         # If False: DB → file fallback
    offset=0,
    newest_first=True
)
```

---

## File Storage Format

```
logs/{session_id}.log
```

```
================================================================================
Session ID: abc-123
Session Name: My Session
Started: 2026-03-21 15:30:00 KST
================================================================================

[2026-03-21 15:30:01] [COMMAND ] PROMPT: ... | {"type": "command", ...}
[2026-03-21 15:30:05] [RESPONSE] SUCCESS: ... | {"type": "response", ...}
...

================================================================================
Session Ended: 2026-03-21 16:00:00 KST
================================================================================
```

---

## Module-Level Functions

| Function | Description |
|----------|-------------|
| `set_log_database(app_db)` | Set DB reference at startup |
| `get_session_logger(session_id, session_name)` | Get/create from logger registry |
| `remove_session_logger(session_id, delete_file)` | Close logger + unregister |
| `list_session_logs()` | List logs via DB → filesystem scan fallback |
| `read_logs_from_file(session_id, limit, level)` | DB → file parsing fallback |
| `count_logs_for_session(session_id, level)` | Cache → DB fallback |

---

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/commands/logs` | List all session log files |
| `GET` | `/api/commands/logs/{session_id}?limit=&level=&offset=` | Get session logs (level comma-separated) |
| `GET` | `/api/commands/stats` | Overall stats (session count + log files) |
| `GET` | `/api/commands/monitor/{session_id}` | Session monitor (includes recent 50 logs) |

---

## Related Files

```
service/logging/
├── __init__.py              # Public API exports
├── types.py                 # LogLevel, LogEntry
└── session_logger.py        # SessionLogger + module-level functions

controller/command_controller.py  # Log query API endpoints
```
