# Analysis 01 — Missing stages 10/11/14 silently drop all tool execution

**Severity: CRITICAL.** Every session running on the default
environment manifests (the only envs Geny ships with after the
20260420_3 cutover) has **no Stage 10 (tool)**, **no Stage 11 (agent)**,
and **no Stage 14 (emit)**. The executor silently bypasses any stage
that is not present in the pipeline, so the LLM's tool calls are
parsed out of the response and then thrown away. This is why the
VTuber cannot delegate to its Sub-Worker via `geny_send_direct_message`,
why `Read` / `Write` / `Edit` / `Bash` / `Glob` / `Grep` do not work
from agents on default envs, and why `web_search` / `news_search` /
`web_fetch` in the VTuber env are no-ops.

---

## 1. Evidence — which stages exist and which don't

The executor defines 16 canonical stage orders.

**`geny-executor/src/geny_executor/core/artifact.py:47–64`** —
`STAGE_MODULES` registry:

```python
STAGE_MODULES: Dict[int, str] = {
    1: "s01_input",    2: "s02_context",  3: "s03_system",
    4: "s04_guard",    5: "s05_cache",    6: "s06_api",
    7: "s07_token",    8: "s08_think",    9: "s09_parse",
    10: "s10_tool",    11: "s11_agent",   12: "s12_evaluate",
    13: "s13_loop",    14: "s14_emit",    15: "s15_memory",
    16: "s16_yield",
}
```

All 16 stage implementations exist on disk. The issue is not that
the executor is missing code — it is that our **manifest factory
never asks for stages 10, 11, or 14**.

**`backend/service/langgraph/default_manifest.py:93–180`** —
`_worker_adaptive_stage_entries()` explicitly lists:

```
order=1   input
order=2   context
order=3   system
order=4   guard
order=5   cache
order=6   api
order=7   token
order=8   think
order=9   parse
order=12  evaluate   ← jumps from 9 to 12
order=13  loop
order=15  memory     ← jumps from 13 to 15
order=16  yield
```

Orders **10 (tool)**, **11 (agent)**, and **14 (emit)** are absent.
The VTuber preset at lines 183–265 is nearly identical and also
omits 10, 11, 14 (and additionally drops 8 think).

The gap is even self-documented. `default_manifest.py:77–80`:

> Stage 10 (`tool`) is left off the declarative stage list —
> presets register it conditionally on `tools` being passed, and
> the **session-level code decides that at pipeline-build time.**

**But there is no such session-level code in the manifest path.**
See §5 below.

---

## 2. Evidence — the executor silently bypasses missing stages

The manifest path materializes a pipeline by iterating the
manifest's stage entries and registering only the ones present:

**`geny-executor/src/geny_executor/core/pipeline.py:284–297`** —
`Pipeline.from_manifest`:

```python
entries = sorted(manifest.stage_entries(), key=lambda e: e.order)
...
for entry in entries:
    if not entry.active:
        continue
    kwargs = _stage_kwargs_for_entry(entry, api_key=effective_key)
    try:
        stage = create_stage(entry.name, entry.artifact, **kwargs)
    except Exception:
        if strict:
            raise
        continue
    pipeline.register_stage(stage)
```

There is no code path that fills in stages the manifest forgot.
If the manifest lists `[1…9, 12, 13, 15, 16]`, that is exactly
what the pipeline holds.

Then the runtime happily runs anyway. Phase B of the agent loop
walks every order from `LOOP_START` to `LOOP_END`, bypassing any
missing slot:

**`pipeline.py:728–743`** — `_run_phases` loop body:

```python
has_loop_stage = self.LOOP_END in self._stages
while True:
    for order in range(self.LOOP_START, self.LOOP_END + 1):
        current = await self._try_run_stage(order, current, state)
    ...
```

**`pipeline.py:784–795`** — `_try_run_stage` silent bypass:

```python
async def _try_run_stage(self, order, current, state):
    stage = self._stages.get(order)
    if stage is None:
        name = self._DEFAULT_STAGE_NAMES.get(order, f"stage_{order}")
        await self._emit("stage.bypass", stage=name, iteration=state.iteration)
        return current                          # ← pass-through, no error
    if stage.should_bypass(state):
        await self._emit("stage.bypass", stage=stage.name, iteration=state.iteration)
        return current
    return await self._run_stage(order, current, state)
```

A missing stage emits a `stage.bypass` event (so the UI *could*
surface it, if anything were looking), passes the stage input
through unchanged, and continues. **No error, no warning, no
raise.** The pipeline completes "successfully" with a response
that appears to contain tool calls but produced no tool effects.

---

## 3. Evidence — tool calls get parsed, then orphaned

Stage 9 (parse) populates `state.pending_tool_calls` with every
tool invocation it extracts from the LLM response:

**`geny-executor/src/geny_executor/stages/s09_parse/artifact/default/stage.py:106–117`**:

```python
state.pending_tool_calls = []
if parsed.has_tool_calls:
    state.pending_tool_calls = [
        {"tool_use_id": tc.tool_use_id,
         "tool_name": tc.tool_name,
         "tool_input": tc.tool_input}
        for tc in parsed.tool_calls
    ]
```

