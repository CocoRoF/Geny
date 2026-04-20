# BoundWorker Contract

> Every VTuber session owns exactly one Worker session. This document is the authoritative spec for how that binding is formed, what holds it together, and how it comes apart.

## Intent

VTuber sessions are the **persona layer** — conversational, in character, optimized for dialog context. Worker sessions are the **execution layer** — tool-heavy, multi-turn, optimized for getting real work done. A VTuber that tries to do both ends up with a bloated system prompt and poor persona consistency; a Worker that tries to hold a conversation does neither well.

The Bound Worker binding makes the two-agent split **first-class**:

- The VTuber's creation request carries the Worker's config (`bound_worker_model`, `bound_worker_system_prompt`, `bound_worker_env_id`).
- The system spawns the Worker atomically as part of VTuber startup.
- The Worker's `session_id` is injected into the VTuber's system prompt as a `## Bound Worker Agent` block, so the VTuber knows who to talk to for complex work.
- The Worker's `linked_session_id` back-references the VTuber, so when the Worker finishes a task it knows who to reply to.

Delegation is just `geny_send_direct_message` from the VTuber to the bound Worker's `session_id`. The reply arrives in the VTuber's inbox tagged `[CLI_RESULT]` and is summarized in persona.

---

## Invariants

### I1. One-to-one

A VTuber session has **exactly one** bound Worker. A Worker session is bound to **at most one** VTuber.

- Enforced at creation: the auto-pair block in `AgentSessionManager.create_session` runs exactly once per VTuber request, guarded by `session_type != "bound" and not linked_session_id`.
- Not enforced at runtime: nothing stops a caller from manually calling `create_session(role=WORKER, linked_session_id=<vtuber_id>, session_type="bound")` a second time. Don't do that. See **Non-goals**.

### I2. Bind at creation

The binding is formed **during VTuber session creation**, not retroactively. There is no `bind_worker(vtuber_id, worker_id)` API.

- The rationale: the VTuber's system prompt depends on knowing the Worker's `session_id` at build time. Late-binding would require tearing down and rebuilding the VTuber's pipeline, which is not a supported operation.

### I3. Dissolve at termination

When either side of the binding terminates, the binding is dissolved.

- **VTuber terminates**: the bound Worker is a leaf and can be cleaned up by the session store's normal termination path. `agent_session_manager.stop_session(vtuber_id)` does **not** currently cascade to the bound Worker — the Worker survives and can be targeted directly. This is intentional (see the **Orphan Worker** failure mode below).
- **Worker terminates**: the VTuber's `## Bound Worker Agent` block now references a dead session. Subsequent `geny_send_direct_message` calls will fail at the tool layer with `is_error=True`. The VTuber remains functional but delegation is broken until a new VTuber session is created.

### I4. No hot-swap

The bound Worker's `session_id`, `env_id`, `model`, and `system_prompt` are frozen at VTuber creation time. There is no API to swap one Worker out for another while keeping the VTuber alive.

- To change Worker config, create a new VTuber session with the desired `bound_worker_*` fields.

### I5. Bound Workers cannot themselves bind

A Worker session with `session_type == "bound"` cannot trigger another auto-pair spawn. The recursion guard in `AgentSessionManager.create_session` is:

```python
if (
    request.role == SessionRole.VTUBER
    and request.session_type != "bound"
    and not request.linked_session_id
):
    # spawn bound Worker
```

The `session_type != "bound"` clause is the load-bearing check. `not linked_session_id` is a second predicate that catches any request already carrying a link (belt-and-braces).

---

## Session lifecycle

### Creation sequence

