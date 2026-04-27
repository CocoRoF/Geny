# Cycle 20260427_1 — Library (NEW): 21-stage visual environment builder

**Date:** 2026-04-27
**Goal:** Add a NEW top-level tab `Library (NEW)` that lets a user build an `EnvironmentManifest` v3.0 by clicking each of the 21 pipeline stages and editing its config in a stage-specific UI. Existing Library / BuilderTab paths stay untouched.

The end-state is: open the new tab → see the 21-stage canvas → click any stage → edit its config in a side panel (or modal) with a stage-curated form → name + tag + Save → `environmentApi.create()` posts the assembled manifest as a fresh env.

Scope is intentionally **forward-only** — no read-back / migration of existing v2 manifests into the new draft state. (The user explicitly opted out of legacy interop; old envs stay editable in the existing BuilderTab.)

---

## 1. Goals

1. **Top-level tab** `library_new` — new entry in `TAB_MAP`, sidebar icon, sub-tab strip not required (single surface).
2. **Visual 21-stage canvas as the primary navigator** — reuse `PipelineCanvas` with a new edit-aware variant.
3. **Per-stage editor framework** — open a side panel when a stage is clicked. The panel hosts either a stage-specific curated editor or a generic fallback (artifact picker + strategy slot picker + JSON config + per-stage model_override + tool_binding).
4. **Stage-curated editors for the high-leverage stages** the user called out: tool / mcp / skills / hooks / memory.
5. **Top-level metadata + tools + pipeline + model editors** — accessible from the tab header (not behind a stage click).
6. **Single-shot Save** — all draft edits live in zustand until the user hits Save; one `environmentApi.create()` call produces a fresh env. No autosave / no incremental persistence.
7. **Per-stage validation & dirty-tracking** — header shows "X stages edited / Y warnings" and disables Save while validation fails.

## 2. Non-goals

- Editing existing v2 envs in the new tab. (`BuilderTab` / old `EnvironmentsTab` keep that responsibility.)
- Changing the persisted manifest schema. The new tab produces v3.0 exactly as `EnvironmentManifest.blank_manifest()` defines.
- Replacing the existing tabs. PR-Layout / PR-Env / PR-Merge already shipped — `라이브러리(NEW)` is parallel.
- Rebuilding hooks / permissions / skills sections in this tab. They remain global (settings.json / `.geny/hooks.yaml`) and are NOT part of `EnvironmentManifest`. The new tab will surface them as **read-only links** to the existing global tabs ("이 환경은 글로벌 hooks/permissions/skills 설정을 그대로 따릅니다 → 편집하기").

---

## 3. Data contract reference

(Compiled from `/home/geny-workspace/Geny/dev_docs/20260427_1/analysis/01_executor_manifest_contract.md` — to be written next; condensed inline below.)

### EnvironmentManifest v3.0 (geny-executor)

| Field | Type | Notes |
|------|------|------|
| `version` | `"3.0"` | constant |
| `metadata` | `EnvironmentMetadata` | id (auto), name (req), description, author, tags[], timestamps, base_preset |
| `model` | `Dict[str, Any]` | top-level `ModelConfig` (provider/model/temperature/thinking/...) |
| `pipeline` | `Dict[str, Any]` | top-level `PipelineConfig` (max_iterations, cost_budget_usd, context_window_budget, stream, single_turn, artifacts, metadata) |
| `stages` | `List[Dict[str, Any]]` | 21-element array of `StageManifestEntry` |
| `tools` | `ToolsSnapshot` | built_in[], adhoc[], mcp_servers[], external[], scope |

### StageManifestEntry per stage

| Field | Editor strategy |
|------|-----------------|
| `order` | derived (1..21) |
| `name` | derived (e.g. `s06_api`) |
| `active` | toggle in side panel |
| `artifact` | dropdown (catalog supplies list per stage) |
| `strategies: Dict[slot_name, strategy_name]` | per-slot dropdown (StrategiesEditor) |
| `strategy_configs: Dict[strategy_name, Dict]` | dynamic form per strategy (JsonSchemaForm) |
| `config: Dict` | dynamic form (JsonSchemaForm) keyed off the artifact's ConfigSchema |
| `tool_binding: Dict` | curated tool checkbox panel (only for stages that have a tool_binding slot, e.g. s10_tools / s11_tool_review) |
| `model_override: Dict` | reuse `ModelConfigEditor` (only enabled for stages where it matters: s02, s06, s18) |
| `chain_order: Dict[slot, str[]]` | reuse `ChainsEditor` (only for stages with chain slots, e.g. s11_tool_review, s14_evaluate) |

