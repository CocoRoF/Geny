# N.1 — Curated knowledge manager settings

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/settings/sections.py` — `CuratedKnowledgeSection` schema (`root` field).
- `backend/service/settings/install.py` — `register_section("curated_knowledge", CuratedKnowledgeSection)`.
- `backend/service/settings/known_sections.py` + parametrized lock test — reader entry.
- `backend/service/memory/curated_knowledge.py` — `CuratedKnowledgeManager._default_path` reads `settings.json:curated_knowledge.root` first; falls back to `DEFAULT_STORAGE_ROOT`.

## What it changes

`settings.json:curated_knowledge.root` now controls the filesystem root under which per-user curated knowledge vaults live (`{root}/_curated_knowledge/{user}`). Previously the path was hardcoded to `service.utils.platform.DEFAULT_STORAGE_ROOT`.

## Why

Audit (cycle 20260426_3, analysis/01) — Tier 6 had curated knowledge as a code-only knob. Operators wanting to relocate vaults (e.g. to a mounted volume) had no UI surface.

## Read semantics

Read at `CuratedKnowledgeManager` construction time (one per user, cached in `_curated_managers`). Changing the root mid-process affects only NEW user managers; existing ones keep their original path. To rotate the root for an existing user, restart the process (or invalidate the cache — out of scope here).

## Out of scope

- Vector store config (separate `LTMConfig.curated_vector_enabled` toggle exists; future N.x can fold it in).
- Per-user override (operators with multi-tenant deployments may want it, but the existing path-derivation already namespaces by username).
- Refresh interval — the current manager is filesystem-backed (no polling), so no interval to expose.
