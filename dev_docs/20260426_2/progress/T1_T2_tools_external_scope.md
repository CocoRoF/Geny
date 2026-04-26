# T.1 + T.2 — `tools.external` picker + `tools.scope` editor (combined)

**PR:** TBD
**Status:** Merged TBD

Bundled into one PR because both touch the same `ToolsEditor` body and validation pipeline; splitting them would mean editing the file twice with overlapping diffs.

**Files changed:**
- `backend/controller/tool_controller.py` — new `GET /api/tools/catalog/external` returning `GenyToolProvider.list_names()` flattened with built_in vs custom category.
- `frontend/src/lib/api.ts` — `externalToolCatalogApi.list()`; `ExternalToolEntry` / `ExternalToolCatalogResponse` types.
- `frontend/src/components/environment/ToolsEditor.tsx` — `ToolsDraft` gains `external: string[]` + `scopeText: string`; new `parseJsonObjectOrEmpty` validator; new `ToolsValidation.scopeError`; checkbox grid renders external candidates from the catalog when `externalCatalog` prop is supplied; `tools.scope` textarea rendered after the external section.
- `frontend/src/components/tabs/BuilderTab.tsx` — loads external catalog on mount; passes through to `<ToolsEditor>`.

## What it changes

**T.1 — external picker.** The Builder Tools view gets a "External tools (GenyToolProvider)" section: scrollable checkbox grid listing every tool the loader advertises (Geny built-ins like `web_search`, `browser`; custom drops in `backend/tools/custom/`). Each row shows the tool name + category badge. Selected names land in `manifest.tools.external`; the executor's `Pipeline.from_manifest_async` reads that whitelist and tells `GenyToolProvider` which tools to actually attach.

Previously the field had no UI — operators had to ImportManifestModal raw JSON to populate `tools.external`. Without it, env-driven sessions couldn't access any custom Geny tool even though `GenyToolProvider` was registered.

**T.2 — scope editor.** Below the external picker: a JSON textarea for `manifest.tools.scope` (free-form dict consumed by host plugins; today's executor accepts any shape so we keep the editor schema-loose). Empty = no scope.

## Why

Audit (cycle 20260426_2, analysis/02 Tier 4) — both fields existed in the manifest and were used by Geny's tool plumbing, but the UI hid them entirely.

## Tests

UI changes plus a thin backend endpoint. The endpoint is a one-liner over `loader.builtin_tools` / `loader.custom_tools` — covered by existing tool_loader tests at the source. CI lint + tsc + Next build is the gate.

## Out of scope

- Per-tool input_schema preview on hover — defer until usage shows demand.
- Structured `tools.scope` form (depends on which host plugins consume it; the schema is currently undocumented at the executor level) — JSON textarea is the honest minimum.
