# Plan 03 — VTuber ↔ Worker binding (first-class feature)

The Geny philosophy, stated by the user:

> VTuber는 대화를 위한 경량적 ENVIRONMENT고, 나머지는 WORKER로 제대로 된
> 업무 수행을 위한 것이야. VTUBER는 이러한 Worker를 하나씩 자신과 BIND하여
> 가지고 있고, 그것을 활용할 수 있는 능력이 있는 것이 우리 GENY의 기본 철학이야.

Translation: VTuber is the **persona layer** (conversational,
lightweight); Worker is the **execution layer** (task-capable).
A VTuber **binds** a Worker to itself and delegates real work to
it.

This plan formalizes the existing CLI-pairing scaffolding
(`agent_session_manager.py:587-660`) into a first-class
`BoundWorker` feature on top of the environment-only architecture
from Plan/02.

---

## Why this needs a dedicated plan

The current implementation works as a happy-path prototype but
has three rough edges that matter once every session is
environment-backed:

1. **Naming**: the paired session is called a "CLI session" in
   code, with fields `cli_model`, `cli_system_prompt`,
   `cli_workflow_id`, `cli_tool_preset_id`. The name predates the
   Worker/VTuber split and causes every new reader to ask "what
   CLI?". Rename to `bound_worker_*`.
2. **Manifest coupling**: the paired session is created with
   `workflow_id="template-optimized-autonomous"` and a hardcoded
   graph_name. Under Plan/02, session creation goes through
   `env_id` and role resolution; the paired session must pass the
   same gate instead of carrying its own `workflow_id`.
3. **Lifecycle ambiguity**: when the VTuber ends, what happens to
   the bound Worker? When the Worker crashes, does the VTuber
   know? Today both are undefined; we document the contract here.

---

## Model

```
┌────────────────────────────┐
│  VTuber session            │
│    role: VTUBER            │
│    env_id: template-vtuber │
│    session_type: "vtuber"  │
│    linked_session_id: W1 ──┼────┐
│    chat_room_id: R1        │    │
└────────────────────────────┘    │
                                  │  bound to
                                  ▼
┌────────────────────────────┐
│  Bound Worker session      │
│    role: WORKER            │
│    env_id: template-worker │
│    session_type: "bound"   │  ← renamed from "cli"
│    linked_session_id: V ───┼────┐
│    bound_to_session_id: V  │    │  back-reference
└────────────────────────────┘    │
                                  ▼
                                VTuber
```

Invariants:

- A VTuber **always** has exactly one bound Worker. No VTuber
  without a Worker; no VTuber with multiple concurrent Workers.
  (Multi-Worker fan-out is a future extension, explicitly out of
  scope here.)
- A Worker **may or may not** be bound. Solo Worker sessions
  still exist — that's the default for developer / researcher /
  planner / plain worker roles. `session_type` distinguishes:
  - `"vtuber"` — is the persona layer
  - `"bound"` — is the executor bound to a VTuber
  - `"solo"` (or unset) — standalone Worker

- The bind is established **atomically at VTuber creation** and
  dissolved **at VTuber termination**. A user cannot "rebind" a
  different Worker mid-session through the UI in this plan; that
  is a later feature.

---

## Session lifecycle

### Creation (VTuber)

1. `AgentSessionManager.create_agent_session(request)` resolves
   `env_id = resolve_env_id(request.role, request.env_id)`. For
   `role=VTUBER` and no explicit env, this is
   `template-vtuber-env`.
2. `EnvironmentService.instantiate_pipeline(env_id, ...)` builds
   the VTuber pipeline from the vtuber manifest.
3. `AgentSession` is created and registered with
   `session_type="vtuber"` and a placeholder
   `linked_session_id=None`.
4. **Spawn the bound Worker**: build a `CreateSessionRequest`
   that carries:
   - `role=WORKER`
   - `env_id=None` (let role resolver pick `template-worker-env`)
   - `session_name=f"{vtuber.session_name}_worker"`
   - `working_dir=vtuber.storage_path` (shared, so memory is
     shared across the pair)
   - `linked_session_id=vtuber.session_id`
   - `session_type="bound"`
   - Optional overrides from request: `bound_worker_model`,
     `bound_worker_system_prompt`, `bound_worker_max_turns`
