# M.1 — VTuber sub-worker auto-spawn config

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/settings/sections.py` — new `VTuberSubWorkerSection` model + `VTuberSection.sub_worker` optional sub-block.
- `backend/service/executor/agent_session_manager.py` — `_load_vtuber_sub_worker_section()` + `_vtuber_sub_worker_notice()` helpers; the hardcoded `_VTUBER_SUB_WORKER_NOTICE` replaced with a function call so settings changes take effect on the next sub-worker spawn (no restart needed); sub-worker spawn falls back through (request override) → (settings default) → (resolve_env_id system default).

## What it changes

Three previously-hardcoded sub-worker config items become settings-editable:

- `notice_template` — markdown appended to the VTuber persona prompt (was the `_VTUBER_SUB_WORKER_NOTICE` constant).
- `default_env_id` — env_id for the sub-worker when the per-request `sub_worker_env_id` is absent.
- `default_model` — model for the sub-worker when the per-request `sub_worker_model` is absent.

Per-request overrides still win (highest priority). Settings defaults are next. The system default (via `resolve_env_id` / model resolution) is the floor.

## Why

Audit (cycle 20260426_3, analysis/01) — VTuber-paired sub-worker spawn config was code-only. Operators wanting a custom Worker template (e.g. a coding-focused Worker for one VTuber persona vs a research-focused Worker for another) had to patch the source.

## Read semantics

The notice template is read on every sub-worker spawn (`_vtuber_sub_worker_notice()` is a function, not a module-level constant). The default env_id / model are read inside the spawn block. So changes to `settings.json:vtuber.sub_worker.*` take effect on the **next sub-worker auto-spawn** without a process restart — same convention as the rest of the cycle's settings sections (the existing per-session bound runtime is not mutated).

## Out of scope

- Per-session sub-worker config UI in CreateSessionModal — the existing per-request fields (`sub_worker_env_id`, `sub_worker_model`, `sub_worker_system_prompt`) already cover this.
- Multi-worker pairing (one VTuber → many workers) — defer; current single-pair contract is what every consumer uses.
- VTuberSubWorkerSection registration in known_sections (the `vtuber` section is already there; the sub-block lives under it).
