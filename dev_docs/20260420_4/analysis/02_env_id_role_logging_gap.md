# Analysis 02 — env_id / role are invisible in per-turn runtime logs

**Severity: LOW-MEDIUM (observability).** The SessionInfo API and
the InfoTab UI already carry `env_id`, `role`, and `session_type`;
a user can see them by clicking into a session's Info tab. But the
**per-turn log entries** that scroll through LogsTab — the surface
the user actually watches while an agent runs — carry **none** of
those fields. When two agents (a VTuber and its Sub-Worker) are
both logging turns simultaneously, there is no way to tell which
line came from which environment without jumping back to InfoTab
and mentally correlating by session_id.

The user's complaint translates to: *"When inspecting each session's
pipeline environment, logging VTuber/Sub-Worker transitions is
impossible. Because of this, I cannot see which environment is
being used."*

---

## 1. What already works (do not re-fix)

### 1.1 Resolution logging at session creation

`EnvironmentService` resolves the env and logs the result at INFO
level.

**`backend/service/langgraph/agent_session_manager.py:480–483`**:

```
"env_id: {env_id} → manifest-backed pipeline built (adhoc_providers=…)"
```

And again when the pipeline is adopted:

**`backend/service/langgraph/agent_session.py:794–803`**:

```
"[{session_id}] Pipeline adopted + runtime attached: "
"preset=env:{env_id}, role={role}, ..."
```

Both lines land in the backend logger (stdout / structured log
handler), not in the per-session LogsTab. They are useful for
server-side debugging, but a UI user watching LogsTab sees nothing.

### 1.2 SessionInfo API carries the fields

**`backend/service/claude_manager/models.py:347–350`** — `SessionInfo`
schema declares `env_id: Optional[str]`.

**`backend/service/langgraph/agent_session.py:1466–1467`** — the
accessor populates it:

```python
env_id=self._env_id,
```

Plus `role` (models.py:289–292) and `session_type` (normalized via
`_normalize_session_type`, lines 19–22).

The REST endpoint `GET /sessions/{id}` returns the full
SessionInfo, so the frontend has everything it needs.

### 1.3 InfoTab renders all three fields

**`frontend/src/components/tabs/InfoTab.tsx`**:

- Line 166: renders `role`.
- Lines 178–181: renders `env_id` as a clickable link that opens
  the environment detail drawer.
- Line 183: renders `session_type` (`"vtuber"` / `"sub"` / `"solo"`).

So for the "which env does this session use?" question, the answer
is *already* a click away. The real gap is in the LogsTab surface.

### 1.4 Frontend types are complete

**`frontend/src/types/index.ts:3–28`** — `SessionInfo` TypeScript
type includes `env_id?: string | null`, `role`, and
`session_type?: string | null`.

---

## 2. What is missing — per-turn logging

### 2.1 Session creation event

**`backend/service/langgraph/agent_session_manager.py:565–570`**
is where a session's "created" event is written to the per-session
log file:

```python
session_logger.log_session_event("created", {
    "model": request.model,
    "working_dir": request.working_dir,
    "max_turns": request.max_turns,
    "type": "agent_session",
})
```

**Missing:** `env_id`, `role`, `session_type`, `linked_session_id`.
The session log starts with a "created" entry that does not record
the environment it was bound to. A postmortem reading a log file
later cannot determine which env the run used.

### 2.2 Command / response log entries

**`backend/service/logging/session_logger.py:235–340`** —
`log_command(...)` and `log_response(...)` accept a fixed set of
fields:

```python
log_command(prompt, timeout, system_prompt, max_turns)
log_response(success, output, duration, cost, ...)
```

Neither includes `env_id` / `role` / `session_type`. These are the
entries LogsTab consumes. So every turn in the UI is a wall of
logs with no environment context.

### 2.3 Executor tool-call events

When a turn runs, the executor emits events like `stage.enter`,
`stage.bypass`, `tool.call`, etc. These surface on the Geny side
via the event bridge (`backend/service/execution/agent_executor.py`).
Spot-check: none of the emitted events carry `env_id` or `role`.

Which matters because of Analysis/01: `stage.bypass` events fire
for the missing stages 10/11/14 on every turn, but an operator
sees them with no indication of "this is happening on
`template-worker-env`" vs "this is happening on
`template-vtuber-env`". The bypass events become noise instead of
signal.

