# Progress 04 — Executor v0.24.0 `Pipeline.attach_runtime()` + Geny pin

| Field | Value |
|-------|-------|
| Plan ref | `plan/02_default_env_per_role.md` → **Prereq B** / PR table rows 1–2 |
| Master ref | `plan/00_overview.md` → **Phase 2 / PRs 7 & 9** |
| Executor PR | [CocoRoF/geny-executor#30](https://github.com/CocoRoF/geny-executor/pull/30) |
| Executor release | [v0.24.0](https://github.com/CocoRoF/geny-executor/releases/tag/v0.24.0) |
| Geny PR | [#148](https://github.com/CocoRoF/Geny/pull/148) |
| Geny merge commit | `34fa77d` on `main` |
| Status | **Both merged** |

---

## What shipped

### Executor — v0.24.0

A single additive helper on `Pipeline`:

```python
def attach_runtime(
    self,
    *,
    memory_retriever:    MemoryRetriever        | None = None,
    memory_strategy:     MemoryUpdateStrategy   | None = None,
    memory_persistence:  ConversationPersistence | None = None,
) -> None: ...
```

| Kwarg | Target | Slot |
|---|---|---|
| `memory_retriever` | Stage 2 (Context) | `retriever` |
| `memory_strategy`  | Stage 15 (Memory) | `strategy`  |
| `memory_persistence` | Stage 15 (Memory) | `persistence` |

- **Keyword-only.** Omitted kwargs preserve the prior slot.
- **Missing target stage** is a silent no-op — a pipeline without
  a Memory stage simply has nowhere to attach memory runtime.
- **Post-run guard.** A new `Pipeline._has_started` flag flips to
  `True` on the first `run()` / `run_stream()` invocation; calling
  `attach_runtime` afterwards raises `RuntimeError`. Earlier stage
  state has already captured slot references, so swapping them
  would yield a mixed-runtime pipeline whose behaviour is hard to
  reason about. Build a fresh pipeline and attach before running.

Implementation detail: `StrategySlot.strategy` is a plain dataclass
field and is directly assignable, so the helper just walks
`pipeline._stages.values()`, looks up the requested slot via
`stage.get_strategy_slots()`, and does `slot.strategy = <obj>`.
No new slot-mutation API was required.

### Why this shape, not the plan's original 6-kwarg sketch

The plan sketch showed six kwargs: `memory_manager`, `llm_reflect`,
`llm_gate`, `curated_knowledge_manager`, `conversation_persistence`,
and so on. That would have moved three Geny-level constructor args
(`llm_reflect`, `llm_gate`, `curated_knowledge_manager`) across the
boundary. But those are *already* arguments to `GenyMemoryStrategy`
and friends — by the time Geny calls `attach_runtime`, it can build
those objects itself and pass the finished `MemoryUpdateStrategy` /
`MemoryRetriever` / `ConversationPersistence`. Narrowing to three
runtime kwargs keeps the executor surface honest about what it
actually injects and avoids leaking Geny-specific concepts into a
library contract.

### Executor tests

`tests/unit/test_pipeline_attach_runtime.py` — **8 new tests**:

| # | Assertion |
|---|-----------|
| 1 | `memory_retriever` replaces Context.retriever slot identity |
| 2 | `memory_strategy` + `memory_persistence` replace Memory slots |
| 3 | All three kwargs applied together |
| 4 | Idempotent before first run — last call wins per kwarg |
| 5 | Missing Memory stage is a silent no-op |
| 6 | Partial attach preserves prior slot (omitted kwarg = untouched) |
| 7 | Post-run call raises `RuntimeError("attach_runtime")` |
| 8 | No-kwarg call is a valid no-op |

Full suite: **1023 passed, 18 skipped.** Ruff + format clean.

### PyPI

Live at `https://pypi.org/project/geny-executor/0.24.0/` (verified
via `pypi/geny-executor/0.24.0/json` endpoint). The workflow's
TestPyPI job failed as on prior releases, but the PyPI job
succeeded — same pattern as 0.22.1 and 0.23.0.

### Geny — pin bump

Two one-line changes:

- `backend/pyproject.toml`: `geny-executor>=0.23.0,<0.24.0` →
  `>=0.24.0,<0.25.0`
- `backend/requirements.txt`: same

**No consumer code changes** in PR #148. `Pipeline.attach_runtime`
is not yet called anywhere — Geny sessions still go through
`GenyPresets.worker_adaptive(...)` and `GenyPresets.vtuber(...)`.
The actual consumer swap happens in master-plan **PR 16**, when
`AgentSession._build_pipeline` is reduced to a
`Pipeline.from_manifest_async(...) + attach_runtime(...)` pair
and the `GenyPresets.*` branches are deleted. Isolating the
executor pin bump from the refactor keeps either one easy to
revert.

---

## Phase 2 status

| # | Title | PR | Status |
|---|-------|----|--------|
| 7 | Executor: `Pipeline.attach_runtime` | executor#30 / v0.24.0 | **Done** |
| 8 | Progress doc for PR 7 | *this doc (part 1)* | **Done** |
| 9 | Geny: pin bump to 0.24.0 | #148 | **Done** |
| 10 | Progress doc for PR 9 | *this doc (part 2)* | **Done** |
| 11 | Geny: populate `build_default_manifest.stages` | — | **Next** |
| 12 | Progress doc for PR 11 | — | pending |
| 13 | Geny: seed `install_environment_templates` + `ROLE_DEFAULT_ENV_ID` | — | pending |
| 14 | Progress doc for PR 13 | — | pending |
| 15 | Geny: `AgentSessionManager` always resolves `env_id` | — | pending |
| 16 | Progress doc for PR 15 | — | pending |
| 17 | Geny: `AgentSession._build_pipeline` → `attach_runtime` only | — | pending |

PRs 8 and 10 are bundled into this single progress doc because the
executor release and the pin bump are inseparable — pinning 0.24.0
has no value without 0.24.0 being published, and the publish was
gated on merging executor#30. Future progress docs will stay
one-to-one with code PRs.

## Next

Proceed to master-plan PR 11: populate
`backend/service/langgraph/default_manifest.py`'s
`build_default_manifest(...)` with `StageManifestEntry` lists for
`worker_adaptive` and `vtuber` that produce pipelines byte-identical
to today's `GenyPresets.*` output. Parity is asserted by a new
unit test that diffs stage chains from both construction paths.
