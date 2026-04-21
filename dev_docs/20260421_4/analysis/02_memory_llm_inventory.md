# Analysis 02 — Memory-LLM call-site inventory

**Date.** 2026-04-21
**Scope.** Every place in the three-repo system (Geny, geny-executor,
geny-executor-web) where *secondary* LLM work — anything other than
the s06_api main call — is already happening, planned, or stubbed.
"Memory work" here includes reflection, history summarization,
retrieval gating, relevance scoring, tag extraction, and curated
knowledge transforms.

This is the factual base layer for the cycle. Analysis 03 picks
this up and argues for the state shape; each plan doc picks it up
to identify which site it is actually modifying.

## 0. Why this inventory exists

The cycle's thesis is: *the per-stage `model_override` interface
already exists inside `geny-executor`, but Geny's memory-related
LLM calls run through three unrelated code paths that don't
participate in the pipeline at all.* Before we propose a fix we
need to enumerate every such path so nothing gets forgotten,
every PR references its exact target, and nothing ships that
"fixes" one path while leaving a sibling quietly hardcoded.

## 1. Role taxonomy

Every memory-adjacent LLM call in the system today (or on the
drawing board) maps to exactly one of these roles:

| Role | What the model decides / produces | Cadence | Cost sensitivity |
|------|-----------------------------------|---------|------------------|
| **Reflection** | Extract reusable insights from an execution's input/output | Once per completed turn (terminal `loop_decision`) | Medium — runs every turn but bounded by `max_insights` |
| **Summarization** | Compress N old messages into a recap block | Only when context window pressure triggers s02 compaction | Low — rare, but every call touches thousands of tokens |
| **Gate** | Binary decision: does this query need memory retrieval at all? | Every retrieval pass (hot path) | **High** — runs every turn; must be cheap or it wastes its own budget |
| **Enrich / tag** | Suggest auto-tags and cross-links for a curated note | Batch curation, not in-flight | Low — offline |
| **Transform / curate** | Rewrite a note (summary / extract / restructure / merge) | Batch curation | Low — offline |

Frame it this way because the `model_override` interface is
uniform, but the *right* model for each role differs: reflection
and gating should run on Haiku-class models; transforms on large
bodies may need the main model; curation is already on Haiku via
a separate path.

## 2. Site-by-site inventory

Numbering follows the order they surface in the call graph of a
single session — start of retrieval (s02 context) → main call
(s06 api, out of scope) → memory writeback (s15). Batch-only
sites are last.

### Site 1 — Reflection callback (Geny host)

- **File.** `/home/geny-workspace/Geny/backend/service/langgraph/agent_session.py`
- **Definition.** L865–916 (`_make_llm_reflect_callback`).
- **Wiring.** L818 builds it during `_build_pipeline`; L846 hands
  it to `GenyMemoryStrategy(llm_reflect=...)`.
- **Client.** `anthropic.AsyncAnthropic(api_key=api_key)` instantiated
  fresh on every call (L902).
- **Model source.** Hardcoded string `"claude-haiku-4-5-20251001"`
  at L904. Ignores `APIConfig.memory_model`.
- **Accounting.** Invisible. No `PipelineEvent`, no token usage
  merged into `state.token_usage`, no log panel entry, no
  `session_logger` row.

**Diagnosis.** This is the single worst offender. A user who
switches `memory_model` in the UI observes no change in behavior,
because the only reflection path on the hot session flow doesn't
read the field. It also means every other memory-model
improvement (cost tracking, provider reuse, streaming) has to
start by detaching this callback. **Routed by PR-6**: Geny will
still build the callback for back-compat during a deprecation
window, but the default path switches to a native s15 reflective
strategy that reads `resolve_model_config(state)`.

### Site 2 — Memory-model factory (Geny config adapter)

- **File.** `/home/geny-workspace/Geny/backend/service/memory/reflect_utils.py`
- **Definition.** L15–41 (`get_memory_model`).
- **Wiring.** Called only from `service/memory/curation_scheduler.py`
  at L126 to hand a `ChatAnthropic` instance to `CurationEngine`.
