# Cycle 20260426_2 — Library coverage uplift

**Date:** 2026-04-26
**Goal:** Surface every geny-executor configuration option in the Library tab, fix the silent hook schema bug, and bring Geny's own extensions into the same UI.
**Trigger:** User directive — "geny-executor에서 설정할 수 있는 모든 옵션들이 전부 존재해야 한다."

## Phase H — Hook schema rescue (3 PR)

### Sprint H.1 — Backend schema rewrite
**Files:**
- `backend/controller/hook_controller.py` — `HookEntryPayload` to executor schema (`command:str`, `args`, `match dict`, `env`, `working_dir`).
- Top-level `HookConfigEnvelope` (`enabled`, `entries`, `audit_log_path`).
- `_KNOWN_EVENTS` synced to executor's `HookEvent` enum.
- Backwards-compat read: `tool_filter` → `match: {"tool": ...}`, `command: list` → `command: str` + `args`.
- Tests: `tests/controller/test_hook_controller_schema.py` (4 cases).

### Sprint H.2 — Frontend rewrite
**Files:**
- `frontend/src/components/tabs/HooksTab.tsx` — full form rewrite.
- 14-event picker (drop legacy STOP/SUBAGENT_STOP/PRE_COMPACT — verify against executor enum).
- Command (single string) + args (one per line) inputs.
- Match dict editor (initially `tool` field; key/value rows).
- Env table (key/value rows).
- Working_dir input.
- Header: enabled toggle + audit_log_path input.
- i18n in en/ko.

### Sprint H.3 — End-to-end parse test
**Files:**
- `backend/tests/integration/test_hook_executor_roundtrip.py` (new).
- Writes a hook via the controller, reads settings.json, passes through `HookConfig.from_mapping`, asserts no exception + entries round-trip.

## Phase P — Pipeline + Model config (2 PR)

### Sprint P.1 — Backend patch endpoints
**Files:**
- `backend/controller/environment_controller.py` — `PATCH /api/environments/{id}/pipeline` + `PATCH /api/environments/{id}/model`.
- Validates against `PipelineConfig` / `ModelConfig` schemas (re-export from executor).
- Returns updated `EnvironmentDetailResponse` with `affected_sessions` (D.3 pattern).
- Tests (3+3 cases).

### Sprint P.2 — Builder editors
**Files:**
- `frontend/src/components/builder/PipelineConfigEditor.tsx` (new) — number steppers, toggles.
- `frontend/src/components/builder/ModelConfigEditor.tsx` (new) — model dropdown, sliders for temperature / top_p, thinking_type enum dropdown.
- `frontend/src/components/tabs/BuilderTab.tsx` — header tabs ("Stages" | "Pipeline" | "Model") to mount each editor.
- i18n.

## Phase S — Per-stage advanced fields (2 PR)

### Sprint S.1 — model_override
- StageDetailPanel form for `model_override` (model + max_tokens + temperature + thinking_*).

### Sprint S.2 — tool_binding (s10)
- StageDetailPanel form for `tool_binding` (allowlist / blocklist patterns specific to s10).

## Phase R — Permission mode (1 PR)

### Sprint R.1
**Files:**
- `backend/service/permission/install.py` — read mode from settings.json:permissions.mode (fall back to env).
- `backend/controller/permission_controller.py` — PATCH `/api/permissions/mode` endpoint.
- `frontend/src/components/tabs/PermissionsTab.tsx` — mode dropdown in header.
- Tests.

## Phase T — Tools surface (3 PR)

### Sprint T.1 — `tools.external` picker
- Backend: `GET /api/tools/catalog/external` exposing `GenyToolProvider.list_names()` (or equivalent).
- Builder Tools view: checkbox grid like ToolCatalog but for external.

### Sprint T.2 — `tools.scope` editor
- Builder Tools view: scope dict editor (key-value rows).

### Sprint T.3 — MCP structured editor
- McpServersTab: form fields per transport (stdio: command/args/env; http/sse: url/headers).
- Keep raw-JSON fallback for advanced users.

## Phase K — Skills + Settings consistency (2 PR)

### Sprint K.1 — Skills missing fields
- SkillsTab editor: `version`, `execution_mode`, `extras`.
- Backend skill upsert payload extension.

### Sprint K.2 — `permissions` settings section
- Register `PermissionsConfigSection` schema in `install_geny_settings`.
- FrameworkSettingsPanel renders the section like the others.
- Permission controller migrates to typed read.

## Phase G — Geny extensions (4 PR)

### Sprint G.1 — Memory provider UI
- Register `MemoryConfigSection` in `install_geny_settings`.
- `MemorySessionRegistry` reads settings.json:memory before falling back to env vars.
- FrameworkSettingsPanel exposes provider/root/dsn/dialect/scope/timezone.

### Sprint G.2 — Memory tuning knobs
- Settings.json:memory.tuning section: `max_inject_chars`, `recent_turns`, `enable_vector_search`, `enable_reflection`.
- `agent_session.py:_build_pipeline` reads these (defaults preserved).

### Sprint G.3 — Affect emitter knob
- `affect.max_tags_per_turn` in settings.json.
- `service/emit/chain_install.py` reads it.

### Sprint G.4 — Notifications CRUD UI
- New Library sub-tab `notifications` (or under Settings).
- CRUD endpoints for notification endpoints.
- Migrates `~/.geny/notifications.json` writes to atomic settings.json:notifications shape.

## Sequencing

Strictly front-to-back per user directive. Each PR opens, merges, then the next branches off main. ~17 PRs total. Carve-outs allowed only when a sprint discovers it spans a multi-cycle architectural shift (e.g. memory provider per-session override).

## Done criteria

- All sprints merged.
- `progress/README.md` table fully ticked.
- Hook end-to-end parse test green.
- Library tab can configure every executor option from the gap analysis without resorting to raw JSON import.