---

## 3. VTuber vs Sub-Worker distinction in logs

The user phrased the issue as *"VTuber / CLI 변환 로깅이
불가능해"* — literally "it's impossible to log the VTuber / Sub-
Worker conversion." Two readings, both true:

**Reading A — per-line role visibility.** When the VTuber delegates
to its Sub-Worker, the operator wants to see a log stream like:

```
[vtuber/template-vtuber-env] turn 3 → tool_call geny_send_direct_message
[sub/template-worker-env]    turn 1 ← received delegation
[sub/template-worker-env]    turn 1 → tool_call Read
[sub/template-worker-env]    turn 1 ← Read result
[sub/template-worker-env]    turn 2 → SUB_WORKER_RESULT
[vtuber/template-vtuber-env] turn 4 ← SUB_WORKER_RESULT received
```

Today they see each session's LogsTab independently, with no tag
on either side indicating role or env. If the LogsTab is a global
stream (not per-session), which several screens imply, there is no
way to tell VTuber lines from Sub-Worker lines except by staring
at the session_id prefix.

**Reading B — delegation protocol events.** There is no structured
log event emitted when a `[DELEGATION_REQUEST]` / `[SUB_WORKER_RESULT]`
crosses between sessions. The tag lives inside the message text,
and the TTS filter strips it before display. An operator
debugging "did the delegation actually fire?" has no signal except
the raw message text.

Both readings point to the same fix: **carry role + env_id on
every log/event**, and **emit explicit delegation events** at the
DM boundary.

---

## 4. Minimum-viable fix scope

Ordered by effort.

### Tier 1 — enrich session-creation event (trivial)

Add `env_id`, `role`, `session_type`, `linked_session_id` to the
dict at `agent_session_manager.py:565–570`. One commit, three
lines, no schema changes. Opens every session log with the env
context on the first line.

### Tier 2 — thread env/role through per-turn logs (small)

Update `session_logger.log_command()` / `log_response()` signatures
in `backend/service/logging/session_logger.py` to accept
`env_id` / `role`, and update the two call sites in
`agent_executor.py:481–485` and `agent_executor.py:518–522` to
pass them. Every turn line gets prefixed with env + role.

### Tier 3 — LogsTab rendering (frontend-only)

Add a sticky header in `LogsTab.tsx` showing the session's
`session_type`, `role`, `env_id` (linked to env detail drawer,
mirroring InfoTab line 179). Optional: add a subtle badge in each
log entry showing the role (1-character chip).

### Tier 4 — explicit delegation events (moderate)

Emit a structured `delegation.sent` / `delegation.received` event
in `backend/service/vtuber/delegation.py` whenever a DM carrying a
`DelegationTag` crosses between sessions. Event carries both
session_ids, tag, timestamp. Surface in LogsTab as a
cross-session row.

Tier 4 is the piece that actually closes the user's complaint
about *"VTuber / CLI 변환 로깅이 불가능해"* — it makes the
transition *itself* a first-class log entry, not a thing inferable
from timing and message text.

---

## 5. Out of scope

- Restructuring the session_logger to a different storage format
  (JSON lines vs DB) — orthogonal to this cycle.
- Cross-session correlated tracing (OpenTelemetry-style) — too big
  for an analysis cycle; note for future.
- Moving env resolution to a different layer.

---

## 6. Citations

| Claim | File:line |
|-------|-----------|
| env_id logged at INFO on create | `backend/service/langgraph/agent_session_manager.py:480–483` |
| env_id logged at pipeline adopt | `backend/service/langgraph/agent_session.py:794–803` |
| SessionInfo schema has env_id | `backend/service/claude_manager/models.py:347–350` |
| SessionInfo populated with env_id | `backend/service/langgraph/agent_session.py:1466–1467` |
| InfoTab renders env_id / role / session_type | `frontend/src/components/tabs/InfoTab.tsx:166,178–181,183` |
| Frontend type has all fields | `frontend/src/types/index.ts:3–28` |
| Creation event omits env_id/role/session_type | `backend/service/langgraph/agent_session_manager.py:565–570` |
| log_command / log_response signature | `backend/service/logging/session_logger.py:235–340` |
| per-turn log call sites | `backend/service/execution/agent_executor.py:481–485,518–522` |
| delegation tag emission | `backend/service/vtuber/delegation.py` |