5. Call `create_agent_session(bound_request)` recursively. The
   recursive call will *not* re-spawn another Worker because the
   role is WORKER, not VTUBER. (Recursion guard is explicit:
   `if request.role == VTUBER and request.session_type != "bound"`.)
6. Back-link: update VTuber session with
   `linked_session_id=worker.session_id`.
7. Inject the delegation block into the VTuber's system prompt:

   ```text
   ## Bound Worker Agent

   You have a Worker agent bound to you: session_id=`<W1>`.
   For complex tasks (coding, research, multi-step execution),
   delegate to the Worker via the `geny_send_direct_message`
   tool with target_session_id=`<W1>`. The Worker's reply will
   arrive in your inbox; read it with `geny_read_inbox` and
   summarize for the user.
   ```
8. Create the VTuber's chat room (existing behavior).
9. Register the VTuber with `ThinkingTriggerService` (existing).

### Creation (plain Worker / developer / researcher / planner)

Same resolver path; no binding, no spawn, no back-link.
`session_type="solo"` (or absent — handled as solo by default).

### Termination

VTuber termination (user closes session, timeout, explicit stop):

- Terminate the VTuber session first (flush memory, emit
  termination events, unregister from trigger service).
- Immediately terminate the bound Worker session. The Worker's
  termination flushes its own memory (which, under shared
  `working_dir`, lives in the same on-disk store that the VTuber
  was writing to).
- Remove the VTuber's chat room only if it has no other
  participants.

Worker termination (only possible if it terminates **first**):

- The Worker's own termination proceeds normally.
- The VTuber's session record is updated:
  `linked_session_id=None`, `bound_worker_status="terminated"`.
- Optionally inject a notice into the VTuber's system prompt on
  next turn: "Your bound Worker has terminated. Delegation is
  unavailable until a new Worker is spawned." (UI hook; not
  implemented in the cutover PR.)

### Worker crash mid-session

If the bound Worker's pipeline raises an uncaught error:

- The `ToolResult(is_error=True)` that `geny_send_direct_message`
  receives is returned to the VTuber. The VTuber sees the error
  in tool results normally — no special handling required.
- The Worker session stays registered but in
  `SessionStatus.ERROR`. Automatic restart is **not** in scope
  here; user can manually terminate/replace.

---

## Existing code to touch

### `backend/service/claude_manager/models.py`

`CreateSessionRequest` today has:

- `cli_model`, `cli_system_prompt`, `cli_workflow_id`,
  `cli_graph_name`, `cli_tool_preset_id`
- `linked_session_id`, `session_type`

Rename / reshape:

- `cli_model` → `bound_worker_model`
- `cli_system_prompt` → `bound_worker_system_prompt`
- `cli_workflow_id` → **DELETE** (under Plan/02, workflow_id is
  gone; envs own stage layout)
- `cli_graph_name` → **DELETE** (same)
- `cli_tool_preset_id` → **DELETE** (under Plan/02, env carries
  the tool list)
- Add `bound_worker_env_id: Optional[str] = None` — explicit
  override if a VTuber wants a non-default Worker env. Default
  `None` → role resolver picks `template-worker-env`.
- `linked_session_id` — keep as-is.
- `session_type` — expand enum values: `"vtuber"`, `"bound"`,
  `"solo"` (was `"vtuber"`, `"cli"`).

No backward compatibility. Any external caller that sent `cli_*`
fields (internal UI only, not a public API) updates in the same
PR that changes the model.

### `backend/service/langgraph/agent_session_manager.py:587-660`

Existing block is the VTuber auto-pair hook. Changes:

- Rename the local variables: `cli_name` → `worker_name`,
  `cli_request` → `worker_request`, `cli_agent` → `worker_agent`,
  `cli_id` → `worker_session_id`.
