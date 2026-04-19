# 02 — Session Graph: linked Environment badge

**Plan ref:** `dev_docs/20260420/plan.md` §2 (Issue 2).
**Branch:** `feat/graph-env-badge`.

## Outcome

GraphTab now surfaces the Environment that a session is bound to (or
the legacy preset, if `env_id` is absent). Clicking the env badge
deep-links into the EnvironmentsTab and pops the env detail drawer.

## Behaviour

- `session.env_id` resolves to a known summary → indigo "Environment:
  <name>" pill with an `ExternalLink` glyph; clickable.
- `session.env_id` exists but the summary is missing (deleted env) →
  red "Environment unavailable" pill with the truncated id, not
  clickable.
- `session.env_id` is null → grey "Preset: <label>" pill (the same
  preset string already shown in the heading, just promoted to a
  visible badge so the absence of an env is explicit).
- The EnvironmentsTab drawer auto-opens because the GraphTab writes
  the requested env id into `useEnvironmentStore.pendingDrawerEnvId`,
  which the tab consumes once on mount/update.

## Changes

| File | Change |
|------|--------|
| `frontend/src/store/useEnvironmentStore.ts` | Added `pendingDrawerEnvId` + `requestOpenEnvDrawer(id)` + `consumePendingDrawerEnvId()` so cross-tab callers can request the env detail drawer without owning EnvironmentsTab's local drawer state. |
| `frontend/src/components/tabs/EnvironmentsTab.tsx` | One-shot `useEffect` that consumes `pendingDrawerEnvId` and forwards it to the local `setOpenEnvId` so the drawer opens. |
| `frontend/src/components/tabs/GraphTab.tsx` | Header now renders the env / preset badge. If `env_id` is set but the store's environments list is empty, fires `loadEnvironments()` once so the badge can resolve a name. |
| `frontend/src/lib/i18n/en.ts` / `ko.ts` | Added `graphTab.environment` / `envLoading` / `envMissing` / `preset`. |

## Skipped (per plan §2)

- Manifest-driven dynamic stage rendering (replacing `PIPELINE_STAGES`
  with the env's actual stage order). Deferred to a separate cycle —
  this PR keeps the static 16-stage layout and only adds the badge +
  drill-down.
