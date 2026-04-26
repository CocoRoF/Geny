# G.2 — Memory tuning knobs

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/settings/sections.py` — new `MemoryTuningSection` model + `MemoryConfigSection.tuning` optional sub-block.
- `backend/service/memory_provider/config.py` — `load_memory_tuning(*, is_vtuber)` helper resolving the four knobs from settings.json with role-aware fallbacks.
- `backend/service/executor/agent_session.py` — `_build_pipeline` reads tuning via the helper instead of hardcoding.
- `backend/tests/service/memory_provider/test_tuning.py` (new) — 10 cases covering defaults, single-int / per-role-dict max_inject_chars, override knobs, and malformed-value fallback.

## What it changes

Four memory-layer knobs that were code-hardcoded in `agent_session._build_pipeline` are now editable via `settings.json:memory.tuning`:

| Knob | Historical default | Where it lives |
|---|---|---|
| `max_inject_chars` | 8000 (vtuber) / 10000 (worker) | `GenyMemoryRetriever` |
| `recent_turns` | 6 | `GenyMemoryRetriever` |
| `enable_vector_search` | True | `GenyMemoryRetriever` |
| `enable_reflection` | True | `GenyMemoryStrategy` |

`max_inject_chars` accepts either an int (applied to every role) or a per-role dict `{"vtuber": int, "worker": int}` to keep the historical role-aware defaults editable.

When the section is absent the loader returns the historical defaults exactly — migration is a no-op.

## Why

Audit (cycle 20260426_2, analysis/02 Tier 6) — these knobs were code-only. Operators tuning recall behaviour (e.g. doubling `recent_turns` to 12 for a memory-dense agent) had to patch agent_session.py.

## Tests

10 unit cases. CI runs them; local tests skip without pydantic.

## Out of scope

- Per-session override (the existing `CreateSessionModal.memory_config` could grow these fields; defer until needed).
- Live re-attach when settings.json:memory.tuning changes mid-process — same restart-required semantics as elsewhere in the cycle.
