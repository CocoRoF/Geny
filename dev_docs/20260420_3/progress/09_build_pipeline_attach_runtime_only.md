# Progress 09 — `AgentSession._build_pipeline` → `attach_runtime` only

| Field | Value |
|-------|-------|
| Plan ref | `plan/02_default_env_per_role.md` → **PR 6 + Step 7** |
| Master ref | `plan/00_overview.md` → **Phase 2 / PR 17 (final)** |
| Geny PR | [#158](https://github.com/CocoRoF/Geny/pull/158) |
| Geny merge commit | `d651d44` on `main` |
| Status | **Merged** |

---

## Why this closes Phase 2

The master plan's Phase 2 exit criterion is a single build path for
every session:

> Any session type goes through the single
> `from_manifest_async → attach_runtime` path. `_build_pipeline`'s
> preset branches are gone.

Before this PR, `_build_pipeline` still held the dual-branch shape
from the 20260420_2 cycle:

1. **Manifest path** — when `prebuilt_pipeline` was supplied, adopt
   it and attach memory kwargs.
2. **Preset fallback** — when it wasn't, call `GenyPresets.vtuber(...)`
   / `GenyPresets.worker_adaptive(...)` in-process and register a
   duplicate `ToolRegistry` of `ReadTool`/`WriteTool`/`EditTool`/
   `BashTool`/`GlobTool`/`GrepTool`.

PR 15 made every caller go through the manifest path at the manager
layer (`resolve_env_id` is now unconditional). After that, the
preset fallback became unreachable. This PR deletes it, which in
turn allows the wider cleanup the master plan lined up behind
"single build path."

## What shipped

### `backend/service/langgraph/agent_session.py`

`_build_pipeline` is now ~100 lines shorter and has no branches on
`prebuilt_pipeline`:

```python
def _build_pipeline(self):
    if self._prebuilt_pipeline is None:
        raise RuntimeError(
            f"[{self._session_id}] prebuilt_pipeline is None. "
            f"Every AgentSession must now be constructed through "
            f"AgentSessionManager..."
        )
    # ... api_key resolution ...
    persona_text = (
        (self._system_prompt or _DEFAULT_VTUBER_PROMPT)
        if self._role == SessionRole.VTUBER
        else (self._system_prompt or _DEFAULT_WORKER_PROMPT)
              + "\n\n" + _ADAPTIVE_PROMPT
    )
    attach_kwargs = {
        "system_builder": ComposablePromptBuilder(blocks=[
            PersonaBlock(persona_text),
            DateTimeBlock(),
            MemoryContextBlock(),
        ]),
        "tool_context": ToolContext(
            session_id=self._session_id,
            working_dir=working_dir,
            storage_path=self.storage_path,
        ),
    }
    if self._memory_manager is not None:
        attach_kwargs["memory_retriever"]   = GenyMemoryRetriever(...)
        attach_kwargs["memory_strategy"]    = GenyMemoryStrategy(...)
        attach_kwargs["memory_persistence"] = GenyPersistence(...)

    self._pipeline = self._prebuilt_pipeline
    self._pipeline.attach_runtime(**attach_kwargs)
```

Decisions worth spelling out:

- **`_DEFAULT_WORKER_PROMPT` / `_DEFAULT_VTUBER_PROMPT` /
  `_ADAPTIVE_PROMPT`** are now module-level constants. Before, they
  lived inside `GenyPresets.worker_adaptive` /
  `GenyPresets.vtuber` in the executor. After deleting the preset
  imports, we needed somewhere to hold the string literals. They
  move to the Geny side because they encode Geny's product choices
  (worker emits `[TASK_COMPLETE]`/`[CONTINUE]`/`[BLOCKED]`, VTuber
  doesn't) — not executor-library defaults.
- **`_ADAPTIVE_PROMPT` is appended only for non-VTuber roles.** The
  tail teaches the LLM the
  `[TASK_COMPLETE]` / `[CONTINUE]` / `[BLOCKED]` vocabulary that
  Stage 12's `binary_classify` evaluator pattern-matches on. VTuber
  sessions use `signal_based` evaluation and a conversational
  persona, so appending the tail would confuse both the model and
  the evaluator.
- **Memory kwargs are conditional on `_memory_manager is not None`.**
  The real `SessionMemoryManager` always initializes before
  `_build_pipeline` in production flow, but tests can stub it to
  `None` and the executor's `attach_runtime` is designed to accept
  any subset of kwargs. Skipping the three memory entries when the
  manager isn't present is both correct (no null retriever) and
  cheaper than constructing throw-away objects.
- **`RuntimeError` replaces the `if prebuilt_pipeline is None`
  fallback.** Any caller that reaches the None branch now has a
  bug we want to see loudly — not silently route through a
  different code path.

### Deletions in `agent_session.py`

| Removed | Size | Why |
|---------|------|-----|
| `from geny_executor.memory import GenyPresets` | 1 line | Preset fallback gone |
| `from geny_executor.tools.builtins import ReadTool, WriteTool, EditTool, BashTool, GlobTool, GrepTool` | 1 line | `manifest.tools.built_in` declares these (PR 11) |
| `from geny_executor.tools.registry import ToolRegistry` | 1 line | Manifest owns tool registration |
| `is_vtuber` branching that built `GenyPresets.vtuber(...)` vs `GenyPresets.worker_adaptive(...)` | ~50 lines | Replaced by single `attach_runtime` call |
| Duplicate `tools.register(...)` loop for the 6 built-in tools | ~10 lines | Dual of `manifest.tools.built_in` — kept until PR 15, now dead |

### `backend/service/langgraph/agent_session_manager.py`

Progress doc 07 flagged this as deferred work: the
`allowed_builtin_tools` / `allowed_custom_tools` /
`allowed_tool_names` computation at lines 359-372 had become dead
code after PR 15 deleted `build_geny_tool_registry`, but the log
line `allowed_tools: N builtin + M custom` was still operationally
useful. PR 17 folds in the cleanup:

```python
# Before (16 lines, 3 local vars consumed by a deleted function)
allowed_builtin_tools = ...
allowed_custom_tools  = ...
allowed_tool_names    = allowed_builtin_tools + allowed_custom_tools
logger.info(f"  allowed_tools: {len(allowed_builtin_tools)} "
            f"builtin + {len(allowed_custom_tools)} custom")

# After (4 lines, log-only)
if self._tool_loader and preset:
    builtin, custom = self._tool_loader.get_allowed_tools_by_category(preset)
    logger.info(f"  allowed_tools: {len(builtin)} builtin + {len(custom)} custom")
elif self._tool_loader:
    total = (len(self._tool_loader.get_builtin_names())
             + len(self._tool_loader.get_custom_names()))
    logger.info(f"  allowed_tools: all ({total})")
```

The user-visible log contract is preserved. The three local
variables are gone because nothing downstream consumed them.

### Module docstring & class docstring

Both updated to describe the new single-path flow — for the next
reader who opens the file wondering "is this manifest-based or
preset-based?", the answer is one paragraph up top.

## Smoke test

Written as `/tmp/test_pr17_attach_runtime.py` (not checked in —
Geny has no committed test tree yet). 5 groups, all passing:

| Group | Checks |
|:-----:|:-------|
| A | `AgentSession(prebuilt_pipeline=None)._build_pipeline()` raises `RuntimeError` mentioning `prebuilt_pipeline` (regression guard for the fallback removal) |
| B | Worker pipeline: `attach_runtime` is called with all 5 kwargs — `memory_retriever`, `memory_strategy`, `memory_persistence`, `system_builder`, `tool_context`; `tool_context.working_dir` and `.session_id` propagate correctly; `system_builder._blocks == [persona, datetime, memory_context]`; persona text contains both the user prompt and `"Execution Strategy"` (adaptive tail appended) |
| C | VTuber pipeline: persona text contains the user prompt but **not** `"Execution Strategy"` (adaptive tail skipped for `SessionRole.VTUBER`) |
| D | When `_memory_manager is None`, `attach_runtime` receives only `{system_builder, tool_context}` — memory kwargs skipped conditionally |
| E | Source invariants: `GenyPresets` import removed, `GenyPresets.vtuber(` / `GenyPresets.worker_adaptive(` call sites removed, `self._pipeline.attach_runtime(` call site present, `allowed_tool_names` computation gone from the manager, `allowed_tools:` log line still present |

Groups B and C stub `agent._memory_manager = MagicMock()` because
the real `SessionMemoryManager` needs `numpy` for vector search
and numpy isn't installed in the executor's test venv. Group D
exists specifically to prove the `_memory_manager is None` branch —
a separate assertion from B/C that together they cover both sides
of the conditional.

## Manual verification

- [ ] App boot: a worker session without explicit `env_id` logs
      `preset=env:template-worker-env` and the `allowed_tools:`
      line still appears once.
- [ ] App boot: a VTuber session without explicit `env_id` logs
      `preset=env:template-vtuber-env` and the persona sent to
      Claude does **not** contain the `[TASK_COMPLETE]`
      vocabulary (check via the `/session/:id/prompt` admin
      endpoint or debug log).
- [ ] Round-trip: create a worker session, send one message, confirm
      the final response ends with `[TASK_COMPLETE]` /
      `[CONTINUE]` / `[BLOCKED]` as usual (Stage 12 pattern still
      fires).

These are boot-time observations, not automated — next dev-server
run should spot-check them and note the result here.

## Phase 2 final status

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
| 16c | Progress doc for 16a + 16b | #157 | Done |
| 17 | Geny: `AgentSession._build_pipeline` → `attach_runtime` only | #158 | **Done** |
| 17c | Progress doc for PR 17 | *this doc* | Done |

Phase 2 is closed. The dual preset / manifest paths are now one
path; every session reaches `Pipeline.attach_runtime` through the
same `resolve_env_id → instantiate_pipeline → adopt + attach`
flow.

## What Phase 3 inherits

Phase 3 renames the VTuber↔Worker binding terminology
(`cli_*` → `bound_worker_*`) and rewrites the delegation prompt.
Every one of those changes is textual — they touch request
schemas, docstrings, and prompt strings. They do **not** touch the
pipeline-build contract. That's the shape the master plan wanted:
with `_build_pipeline` stable, Phase 3 is pure cleanup against a
fixed foundation.

## Next

Master-plan PR 18 — rename `cli_session_id` / `cli_workflow_id`
to `bound_worker_session_id` / `bound_worker_workflow_id` in
`CreateSessionRequest` and the VTuber auto-pair block. Mechanical
rename guided by grep, no behavioral change; pure naming.
