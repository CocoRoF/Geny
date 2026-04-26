# E.1 — Between-turn live reload of permissions / hooks

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/executor/agent_session.py` — `_pending_runtime_refresh` field; `queue_runtime_refresh` + `_apply_pending_runtime_refresh` methods; drain hooks at the top of `invoke` + `astream`.
- `backend/controller/admin_controller.py` — new `POST /api/admin/reload-runtime` endpoint.
- `backend/tests/service/executor/test_runtime_refresh_queue.py` (new) — 9 cases covering queue/drain semantics.
- `frontend/src/lib/api.ts` — `adminTelemetryApi.reloadRuntime` + `ReloadRuntimeResponse` type.
- `frontend/src/components/admin/ReloadRuntimeButton.tsx` (new) — small dropdown button (all / permissions / hooks).
- `frontend/src/components/tabs/EnvironmentTab.tsx` — mount the button in the Library scope header.

## What it changes

Operators can push fresh permission rules / hook runner into every active session without restarting them. Mechanism:

1. Operator clicks "Reload runtime" → backend iterates active sessions and sets `_pending_runtime_refresh` on each.
2. The next time a session enters `invoke` or `astream`, `_apply_pending_runtime_refresh` runs first:
   - Re-reads via `install_permission_rules()` / `install_hook_runner()`.
   - Calls the executor's stage-slot setters (`_set_tool_stage_permission_matrix`, `_set_tool_stage_hook_runner`) — same path `attach_runtime` uses internally.
3. Currently-executing turns finish on the pre-refresh runtime; the next turn picks up the new state. No mid-turn swap, no inconsistent state.

## Why this design (not direct `attach_runtime`)

`Pipeline.attach_runtime` raises after `_has_started=True` because executing state holds references to the slot values. The executor's hard error guards against careless mid-turn swaps. We bypass it explicitly in `_apply_pending_runtime_refresh` because:
- We always swap at a turn boundary (start of `invoke`/`astream`, before `pipeline.run_stream`).
- A fresh `PipelineState` is built each turn via `Pipeline._init_state`, so it picks up the new slot values cleanly.

Risk: the private setter names could be renamed in a future executor pin. Mitigation: `getattr(..., None)` guard in the apply helper — a missing setter logs nothing and continues, no crash.

## Why scope is limited to permissions + hooks

- **Skills** would require re-running `install_skill_registry` and re-running the MCP-prompts-as-skills bridge. Bigger change; deferred.
- **MCP servers** would require restarting the MCPManager subprocess pool. Bigger change; deferred.
- **System builder / persona / memory** — they all consult dynamic resolvers per turn already (the `DynamicPersonaSystemBuilder` pattern); no restart needed.

## API

```http
POST /api/admin/reload-runtime
{
  "scope": "permissions" | "hooks" | "all"
}

200 OK
{
  "scope": "all",
  "queued_session_ids": ["s1", "s2"],
  "skipped_session_ids": [],
  "queued_count": 2,
  "note": "Refresh applied at the start of the next invoke / astream …"
}
```

`400` for unknown scope.

## Tests

9 cases in `test_runtime_refresh_queue.py`:
- queue rejects unknown scope / uninitialized session / no-pipeline session
- queue accepts valid scope
- apply is no-op when queue empty
- apply clears flag even on failure (one-shot semantics)
- apply calls permissions setter on permissions scope
- apply calls both setters on `all` scope
- apply skips hook setter when `install_hook_runner` returns None (env gate closed / no hooks declared)

Local: skipped (pydantic). CI runs them.

## Out of scope

- True mid-turn hot-swap (would require executor-side support).
- Refreshing skills / MCP servers (separate cycle).
- Per-session targeting (current endpoint is fan-out; per-session would need a new endpoint).
- UI confirmation modal (the toast result feedback is enough for now; defer modal to UX cycle if requested).
