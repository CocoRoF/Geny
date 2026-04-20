# Plan/02 — Observability (Phase 2)

Four PRs. Covers `analysis/02_env_id_role_logging_gap.md`. Each PR
is independent within this phase — they can be reviewed and
merged in any order, as long as Phase 1 has already landed.

---

## PR #4 — Creation event: add env_id / role / session_type / linked_session_id

**Branch.** `obs/creation-event-enrich`

**Files.**
- `backend/service/langgraph/agent_session_manager.py` (edit
  the `"created"` event dict around lines 565–570)
- Tests.

**Change.**

Today the session log's first entry reads:

```python
session_logger.log_session_event("created", {
    "model": request.model,
    "working_dir": request.working_dir,
    "max_turns": request.max_turns,
    "type": "agent_session",
})
```

Add four fields:

```python
session_logger.log_session_event("created", {
    "model": request.model,
    "working_dir": request.working_dir,
    "max_turns": request.max_turns,
    "type": "agent_session",
    "env_id": env_id,
    "role": request.role.value if request.role else "worker",
    "session_type": request.session_type,          # "vtuber" | "sub" | "solo" | None
    "linked_session_id": request.linked_session_id,
})
```

`env_id` is already resolved earlier in the function (line
~455). `request.role` is set on the request object. The other
two fields come straight from the request.

**Tests.**

1. `test_creation_event_includes_env_id` — create a session
   via the manager, read back the first log entry, assert
   all four new keys are present and correct.
2. `test_creation_event_vtuber_vs_sub` — create a VTuber +
   auto-paired Sub-Worker, assert their respective creation
   events carry the correct `session_type` and
   `linked_session_id`.

**Out of scope.**

- Changing the log entry shape (schema stays append-only).
- Logging deletion / restore events (separate PR if needed).

---

## PR #5 — Per-turn logs: thread env_id / role through

**Branch.** `obs/per-turn-env-role`

**Files.**
- `backend/service/logging/session_logger.py` (extend
  `log_command` and `log_response` signatures)
- `backend/service/execution/agent_executor.py` (two call
  sites around lines 481–485 and 518–522)
- Tests.

**Change.**

Extend the signatures to accept optional `env_id` and `role`:

```python
def log_command(
    self,
    prompt: str,
    *,
    timeout: Optional[float] = None,
    system_prompt: Optional[str] = None,
    max_turns: Optional[int] = None,
    env_id: Optional[str] = None,      # NEW
    role: Optional[str] = None,        # NEW
) -> None:
    metadata = {...}
    if env_id is not None:
        metadata["env_id"] = env_id
    if role is not None:
        metadata["role"] = role
    self._emit("command", prompt, metadata)
```

Same for `log_response`. Both keep kwargs optional so no caller
breaks; the executor call sites pass them explicitly.

In `agent_executor.py`, the executor already has a handle on the
`AgentSession` instance. Add:

```python
session_logger.log_command(
    prompt=prompt,
    timeout=timeout,
    system_prompt=system_prompt,
    max_turns=max_turns,
    env_id=agent._env_id,
    role=str(agent._role.value if agent._role else "worker"),
)
```

(If `_env_id` / `_role` access is painful, add a thin accessor
on `AgentSession`.)

**Tests.**

1. `test_log_command_includes_env_id` — execute a command,
   inspect the log entry metadata for `env_id`.
2. `test_log_response_includes_role` — same for response.
3. Round-trip: `test_log_roundtrip_through_logstab_payload` —
   the log entry serializes into the same shape the frontend
   expects (no breakage to `LogEntryMetadata`).

**Out of scope.**

