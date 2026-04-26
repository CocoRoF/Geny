# K.1 — Skills missing fields (version + execution_mode + extras)

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/controller/skills_controller.py` — `UserSkillUpsertRequest` extended with `version`, `execution_mode`, `extras`. `_build_skill_md` emits the new keys into the SKILL.md frontmatter (extras as a flat YAML mapping; nested values silently skipped — operators with deeper structures hand-edit). `_VALID_EXECUTION_MODES = {"inline", "fork"}` validation.
- `frontend/src/lib/api.ts` — `SkillDetail` + `UserSkillUpsertRequest` carry the new fields.
- `frontend/src/components/tabs/SkillsTab.tsx` — `FormState` extended; create/edit modal gains "Version" + "Execution mode" inputs (side-by-side) and an "Extras" JSON textarea.

## What it changes

User skills can now declare `version`, `execution_mode` (inline | fork), and `extras` (flat dict) — three fields supported by `geny_executor.skills.SkillMetadata` but previously dropped at the controller boundary. `extras` covers operator-defined metadata (icons, owner tags, etc.) that the executor's frontmatter parser surfaces back via `Skill.metadata.extras`.

## Why

Audit (cycle 20260426_2, analysis/02 Tier 5) — these three fields existed in the executor's metadata schema but had no surface in Geny's editor.

## Constraints

- `extras` serialiser only handles **flat scalar values** (string / number / boolean). Nested structures are silently skipped on write because the SKILL.md frontmatter format doesn't have a generic emitter inside the controller. Operators wanting nested extras edit the SKILL.md directly.
- `execution_mode` validated server-side; an unknown value yields HTTP 400.

## Tests

UI + serialiser changes; covered by existing controller tests for the round-trip path. CI lint + tsc + Next build is the gate.

## Out of scope

- Bundled skills exposing their version / extras read-only — defer; bundled skills are read-only by design and the existing detail viewer already shows the body.
- Nested-extras YAML emitter — defer.