- **Client.** `ChatAnthropic(model=..., api_key=...)` (LangChain).
- **Model source.** `APIConfig.memory_model` (correct). Returns
  `None` when key or model is missing — curation engine degrades
  gracefully.

**Diagnosis.** Only correct consumer of `APIConfig.memory_model`
on the Geny side. But it exists in a sidecar batch job, not in
the session flow, so the in-session reflection at Site 1 never
reuses it. **Not directly modified** by this cycle — the cycle
routes the session flow through the executor's new shared client,
and curation stays on its existing path. We note it here so
reviewers understand why Site 1 cannot just "be replaced with
`get_memory_model()`" (it would still bypass the pipeline).

### Site 3 — Config field `APIConfig.memory_model`

- **File.** `/home/geny-workspace/Geny/backend/service/config/sub_config/general/api_config.py`
- **Definition.** L36 (`memory_model = "claude-haiku-4-5-20251001"`);
  L45 env binding (`"MEMORY_MODEL"`); L154–161 UI metadata
  (SELECT with "Same as main model" option at the top).

**Diagnosis.** The knob exists and is exposed in the UI; what's
missing is the *routing* from this field to the actual LLM call
sites. PR-6 adds the missing glue: `APIConfig.memory_model →
ModelConfig → PipelineMutator.set_stage_model(2, …) /
set_stage_model(15, …)`.

### Site 4 — Reflection invocation (executor strategy)

- **File.** `/home/geny-workspace/geny-executor/src/geny_executor/memory/strategy.py`
- **Definition.** L162–240 (`GenyMemoryStrategy._reflect`); key
  invocation at L191 (`await self._llm_reflect(input_text[:2000],
  output_text[:3000])`).
- **Wiring.** Strategy stored in Stage 15's `strategy` slot;
  `_llm_reflect` is a constructor kwarg passed by Geny (Site 1)
  at `attach_runtime`/post-construction.
- **Fallback.** When `_llm_reflect is None`, writes
  `state.metadata["needs_reflection"] = True` and emits
  `memory.reflection_queued` — a signal to an external curator
  but not an in-pipeline action.

**Diagnosis.** The strategy is the correct place to *consume* a
resolved model, but it currently consumes only a pre-baked
callback. PR-5 adds a native LLM reflection path inside the
strategy that reads `stage.resolve_model_config(state)` and calls
`state.llm_client` when the callback is absent. Callback remains
as a one-cycle legacy branch so regressions can be A/B'd.

### Site 5 — LLM gate for retrieval (executor retriever)

- **File.** `/home/geny-workspace/geny-executor/src/geny_executor/memory/retriever.py`
- **Definition.** L47–103 (`GenyMemoryRetriever.retrieve`); gate
  invocation at L98 (`await self._llm_gate(search_query)`).
- **Wiring.** Constructor kwarg `llm_gate: Optional[Callable[[str],
  Awaitable[bool]]] = None`. Not passed from `agent_session.py`;
  always `None` in production. Presets in
  `memory/presets.py:111,174` accept it but host code doesn't
  populate it.

**Diagnosis.** Dead on arrival in the hot path. This cycle does
**not** enable it — gating is a legitimate follow-up but adds
policy complexity and a per-turn Haiku call that needs its own
justification. We note the site so future cycles have the
landing pad. Listed here so the PR-5/PR-6 scope does not
accidentally grow to cover it.

### Site 6 — Provider-layer reflection (executor stage 15)

- **File.** `/home/geny-workspace/geny-executor/src/geny_executor/stages/s15_memory/artifact/default/stage.py`
- **Definition.** L221–242 (`_drive_provider`).
- **Hook.** `MemoryHooks.should_reflect` default is
  `lambda s: False`; when a host does wire it, the stage calls
  `provider.reflect(ctx)` on terminal decisions.
- **Concrete providers today.** `FileMemoryProvider`,
  `SQLMemoryProvider`, `EphemeralMemoryProvider`, and
  `CompositeMemoryProvider` all return `()` — no LLM.