### Out-of-manifest concerns

- **Hooks** → `.geny/hooks.yaml` (HookConfigEntry). Global, not env-scoped. **Defer to existing `HooksTab` via cross-link.**
- **Permissions** → settings.json cascade. Global. **Defer to existing `PermissionsTab` via cross-link.**
- **Skills** → Geny-only concept. Currently global via `SkillsTab`. **Defer via cross-link.**

If we later want per-env hooks/permissions/skills we'll need executor + backend changes; not in scope here.

---

## 4. Architecture

### 4.1 New zustand store: `useEnvironmentDraftStore`

Owns the in-progress `EnvironmentManifest` plus per-stage dirty flags + validation. Lives separate from `useEnvironmentStore` (which only deals with persisted envs). Discarded on tab unmount unless user opts to persist.

```ts
interface EnvironmentDraftState {
  draft: EnvironmentManifest | null;        // null until "New" clicked
  stageDirty: Set<number>;                  // stage orders touched
  validationErrors: Record<string, string>; // path → message
  // actions
  newDraft(seed?: 'blank' | 'preset', presetName?: string): Promise<void>;
  patchMetadata(patch: Partial<EnvironmentMetadata>): void;
  patchModel(patch: Record<string, unknown>): void;
  patchPipeline(patch: Record<string, unknown>): void;
  patchStage(order: number, patch: Partial<StageManifestEntry>): void;
  patchTools(patch: Partial<ToolsSnapshot>): void;
  resetDraft(): void;
  saveDraft(): Promise<{ id: string }>;
}
```

`newDraft('blank')` calls a tiny new helper — either backend endpoint or frontend builder — that emits `EnvironmentManifest.blank_manifest()`-equivalent JSON. (Decision in §6.)

### 4.2 Component tree

```
src/components/library_new/
  LibraryNewTab.tsx                   # top-level wrapper (TabShell)
  PipelineCanvasEditable.tsx          # thin wrapper around PipelineCanvas with onStageClick + stageDirty highlighting
  TopBar.tsx                          # name / desc / tags + Save / Discard
  GlobalSection.tsx                   # collapsible "전역 설정" (model + pipeline + tools + cross-links to hooks/perms/skills)
  StageEditorPanel.tsx                # right slide-in panel — picks the right inner editor per stage
  stages/
    StageGenericEditor.tsx            # fallback (artifact + strategies + chains + JsonSchemaForm)
    Stage06ApiEditor.tsx              # LLM provider / model / temperature / thinking
    Stage10ToolsEditor.tsx            # checkbox-driven built_in + custom + mcp picker; writes to tool_binding + tools snapshot
    Stage11ToolReviewEditor.tsx       # reviewer chain ordering + per-reviewer config
    Stage15HitlEditor.tsx             # requester + timeout strategies, threshold form
    Stage18MemoryEditor.tsx           # strategy + persistence + model_override picker
    Stage19SummarizeEditor.tsx        # (when implemented in executor) summarizer prompt + cadence
```

