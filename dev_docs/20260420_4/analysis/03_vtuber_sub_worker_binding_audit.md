# Analysis 03 — VTuber ↔ Sub-Worker binding audit

**User intent:** verify that the VTuber / Sub-Worker binding works
correctly. The user's own impression is "잘 되는 것으로 보이긴 해"
(seems to work). This document exists to back that impression with
evidence — or to surface defects the surface-level observation
missed. Seven areas were audited end-to-end.

**Bottom line.** The happy-path binding is solid: creation,
persistence, restoration, teardown cascade, and frontend
visibility all behave as designed. Two real problems exist, both
concurrency-related — one already documented in
`docs/TRIGGER_CONCURRENCY_ANALYSIS.md` and never fixed, and one
silent-exception gap in the auto-pair block. Neither is a
regression introduced by the 20260420_3 cycle; both pre-date it.

| # | Area | Verdict |
|---|------|---------|
| 1 | Auto-pair block | **OK** (with silent-exception RISK — see §1) |
| 2 | Restoration on reboot | **OK** |
| 3 | Delegation round-trip | **OK happy-path / RISK under concurrency** |
| 4 | Lifecycle / teardown | **OK** (cascade works; orphans are intentional) |
| 5 | One-to-one invariant | **GAP (documented as acceptable)** |
| 6 | Frontend visibility | **OK** |
| 7 | Known concurrency issues | **RISK — two unfixed items** |

---

## 1. Auto-pair block — OK with silent-exception RISK

`backend/service/langgraph/agent_session_manager.py` — the
`create_session` auto-pair block.

**Recursion guard (lines 601–605).** `session_type != "sub" and
not linked_session_id` — both checks fire. Post-PR #169, the
canonical form is `session_type == "sub"`, and legacy values
(`"bound"`, `"cli"`) are normalized at the request validator
before they reach this block, so the `!= "sub"` check is
load-bearing and accurate.

**env_id inheritance (line 627).** Sub-Worker creation passes
`env_id=request.sub_worker_env_id` → resolves via
`resolve_env_id(WORKER, explicit=sub_worker_env_id)` → falls back
to `template-worker-env` when unset. Correct.

**Back-linking (lines 636–642).** After Sub-Worker creation, the
VTuber's `linked_session_id` is set to the Sub-Worker's id; the
Sub-Worker was created with `linked_session_id=<vtuber_id>` on
line 628. Both sides persisted via `_store.update()`.

**Session type (line 629).** Sub-Worker receives exactly `"sub"`,
matching the canonical form after the rename PR #169.

**Prompt injection (lines 648–660, restoration path 290–297).**
VTuber gets a `## Sub-Worker Agent` block with the Worker's
session_id; Sub-Worker gets a `## Paired VTuber Agent` block with
the VTuber's session_id. On restart, the same injection runs
again via `_build_system_prompt()`.

**RISK — silent exception in auto-pair.** The block is wrapped in
a broad `try / except` (around lines 606–689). If Sub-Worker
creation fails mid-way, the VTuber is **already registered** with
`self._store.register()` on line 574 and is returned to the
client. The client sees "session created, id=…" but the returned
session has:

- no `linked_session_id` in the store,
- no `## Sub-Worker Agent` prompt block,
- no back-linked Sub-Worker to delegate to.

Future calls to `geny_send_direct_message` from that VTuber will
route to nothing. The error is logged at ERROR on the backend
(per the exception handler) but there is no client signal, no
retry, and no indication in the UI.

**Proposed mitigation (for plan doc).** Either (a) raise the
exception to the client so the CLI/UI can surface a failure and
the user can retry, or (b) delete the partially-registered VTuber
in the exception path and re-raise, leaving the system in a clean
"nothing was created" state. Option (b) preserves atomicity:
either a full VTuber+Sub-Worker pair is created, or neither is.

---

## 2. Restoration on reboot — OK

When the app restarts, `AgentSessionManager.__init__` loads
persisted sessions. The restoration path reconstructs each
session with the stored `linked_session_id` and `session_type`
values (which are now tolerant of legacy `"bound"` / `"cli"` via
the `_normalize_session_type` validator — see
`backend/service/claude_manager/models.py:16–22`).

Prompt re-injection fires correctly:

- `agent_session_manager.py:275–287` re-checks
  `if role == "vtuber" and request.linked_session_id:` and
  injects the Sub-Worker block.
- `agent_session_manager.py:290–297` re-checks
  `if session_type == "sub" and linked_session_id:` and injects
  the VTuber block.

Always-warm policy in `agent_session.py:340–354` keeps both the
VTuber (`_role == VTUBER`) and the linked Sub-Worker
(`_session_type == "sub" and _linked_session_id`) permanently
warm, so neither idles off between uses.

No issues found.

---

## 3. Delegation round-trip — OK happy-path / RISK under concurrency

### 3.1 Happy path

1. VTuber LLM emits tool call `geny_send_direct_message(target=<sub>, content="…")`.
2. *(Assuming Analysis/01 is fixed)* Stage 10 (tool) resolves the
   tool via the tool registry, which routes through
   `GenyToolProvider` → `InboxManager.deliver()`.
3. The DM appears in the Sub-Worker's inbox.
4. `agent_executor.py:139–227` on the Sub-Worker side runs the
   turn, and on completion formats `[SUB_WORKER_RESULT] …` and
   **attempts immediate execution** on the VTuber
   (`_notify_linked_vtuber`, line 177).
5. If the VTuber is idle, the reply is injected as a new turn.

### 3.2 Concurrency fallback path

If the VTuber is already executing a turn when the Sub-Worker's
reply arrives, `agent_executor.py:178` catches
`AlreadyExecutingError` and falls back to depositing the reply in
the VTuber's inbox (lines 182–187). This is the **safe** path —
the reply is not lost *at this step*.

