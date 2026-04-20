# Plan/03 — Binding hardening (Phase 3)

Two PRs. Covers the two real defects found in
`analysis/03_vtuber_sub_worker_binding_audit.md`. Both are
concurrency / error-handling edges that pre-date the 20260420_3
cycle but become more visible now that the binding is
first-class.

---

## PR #8 — Atomize VTuber + Sub-Worker creation

**Branch.** `fix/atomic-vtuber-pair`

**Files.**
- `backend/service/langgraph/agent_session_manager.py`
  (rework the auto-pair block around lines 594–689)
- Tests.

**Problem.**

`create_session` today registers the VTuber with the store at
line 574, then attempts to create the Sub-Worker at line ~632.
If Sub-Worker creation raises, the broad `try / except` (lines
606–689) logs the error and returns the VTuber to the caller
*anyway*. The resulting session has:

- `linked_session_id` = null in the store,
- no "Sub-Worker Agent" prompt block,
- no paired Sub-Worker.

Later attempts to delegate via `geny_send_direct_message` fail
silently at the tool layer. The client sees nothing wrong.

**Fix.**

Make VTuber+Sub-Worker creation atomic. Either both succeed, or
neither remains in the store.

Approach — restructure the exception path:

```python
try:
    # ... existing auto-pair block ...
    sub_worker = await self.create_session(sub_request)
    # back-link & prompt-inject (existing code)
except Exception:
    logger.exception(
        "[%s] Sub-Worker auto-pair failed; rolling back VTuber",
        session_id,
    )
    # Remove the VTuber from memory + store so the client can retry
    try:
        await self.delete_session(session_id, hard=True)
    except Exception:
        logger.exception(
            "[%s] Cleanup of partially-created VTuber also failed",
            session_id,
        )
    # Propagate the original failure so the caller knows
    raise
```

`delete_session(hard=True)` — if hard-delete doesn't exist, use
`soft_delete` plus memory eviction. The rollback path must at
minimum: (a) remove the session from `self._sessions`, (b) remove
the store entry, (c) close any already-attached pipeline.

**Tests.**

1. `test_sub_worker_failure_rolls_back_vtuber` — mock Sub-Worker
   creation to raise; assert that after the exception
   propagates, `manager.get_session(vtuber_id)` returns None and
   the store has no entry for either session.
2. `test_sub_worker_success_leaves_both_sessions` — happy path
   unchanged, both sessions present and back-linked.
3. `test_rollback_failure_does_not_leak_state` — mock both
   Sub-Worker creation *and* `delete_session` to raise; assert
   the original exception still propagates and the partial
   state is logged at ERROR with exc_info.

**Out of scope.**

- Retrying Sub-Worker creation automatically. The client is
  responsible for retry.
- Exposing a dedicated REST endpoint for "retry Sub-Worker".
  Existing session creation handles it.

---

## PR #9 — Inbox auto-drain in `execute_command()` finally block

**Branch.** `fix/inbox-auto-drain`

**Files.**
- `backend/service/execution/agent_executor.py` (add
  `_drain_inbox` and invoke it in `execute_command`'s finally
  block; reference the prescription in
  `docs/TRIGGER_CONCURRENCY_ANALYSIS.md:201–226`)
- `backend/service/vtuber/inbox.py` (if needed, add a
  `peek_unread` or `drain_unread` helper)
- Tests.

**Problem.**

Scenario D from `TRIGGER_CONCURRENCY_ANALYSIS.md`:

1. VTuber is executing command A.
2. Sub-Worker finishes task B, calls `_notify_linked_vtuber`.
3. `_notify_linked_vtuber` tries to execute on the VTuber,
   catches `AlreadyExecutingError`, falls back to deposit in
   VTuber's inbox.
4. VTuber finishes command A. **Nothing looks at the inbox.**
5. The `[SUB_WORKER_RESULT]` sits unread indefinitely. The user
   never hears about the Sub-Worker's work.

**Fix.**

Add a `_drain_inbox` method that:

1. Pops unread messages from the session's inbox, **marking them
   consumed as they are pulled** (prevents re-delivery on the
   next drain — the one real loop risk).
2. For each message in order, synthesize a follow-up execution
   — the message becomes the next `prompt` to the agent.

Invoke in `execute_command`'s `finally` block, after the current
execution releases the lock. Use `asyncio.create_task` so the
drain does not block the original caller's return:

```python
finally:
    # ... existing cleanup ...
    if not state.cancelled:
        asyncio.create_task(self._drain_inbox(session_id))
```

**Ordering.** Process one message at a time. Each synthesized
turn runs through `execute_command`, whose own finally block
re-invokes `_drain_inbox` — so multiple queued messages naturally
chain without ever running in parallel. The existing
`AlreadyExecutingError` on re-entry is the backstop.

**No loop-prevention plumbing.** The VTuber↔Sub-Worker binding
has no self-injection path (neither side deposits into its own
inbox in normal operation). The only real loop risk is
re-consuming the same message, and the consumed-on-pull
semantics in step 1 prevents that. We do not add hop counters,
source-tag filters, or recursion guards — they would be
defenses against scenarios that cannot arise.

**Tests.**

1. `test_sub_worker_result_drained_after_busy_period` — mock a
   VTuber that is mid-execution; have the Sub-Worker deposit a
   `[SUB_WORKER_RESULT]` in its inbox; complete the VTuber's
   execution; assert the VTuber starts a follow-up turn with
   the result as prompt.
2. `test_drain_skips_empty_inbox` — no unread messages, drain
   is a no-op.
3. `test_drain_serializes_multiple_unreads` — two messages
   queued, drain processes them in order, not in parallel.
4. `test_drain_marks_consumed` — after drain pulls a message,
   a second drain call does not re-pick the same message.

**Out of scope.**

- Trigger-abort mechanism (Scenario A). That is separate —
  handles *user* messages during thinking triggers, not
  delegation results.
- Inbox persistence across restarts. Assumed already handled.

---

## Verification at the end of Phase 3

Manual smoke:

- [ ] Simulate Sub-Worker failure during VTuber creation (point
      a test request at a bad `sub_worker_env_id`); confirm the
      client gets a proper error and no orphaned VTuber appears
      in the session list.
- [ ] Start a long-running task on the Sub-Worker. While it is
      running, send a second question to the VTuber. When the
      Sub-Worker finishes, confirm the VTuber eventually
      surfaces the `[SUB_WORKER_RESULT]` without the user
      having to prod it.
- [ ] Repeat the above with three rapid-fire Sub-Worker
      results; confirm they are surfaced in order, not
      dropped.

---

## Rollback plan

- PR #8: revert to the silent-catch behaviour. Partially-created
  VTubers reappear. Not harmful to system stability, but the UX
  regression returns.
- PR #9: revert the finally block. Inbox orphaning returns. Not
  harmful to other running sessions.

Both revertible cleanly.

---

## Summary across Phases 1–3

After all nine PRs:

- VTuber reliably delegates to Sub-Worker via tool calls.
- All log surfaces (file + LogsTab) show env_id / role /
  session_type / delegation events.
- Sub-Worker creation failure doesn't leave half-created
  sessions.
- Sub-Worker replies are never permanently orphaned.

Cycle exit: the environment-first architecture fully supports
the two-agent workflow the user envisioned in 20260420_3.