```
Client POST /api/sessions
    │
    ▼
AgentSessionManager.create_session(role=VTUBER, bound_worker_env_id=...)
    │
    ├─ resolve_env_id(VTUBER, request.env_id)         → env_id: "template-vtuber-env"
    ├─ build manifest from env_id
    ├─ instantiate AgentSession (V1)
    ├─ attach_runtime(system_builder, tool_context, …)
    ├─ start pipeline for V1
    │
    ├─ recursion guard: role==VTUBER, session_type!="bound", linked_session_id is None  ✓
    │
    ├─ build worker_request:
    │     role                      = WORKER
    │     env_id                    = request.bound_worker_env_id   (may be None)
    │     model                     = request.bound_worker_model    (may be None)
    │     system_prompt             = request.bound_worker_system_prompt
    │     linked_session_id         = V1.session_id
    │     session_type              = "bound"
    │
    ├─ recurse: create_session(worker_request)
    │     └─ resolve_env_id(WORKER, request.env_id)   → "template-worker-env" if None
    │     └─ guard: session_type=="bound"   ✗  (no further spawn)
    │     └─ returns W1
    │
    ├─ inject V1._system_prompt += "## Bound Worker Agent\n… session_id=`W1` …"
    ├─ log "🔗 Bound Worker created: W1"
    │
    ▼
Return V1 to client.  W1 exists, back-linked to V1, addressable via DM.
```

### Termination paths

| Initiator | Effect on VTuber | Effect on bound Worker |
|-----------|------------------|------------------------|
| Client stops V1 | V1 → STOPPED | W1 continues running (can be stopped separately) |
| Client stops W1 | V1 continues; future DMs to W1 fail | W1 → STOPPED |
| V1 crashes | V1 → ERROR | W1 unaffected; can be reparented manually if needed |
| W1 crashes | V1 continues; next DM to W1 fails at tool layer | W1 → ERROR |
| Idle monitor | V1 stays RUNNING (VTubers are always-on) | W1 stays RUNNING (bound Workers share the always-on policy via `AgentSession._is_always_on`) |

No automatic cascade: stopping one side does not stop the other. Operators who want both-gone need to call `stop_session` twice, or rely on the session store's bulk cleanup.

### Restoration after restart

When the backend restarts, `AgentSessionManager._build_system_prompt` re-runs during session restoration. For VTubers, the `role == "vtuber" and request.linked_session_id` branch re-injects the `## Bound Worker Agent` block using the persisted `linked_session_id`. The wording matches the auto-pair creation path verbatim, so a VTuber reads the same system prompt across restarts.

---

## env_id resolution

Bound Workers flow through `resolve_env_id(role, explicit)` just like any other session (see `plan/02_default_env_ids.md`):

| `bound_worker_env_id` passed | Effect |
|------------------------------|--------|
| `None` (default) | `resolve_env_id(WORKER, None)` → falls back to `ROLE_DEFAULT_ENV_ID[WORKER]` = `"template-worker-env"` |
| `"template-worker-env"` | Explicit default; same behavior as `None` but documented |
| `"template-developer-env"` | Bound Worker runs with the developer manifest (broader tool surface, dev-oriented system prompt) |
| Unknown env_id | `resolve_env_id` raises at VTuber creation time → client gets an error, no partial state |

Under plan/02, envs own stage layout and `manifest.tools.built_in` / `.external` carry tool selection. The bound Worker has no `workflow_id` / `graph_name` / `tool_preset_id` overrides in the auto-pair path — if you need something custom, author a new env.

---

## Failure modes

### Worker unavailable at send time

Symptom: VTuber calls `geny_send_direct_message(target_session_id=<W1>, …)` and gets `is_error=True`.

Handling:
- The MCP tool layer returns the error to the VTuber's agent loop as a normal tool result.
- The VTuber is expected to recover conversationally ("뭔가 문제가 생긴 것 같아…") rather than retry blindly.
- **No automatic restart.** Re-creating the Worker would violate I4 (no hot-swap) and require regenerating the VTuber's system prompt.

### Inbox full

Symptom: `InboxManager.deliver` raises or truncates when the target session's inbox exceeds its retention window.

Handling:
- Inbox retention is a global policy (see `SHARED_FOLDER.md` cleanup rules — inboxes are currently unbounded JSON files). An overflow is not expected under normal use.
- If it occurs, the producer-side tool call surfaces an error to the VTuber's agent loop. Same recovery path as "Worker unavailable."

### Tool call timeout

Symptom: VTuber's `geny_send_direct_message` call does not return within the MCP tool timeout (default 60s for simple send; longer for `execute`-style tools that wait on a reply).

Handling:
- `geny_send_direct_message` is fire-and-forget — it only confirms the DM was queued, not that the Worker has processed it. The normal path is: VTuber calls send → returns quickly → Worker processes asynchronously → Worker replies with its own `geny_send_direct_message` tagged `[CLI_RESULT]` → arrives in VTuber's inbox → VTuber's next agent turn drains inbox.
- If the VTuber wants to wait on a specific result, it should stay in persona ("잠시만, 알아볼게!") and let the `[CLI_RESULT]` trigger wake it up when the Worker finishes.

