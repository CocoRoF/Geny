# 01 — Merge Builder tab into Environments

**Plan ref:** `dev_docs/20260420/plan.md` §1 (Issue 1).
**Branch:** `feat/merge-builder-into-environments`.

## Outcome

Single "Environments" tab. List vs Builder is an internal mode driven by
`useEnvironmentStore.builderEnvId`:

- `builderEnvId === null` → list view (cards, filters, bulk actions, …).
- `builderEnvId !== null` → builder view (stages, tools, manifest preview).

The card → drawer → "Open in Builder" flow now ends with the user
remaining in the Environments tab; only the in-tab body swaps.

## Changes

| File | Change |
|------|--------|
| `frontend/src/components/TabNavigation.tsx` | Removed `'builder'` from `GLOBAL_TAB_IDS` and `DEV_ONLY_GLOBAL`. The tab bar now shows one item where there were two. |
| `frontend/src/components/TabContent.tsx` | Dropped the dynamic `BuilderTab` import. Kept a `'builder'` key in `TAB_MAP` that resolves to `EnvironmentsTab` so any stale `activeTab === 'builder'` value (saved store state, deep links) auto-routes to the same component. |
| `frontend/src/components/tabs/EnvironmentsTab.tsx` | Subscribes to `builderEnvId` and short-circuits to `<BuilderTab />` when it is set. List state (filters, drawer, bulk selection) is untouched and restored on `closeBuilder`. |
| `frontend/src/components/tabs/BuilderTab.tsx` | Removed the `setActiveTab` import. `closeBuilder()` no longer chases the tab — the parent re-renders the list automatically. The empty-state branch (no env picked) is gone since the parent gates mounting; left a defensive `return null` in case of a stale render. |
| `frontend/src/components/EnvironmentDetailDrawer.tsx` | "Open in Builder" now calls `setActiveTab('environments')` instead of `'builder'` — same target component now. |

No backend changes. No data model changes.

## Behaviour after merge

- Tab bar lists: Main / Playground / Playground 2D / Tool Sets /
  Environments / Shared Folder / Settings (Builder removed).
- Click an env card → drawer opens (unchanged).
- Click "Open in Builder" → drawer closes, EnvironmentsTab body becomes
  the BuilderTab editor; tab badge stays "Environments".
- Click "Back to Environments" or "Close" inside the builder → list view
  restored; sort / filter / selection preserved.
- Any external code that still does `setActiveTab('builder')` now lands
  in the EnvironmentsTab (list or builder, depending on
  `builderEnvId`) — no broken state.

## Skipped / out of scope

- The `tabs.builder` i18n key is left in `en.ts` / `ko.ts` as an unused
  string; removing it is a churn-only change.
- "Manifest-driven dynamic stage rendering" stays under Issue 2 stretch.