**Diagnosis.** This is the alternative reflection path Geny does
*not* use (Geny plugs in `GenyMemoryStrategy` via `attach_runtime`
and bypasses the provider protocol for reflection). The cycle
does not unify these two paths; PR-5 focuses on the
strategy-slot path that Geny actually runs. Noted as a follow-up:
if a future cycle introduces a pure-provider deployment (no
host-supplied strategy), it will need the same `resolve_model_config`
plumbing — the work will be straightforward because PR-3 puts
`state.llm_client` on the state, reachable from any stage.

### Site 7 — Summarization compactor stub (executor stage 2)

- **File.** `/home/geny-workspace/geny-executor/src/geny_executor/stages/s02_context/artifact/default/compactors.py`
- **Definition.** L28–66 (`SummaryCompactor`). Docstring reads:
  *"actual summarization would require an API call. This
  implementation provides the structural framework; integration
  with the API stage would be done at the pipeline level."*
- **Current behavior.** Replaces the dropped prefix with a
  hardcoded placeholder string:
  `"[Summary of {N} previous messages. Conversation history has
  been compacted to save context window.]"`.

**Diagnosis.** Real work deferred to this cycle. PR-5 replaces
the placeholder branch with an actual summarization call:
`resolve_model_config(state) → state.llm_client.create_message(...)`.
The static-placeholder branch is retained as the fallback when
no model override is configured (keeps the no-cost guarantee
documented in the risk table).

### Site 8 — Curation analysis (Geny batch job)

- **File.** `/home/geny-workspace/Geny/backend/service/memory/curation_engine.py`
- **Definition.** L429–473 (`_llm_analyze`).
- **Client.** `self._llm` — a `ChatAnthropic` from Site 2.
- **Trigger.** `curate_note()` at L324 when `method=="auto"`.

**Diagnosis.** Runs offline in `curation_scheduler`; does not
ride the pipeline. **Out of scope** for this cycle. Site 2 will
keep serving it. The cycle does not delete Site 2 because
unifying offline curation under the pipeline has its own
migration cost not worth bundling here.

### Site 9 — Curation content transform (Geny batch job)

- **File.** `/home/geny-workspace/Geny/backend/service/memory/curation_engine.py`
- **Definition.** L517–524 (`_transform`).
- **Wiring.** Same `ChatAnthropic` via Site 2. Five strategies:
  `direct` (no LLM), `summary`, `extract`, `restructure`, `merge`.

**Diagnosis.** Offline, out of scope. Noted only so a future
"unify all memory LLM calls" cycle has the list.

### Site 10 — Curation enrichment (Geny batch job)

- **File.** `/home/geny-workspace/Geny/backend/service/memory/curation_engine.py`
- **Definition.** L559–596 (`_enrich`).
- **Wiring.** Same `ChatAnthropic`. Emits JSON with `auto_tags`,
  `suggested_links`, `importance_assessment`.

**Diagnosis.** Offline, out of scope.

### Site 11 — `MemoryHooks` policy

- **File.** `/home/geny-workspace/geny-executor/src/geny_executor/memory/provider.py`
- **Definition.** L758–765.
- **Current defaults.** `should_record_execution=lambda s: bool(s.final_text)`,
  `should_reflect=lambda s: False`, `should_auto_promote=lambda i:
  i.should_auto_promote()`.

**Diagnosis.** Policy-only — hooks do not invoke LLMs themselves;
they gate whether the provider path (Site 6) or the strategy path
(Site 4) runs. **Unchanged by this cycle.** Listed so the hook
name `should_reflect` isn't confused with a new LLM call site.

### Site 13 — s06_api vendor providers (executor)

- **Files.** `src/geny_executor/stages/s06_api/artifact/{default,openai,google}/providers.py`.
- **Role.** Not a *memory* call site, but listed here because
  this cycle unifies it with the memory paths. `AnthropicProvider`
  / `OpenAIProvider` / `GoogleProvider` are the one path that
  already speaks `APIRequest`/`APIResponse` today; PR-3 hoists
  that shape into `geny_executor/llm_client/` as the canonical
  `BaseClient` contract, and PR-4 deletes these three files by
  making `APIStage` call `state.llm_client` directly.