- Tool-call specific logs (deferred to PR #7).
- Backfilling old sessions. New sessions start carrying the
  fields; old logs stay as they are.

---

## PR #6 — LogsTab: sticky header showing session env / role / session_type

**Branch.** `obs/logstab-header`

**Files.**
- `frontend/src/components/tabs/LogsTab.tsx` (add header)
- `frontend/src/lib/i18n/en.ts` (new strings)
- `frontend/src/lib/i18n/ko.ts` (new strings)

**Change.**

Add a sticky header band at the top of LogsTab that renders:

```
┌────────────────────────────────────────────────────────────────┐
│ [VTuber | template-vtuber-env] {session_name}   [paired: sub…]│
└────────────────────────────────────────────────────────────────┘
```

Fields (from the already-available SessionInfo payload):

- `session_type` — badge ("VTuber" / "Sub" / "Solo")
- `role` — secondary badge
- `env_id` — clickable, opens the env detail drawer (same
  behavior as InfoTab line 179)
- If `linked_session_id` present, show a small "paired:
  <name-or-8-char-id>" chip that navigates to the linked
  session

**Keep InfoTab unchanged.** Duplication is intentional — LogsTab
is where operators stare for long periods, InfoTab is a
one-click drill-down.

**Tests.**

Frontend has no test runner in this workspace, but add a
self-review checklist to the progress doc:

- [ ] Open a VTuber session; header shows
      "VTuber | template-vtuber-env" and a paired-Sub chip.
- [ ] Open the paired Sub-Worker; header shows
      "Sub | template-worker-env" and a paired-VTuber chip.
- [ ] Click the env chip; env drawer opens.
- [ ] Click the paired chip; navigates to the linked session.

**Out of scope.**

- Per-log-entry role badges. Header-level context is enough;
  adding per-row chips clutters the feed.
- Light/dark mode tweaking.

---

## PR #7 — Delegation events: emit `delegation.sent` / `delegation.received`

**Branch.** `obs/delegation-events`

**Files.**
- `backend/service/vtuber/delegation.py` (emit new structured
  events at message formatting time)
- `backend/service/execution/agent_executor.py` (emit on
  `_notify_linked_vtuber` entry)
- `backend/service/logging/session_logger.py` (new log event
  type or route through the existing event stream)
- Frontend `LogsTab.tsx` (render new entry kind)

**Change.**

Whenever a message carrying a `DelegationTag` crosses between
sessions, emit a structured event on *both* sides of the
transfer:

```json
// On the sender's side
{
  "event": "delegation.sent",
  "tag": "[DELEGATION_REQUEST]" | "[SUB_WORKER_RESULT]" | ...,
  "from_session_id": "<vtuber_id>",
  "from_role": "vtuber",
  "to_session_id": "<sub_id>",
  "to_role": "sub",
  "task_id": "<task_id>",
  "timestamp": "2026-04-20T…"
}

// On the receiver's side
{
  "event": "delegation.received",
  ...mirror...
}
```

Surface in LogsTab as a distinguishable row type — arrow icon
and both session ids. Lets an operator trace a delegation
chain at a glance.

Hook points:

- Sender emission: `delegation.format_delegation_request()`,
  `delegation.format_delegation_result()`, and the raw
  `DelegationMessage.format()` — emit just before returning the
  formatted string.
- Receiver emission: `_notify_linked_vtuber()` in
  `agent_executor.py` (and the inbox delivery path for
  fallback) — emit when the message actually enters the
  recipient's event stream.

**Tests.**

1. `test_delegation_sent_event_emitted_on_dm` — send a DM
   from a mock VTuber to a mock Sub-Worker; assert the
   VTuber's log stream contains a `delegation.sent` event.
2. `test_delegation_received_event_emitted` — on the Sub-Worker
   side, the matched `delegation.received`.
3. Smoke: round-trip a full delegation and inspect both sides'
   event streams.

**Out of scope for this PR (but useful follow-ups).**

- OpenTelemetry spans bridging delegation events into a proper
  distributed trace.
- Persisting delegation events to a separate table for
  cross-session querying.

---

## Verification at the end of Phase 2

Manual smoke:

- [ ] Any session created after Phase 2 merge has env_id / role
      / session_type in its `.log` file's "created" entry.
- [ ] Every command/response entry in `.log` includes env_id
      and role metadata.
- [ ] LogsTab header visibly displays env / role on every
      session.
- [ ] Delegating from VTuber to Sub-Worker produces a
      `delegation.sent` entry in the VTuber's log and a
      `delegation.received` entry in the Sub-Worker's log,
      both with matching `task_id`.

---

## Rollback plan

All four PRs are additive. Reverting any one:

- PR #4: creation events lose the four fields, no other impact.
- PR #5: log_command / log_response signatures add optional
  kwargs; reverting means older logs stop gaining the fields.
- PR #6: LogsTab loses the header band. Works without it.
- PR #7: the event stream loses the new entry type. LogsTab
  either tolerates unknown types (if that's the current
  pattern) or needs a small follow-up.