### 3.3 Orphaning RISK

The `execute_command()` path does **not** drain inbox after a
turn completes. When the in-flight turn ends, the VTuber sits
idle with an unread `[SUB_WORKER_RESULT]` in its inbox and never
picks it up. The VTuber will only read inbox if it happens to
call `geny_read_inbox` proactively — which it typically does not,
because the trigger to do so was supposed to be receiving a
thinking-trigger that mentions the pending result, and the
thinking trigger is only emitted on idle cadence.

Net effect: under load, **Sub-Worker results can be orphaned
permanently in the VTuber's inbox**. The user does not see a
reply; the Sub-Worker did the work but the VTuber never reports
back.

This is Scenario D in `docs/TRIGGER_CONCURRENCY_ANALYSIS.md`.

---

## 4. Lifecycle / teardown — OK

**VTuber delete cascades to Sub-Worker** via
`SessionStore.soft_delete()`, which inspects `linked_session_id`
and recursively soft-deletes the linked session, guarded against
loops by `is_deleted`. Storage metadata is preserved for restore.

**Reverse direction does not cascade.** Deleting a Sub-Worker
independently leaves the VTuber with a stale
`linked_session_id`. Per `backend/docs/SUB_WORKER.md:39–40`, this
is intentional — operators may debug or reuse the Sub-Worker
independently, and the VTuber's attempts to delegate will fail
at the tool layer (target-not-found) rather than cascade-destroy
a persona.

No action required.

---

## 5. One-to-one invariant — GAP (documented as acceptable)

`SUB_WORKER.md:27–28` states the invariant and immediately notes
it is "not enforced at runtime." There is no unique constraint in
`CreateSessionRequest` and no check in `AgentSessionManager` that
would prevent a caller from creating a second Sub-Worker for the
same VTuber, or two VTubers pointing to the same Sub-Worker.

Risk is low in practice because the auto-pair block only fires
once per VTuber create and manual duplicate creation is not
exposed in the REST API. Flagged here for completeness; no fix
recommended unless a misuse becomes observable.

---

## 6. Frontend visibility — OK

`frontend/src/components/obsidian/SessionSelector.tsx:17–19`:

```ts
const visibleSessions = activeSessions.filter(
  (s) => !(s.session_type === 'sub' && s.linked_session_id),
);
```

Exact behavior: hide sessions that are both `sub` and linked. An
unlinked Sub-Worker (debug artifact) stays visible. A bound
Sub-Worker is hidden from the normal sidebar but reachable by
session_id lookup. Correct. No admin-view toggle exists — if
operators need to inspect a bound Sub-Worker routinely, that's a
future enhancement, not a bug.

---

## 7. Known concurrency issues — RISK

`docs/TRIGGER_CONCURRENCY_ANALYSIS.md` enumerates five scenarios
documented but not fixed. Two bear directly on the binding:

### 7.1 Scenario D — Sub-Worker result orphaning

Already described in §3.3. Sub-Worker finishes while VTuber is
busy → result deposits in inbox → inbox is never auto-drained →
result permanently unread. Fix proposed in that doc: add
`_drain_inbox()` in the `finally` block of `execute_command()`.

### 7.2 Scenario E — Activity trigger stepping on user messages

Thinking-trigger sends an activity prompt to VTuber, which
delegates to Sub-Worker. Meanwhile the user's next message also
tries to deposit into the VTuber's inbox. If the trigger has
raced ahead and claimed the execution slot, the user's message
falls back to inbox; if inbox drain is also broken, the user
message is lost under the same failure mode as 7.1.

### 7.3 Trigger-abort gap

There is no mechanism to preempt a running trigger execution when
a user message arrives. The user sees "Currently busy" and their
message is rejected at the boundary. Documented but not
addressed.

---

## 8. Prioritized problems to fix in this cycle

Ordered by severity × likelihood:

1. **[HIGH] Sub-Worker creation failure silently swallowed.**
   Partial-VTuber state is observable in production. Fix by
   atomizing the VTuber+Sub-Worker creation — see §1 mitigation.

2. **[HIGH] Inbox auto-drain missing.** Known concurrency bug;
   Sub-Worker results can vanish. Fix per
   `TRIGGER_CONCURRENCY_ANALYSIS.md:201–226`. Blocked for
   production use at any non-trivial concurrency.

3. **[MEDIUM] Trigger-abort mechanism.** User messages can be
   rejected when a thinking-trigger is in flight. Separate fix
   from #2 but same general surface.

4. **[LOW] One-to-one enforcement at the session manager.**
   Optional; only fix if a misuse is observed. Current
   documentation explicitly permits the absence.

Items 1 and 2 are the ones the user will feel. Plan doc should
sequence them early.

---

## 9. Citations

| Claim | File:line |
|-------|-----------|
| Recursion guard + auto-pair block | `backend/service/langgraph/agent_session_manager.py:595–689` |
| Session-type normalization | `backend/service/claude_manager/models.py:16–22` |
| Restoration re-injects prompts | `backend/service/langgraph/agent_session_manager.py:275–297` |
| Always-warm policy | `backend/service/langgraph/agent_session.py:340–354` |
| Notify-linked-VTuber + inbox fallback | `backend/service/execution/agent_executor.py:139–227` |
| Sub-Worker intentional orphan policy | `backend/docs/SUB_WORKER.md:27–28,39–40` |
| Sidebar hides bound Sub-Worker | `frontend/src/components/obsidian/SessionSelector.tsx:17–19` |
| Concurrency scenarios D / E / trigger-abort | `docs/TRIGGER_CONCURRENCY_ANALYSIS.md` |
