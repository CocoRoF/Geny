# 05 — Session "Environment" tab from the real manifest

**Cycle:** 2026-04-20 follow-up.
**Branch:** `feat/session-env-tab-from-manifest`.
**Reported:** the legacy "Graph" tab under a selected session was
still rendering a hard-coded 16-stage diagram regardless of what
environment the session was actually bound to. After the v0.20.0
environment pivot, *every* session runs through an
`EnvironmentManifest`, so the old graph view lies about which stages
are active, which ones have config, and what strategies/tools are
bound at each step.

Quoting the user: "이제 Graph라는 용어는 제거되고, '환경'이라는 동일한
용어로 Sessions의 Stage들을 볼 수 있도록 열려야 하고, 이것을 눌렀을 때
해당 Sessions에 할당된 환경을 정확하게 보여줘야만 해."

## Outcome

1. **Graph tab renamed to Environment tab** everywhere the user sees
   it — tab label, tab ID, component filename.
2. **Stage list is derived from the session's actual manifest**, not
   a static list. Inactive stages are visibly dimmed; active stages
   show a green badge; stages with real configuration expand to
   reveal the config JSON, strategy map, tool binding, and model
   override.
3. **Sessions without an env bound** (legacy sessions, pre-v0.20.0)
   now show an explicit "not bound" state with a CTA that takes the
   user to the Environments tab — no more fake 16-stage diagram.
4. **Sessions whose env_id has been deleted** get a clear
   "Environment unavailable" state instead of a silent blank.

## Changes

| File | Change |
|------|--------|
| `frontend/src/components/tabs/GraphTab.tsx` → `SessionEnvironmentTab.tsx` | `git mv` — rewrite the body to read the session's env_id, fetch the full `EnvironmentDetail` via `environmentApi.get`, and render stages grouped by category (ingress / preflight / execution / decision / egress). Expandable `StageCard` per stage shows config, strategies, tool_binding, model_override. 5 UI states: unbound / env-missing / loading / error / loaded. |
| `frontend/src/components/TabContent.tsx` | Swap the `GraphTab` dynamic import for `SessionEnvironmentTab`. TAB_MAP gets a new `environment` key; the old `graph` key is kept as a legacy redirect to the same component. |
| `frontend/src/components/TabNavigation.tsx` | `SESSION_TAB_DEFS` entry `{ id: 'graph' }` → `{ id: 'environment' }`. `DEV_ONLY_SESSION` updated to match. |
| `frontend/src/store/useAppStore.ts` | Add `'environment'` to `SESSION_TAB_IDS` and to the dev-only tab list (kept `'graph'` alongside so any deep-linked stale tab state still resolves). |
| `frontend/src/lib/i18n/en.ts`, `ko.ts` | Added `tabs.environment`; replaced the `graphTab.*` namespace with `sessionEnvironmentTab.*` covering title / selectSession / sessionLine / envLoading / envMissing{,Headline,Body} / noEnvBound / unbound{Headline,Body} / goToEnvironments / openInEnvironments / reload / loading / loadFailed / manifestEmpty / stageCount / active / inactive / config / strategies / toolBinding / modelOverride / category.{ingress,preflight,execution,decision,egress}. `tabs.graph` label is repurposed to "Environment / 환경" so legacy-ID routes still render the right header. |

## Why fetch the manifest locally

`useEnvironmentStore.loadEnvironment(envId)` already exists and would
hydrate the env with its manifest — but it writes into the shared
`selectedEnvironment` slot that `EnvironmentDetailDrawer` and the
builder rely on. Having the per-session tab stomp that state would
cause the drawer/builder to flicker to the session's env whenever
the user switched to the Environment tab. `SessionEnvironmentTab`
keeps a local `manifestEnv` state (via `environmentApi.get(envId)`)
so it's inert w.r.t. the global store.

## Stage categorization

`StageManifestEntry` exposes `order` and `name` but not a category
field (category lives in `StageIntrospection` on the catalog endpoint,
not on the per-env manifest). The tab therefore derives the category
from the stage order using the canonical Geny executor ranges:

| Order | Category |
|-------|----------|
| 1–3   | Ingress |
| 4–5   | Preflight |
| 6–11  | Execution |
| 12–13 | Decision |
| 14–16 | Egress |

This matches the 16-stage reference layout documented in
`geny-executor/src/geny/executor/pipelines/phase1.py`. A future
refinement could fetch the catalog once and look up the real
category instead, but the order ranges are stable and avoid an
extra round-trip.

## Verification

- Manual: select a session with an env_id bound → Environment tab
  shows the env name badge, stage count "X active · Y stages", and
  category-grouped stage cards. Inactive stages dimmed.
- Manual: expand a stage card with config/strategies → JSON + pill
  list render. Stage cards with no extra config are non-expandable.
- Manual: select a legacy session with no env_id → "not bound"
  screen with CTA into the Environments tab.
- Manual: select a session whose env_id no longer exists → red
  "Environment unavailable" banner.
- Manual: old deep link to `activeTab=graph` still resolves and
  renders the Environment tab (legacy redirect).
- TypeScript / lint: relies on CI (no local node toolchain in this
  environment).

## Out of scope

- Live status per stage (running / succeeded / failed) — the tab is
  read-only w.r.t. manifest shape; runtime status still lives on the
  main chat stream and the logs tab. A follow-up could layer a
  per-run status overlay on top of `StageCard`.
- Catalog-driven category labels (see above).
- Inline editing: this view is intentionally read-only. Clicking
  "Open in Environments" sends the user to the drawer where editing
  lives.
