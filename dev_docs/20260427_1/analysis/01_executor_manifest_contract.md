# 01 — geny-executor manifest contract (per-stage config inventory)

**Sourced from:** `/home/geny-workspace/geny-executor` exploration on 2026-04-27. Compiled into a single reference so the cycle 20260427_1 plan can map each editor to a concrete data field.

---

## EnvironmentManifest v3.0

`environment.py:245-428` (executor)

| Field | Type | Notes |
|------|------|------|
| `version` | `"3.0"` | constant |
| `metadata` | `EnvironmentMetadata` | id, name, description, author, tags[], timestamps, base_preset |
| `model` | `Dict[str, Any]` | top-level `ModelConfig` |
| `pipeline` | `Dict[str, Any]` | top-level `PipelineConfig` |
| `stages` | `List[Dict]` | 21 × `StageManifestEntry` |
| `tools` | `ToolsSnapshot` | built_in[], adhoc[], mcp_servers[], external[], scope |

Factory: `EnvironmentManifest.blank_manifest(name, ...)` (environment.py:355-428) emits a fully-populated 21-stage scaffold with default strategies + configs already filled in. **Use this as the seed for new drafts.**

---

## ModelConfig (`config.py:12-81`)

| Field | Type | Default | UI hint |
|------|------|--------|--------|
| `model` | str | `"claude-sonnet-4-20250514"` | dropdown — populate from supported list |
| `max_tokens` | int | 8192 | number input |
| `temperature` | float | 0.0 | slider 0..2 |
| `top_p` | float\|None | None | optional number |
| `top_k` | int\|None | None | optional number |
| `stop_sequences` | List[str]\|None | None | tag input |
| `thinking_enabled` | bool | False | toggle |
| `thinking_budget_tokens` | int | 10000 | number (only if thinking_enabled) |
| `thinking_type` | str | `"enabled"` | enum: enabled / disabled / adaptive |
| `thinking_display` | str\|None | None | enum: summarized / omitted / null |

Per-stage override via `StageManifestEntry.model_override`. Stages that read it: **s02 context**, **s06 api**, **s18 memory**.

Existing reusable component: `frontend/src/components/builder/ModelConfigEditor.tsx`. Already validates + emits change-only payloads.

---

## PipelineConfig (`config.py:84-188`)

| Field | Type | Default | UI hint |
|------|------|--------|--------|
| `name` | str | `"default"` | text |
| `model` | ModelConfig | (nested) | use ModelConfigEditor |
| `api_key` | str | `""` | password input (or "use env var" toggle) |
| `base_url` | str\|None | None | optional URL |
| `max_iterations` | int | 50 | number stepper |
| `cost_budget_usd` | float\|None | None | optional currency |
| `context_window_budget` | int | 200000 | number |
| `stream` | bool | True | toggle |
| `single_turn` | bool | False | toggle (advanced) |
| `artifacts` | Dict[str, str] | {} | per-stage artifact override (mostly handled at stage level) |
| `metadata` | Dict[str, Any] | {} | JSON textarea (advanced) |

Existing reusable: `frontend/src/components/builder/PipelineConfigEditor.tsx`.

---

## StageManifestEntry (`environment.py:118-163`)

8 fields per stage. Editor strategy varies per field.

| Field | Type | Editor |
|------|------|--------|
| `order` | int | derived |
| `name` | str | derived |
| `active` | bool | toggle in side panel header |
| `artifact` | str | dropdown (catalog supplies list) |
| `strategies` | Dict[slot, name] | per-slot dropdown — reuse `StrategiesEditor` |
| `strategy_configs` | Dict[strategy, Dict] | reuse `JsonSchemaForm` driven by per-strategy ConfigSchema |
| `config` | Dict | reuse `JsonSchemaForm` driven by artifact's ConfigSchema |
| `tool_binding` | Dict\|None | curated checkbox panel for s10/s11; null elsewhere |
| `model_override` | Dict\|None | reuse `ModelConfigEditor`; null = inherit pipeline.model |
| `chain_order` | Dict[slot, str[]] | reuse `ChainsEditor` (s11_tool_review, s14_evaluate) |

---

## Per-stage focal config

### Stage 6 — api (LLM caller)

- Reads `model_override` (per-stage ModelConfig) — this is the primary field
- Reads `pipeline.stream` for streaming response handling
- Curated editor: just `ModelConfigEditor` against `stage.model_override` + a "use pipeline default" toggle that nulls model_override

### Stage 10 — tools (tool execution)

- `tool_binding` shape: `{stage_order, allowed: Set<str>|None, blocked: Set<str>|None, extra_context: Dict}` (`tools/stage_binding.py:22-94`)
- Built-in tools registry: `BUILT_IN_TOOL_CLASSES` Dict (`tools/built_in/__init__.py`) — 35+ tools
- Manifest-level enable list: `manifest.tools.built_in: List[str]` (or `["*"]` for all)
- **UX**: 2-column checkbox grid grouped by capability category. Pull canonical list from `frameworkToolApi.list()`. Selection writes to `manifest.tools.built_in` (global enable) AND `tool_binding.allowed` (per-stage scope) — separate concerns.

### Stage 11 — tool_review (review chain)

