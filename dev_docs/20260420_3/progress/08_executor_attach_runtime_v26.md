# Progress 08 — Executor v0.26.0 `attach_runtime` expansion + Geny pin

| Field | Value |
|-------|-------|
| Plan ref | `plan/02_default_env_per_role.md` → **Prereq (unscheduled)** for PR 17 |
| Master ref | `plan/00_overview.md` → **Phase 2 / between PRs 15 and 17** |
| Executor PR | [CocoRoF/geny-executor#32](https://github.com/CocoRoF/geny-executor/pull/32) |
| Executor release | [v0.26.0](https://github.com/CocoRoF/geny-executor/releases/tag/v0.26.0) |
| Geny PR | [#156](https://github.com/CocoRoF/Geny/pull/156) |
| Geny merge commit | `c08fd12` on `main` |
| Status | **Both merged** |

---

## Why this PR exists (and was not in the plan)

Master-plan PR 17 collapses `AgentSession._build_pipeline` to a
single `Pipeline.attach_runtime(...)` call after
`from_manifest_async`. Progress doc 05 already flagged that the
manifest path restores Stage 3 with a default empty
`ComposablePromptBuilder()` and that *"a later PR will expand
`attach_runtime` with a `system_builder=` kwarg."* When I sat down
to execute PR 17 against executor v0.25.0, two gaps blocked a clean
implementation:

1. **`ComposablePromptBuilder` cannot live in a manifest.** Geny
   wires `PersonaBlock(prompt) + DateTimeBlock() + MemoryContextBlock()`
   per session. A manifest's `system.prompt` is a single string —
   block composition is runtime behavior. v0.24.0's `attach_runtime`
   had no slot for the builder.
2. **`ToolContext(working_dir=…, storage_path=…)` cannot live in
   a manifest.** Stage 10's `execute` builds per-call
   `ToolContext` using `self._context.working_dir /
   .storage_path`. Those paths live under the session's scratch
   directory, allocated at session-creation time. v0.24.0's
   `attach_runtime` had no hook for the tool stage's context.

Reaching into `SystemStage._slots["builder"].strategy =` and
`ToolStage._context =` from Geny would have re-created the exact
pattern v0.24.0's `attach_runtime` was introduced to *eliminate* —
hosts mutating stage internals after construction. The right move
was one more additive executor release before PR 17 lands.

This is the same scope-drift shape as PR 10a (unscheduled
`binary_classify` registration in v0.25.0, discovered while
populating `build_default_manifest.stages`): a prereq surfaced
inside the Phase 2 cutover, not during planning. The plan anticipated
the `system_builder` part; the `tool_context` part is new scope
the plan did not foresee.

## What shipped — executor v0.26.0

Additive expansion of the existing helper:

```python
def attach_runtime(
    self,
    *,
    memory_retriever:   MemoryRetriever         | None = None,   # 0.24.0
    memory_strategy:    MemoryUpdateStrategy    | None = None,   # 0.24.0
    memory_persistence: ConversationPersistence | None = None,   # 0.24.0
    system_builder:     PromptBuilder           | None = None,   # 0.26.0
    tool_context:       ToolContext             | None = None,   # 0.26.0
) -> None: ...
```

| Kwarg | Target | Slot / attr |
|---|---|---|
| `memory_retriever` | Stage 2 (Context) | `retriever` slot |
| `memory_strategy` | Stage 15 (Memory) | `strategy` slot |
| `memory_persistence` | Stage 15 (Memory) | `persistence` slot |
| `system_builder` | Stage 3 (System) | `builder` slot |
| `tool_context` | Stage 10 (Tool) | `_context` attribute |

Implementation details:

- `system_builder` reuses the existing
  `_set_stage_slot_strategy("system", "builder", …)` helper —
  Stage 3's `builder` is already a pluggable slot.
- `tool_context` gets a new narrow helper
  `_set_tool_stage_context(…)` because `ToolContext` is a data
  carrier, not a pluggable strategy slot. Stage 10's `_context`
  is a plain instance attribute. The helper keeps the "all
  runtime injections live in one place" contract.
- Post-run guard covers both new kwargs — attaching after
  `_has_started` flips still raises `RuntimeError`.
- Missing target stage is a silent no-op for both new kwargs —
  a pipeline without a Tool stage simply has nowhere to attach
  a `ToolContext`.
- `session_id` inside `ToolContext` is still overwritten from
  the pipeline's per-run state inside Stage 10's `execute`. The
  attached context carries *host-level* fields that persist
  across runs.

### Executor tests

`tests/unit/test_pipeline_attach_runtime.py` — **6 new tests** (14
total, all passing):

| # | Assertion |
|---|-----------|
| 9 | `system_builder` replaces Stage 3 `builder` slot identity |
| 10 | `tool_context` overwrites Stage 10 `_context` with path/metadata preserved |
| 11 | `system_builder` silently skipped when no SystemStage present |
| 12 | `tool_context` silently skipped when no ToolStage present |
| 13 | Five-kwarg call wires all target stages in one shot |
| 14 | Post-run guard raises `RuntimeError` for both new kwargs |

Full suite: **1035 passed, 18 skipped.** Ruff + format clean.

## What shipped — Geny pin

Two one-line changes on top of 07's state:

- `backend/pyproject.toml`: `geny-executor>=0.25.0,<0.26.0` →
  `>=0.26.0,<0.27.0`
- `backend/requirements.txt`: same

**No consumer code changes** in PR #156. The Geny side still
follows the v0.25.0 API — this PR is a pure pin bump so that PR 17
can call the new kwargs as soon as it lands. Isolating the pin from
the refactor keeps either revertible on its own.

## Scope the plan still owes

Master-plan PR 17 is now unblocked. It can:

- Build a `ComposablePromptBuilder([PersonaBlock(role_prompt),
  DateTimeBlock(), MemoryContextBlock()])` and pass it as
  `attach_runtime(system_builder=...)` — replacing the default
  empty composable builder that `from_manifest_async` restores.
- Build a session-scoped
  `ToolContext(working_dir=session_workdir,
  storage_path=session_storage)` and pass it as
  `attach_runtime(tool_context=...)` — replacing the default
  empty `ToolContext()` that `ToolStage` constructs.
- Delete the `GenyPresets.vtuber` / `worker_adaptive` fallback
  branches, the dead `allowed_tool_names` /
  `allowed_builtin_tools` / `allowed_custom_tools` computation in
  `agent_session_manager.py`, and the duplicate
  `ToolRegistry + built_in tools` registration inside
  `_build_pipeline`.

## Phase 2 status

| # | Title | PR | Status |
|---|-------|----|--------|
| 7 | Executor: `Pipeline.attach_runtime` (v0.24.0) | executor#30 | Done |
| 8 | Progress doc for PR 7 | #149 (bundled) | Done |
| 9 | Geny: pin bump to 0.24.0 | #148 | Done |
| 10 | Progress doc for PR 9 | #149 (bundled) | Done |
| 10a | Executor: register `binary_classify` (v0.25.0) | executor#31 | Done |
| 11 | Geny: populate `build_default_manifest.stages` + pin 0.25.0 | #150 | Done |
| 12 | Progress doc for PR 11 | #151 | Done |
| 13 | Geny: seed `install_environment_templates` + `ROLE_DEFAULT_ENV_ID` | #152 | Done |
| 14 | Progress doc for PR 13 | #153 | Done |
| 15 | Geny: `AgentSessionManager` always resolves `env_id` | #154 | Done |
| 16 | Progress doc for PR 15 | #155 | Done |
| 16a | Executor: `attach_runtime(system_builder, tool_context)` (v0.26.0) | executor#32 | Done |
| 16b | Geny: pin bump to 0.26.0 | #156 | Done |
| 16c | Progress doc for 16a + 16b | *this doc* | Done |
| 17 | Geny: `AgentSession._build_pipeline` → `attach_runtime` only | — | **Next** |

PRs 16a / 16b / 16c follow the same naming convention as 10a —
unscheduled work the plan didn't foresee but that a downstream PR
depends on. Bundling 16a + 16b into a single progress doc matches
04's precedent (executor release and pin bump are inseparable —
pinning 0.26.0 has no value without 0.26.0 being published).

## Next

Master-plan PR 17 — the last PR of Phase 2. Collapse
`AgentSession._build_pipeline` to a single `attach_runtime` call:

- Build `GenyMemoryRetriever` / `GenyMemoryStrategy` /
  `GenyPersistence` from `self._memory_manager` + curated_km +
  `llm_reflect` callback.
- Build `ComposablePromptBuilder` from the role-resolved system
  prompt + `DateTimeBlock` + `MemoryContextBlock`.
- Build `ToolContext` from the session's working_dir +
  storage_path.
- Call `self._prebuilt_pipeline.attach_runtime(
  memory_retriever=..., memory_strategy=..., memory_persistence=...,
  system_builder=..., tool_context=...)`.
- Delete: the `GenyPresets.*` imports and fallback branch, the
  `is_vtuber` logic, the dead `allowed_tool_names` /
  `allowed_builtin_tools` / `allowed_custom_tools` computation in
  `agent_session_manager.py`, and the duplicate
  `ToolRegistry + built_in tools` registration inside
  `_build_pipeline` (since `manifest.tools.built_in` now covers
  it declaratively).

Exit criterion for Phase 2 (from master plan): any session type
goes through the single `from_manifest_async → attach_runtime`
path. `_build_pipeline`'s preset branches are gone. After that,
Phase 3 (VTuber↔Worker binding rename + prompt updates) is pure
cleanup against a stable pipeline-build contract.
