# D.3 — Manifest edit shows affected active sessions

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/environment/schemas.py` — new `AffectedSessionsSummary` model + optional `affected_sessions` on `EnvironmentDetailResponse`.
- `backend/controller/environment_controller.py` — `_affected_sessions_summary(env_id)` helper; populated on PUT `/api/environments/{env_id}`, PUT `/api/environments/{env_id}/manifest`, PATCH `/api/environments/{env_id}/stages/{order}` responses.
- `backend/tests/controller/test_environment_affected_sessions.py` (new) — 4 cases.
- `frontend/src/types/environment.ts` — `AffectedSessionsSummary` interface; field on `EnvironmentDetail`.
- `frontend/src/store/useEnvironmentStore.ts` — sonner toast helper `_warnAffectedSessions`; called from `replaceManifest` + `updateStage` actions after successful save.

## What it changes

When the user saves a manifest edit (full replace via PUT `/manifest`, partial via PATCH `/stages/{order}`, or top-level metadata via PUT `/{env_id}`), the response now carries:

```json
{
  "affected_sessions": {
    "count": 2,
    "session_ids": ["s1", "s2"],
    "session_names": ["alpha", "beta"]
  }
}
```

The FE store consumes this and emits a sonner warning toast:

> 2 active sessions still running on the pre-edit manifest.
> Restart to pick up the change: alpha, beta

The toast is suppressed when `count === 0`, so quiet edits stay quiet.

## Why

Audit (cycle 20260426_1, analysis/02 §B.5). Each `AgentSession` holds a frozen runtime snapshot via `Pipeline.attach_runtime` from `initialize()`. Mutating the manifest on disk has no effect on running sessions until they restart. Without the post-save warning, operators conclude the editor is broken.

This complements C.1's "next session" banner — that's a *passive* signal on the editor; D.3 is an *active* per-save signal.

## Tests

4 cases in `test_environment_affected_sessions.py`:
- counts only matching env_id
- falls back to session_id when session_name is missing
- returns zero for unknown env
- returns zero (instead of raising) when session store is unavailable

Local: skipped (pydantic). CI runs them.

## Out of scope

- Per-session restart action button (would require a new endpoint and confirmation UI).
- Diff between pre-edit and post-edit manifest — surfaced separately by `EnvironmentDiffResponse`.
- Live runtime swap to active sessions — that's E.1.