Stage 10 (tool) is where those calls get executed:

**`geny-executor/src/geny_executor/stages/s10_tool/artifact/default/stage.py:85–90`**:

```python
def should_bypass(self, state: PipelineState) -> bool:
    return not state.pending_tool_calls

async def execute(self, input, state):
    if not state.pending_tool_calls:
        return input
    # ← resolve each pending call through registry and run it
```

When Stage 10 is **not registered**, `state.pending_tool_calls`
stays populated, the bypass path at `pipeline.py:790` fires, and
no code ever drains the list. The VTuber's delegation call to
the Sub-Worker goes through the LLM → Parse → dropped on the floor.

---

## 4. Concrete failure trace — VTuber delegation

User asks VTuber to do a task requiring delegation:

1. `agent_executor.execute_command()` runs a turn.
2. Stage 1 (input) wraps the user message.
3. Stages 2–7 run (context, system, guard, cache, api, token).
4. Stage 8 (think) processes thinking blocks if present.
5. **Stage 9 (parse)** extracts the tool call the LLM produced:
   `{"tool_name": "geny_send_direct_message",
     "tool_input": {"target_session_id": "<sub_id>",
                    "content": "Please do X"}}`.
   This is placed into `state.pending_tool_calls`.
6. **Stage 10 (tool) is not in `pipeline._stages`.**
   `_try_run_stage(10, …)` logs `stage.bypass` and returns `current`
   unchanged. The tool call is never dispatched.
7. **Stage 11 (agent) is not registered.** No multi-agent routing
   occurs.
8. Stage 12 (evaluate) decides whether to continue the loop.
   Because `pending_tool_calls` was never consumed but Evaluate
   does not inspect it (Evaluate looks at `completion_signal` and
   loop budget), the evaluator sees a completed-looking turn.
9. Stage 13 (loop) runs the controller; loop may exit or continue.
10. **Stage 14 (emit) is missing.** Finalize-phase emissions are
    skipped.
11. Stage 15 (memory) appends the turn with the empty tool result.
12. Stage 16 (yield) formats the response.

The Sub-Worker **never receives** the DM. From the VTuber's
transcript it looks as if the call happened; from the Sub-Worker's
inbox there is nothing. The paired `[SUB_WORKER_RESULT]` reply
cycle never starts because there was no request.

**This is the user-visible failure.** Everything else works —
the LLM responds, the UI shows activity, logs show a turn
completing — but the work never ran.

The same bug cascades to every built-in tool (`Read`, `Write`,
`Edit`, `Bash`, `Glob`, `Grep`) and every external tool
(`web_search`, `news_search`, `web_fetch`, browser tools). Any
agent on `template-worker-env` or `template-vtuber-env` is a
**chat-only shell** that cannot take real actions.

---

## 5. Root cause — the manifest builder shipped without a tool-conditional

The 20260420_3 plan explicitly noted in `default_manifest.py:77–80`
that Stage 10 would be "registered conditionally at session build
time." The comment is accurate about intent, but the code never
landed.

**`default_manifest.py:341`** is the entire stage composition:

```python
entries = _build_stage_entries(effective)
```

It returns whatever `_worker_adaptive_stage_entries` or
`_vtuber_stage_entries` emits, unconditionally — no inspection of
`external_tool_names`, `tools.built_in`, or whether any
`GenyToolProvider` is attached. So the manifest that gets written
to disk as `template-worker-env.json` and `template-vtuber-env.json`
is structurally incomplete for any tool use.

**`backend/service/langgraph/agent_session.py:683–795`** confirms
the other end of the path doesn't compensate either. The session
calls `EnvironmentService.instantiate_pipeline` (which reads the
manifest and builds the pipeline) then `Pipeline.attach_runtime`.
Neither path appends a Stage 10 / 11 / 14 based on declared tools.

The comparison to the imperative builder path is stark:

**`geny-executor/src/geny_executor/core/builder.py:135–220`** —
`PipelineBuilder.build()` conditionally adds stages based on what
was configured:

```python
pipeline.register_stage(InputStage())
pipeline.register_stage(self._build_api_stage(config))
pipeline.register_stage(TokenStage())
pipeline.register_stage(ParseStage())
pipeline.register_stage(YieldStage())
if "context" in self._stage_configs:
    pipeline.register_stage(ContextStage(...))
...
if "agent" in self._stage_configs:
    pipeline.register_stage(AgentStage(...))
if "evaluate" in self._stage_configs:
    pipeline.register_stage(EvaluateStage(...))
...
if "emit" in self._stage_configs:
    pipeline.register_stage(EmitStage(...))
if "memory" in self._stage_configs:
    pipeline.register_stage(MemoryStage(...))
```

The builder path knows how to decide "do I need a tool stage?";
the manifest path has no equivalent.

Further — no `PipelineBuilder` call to `.with_tools()` exists in
the Geny backend either. The built-in 6-tool set that was the
justification for `_DEFAULT_BUILT_IN_TOOLS` (`default_manifest.py:30–37`)
has nowhere to plug in.

