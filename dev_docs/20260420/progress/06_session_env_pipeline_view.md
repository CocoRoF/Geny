# 06 — Session Environment tab as the pipeline canvas

**Cycle:** 2026-04-20 follow-up to #05.
**Branch:** `feat/session-env-pipeline-view`.

## Context

Progress #05 rebuilt the per-session Environment tab from the real
manifest, but as a category-grouped list of expandable cards. The
user followed up:

> "sessions의 환경을 눌렀을 때, 그것이 geny-executor-web의 pipeline
> 페이지처럼 보였으면 좋겠어. geny-executor-web의 파이프라인 view처럼
> 더욱 멋지고 완벽하게 바꿔보자."

And then clarified the scope:

> "실행 상태를 보여줄 필요는 없지. 이건 어떤 ENVIRONMENT가 적용되었는지
> 확인하는 페이지일 뿐이고, 실제 실행을 하는 부분은 아니니까."

So: port executor-web's pipeline canvas aesthetic into Geny's session
tab, but strip anything execution-related — no `active`/`completed`/
`error` circle states, no pulse animation, no live event wiring.
"Is this stage configured and active in the applied environment?"
is the only question the circles answer.

## Outcome

1. **3-phase SVG+HTML hybrid canvas** matching executor-web 1:1 at
   the layout level (GAP=110, LM=120, ROW_A=55, ROW_B1=175, ROW_B2=305,
   ROW_C=435, R=27, CANVAS_W=770, CANVAS_H=510), including the U-turn
   curve 7→8 on the right, the dashed loop-back 13→2 on the left, the
   Phase B bounding box, phase labels (A/B/C with EN/KO sub-labels),
   and the dot grid.
2. **Read-only circle states only** — `.active` (configured & active
   in the manifest) vs `.inactive` (absent from the manifest or
   `active: false`), plus `.selected` for the open detail panel.
   The executor-web `.completed` / `.error` / `.editable` /
   `pulse-glow` variants are intentionally omitted.
3. **Slide-in StageDetailPanel** on the right shows: header with
   category-colored order circle + Playfair display name, status
   badges (Active/Inactive/Phase/Bypassable), Overview,
   Technical Behavior, Strategy Slots (catalog view — the impl the
   manifest picked is highlighted with an "in use" badge), Current
   Configuration (live manifest: strategies map, `config`,
   `strategy_configs`, tool_binding, model_override), and
   Architecture notes.
4. **Code modal** shows the raw `manifest` JSON for the bound
   environment, with a copy-to-clipboard button. Closes on Esc or
   backdrop click.
5. **Scoped styling** — all pipeline CSS is behind `.pipeline-scope`
   on the tab root. CSS vars are `--pipe-*`-prefixed so Geny's global
   tokens (`--bg-primary`, `--accent`, etc.) stay untouched.
6. **Playfair Display + JetBrains Mono** added to the Next.js root
   layout alongside the existing Inter. Inter remains the default
   body font; the pipeline view opts into the other two via
   `.pipe-serif` / `.pipe-mono` / local `style={{ fontFamily }}`.

## Files

