# Q.1 — Per-session memory tuning override

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/controller/agent_controller.py` — `CreateSessionRequest.memory_config` docstring extended to document the optional `tuning` sub-block.
- `backend/service/executor/agent_session.py:_build_pipeline` — merges `self._memory_config.tuning` over the global `load_memory_tuning()` result; per-field validation with warning-on-bad-type.
- `frontend/src/components/modals/CreateSessionModal.tsx` — collapsible "Memory tuning (advanced)" section with the four knobs; submit logic builds `memory_config.tuning` and emits `memory_config` even when no provider override.
- `frontend/src/lib/i18n/{en,ko}.ts` — `createSession.memoryTuningHeader`.

## What it changes

`CreateSessionModal` operators get four new tuning fields per session:

- `max_inject_chars` (int ≥ 1)
- `recent_turns` (int ≥ 0)
- `enable_vector_search` (true / false / use global)
- `enable_reflection` (true / false / use global)

Each field is independently overridable. Empty inputs fall through to the global tuning loaded via G.2's `load_memory_tuning(is_vtuber=…)`.

Backend merge happens in `_build_pipeline` after the global tuning load — same lookup chain as G.2, but with per-session as the strongest source. Invalid values surface a warning and fall through to the global value (no crash).

## Why

Audit (cycle 20260426_3, analysis/01) — G.2 made memory tuning globally editable, but operators running A/B tests want to vary `max_inject_chars` per session without rotating the global setting.

## Tests

Type-only + UI changes; backend logic is two-line merge over G.2's already-tested `load_memory_tuning`. Existing tests continue to pass; G.2's parametrized cases still exercise the global path.

## Out of scope

- Per-session affect / persona / channel overrides (only memory tuning has the per-session use case operators asked for).
- Session info display showing the resolved tuning — defer to a separate UX cycle (the JSON config is already on the session record).