---

## 6. Why this wasn't caught earlier

1. **Manifests write successfully, pipelines build successfully,
   runs complete successfully.** Every integration boundary
   returns `OK`.
2. **`stage.bypass` events are emitted** but no test or assertion
   consumes them. The UI has no banner like "stage X is missing."
3. **LLMs confabulate completion.** When a tool is requested and
   the result never comes back, Claude often just narrates what
   would have happened ("I've sent the message to the Sub-Worker")
   which reads as success in the VTuber transcript.
4. **The previous cycle's smoke tests** (see
   `dev_docs/20260420_3/progress/09_build_pipeline_attach_runtime_only.md`)
   focused on "pipeline builds from manifest without error," not
   "tool calls actually execute."
5. **News-search regressions in 20260420_3** (Analysis/01 of that
   cycle) were diagnosed as *tool_bridge* bugs, which masked the
   deeper issue — the stage that the tool bridge feeds into
   (Stage 10) was not in the pipeline at all.

---

## 7. Fix direction (decide in plan, not here)

Three non-mutually-exclusive options. Analysis only — the plan
doc will pick.

### Option A — Add stages 10/11/14 to the default manifest always

Simple. Every manifest carries stages 10 (tool), 11 (agent), 14
(emit) with their default strategies. Stages 10/11/14 already
have `should_bypass(state)` logic that turns them into no-ops
when there's nothing to do (Stage 10 bypasses when
`pending_tool_calls` is empty; Stage 11 bypasses when no agent
handoff; Stage 14 bypasses when no emit target). So adding them
is safe even for sessions that happen not to use tools that run.

Pros: minimal code change. Matches operator expectation that the
seed envs "just work."
Cons: the stored manifest JSON gets three more entries. Users who
customize envs inherit them automatically.

### Option B — Conditional insertion at session build time

Implement the comment on `default_manifest.py:77–80`. Either
(a) extend `build_default_manifest` to append stages 10/11/14
whenever `external_tool_names` or `_DEFAULT_BUILT_IN_TOOLS` is
non-empty (which is always, in practice), or (b) have
`EnvironmentService.instantiate_pipeline` append them if
`manifest.tools.built_in` / `manifest.tools.external` is non-empty.

Pros: the manifest stays "declarative of intent"; the pipeline
gets "complete shape."
Cons: more code paths to keep in sync. The "what you see in the
env editor" vs "what actually runs" divergence returns.

### Option C — Hybrid

Manifest always lists 10/11/14 (Option A); `instantiate_pipeline`
validates the manifest against `manifest.tools` at build time and
raises if tools are declared but stage 10 is missing (catches
future-drift from manual edits).

---

## 8. Scope of the blast radius

Any session created via `EnvironmentService.instantiate_pipeline`
through the seed envs is affected. That is **all sessions** after
the 20260420_3 cutover. Specifically:

- VTuber sessions — no tool use at all, which breaks Sub-Worker
  delegation and web search.
- Sub-Worker (bound Worker) sessions — no Read/Write/Edit/Bash,
  so they cannot actually execute code tasks.
- Solo Worker / Developer / Researcher / Planner sessions — same
  as Sub-Worker, since they share `template-worker-env`.

The fix unblocks every agent role simultaneously.

---

## 9. Verification plan (for the fix PR)

Once the fix lands:

1. Unit test: build a pipeline from the default worker manifest
   and assert `pipeline._stages` contains orders `{1…16} \ {}` or
   at minimum includes 10, 11, 14.
2. Integration test: spin up a VTuber + Sub-Worker pair, send
   `geny_send_direct_message` from VTuber, assert the Sub-Worker's
   inbox receives the DM.
3. Integration test: run a solo Worker with `Read` on a fixture
   file, assert the tool call executes and result reaches the
   turn output.
4. Smoke: run one turn with an empty toolset, assert Stage 10
   bypass fires cleanly (should_bypass path) and no error.

---

## 10. Citations

| Claim | File:line |
|-------|-----------|
| Stage module registry | `geny-executor/src/geny_executor/core/artifact.py:47–64` |
| Worker manifest stage list | `backend/service/langgraph/default_manifest.py:93–180` |
| VTuber manifest stage list | `backend/service/langgraph/default_manifest.py:183–265` |
| Manifest builder never appends stage 10/11/14 | `backend/service/langgraph/default_manifest.py:341` |
| Executor registers only what the manifest lists | `geny-executor/src/geny_executor/core/pipeline.py:284–297` |
| Silent bypass for missing stage | `geny-executor/src/geny_executor/core/pipeline.py:784–795` |
| Phase B loop body | `geny-executor/src/geny_executor/core/pipeline.py:728–743` |
| Parse stage populates `pending_tool_calls` | `geny-executor/src/geny_executor/stages/s09_parse/artifact/default/stage.py:106–117` |
| Tool stage consumes `pending_tool_calls` | `geny-executor/src/geny_executor/stages/s10_tool/artifact/default/stage.py:85–90` |
| Builder conditionally adds stages | `geny-executor/src/geny_executor/core/builder.py:135–220` |
