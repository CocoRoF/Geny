# 01 — Hook UI is non-functional (HIGH bug)

**Date:** 2026-04-26
**Severity:** HIGH (silent prod bug — hooks NEVER fire even when fully configured)
**Discovered during:** Cycle 20260426_2 Library coverage audit

## Symptom

The operator opens the Hooks tab, registers a `PRE_TOOL_USE` hook with command `["/usr/local/bin/audit-hook"]` and saves. The UI confirms. They set `GENY_ALLOW_HOOKS=1` and restart. **The hook never fires.**

The reason is silent: Geny writes a settings.json shape that the executor's parser rejects, and the parse failure is swallowed in `service/hooks/install.py` with a single `logger.warning` line.

## Root cause — schema mismatch

Geny serializes (`backend/controller/hook_controller.py:153-160`):

```json
{
  "command": ["/usr/local/bin/audit-hook"],
  "timeout_ms": 1000,
  "tool_filter": ["Bash", "Read"]
}
```

Executor's `HookConfigEntry` (`/home/geny-workspace/geny-executor/src/geny_executor/hooks/config.py:65-90`) requires:

```python
@dataclass(frozen=True)
class HookConfigEntry:
    command: str               # ← must be str, not list
    args: List[str] = []
    timeout_ms: int = 5000
    match: Dict[str, Any] = {} # ← e.g. {"tool": "Bash"}, NOT a list of names
    env: Dict[str, str] = {}
    working_dir: Optional[str] = None
```

`_coerce_entry` (line 136-142) explicitly raises:

```python
command = raw.get("command")
if not isinstance(command, str) or not command.strip():
    raise ValueError(f"{source}: hook entry missing required string 'command'")
```

So the executor's `HookConfig.from_mapping` raises immediately on Geny's payload. The defensive fallback path in `service/hooks/install.py:64-76` constructs `HookConfig` directly with raw dicts, which type-violates the dataclass — at runtime `HookRunner` calls `entry.matches()` / `entry.args` and either throws AttributeError or silently misbehaves.

## Why this hasn't been noticed

`GENY_ALLOW_HOOKS=1` env gate is closed in most deployments. The install layer short-circuits before parsing. The integration health card from C.2 (cycle 20260426_1) flags the env gate as red — not the schema mismatch behind it.

## Field-by-field gap

| Geny writes | Executor expects | Effect |
|---|---|---|
| `command: List[str]` | `command: str` | **PARSE FAILURE** |
| `tool_filter: List[str]` | `match: Dict[str, Any]` | unknown key → silently dropped |
| (nothing) | `args: List[str]` | always empty → command receives no args |
| (nothing) | `env: Dict[str, str]` | no extra env can be set |
| (nothing) | `working_dir: Optional[str]` | no override |
| (nothing top-level) | `audit_log_path: Optional[str]` | no audit log can be configured |

## Event coverage gap

Geny's `_KNOWN_EVENTS` (hook_controller.py:48-56):

> PRE_TOOL_USE, POST_TOOL_USE, USER_PROMPT_SUBMIT, STOP, SESSION_START, SESSION_END, SUBAGENT_STOP, PRE_COMPACT (8 events)

Executor's `HookEvent` enum (`geny_executor/hooks/events.py:16`):

> SESSION_START, SESSION_END, PIPELINE_START, PIPELINE_END, STAGE_ENTER, STAGE_EXIT, USER_PROMPT_SUBMIT, PRE_TOOL_USE, POST_TOOL_USE, POST_TOOL_FAILURE, PERMISSION_REQUEST, PERMISSION_DENIED, LOOP_ITERATION_END, CWD_CHANGED, MCP_SERVER_STATE, NOTIFICATION (16 events)

Geny's whitelist is stale; 8 events are unreachable from the UI even after the schema fix.

## Migration plan

1. **Schema rewrite** (sprint H.1):
   - `HookEntryPayload`: `command: str`, `args: List[str]`, `timeout_ms`, `match: Dict[str, Any]`, `env: Dict[str, str]`, `working_dir: Optional[str]`.
   - Top-level `HookConfigEnvelope`: `enabled`, `entries`, `audit_log_path`.
   - `_KNOWN_EVENTS` synced to executor's enum.
   - Migration on read: `tool_filter: ["X", "Y"]` → `match: {"tool": "X"}` (only single-tool case is preservable; multi-tool entries get split or surfaced as a warning).
   - Migration on read: `command: ["a", "b"]` → `command: "a"`, `args: ["b"]`.

2. **Frontend rewrite** (sprint H.2):
   - 14-event picker (drop the 2 STOP/SUBAGENT_STOP/PRE_COMPACT unless the executor actually has them — verify).
   - Command input (string), separate args input (one per line).
   - Match dict editor (key-value pairs; today's only meaningful key is `tool`, but the dict shape is forward-compat).
   - Env table (key-value pairs).
   - Working_dir input.
   - Audit_log_path input on the top-level header.

3. **End-to-end test** (sprint H.3):
   - Write a hook via the Geny endpoint.
   - Read settings.json file directly.
   - Pass the `hooks` section through executor's `HookConfig.from_mapping`.
   - Assert no exception + entries round-trip.

## Out of scope

- Hook output schema (`HookOutcome`) editing — the executor consumes it; not user-configurable.
- Per-event UI affordances (different fields per event kind) — universal `match` dict suffices for all events today.