### Orphan Worker (VTuber gone, Worker alive)

Symptom: VTuber session stopped or crashed; bound Worker still in the session store.

Handling:
- The Worker remains addressable via direct DM from other sessions. This is **intentional** — it lets operators debug or reuse the Worker independently.
- The session store's bulk cleanup (`DELETE FROM sessions WHERE ended_at < NOW() - INTERVAL '7 days'`) eventually removes it. There is no shorter TTL specific to orphaned bound Workers.

### Recursion guard failure

Symptom: A VTuber request slips past the recursion guard and spawns an infinite chain of bound Workers.

Handling:
- The guard is `session_type != "bound" and not linked_session_id`. A bug that sets neither field on a bound Worker request would break this. Smoke tests in PRs 18 + 20 verify the current guard holds.
- If it ever does fail in practice, `SessionStore.count_active_sessions()` will spike and the idle monitor log will show many `🔗 Bound Worker created:` lines in a tight window. Kill the runaway sessions manually.

---

## Non-goals

These are **explicitly out of scope** for the BoundWorker contract as designed. They are not bugs; they are features we chose not to build.

### Multi-Worker fan-out

*"A VTuber with two bound Workers — one for code, one for research."*

Not supported. The binding is 1:1 by invariant I1. To approximate fan-out, a single Worker can itself delegate to sub-sessions via `geny_send_direct_message` (targeting any session, not just a bound one). But the VTuber still sees one Worker.

### Hot-swap

*"Replace the bound Worker without recreating the VTuber."*

Not supported. See invariant I4. Rebuilding the VTuber's system prompt at runtime was evaluated and rejected — it would require tearing down and re-attaching the pipeline, which is not idempotent in the current executor (v0.26.0).

### Cross-VTuber sharing

*"Two VTubers sharing one bound Worker to save resources."*

Not supported. The Worker's `linked_session_id` is a single field, not a list. Back-replies via `[CLI_RESULT]` target exactly one VTuber. Sharing would require a routing layer.

### Dynamic rebind

*"Re-bind the Worker to a different VTuber when the first one ends."*

Not supported. When a VTuber terminates, its bound Worker becomes an orphan Worker (see **Failure modes**), not a pool resource. If a future need emerges, it would be a new feature — not a repair of the current contract.

---

## Related code

| File | Role in the binding |
|------|---------------------|
| `service/claude_manager/models.py` | `CreateSessionRequest.bound_worker_model` / `_system_prompt` / `_env_id`; `session_type` enum values include `"bound"` |
| `service/langgraph/agent_session_manager.py` | Auto-pair block in `create_session`; recursion guard; prompt injection at creation and restoration |
| `service/langgraph/agent_session.py` | `_session_type` field and `_is_always_warm` policy (`"bound"` → not always warm) |
| `service/execution/agent_executor.py` | Emits `[CLI_RESULT]`-tagged replies from Worker → VTuber on task completion |
| `service/vtuber/delegation.py` | `DelegationTag.CLI_RESULT` / `ACTIVITY_TRIGGER` literals consumed by the VTuber agent loop |
| `service/vtuber/thinking_trigger.py` | Emits `[ACTIVITY_TRIGGER]` prompts that the VTuber then delegates to its bound Worker |
| `controller/tts_controller.py` | Strips `[CLI_RESULT]` / `[ACTIVITY_TRIGGER]` tag literals before TTS output |
| `prompts/vtuber.md` | VTuber persona base prompt — delegation paragraph, trigger handling |

## See also

- [`SESSIONS.md`](SESSIONS.md) — general session lifecycle, idle monitor, state machine
- [`PROMPTS.md`](PROMPTS.md) — prompt layer architecture and token budgets
- [`EXECUTION.md`](EXECUTION.md) — agent executor, `[CLI_RESULT]` emission, tool call flow
- `dev_docs/20260420_3/plan/03_vtuber_worker_binding.md` — the plan that produced this contract
- `dev_docs/20260420_3/plan/02_default_env_ids.md` — `resolve_env_id` and role defaults
