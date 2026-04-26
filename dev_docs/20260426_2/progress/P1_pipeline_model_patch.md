# P.1 — Manifest pipeline / model patch endpoints

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/environment/service.py` — `EnvironmentService.update_pipeline` + `update_model` shallow-merge methods.
- `backend/service/environment/schemas.py` — `UpdatePipelineConfigRequest` + `UpdateModelConfigRequest` Pydantic schemas mirroring `PipelineConfig` / `ModelConfig`.
- `backend/controller/environment_controller.py` — `PATCH /api/environments/{id}/pipeline` + `PATCH /api/environments/{id}/model` endpoints, both returning `EnvironmentDetailResponse` with `affected_sessions` (D.3 pattern).
- `backend/tests/service/environment/test_update_pipeline_model.py` — 9 unit cases.

## What it changes

Operators can now patch `manifest.pipeline.max_iterations` (or any other PipelineConfig field) and `manifest.model.temperature` (or any ModelConfig field) without re-uploading the whole manifest via ImportManifestModal.

Schema validation enforces the executor's bounds:
- `max_iterations >= 1`
- `cost_budget_usd >= 0.0`
- `context_window_budget >= 1024`
- `temperature in [0.0, 2.0]`
- `top_p in [0.0, 1.0]`
- `top_k >= 1`
- `max_tokens >= 1`
- `thinking_budget_tokens >= 1`

Excludes:
- `model.api_key` — never accepted via API (deploy-time secret).
- `model` (the nested ModelConfig) is its own block; `pipeline.model` is intentionally not editable here. Use `PATCH /model` for model fields.

## Why

Audit (cycle 20260426_2, analysis/02 Tier 1) — pipeline/model config was completely read-only in the Builder. Operators had to use `ImportManifestModal` and replace the entire JSON to change `max_iterations`. This PR is the backend half; P.2 ships the frontend forms.

## Tests

9 unit cases in `test_update_pipeline_model.py`:
- update_pipeline merges + adds new keys + handles empty + raises NotFound
- update_model merges + adds thinking fields + raises NotFound
- crossover guard: pipeline change doesn't bleed into model dict
- round-trip through `EnvironmentManifest.from_dict` confirms patched manifest stays valid

Local: skipped (pydantic + executor). CI runs them.

## Out of scope

- Frontend forms — sprint P.2.
- Model name dropdown source (will need a `/api/admin/known-models` endpoint or similar) — defer to P.2 if needed.
