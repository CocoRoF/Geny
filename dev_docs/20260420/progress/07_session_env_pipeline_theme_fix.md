# 07 — Pipeline view follows Geny's light/dark theme

**Cycle:** 2026-04-20 follow-up to #06.
**Branch:** `feat/session-env-pipeline-theme-fix`.

## Context

#06 landed the new Session Environment tab as a pipeline canvas, but
the styling was a near-straight port of `geny-executor-web`'s
palette — fixed near-black backgrounds (`#0c0c0c` / `#141414`) and
the executor-web gold accent (`#c8a45c`). The user called this out:

> "스타일은 기존 GENY와 호환성을 맞춰서 만들었어야지. 지금은
> geny-executor-web의 색상같은 스타일을 전부 가져온 상태야. 기존
> geny의 light/dark 모드에 맞춰서 색상 디자인을 수정해보자."

So: keep the pipeline view's *structural* design (radial-gradient
stage circles, U-turn/loop-back SVG paths, phase labels, dashed
flow animation, Playfair serif headings) but replace every color
with a Geny theme token so the view follows the global light/dark
switch.

## Outcome

1. **All `--pipe-*` CSS vars alias Geny's existing tokens**
   (`var(--bg-primary)`, `var(--primary-color)`, `var(--success-color)`,
   etc.) — no more hard-coded hex values in `.pipeline-scope`.
2. **Per-theme overrides** for tint / glow / shadow inside
   `html.dark .pipeline-scope` and `html.light .pipeline-scope`:
   dark mode keeps a richer glow and darker ambient shadow; light
   mode gets a paler tint and a much softer shadow so the circles
   don't feel heavy on a white canvas.
3. **Category colors reuse Geny's semantic tokens** where possible —
   ingress/pre_flight/decision/egress map to primary/warning/
   success/danger respectively. Execution (purple) and the
   bypassable indicator (cyan) have no Geny equivalent, so they
   carry explicit dark/light shades.
4. **`getCategoryColor` rewritten with `color-mix`** instead of
   hard-coded rgba — the bg/border tints now derive from the
   current accent token, so they flip with the theme automatically.
5. **Primary-button text color** in the tab header and unbound-CTA
   switched from `var(--pipe-bg-primary)` (which yielded "blue
   button with near-black text" on dark mode) to plain `#ffffff`,
   matching the rest of Geny's primary buttons (`text-white`).

## Files

| File | Change |
|------|--------|
| `frontend/src/app/globals.css` | Rewrote the `.pipeline-scope` block header and var declarations: every `--pipe-*` now aliases a Geny theme token instead of a literal hex. Added `html.dark .pipeline-scope { ... }` and `html.light .pipeline-scope { ... }` sections for the tint / glow / circle-shadow / inactive-opacity values that need to differ per theme. Replaced the hard-coded `rgba(0,0,0,0.35)` / `rgba(0,0,0,0.5)` circle shadows with `var(--pipe-circle-shadow)` / `var(--pipe-circle-shadow-hover)`. Swapped the accent-tint radial gradient from `rgba(200,164,92,0.12)` to `var(--pipe-accent-tint)`. Added fallback values in the base block so the view renders correctly even before the theme-init script runs. |
| `frontend/src/components/session-env/stageMetadata.ts` | Rewrote `getCategoryColor` to build bg/border strings with `color-mix(in srgb, <var> <pct>%, transparent)` instead of hard-coded rgba. Category accent vars now resolve to Geny's semantic tokens (`--pipe-blue` → `--primary-color`, `--pipe-green` → `--success-color`, etc.). |
| `frontend/src/components/session-env/StageDetailPanel.tsx` | Replaced every hard-coded rgba in badge/bypass-note/in-use-pill styles with either `color-mix` over theme vars or Geny's `var(--shadow-lg)`. The "in use" pill text color switched to `#ffffff` so it's readable in both themes. Kept the backdrop as `rgba(0,0,0,0.4)` — dark scrim is the standard modal convention on both themes. |
| `frontend/src/components/session-env/CodeViewModal.tsx` | Replaced the hard-coded `0 20px 80px rgba(0,0,0,0.6)` shadow with `var(--shadow-lg)` so the modal blends with Geny's existing card shadows per theme. |
| `frontend/src/components/tabs/SessionEnvironmentTab.tsx` | Primary-button text swapped from `var(--pipe-bg-primary)` to `#ffffff` (matches Geny's `text-white` convention and avoids a blue-on-near-black button on dark mode). |

## Design notes

### Why alias, not rename

Keeping the `--pipe-*` names (now aliases) means every component
file from #06 continues to work without edits. Scoping stays
clean — nothing outside `.pipeline-scope` sees these vars.

### Why `color-mix` over rgba

Hard-coded rgba locks in a specific hex; `color-mix` keeps
everything keyed to the live token. If Geny later retunes
`--primary-color` (e.g. a brand refresh), the pipeline view's
tints / glows / category pills move with it — no pipeline-specific
touch-up needed.

### Why the backdrop stays dark on light mode

The panel and code modal both lean on `var(--pipe-bg-secondary)`
for their surface color. On light mode that surface is
`#f8fafc` — almost the same as the underlying canvas
(`#ffffff`). A light scrim on light UI gives no separation, so
the backdrop stays dark-translucent in both themes. This is the
standard Material / shadcn modal pattern.

### Why execution/cyan still carry literals

`--warning-color` maps closely to the amber/gold we want for
`pre_flight`, but Geny has no purple or cyan token — those are
unique to the pipeline view's category spectrum. Rather than
invent global tokens, the `.pipeline-scope` block carries two
hex-per-theme values (`#a855f7` / `#7c3aed` for purple,
`#22d3ee` / `#0891b2` for cyan), and nothing else.

## Verification

Manual in both themes (toggled via the Geny theme switcher):

- **Dark mode**: canvas is near-black, active circles glow blue,
  phase labels and loop-back dashes are Geny blue. Inactive
  stages dim to ~42% opacity.
- **Light mode**: canvas is white, active circles have a soft blue
  glow, inactive circles dim to ~60% opacity (0.42 was too subtle
  on a white bg). Stage borders visible as `#cbd5e1` lines.
- Stage detail panel header and JSON sub-cards in both themes
  carry the same contrast hierarchy (panel surface > card surface
  > inline code block).
- Code modal scrim provides separation on both themes.
- Category color pills (ingress/pre_flight/execution/decision/
  egress) render readable in both themes — tint bg is a 10%
  color-mix, border a 28% color-mix.
- TypeScript / lint: defers to CI (no local node toolchain).

## Out of scope

- Migrating the existing Geny palette to add purple / cyan tokens —
  out of scope for this PR. If another feature ends up needing them,
  they can be promoted from `.pipeline-scope` into the global
  `html.dark` / `html.light` blocks.
- Re-theming the tab header layout or typography. Only the color
  palette was re-targeted; structure and spacing are unchanged.
