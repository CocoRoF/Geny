# Progress/01 — `default_manifest.py`: include stages 10 / 11 / 14

**PR.** `fix/manifest-tool-stages` (Phase 1 · PR #1 of 9)
**Plan.** `plan/01_tool_execution_fix.md` §PR #1
**Date.** 2026-04-20

---

## What changed

`backend/service/langgraph/default_manifest.py`:

- `_worker_adaptive_stage_entries` — inserted three
  `StageManifestEntry` rows between existing entries: order 10
  (`tool`), order 11 (`agent`), order 14 (`emit`).
- `_vtuber_stage_entries` — same three rows inserted at the same
  slots.
- Docstring block (previously lines 77–80) rewritten. The stale
  claim *"Stage 10 (`tool`) is left off the declarative stage
  list — presets register it conditionally"* is replaced with an
  accurate description: all three stages are declared
  unconditionally and rely on each stage's `should_bypass` for
  the no-work path.

The three new entries reflect the executor's default
constructors verbatim:

```python
StageManifestEntry(
    order=10,
    name="tool",
    strategies={"executor": "sequential", "router": "registry"},
),
StageManifestEntry(
    order=11,
    name="agent",
    strategies={"orchestrator": "single_agent"},
    config={"max_delegations": 4},
),
StageManifestEntry(
    order=14,
    name="emit",
    strategies={},
    chain_order={"emitters": []},
),
```

Rationale for each:

- **Stage 10 (tool).** `executor="sequential"` and
  `router="registry"` match the default slots on `ToolStage`
  (`geny-executor/.../s10_tool/artifact/default/stage.py:37–55`).
  `should_bypass` returns `True` when `state.pending_tool_calls`
  is empty, so turns that do not request tools incur no cost.
- **Stage 11 (agent).** `orchestrator="single_agent"` — the
  no-op orchestrator. Multi-agent delegation in Geny happens via
  the `geny_send_direct_message` tool call in Stage 10, not via
  Stage 11's orchestrator, so the default is correct.
  `max_delegations=4` matches the default in the stage schema.
- **Stage 14 (emit).** Empty emitters chain. `EmitStage`'s
  `should_bypass` returns `True` on an empty chain, making the
  stage inert today. Declaring it keeps the slot live for future
  TTS / callback emitters without another migration.

## Why

Sessions built from an `EnvironmentManifest` that does not list
a stage silently skip it — `Pipeline._try_run_stage` emits
`stage.bypass` and returns the input unchanged
(`geny-executor/.../core/pipeline.py:784–795`). Omitting stages
10/11/14 was therefore not "disabled conditionally"; it was
"disabled permanently with no way to re-enable short of editing
the manifest builder."

Consequence: `geny_send_direct_message` and every other tool
call emitted by the LLM landed in `state.pending_tool_calls`,
Stage 10 never ran, and the VTuber's delegation requests went
nowhere. This PR is the root cause fix for that bug.

## Verification

1. `python3 -m py_compile backend/service/langgraph/default_manifest.py` — OK.
2. Import-only smoke (bypassing the package `__init__` which
   pulls in pydantic):

   ```
   worker_adaptive: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
   vtuber:         [1, 2, 3, 4, 5, 6, 7,    9, 10, 11, 12, 13, 14, 15, 16]
   worker_easy:    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
   ```

   VTuber correctly omits stage 8 (`think`) per preset; worker
   variants keep it. Orders 10/11/14 present everywhere.
3. `Pipeline.from_manifest(...)` materialization smoke:

   ```
   worker_adaptive pipeline stages: [1..16]
   vtuber pipeline stages:          [1..16 minus 8]
   worker_easy pipeline stages:     [1..16]
   ```

   All three new stages register into `pipeline._stages` as
   expected.

Formal test file is deferred — the backend has no test harness
in this workspace. The smoke script above is the durable
verification; PR #3 (integration delegation round-trip) is the
end-to-end proof that the stages actually execute tool calls.

## Out of scope

- Migrating on-disk seed envs (PR #2).
- End-to-end tool-call smoke (PR #3).
- Extending the preset set or changing slot strategies.

## Rollback

Revert `default_manifest.py` to drop the three entries. The
manifest format is backward-compatible (missing stages bypass
silently) so revert does not corrupt existing envs — it simply
restores the tool-execution gap.
