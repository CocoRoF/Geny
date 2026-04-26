# S.2 — Per-stage tool_binding editor

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `frontend/src/components/tabs/BuilderTab.tsx` — `StageDraft.toolBindingText` field + populate from `entry.tool_binding` + dirty check + `handleSave` validation + new editor section after model_override.

## What it changes

The per-stage detail (Stages view) gets a "Tool binding (optional, mostly s10)" textarea. Operators can paste a `StageToolBinding` JSON (`{"mode": "allowlist", "patterns": ["Bash", "Read"]}`) to restrict which tools the stage can dispatch.

Same UX pattern as S.1 (model_override):
- Empty = inherit pipeline tool roster.
- Non-empty = JSON object; validation error inline.

Shown on every stage for symmetry with the manifest schema; the help text notes that `tool_binding` is mostly meaningful on s10 (the Tool stage).

## Why

Audit (cycle 20260426_2, analysis/02 Tier 2) — `tool_binding` per stage was supported by the backend `update_stage` service method but had no UI surface. Operators had to use ImportManifestModal.

## UX choice

JSON textarea (same rationale as S.1): per-stage bindings are rare; canonical shape `{"mode": ..., "patterns": [...]}` is documented inline.

## Out of scope

- Structured form with `mode` enum dropdown + `patterns` list editor — defer until usage telemetry shows demand.
- Per-stage tool affordances tied to stage type — deferred.