**Diagnosis.** Migration-only. The behavior stays byte-identical
(parity tests in PR-4 assert this); what changes is the *shape*
memory stages see when they reach for an LLM — the same shape
s06_api already uses.

### Site 12 — `RetrievalQuery.use_llm_gate` flag

- **File.** `/home/geny-workspace/geny-executor/src/geny_executor/memory/provider.py`
- **Definition.** L428–445 — field `use_llm_gate: bool = False`
  on `RetrievalQuery`.
- **Consumers.** None. Grep confirms no code reads this flag.

**Diagnosis.** Dead flag, reserved for a future gate
implementation. Same fate as Site 5: noted, not touched.

## 3. Aggregate view

| # | Role | Lives in | Hot-path? | Reads `memory_model`? | Counts tokens? | Planned fate |
|---|------|----------|-----------|----------------------|----------------|--------------|
| 1 | Reflection | Geny host | Yes | **No** (hardcoded Haiku) | No | Deprecated by PR-6 (kept as fallback one cycle) |
| 2 | Model factory | Geny util | No | Yes | No | Unchanged; curation retains its path |
| 3 | Config field | Geny config | N/A | — | — | Becomes *the* routing input in PR-6 |
| 4 | Reflection invoker | Executor strategy | Yes | Via callback (→ Site 1) | No | PR-5 adds native path via `llm_client` + `resolve_model_config` |
| 5 | LLM gate | Executor retriever | Yes (if enabled) | No (never called) | N/A | Follow-up cycle |
| 6 | Provider reflect | Executor s15 | Yes (if `should_reflect`) | No (no-op today) | N/A | Follow-up cycle |
| 7 | Summary compactor | Executor s02 | Yes (on compaction) | No (stub) | No | PR-5 turns into real call |
| 8 | Curation analyze | Geny batch | No | Via Site 2 | No | Unchanged |
| 9 | Curation transform | Geny batch | No | Via Site 2 | No | Unchanged |
| 10 | Curation enrich | Geny batch | No | Via Site 2 | No | Unchanged |
| 11 | Hooks policy | Executor provider | N/A | — | — | Unchanged |
| 12 | Query-gate flag | Executor provider | N/A | — | — | Unchanged |
| 13 | s06 vendor providers | Executor artifact | Yes (main call) | N/A | Yes (today) | PR-3 extracts shape; PR-4 deletes artifacts, routes through `state.llm_client` |

## 4. Systemic problems

Four patterns fall out of the table and together motivate the
PR plan:

1. **Fragmented model sources.** Three independent paths decide
   which model runs: hardcoded (Site 1), `APIConfig.memory_model`
   via `get_memory_model` (Sites 2, 8–10), and "nothing"
   (Sites 4, 7 — they have no model at all). Flipping a UI knob
   only affects the middle column. Fix: one routing input
   (`APIConfig.memory_model`) driving every hot-path site via a
   single interface (`PipelineMutator.set_stage_model`).

2. **Fragmented clients.** Site 1 uses raw
   `anthropic.AsyncAnthropic`; Sites 2, 8–10 use LangChain's
   `ChatAnthropic`; Site 13 (s06_api) uses the executor's
   `AnthropicProvider` (+ `OpenAIProvider`, `GoogleProvider`).
   Three in-session wrappers, three retry policies, three
   token-counting conventions. Fix: PR-3 adds
   `geny_executor/llm_client/` as the canonical `BaseClient`
   contract; PR-4 migrates s06_api onto it (deleting Site 13's
   artifacts); PR-5 routes Sites 4 and 7 through
   `state.llm_client`; PR-6 retires Site 1 in Geny. Sites 2 and
   8–10 stay on ChatAnthropic (offline batch, different lifecycle).