- Default chain: SchemaReviewer → SensitivePatternReviewer → DestructiveResultReviewer → NetworkAuditReviewer → SizeReviewer (`stages/s11_tool_review/artifact/default/stage.py:44-77`)
- Configurable: chain order via `chain_order: Dict[slot, str[]]`
- Per-reviewer config under `strategy_configs[reviewer_name]` (e.g. SensitivePatternReviewer takes patterns list, SizeReviewer takes byte threshold)
- **UX**: drag-to-reorder list of the 5 reviewers + per-reviewer "configure" expander

### Stage 15 — hitl (human-in-the-loop)

- Two strategy slots:
  - `requester` → null / callback / pipeline_resume (`s15_hitl/types.py:20-76`)
  - `timeout` → indefinite / auto_approve / auto_reject (with `timeout_seconds` config)
- HITLRequest shape: `{token, reason, severity, tool_call_id, payload, created_at}`
- **UX**: 2 dropdowns + conditional `timeout_seconds` field; helper text explains each strategy

### Stage 18 — memory

- Two strategy slots (`s18_memory/artifact/default/stage.py:46-102`):
  - `strategy` → append_only / no_memory / reflective / structured_reflective
  - `persistence` → null / in_memory / file (config: `base_dir`)
- `model_override` consumed when strategy = reflective / structured_reflective
- Stateless flag: `stateless: bool` (disable persistence entirely)
- **UX**: 2 dropdowns + `base_dir` field (visible when persistence=file) + ModelConfigEditor (visible when strategy is reflective)

### Stage 19 — summarize

- ⚠️ **Implementation status**: analyst report flagged "configured via StageManifestEntry but implementation TBD" in executor. Verify before PR-E ships an editor. Until then: keep generic editor + "Beta" badge.

### Stage 1 — input

- Primary editable field: `stage.config.system_prompt` (string)
- **UX**: friendly textarea + persona starter chips (loaded from existing persona blocks in settings if available)

### Stage 14 — evaluate (loop terminator)

- Reads `pipeline.max_iterations`, `pipeline.cost_budget_usd`, `pipeline.context_window_budget` for ceilings
- Configurable convergence strategies (artifact-dependent)
- **UX**: pull schema via `catalogApi.stage(14)`; render JsonSchemaForm; cross-link to PipelineConfigEditor for the budget fields

### Other stages (2/3/4/5/7/8/9/12/13/16/17/20)

Mostly internal plumbing (context, system, guard, cache, token, think, parse, agent, task_registry, loop, emit, persist). Generic editor (artifact picker + strategies + JsonSchemaForm) is sufficient. Only escalate to a curated editor if a specific stage proves to need one.

---

## ToolsSnapshot (`environment.py:69-105`)

| Field | Type | Editor |
|------|------|--------|
| `built_in` | List[str] | global checkbox grid in Global section |
| `adhoc` | List[Dict] | read-only listing (custom tools registered programmatically — out of scope for tab UI) |
| `mcp_servers` | List[Dict] | embed a `<McpServerForm>` extracted from existing `McpServersTab` |
| `external` | List[str] | tag input (host-supplied tool names) |
| `scope` | Dict | JSON textarea (advanced) |

`mcp_servers` entry shape (per `tools/mcp/manager.py:87-97`):
```ts
{ name, command, args[], env, transport: "stdio"|"http"|"sse", url, headers }
```

---

## Out-of-manifest concerns

| Concern | Lives in | Why deferred |
|--------|---------|---|
| Hooks | `.geny/hooks.yaml` (executor-side, global) | Not part of EnvironmentManifest. Per-env hooks would need v4.0 schema + executor changes. |
| Permissions | `settings.json` cascade (CLI > local > project > user > preset) | Same — global resolution outside manifest. PermissionRule rules can be set at preset source if needed. |
| Skills | Geny `SkillsTab` (Geny-only concept; executor doesn't know about skills as a first-class entity) | Skills are loaded as ad-hoc tool providers; not modeled as their own manifest field. |

The new tab will surface these as **read-only links** ("이 환경은 글로벌 설정을 따릅니다 → Hooks 탭에서 편집") rather than duplicating the editors.

---

## Catalog endpoints (already exist)

Frontend `lib/environmentApi.ts` exposes:

- `catalogApi.full()` → all stages + artifacts + strategies + chains
- `catalogApi.stage(order)` → `StageIntrospection` (full schema for one stage)
- `catalogApi.listArtifacts(order)` → list of artifact names per stage
- `catalogApi.artifactByStage(order, name)` → introspection for a specific artifact

These give us **runtime-introspected JSON schemas** for every artifact's ConfigSchema and every strategy's config. No hand-maintained schema files needed — the editor forms can be schema-driven via existing `JsonSchemaForm` for any stage where curated UI isn't worth the build.

---

## Save endpoints (already exist)

- `environmentApi.create(payload)` — POST /api/environments. **Currently doesn't accept `manifest_override`.**
- `environmentApi.replaceManifest(envId, manifest)` — PUT /api/environments/{id}/manifest. **Works for full-manifest replacement.**

PR-A will use the **two-step flow** (create blank → replaceManifest) to avoid backend changes. Promote to single-step `manifest_override` later if desired.