| File | Change |
|------|--------|
| `frontend/src/app/layout.tsx` | Add `Playfair_Display` + `JetBrains_Mono` from `next/font/google` and expose `--font-playfair` / `--font-jetbrains-mono` on `<body>`. Inter remains the body class. |
| `frontend/src/app/globals.css` | Append `.pipeline-scope { ... }` block: `--pipe-*` color palette (near-black background, gold accent, category colors), `.pipe-serif` / `.pipe-mono` font helpers, `.stage-circle` + `:hover` + `.active` + `.inactive` + `.selected` states, `pipe-dash-flow` keyframes for the loop-back animation, `pipe-slide-in-right` keyframes for the panel. Scoped `::selection` and `::-webkit-scrollbar`. |
| `frontend/src/components/session-env/useZoomPan.ts` | New. Callback-ref zoom/pan hook, direct port of executor-web's hook (wheel 1.08/0.92 factor, pointer pan with `setPointerCapture`, `fitToView`, `resetView`). |
| `frontend/src/components/session-env/stageMetadata.ts` | New. Full bilingual (EN/KO) metadata for the 16 stages: displayName, categoryLabel, detailedDescription, technicalBehavior[], strategies[{slot, options[{name, description}]}], architectureNotes, canBypass/bypassCondition. Exports `getStageMetaByOrder(order, locale)`, `getAllStageMeta(locale)`, `getCategoryColor(category)` (returns `var(--pipe-*)` refs), `inferPhaseFromOrder`, `inferCategoryFromOrder`. |
| `frontend/src/components/session-env/PipelineCanvas.tsx` | New. SVG (Decorations + Connections) + HTML (StageNode circles) hybrid canvas. Renders all 16 order slots so layout stays stable even when the manifest skips stages — missing slots render as `.inactive`. `useZoomPan(0.4, 3)` hook, auto-fit on mount, parent-exposed `onResetView`. |
| `frontend/src/components/session-env/StageDetailPanel.tsx` | New. Backdrop + slide-in right panel (420px). Header with order circle, Playfair name, category label, status badges, artifact line. Sections: Overview (with bypass note), Technical Behavior (bullet list), Strategy Slots (catalog options; manifest impl highlighted via lenient slot-name matching), Current Configuration (strategies map, config JSON, strategy_configs JSON, tool_binding pills, model_override JSON), Architecture. Read-only — no inline edits, no "Go to builder" button since the tab header already offers "Open in Environments". |
| `frontend/src/components/session-env/CodeViewModal.tsx` | New. Full-screen modal (max-width 960px, 80vh) with copy button. Displays `JSON.stringify(manifest, null, 2)`. ESC to close. |
| `frontend/src/components/tabs/SessionEnvironmentTab.tsx` | Rewrite. Drop the legacy `StageCard` / category-grouped layout. New layout: compact header (Pipeline label + "16-Stage Architecture" serif title + Environment·source·ratio·session line + Code/Reset/Reload/Open-in-Environments button row), then full-bleed pipeline canvas. Empty states (unbound / env-missing / loading / error / no-stages) re-themed with `.pipeline-scope` tokens. Manages `selectedOrder`, `codeOpen`, and a `resetViewRef` the canvas populates. |
| `frontend/src/lib/i18n/en.ts`, `ko.ts` | Extend `sessionEnvironmentTab.*` with a `pipeline.*` sub-namespace: `label`, `title`, `sourceEnvironment`, `sourcePreset`, `activeRatio`, `hint`, `code`/`reset`/`copy`/`copied`, `phase`, `phaseAInit`/`phaseBAgentLoop`/`phaseCFinal`, `loop`, `overview`, `technicalBehavior`, `strategySlots`, `strategyConfigs`, `currentConfig`, `architecture`, `bypassable`, `bypass`, `artifact`, `inUse`, `notInManifest`. |

## Design decisions

### Why a 16-slot layout even when the manifest has fewer stages

The pipeline shape is a recognizable visual — losing a stage would
distort the topology (e.g. the U-turn at stage 7 and the loop-back
from 13 are anchored to specific positions). Rendering missing slots
as `.inactive` keeps the canvas legible and communicates "this stage
isn't part of the applied environment" at a glance, which is exactly
what the tab is for.

### Why scoped CSS instead of extending global tokens

Geny's global palette is lighter / more neutral than executor-web's
near-black pipeline aesthetic. Dropping `--bg-primary: #0c0c0c`
globally would flip the whole app dark-er; wrapping the new view in
`.pipeline-scope { --pipe-*: ... }` and referencing those vars from
every pipeline style sheet keeps the rest of Geny visually stable.

### Why no catalog lookup for strategy impls

`getStageMetaByOrder` already knows the full strategy-option catalog
per stage. The manifest's `strategies: Record<slot, impl>` tells us
which option is currently selected. Merging those two is a single
`findManifestImplForSlot` call (with lenient key-normalization because
manifest keys are snake_case and metadata slots are display strings).
No extra `/api/catalog/*` round-trip needed for this PR; a future
iteration could bring in `StageIntrospection` for stages that don't
have static metadata in `stageMetadata.ts`.

### Why no execution overlay

Per user direction — this tab answers "which environment is
applied?", not "is it running now?". Live run state is already
visible on the Command and Logs tabs. Re-introducing pulse /
completed / error visuals would also require subscribing to the
session's event stream, which is work we're explicitly not doing
here.

## Verification

Manual checks on a session bound to an env with ~9 active stages:

- Canvas renders with 16 circles in the correct 3-phase layout,
  loop-back dashes animating left-side, phase labels A/B/C visible,
  Phase B bounding box visible.
- Active stages glow gold; inactive/absent stages are dim.
- Wheel over canvas zooms; drag pans; Reset button re-fits.
- Clicking a stage opens the right panel with its metadata +
  manifest config; backdrop click / × / selecting another stage all
  update correctly.
- Code button opens the JSON modal with the env's manifest; Copy
  works; Esc closes.
- Locale toggle (EN ↔ KO) swaps stage names, phase sub-labels, and
  detail-panel copy.
- Empty states: unbound session still shows the "bind an environment"
  CTA (unchanged behavior, restyled).
- TypeScript / lint: no local node toolchain in this environment, so
  validation defers to CI.

## Out of scope

- Catalog-driven stage metadata (only matters for custom environments
  that introduce stages outside the 16-stage core).
- Inline stage editing / drag-to-reorder — Environment Builder owns
  those.
- Per-run execution overlays (see "Why no execution overlay").