3. **Invisible accounting.** Every hot-path secondary call
   today is invisible to `state.token_usage`,
   `state.total_cost_usd`, the event stream, and the log panel.
   Users complain that "memory is slow" but can't see why. Fix:
   PR-3's `BaseClient.create_message` takes a `purpose: str`
   argument (e.g. `"s15.reflect"`, `"s02.compact"`) so a future
   cycle can aggregate them into a secondary-cost accumulator.
   *This cycle does not implement the accumulator* — the risk
   line (double-charging in index.md) is mitigated by gating
   every new call on "a model override was explicitly set," not
   by accounting.

4. **Stubs that advertise completion.** Both Site 7 and Site 6
   name themselves "SummaryCompactor" and `provider.reflect()`
   as if they summarize and reflect — but neither does. A new
   contributor reading the code reasonably assumes the feature
   exists. Fix: PR-5 gives Site 7 real behavior; Site 6 gets a
   docstring note that Geny's deployment uses the
   strategy-slot path, not the provider path, and the
   provider-path implementation is a follow-up.

## 5. What "correctly wired" looks like (per hot-path site)

The six PRs collectively move Sites 4 and 7 to this shape:

```
# Inside a stage's execute()
override = self.resolve_model_config(state)   # PR-2
if override is None:
    return                                    # no override → no new call (risk 1 mitigated)

client = state.llm_client                     # PR-3
response = await client.create_message(
    model_config=override,
    messages=[...],
    system=...,
    purpose="s15.reflect",                    # for future cost routing
)
```

Site 1 becomes a thin legacy fallback:

```
# In Geny's _build_pipeline (PR-6)
cfg = ModelConfig(model=api_config.memory_model or api_config.anthropic_model)
mutator.set_stage_model(2, cfg)     # s02 summarization
mutator.set_stage_model(15, cfg)    # s15 reflection
client_cls = ClientRegistry.get(api_config.provider)   # anthropic | openai | google | vllm
pipeline.attach_runtime(..., llm_client=client_cls(api_key=api_key))
# llm_reflect callback: constructed only if APIConfig.use_legacy_reflect,
# otherwise None → executor runs its own reflect via state.llm_client
```

The shape is small because the work is almost entirely on the
interface side — the new LLM calls themselves are short
Anthropic API invocations.

## 6. Sites NOT touched by this cycle (explicit)

- Site 2 and Sites 8–10 — curation batch path keeps its own
  `ChatAnthropic`. Unifying it under the pipeline adds lifecycle
  complexity (the curator runs on a schedule, not in a session)
  and has no routing problem (it already reads
  `APIConfig.memory_model`).
- Site 5 and Site 12 — LLM-gated retrieval. Real value but
  unrelated per-turn policy work that would grow the cycle.
- Site 6 — `provider.reflect()` LLM-backed implementation.
  Follow-up cycle can add an `LLMReflectionProvider` alongside
  the current `FileMemoryProvider`. PR-3's
  `state.llm_client` already makes this reachable, so no further
  core work is needed when that cycle starts.
- Site 11 — `MemoryHooks` policy. Unchanged; hooks are plain
  callables, not LLM wrappers.

## 7. Acceptance checklist for this cycle's work

A reader verifying the cycle after PR-6 lands should be able to
answer yes to all of:

- [ ] Flipping `APIConfig.memory_model` in the UI changes which
      model the reflection call uses, visible in executor events.
- [ ] Removing the `llm_reflect` parameter from
      `_build_pipeline` still produces reflection output (the
      executor's native path kicks in).
- [ ] Running a session with an override on s02 and watching
      `stage.enter(context) → events` shows a new
      `memory.compaction.summarized` event with a model name.
- [ ] Running without any override produces **zero** new
      memory LLM calls — the no-override branch is still the
      pre-cycle behavior, so no one gets double-billed silently.
- [ ] `PipelineState.shared` and `Stage.local_state` (PR-1) are
      used by at least the summarizer (to stash partial recaps
      across iterations) — confirming the state interfaces are
      used in anger, not just shipped as empty hooks.