- Remove `workflow_id=request.cli_workflow_id or ...` — the
  request no longer carries `workflow_id`; env_id resolution
  handles this.
- Remove `tool_preset_id=request.cli_tool_preset_id` — same
  reason.
- Add `env_id=request.bound_worker_env_id` so the resolver picks
  the default when unset.
- Update the prompt injection text from "Paired CLI Agent" to
  "Bound Worker Agent".
- Add recursion guard: if this request came *from* the recursive
  spawn (`request.session_type == "bound"`), skip the whole pair
  block. Today the guard is `not request.linked_session_id` which
  works but is implicit — make it explicit on `session_type`.

### `backend/service/langgraph/agent_session.py`

No structural change. The VTuber `AgentSession` object itself
does not know or care that a Worker is bound to it; the binding
is a **session-manager-level** concept. The VTuber's prompt
includes the Worker's session_id as a string, which is
sufficient for it to address DM-based delegation.

The one field that changes on `AgentSession`:

- `self._session_type` — new allowed values `{"vtuber", "bound",
  "solo"}` (was `{"vtuber", "cli", None}`). Add a validator in
  the constructor.

### `backend/service/chat/inbox.py` + `geny_tools.py`

The `geny_send_direct_message` tool already exists and already
does the auto-trigger. No changes. The VTuber calls it with
`target_session_id=<bound_worker_session_id>` and the Worker
picks up the message via `geny_read_inbox` (or automatic
inbox drain).

### `backend/prompts/vtuber.md` (persona base prompt)

Update the guidance for VTubers to explicitly describe the
bound-Worker pattern rather than the old CLI-pair language.
Keep the voice and persona unchanged; just rewrite the
"delegation" paragraph. Exact text lands in the PR; this plan
doesn't fix the wording.

---

## PR decomposition

| # | Title | Depends on |
|---|-------|------------|
| A | **Geny**: rename `cli_*` fields to `bound_worker_*` in `CreateSessionRequest` + all call sites | Plan/02 PR 6 merged |
| B | **Geny**: reshape the VTuber auto-pair block in `create_agent_session` — use env_id resolution, add explicit `session_type == "bound"` recursion guard, update prompt injection text | A |
| C | **Geny**: rewrite `backend/prompts/vtuber.md` delegation paragraph | B |
| D | **Geny**: document BoundWorker contract in `backend/docs/` (invariants, lifecycle, failure modes) | C — purely docs |

Each PR has a matching progress doc in
`dev_docs/20260420_3/progress/`.

Every PR is small enough to review in a single session. A / B are
the load-bearing ones; C / D are documentation-only and can merge
together if review bandwidth allows.

---

## Verification

- [ ] New VTuber session auto-creates bound Worker. Both appear
      in the session list; bound Worker is labeled as such in the
      UI (`session_type="bound"`).
- [ ] VTuber's system prompt contains a "Bound Worker Agent"
      block with the correct Worker session_id.
- [ ] VTuber calls `geny_send_direct_message` to the Worker;
      Worker processes; reply lands in VTuber inbox.
- [ ] Worker spawned solo (without a VTuber) is flagged
      `session_type="solo"` and has no `linked_session_id`.
- [ ] Ending the VTuber ends the bound Worker (both statuses
      move to `TERMINATED`).
- [ ] Worker crash → VTuber sees `is_error=True` in the DM
      tool_result, but stays alive.
- [ ] Recursion guard: the bound Worker does **not** try to
      spawn its own bound Worker.

---

## Non-goals

- **Multi-Worker fan-out** (one VTuber bound to N Workers).
  Future extension; current plan locks to 1:1.
- **Hot-swap of bound Workers** mid-session. Users today create a
  new VTuber if they want a different Worker.
- **Cross-VTuber Worker sharing** (one Worker serves multiple
  VTubers). Not allowed — `linked_session_id` is single-valued
  by design.
- **UI for viewing the bound-Worker relationship.** The backend
  carries the data; the UI surface is a separate cycle's work.