Reused as-is (no fork):
- `ModelConfigEditor`, `PipelineConfigEditor` (in `builder/`)
- `JsonSchemaForm` (in `environment/`)
- `StrategiesEditor`, `ChainsEditor` (in `environment/`)
- `stageMetadata.ts` (in `session-env/`)
- `PipelineCanvas.tsx` (extend with optional `onStageClick` + `dirtyStages` props — additive, doesn't break SessionEnvironmentTab)

### 4.3 Save flow

1. User edits stages → `patchStage()` mutates `draft` and adds `order` to `stageDirty`.
2. Header shows `${stageDirty.size}개 단계 편집됨`.
3. Per-stage editor runs synchronous client-side validation; errors go into `validationErrors`. Save button disabled while non-empty.
4. Click Save → `saveDraft()` posts the entire `draft` via `environmentApi.create({ mode: 'blank', name, description, tags, manifest_override: draft })`.
   - **Open question (Q1)**: does `create()` accept a full manifest_override today? If not, we need a tiny backend extension. See §6.
5. On success, navigate user to the existing `EnvironmentDetailDrawer` of the new env, and clear the draft.

### 4.4 Discard flow

If `stageDirty.size > 0` or metadata is dirty, prompt before tab switch / unmount. Use existing `ConfirmModal`.

---

## 5. Phased PR breakdown

Each PR is independently reviewable and shippable. PR-1 lands the scaffold without ANY stage editor (all stages show "Coming soon"); subsequent PRs replace the placeholder with real editors one or two stages at a time.

### **PR-A — Scaffold + draft store + canvas wiring** (~600 LOC)

- New tab `library_new` registered in `TabContent.tsx` + `useAppStore.activeTab` (no type change needed — already `string`)
- Sidebar / tab strip: add icon + label entry. (Verify which file owns the global tab strip — see §6 Q3.)
- New zustand store `useEnvironmentDraftStore` (state + actions skeleton, no validation logic yet)
- `LibraryNewTab.tsx` with `TabShell`, top bar (name + Save disabled placeholder), Global section (collapsed, links to existing tabs + ModelConfigEditor + PipelineConfigEditor wired into draft.model / draft.pipeline)
- `PipelineCanvasEditable.tsx`: extend `PipelineCanvas` with `onStageClick` callback and `dirtyStages: Set<number>` for visual highlighting
- `StageEditorPanel.tsx`: side panel skeleton — selects a stage, renders `StageGenericEditor` for ALL stages (every stage uses the generic fallback)
- `StageGenericEditor.tsx`: artifact picker + active toggle + StrategiesEditor + ChainsEditor + JsonSchemaForm for `config` — all writing to `patchStage()`
- "New blank draft" button + "Discard" button + dirty-tracking + ConfirmModal on unmount
- Save: posts `environmentApi.create()` (assuming Q1 resolves to "create accepts manifest_override"; otherwise this PR adds the backend hook too)
- i18n keys added under `libraryNewTab.*` for both en / ko
- Unit smoke: store actions + draft serialization

**Acceptance**: open the new tab → click "새 환경" → click stage 6 → see generic editor → tweak artifact → close panel → see stage 6 highlighted as dirty → click Save → env appears in old EnvironmentsTab list.

### **PR-B — Stage 6 (api) + Stage 18 (memory) curated editors** (~400 LOC)

- `Stage06ApiEditor.tsx` — uses `ModelConfigEditor` against `stage.model_override`; "Use pipeline default" toggle that nulls model_override
- `Stage18MemoryEditor.tsx` — strategy dropdown (append_only / no_memory / reflective / structured_reflective), persistence dropdown (null / in_memory / file with path field), optional model_override (same `ModelConfigEditor`), retention notes
- `StageEditorPanel` routing table: stage 6 → curated, stage 18 → curated, others → generic
- Unit: serializing each curated editor's draft into `StageManifestEntry`

### **PR-C — Stage 10 (tools) curated editor + tools-snapshot integration** (~500 LOC)

- `Stage10ToolsEditor.tsx` — checkbox grid for built_in (uses `frameworkToolApi.list()`), then a "MCP 서버" section that lists `manifest.tools.mcp_servers` (read-only here, edited in Global section). Picks which subset is exposed in s10_tools via `tool_binding.allowed/blocked`.
- Update `Global section` to host the **MCP server picker** (re-uses logic extracted from current `McpServersTab` JSON form into a standalone `<McpServerForm>` — small refactor)
- Update `Global section` to host the **custom tool snapshot** (read-only listing of `tools.adhoc` since custom tool registration is a developer concern; show the serialized list for verification)
- Cross-link to `ToolSetsTab` for "이미 만들어둔 프리셋에서 시작하기" (pre-fills tools snapshot from a chosen preset)

### **PR-D — Stage 11 (tool_review) + Stage 15 (hitl) curated editors** (~400 LOC)

- `Stage11ToolReviewEditor.tsx` — chain order drag-list (or button-based reorder) for the 5 reviewers (SchemaReviewer / SensitivePatternReviewer / DestructiveResultReviewer / NetworkAuditReviewer / SizeReviewer); per-reviewer config (sensitive patterns, destructive heuristics, size threshold)
- `Stage15HitlEditor.tsx` — requester strategy dropdown (null / callback / pipeline_resume), timeout strategy dropdown (indefinite / auto_approve / auto_reject + timeout_seconds field)

### **PR-E — Stage 1 (input) + Stage 14 (evaluate) curated editors** (~300 LOC)

- `Stage01InputEditor.tsx` — friendly system_prompt textarea (rendered as `stage.config.system_prompt`); pre-set persona templates as starter chips
- `Stage14EvaluateEditor.tsx` — convergence strategy + score threshold + retry policy + cost-aware termination flags (these often live partially in pipeline.config, partially in stage.strategy_configs — clarify in PR description)

### **PR-F — Polish: validation + warnings + presets** (~300 LOC)

- Per-stage validation: required fields per artifact (driven by `catalogApi.stage(order)` schemas)
- Warning banner system inside each panel ("이 stage는 비활성 상태인데 active=true 인 stage 11이 의존합니다" etc.)
- "프리셋에서 시작" — pull list from current preset envs (`environmentApi.list().filter(tags includes 'preset')`) and seed `draft` from one
- Side-by-side diff against the preset (uses existing `EnvironmentDiffModal`)

Total: 6 PRs, ~2500 LOC net new (excluding reused editors). Each PR ships independently — even after PR-A users get a usable (if minimal) new tab.

---

## 6. Open questions

**Q1 — Backend: does `POST /api/environments` accept a full `manifest_override`?**
Current `CreateEnvironmentPayload` (frontend `environmentApi.ts`) uses `{ mode, name, description, tags, session_id?, preset_name? }`. There's no field for "give me a fully-formed manifest". Either:
- (a) Add `manifest_override?: EnvironmentManifest` to the create endpoint (preferred — small backend change in `environment_controller.py`)
- (b) Use the existing two-step flow: `create({ mode: 'blank', name })` → returns `{ id }` → `replaceManifest(id, draft)`
Option (b) works today with no backend change, at the cost of a window where the env exists with the blank manifest. PR-A will use (b) unless we decide otherwise.

**Q2 — Where does the `blank_manifest()` factory live for the frontend?**
Backend `EnvironmentManifest.blank_manifest()` produces the 21-stage scaffolding. Frontend has no mirror. Options:
- (a) Call `environmentApi.create({ mode: 'blank' })` and use the returned `EnvironmentDetail.manifest` as the starting draft (one network round-trip per "new draft" click — acceptable)
- (b) New endpoint `GET /api/environments/blank-manifest` returns the JSON without persisting
- (c) Mirror `blank_manifest()` in TS via `catalogApi.full()` + per-stage default config
PR-A will use (a). We can promote to (b) later if persistent "abandoned drafts" become noisy.

**Q3 — Where does the global tab strip render?**
Inventory found `Sidebar.tsx` is session-scoped. The top-level `메인 / 라이브러리 / 공유 폴더 / ...` strip is rendered elsewhere — possibly `Header.tsx` or `TopNav.tsx`. Need to confirm in PR-A scope and decide whether the new `Library (NEW)` shows up next to `Library` or somewhere distinct (e.g., end of the strip with a `BETA` badge).

**Q4 — Per-env vs. global hooks/permissions/skills?**
Plan defers them to the existing global tabs via cross-links. If we later decide they should be per-env, that requires:
- executor: store these inside `EnvironmentManifest` (needs `version: "4.0"`)
- backend: schema migration + install layer changes
- frontend: new manifest fields + draft store integration
This is a separate cycle. For now: cross-link is correct.

**Q5 — Stage 19 (summarize) executor implementation status?**
Analyst report flagged Stage 19 as "configured via `StageManifestEntry` but implementation TBD". PR-E should ship its editor only after the executor side lands; otherwise show "Coming soon" placeholder.

---

## 7. Risk register

| Risk | Mitigation |
|------|-----------|
| `PipelineCanvas` extension breaks `SessionEnvironmentTab` | Make new props optional + default to current behavior; add a smoke test that mounts `SessionEnvironmentTab` with no props change |
| Draft store leaks across tab switches | Reset on unmount + ConfirmModal on dirty switch + persist key under `sessionStorage` so refresh recovers |
| Save creates a "blank then replace" window where env temporarily has the blank manifest (Q1 option b) | Only blocks if user navigates away mid-save; show optimistic UI; toast on completion |
| Per-stage config schemas not actually exposed by `catalogApi.stage(order)` | Verify in PR-A; if missing, fall back to raw JSON textarea (current `BuilderTab` behavior) |
| Adding `library_new` to `LIBRARY_SUB_REDIRECT` map by accident bounces user back to old Library | Explicitly set `activeTab: 'library_new'` directly; do NOT add it to redirect map |

---

## 8. Out-of-scope explicitly

- Replacing or removing the existing `EnvironmentsTab` / `BuilderTab`. They keep working.
- Migration tool for v2 → v3 envs (executor already auto-upgrades on load — no UI tool needed).
- Multi-user collaborative editing of a draft.
- Manifest version > 3.0.
- Hooks / permissions / skills moved into per-env scope (see Q4).
