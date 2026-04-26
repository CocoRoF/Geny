# P.2 — Builder Pipeline + Model config editors

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `frontend/src/components/builder/PipelineConfigEditor.tsx` (new) — form for `manifest.pipeline` (8 fields).
- `frontend/src/components/builder/ModelConfigEditor.tsx` (new) — form for `manifest.model` (10 fields).
- `frontend/src/lib/environmentApi.ts` — `updatePipeline` + `updateModel` clients hitting P.1 endpoints.
- `frontend/src/store/useEnvironmentStore.ts` — `updatePipeline` / `updateModel` actions; reuse `_warnAffectedSessions` (D.3).
- `frontend/src/components/tabs/BuilderTab.tsx` — view toggle gains "Pipeline" + "Model" buttons; renders the editors when selected.

## What it changes

The Builder header tab strip now has 4 views: **Stages** · **Pipeline** · **Model** · **Tools**. Each is its own form panel.

**Pipeline view** (`manifest.pipeline`):
- name, base_url
- max_iterations (int ≥ 1), context_window_budget (int ≥ 1024), cost_budget_usd (float ≥ 0)
- stream / single_turn (Switch toggles)
- artifacts (JSON object — stage_name → artifact override)
- metadata (JSON object — free-form)

**Model view** (`manifest.model`):
- model (free text — Anthropic / OpenAI / Google id)
- max_tokens, temperature (0.0–2.0), top_p (0.0–1.0), top_k
- stop_sequences (one per line)
- thinking_enabled toggle + `thinking_budget_tokens` / `thinking_type` / `thinking_display` enum dropdowns (greyed out when thinking_enabled=false)

Both editors are shallow-merge: only changed fields are sent. **Empty inputs mean "leave unchanged"** — to clear an optional field, edit the manifest via ImportManifestModal. Validation surfaces inline above the form.

After successful save, the store's `_warnAffectedSessions` (from D.3) emits a sonner toast listing active sessions still on the pre-edit snapshot.

## Why

Audit (cycle 20260426_2, analysis/02 Tier 1) — pipeline/model config was completely read-only. Operators had to use ImportManifestModal to change `max_iterations` or `temperature`. P.2 closes this gap end-to-end.

## Tests

UI-only changes; CI lint + tsc + Next build is the gate.

## Out of scope

- Per-stage `model_override` editor — sprint S.1.
- Model picker dropdown sourced from `/api/admin/known-models` — defer; for now operators type the model id (matches the rest of the codebase's text inputs).
- i18n strings — inline english for now (matches existing tab style).
