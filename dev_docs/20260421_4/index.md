# Cycle 20260421_4 — Stage state interface + unified LLM client + per-stage model routing

**Date.** 2026-04-21
**Scope.** geny-executor core + Geny backend. No frontend work in this
cycle.
**Trigger.** Three intertwined asks from the user, treated as one cycle
because the interfaces touch:

1. **Per-stage model routing.** The per-stage `model_override`
   interface already exists inside `geny-executor`, but nothing outside
   `s06_api` uses it. The user wants memory-side LLM work (context
   summarization, reflection, tag extraction) to run on a cheap model
   while the main reasoning stage (s06_api) keeps the expensive one.
2. **First-class `shared` and per-stage state.** The user wants a
   global state dict every stage can read/write during a run, plus an
   ergonomic per-stage scratchpad so stages can keep their own
   bookkeeping without colliding.
3. **Unified LLM client package.** Not every stage uses a model, but
   the ones that do should all go through one interface. Today three
   parallel paths exist: s06_api's `APIProvider` artifact system,
   Geny's raw `anthropic.AsyncAnthropic` client for reflection, and
   LangChain's `ChatAnthropic` in curation. The user wants a dedicated
   `geny_executor/llm_client/` package with a common `BaseClient`
   abstract and concrete adapters for Anthropic / OpenAI / Google /
   vLLM. After that lands, s06_api's artifact-based provider mechanism
   is **removed** — the API stage picks a client by provider name
   (from config) and the unified package is the only way LLMs are
   called.

## Bug / regression summary

The root cause behind all three asks: **interfaces exist but nothing
calls them, or they are duplicated across repos in incompatible
shapes.**

1. **`Stage.model_override` is live wiring with one customer.**
   `src/geny_executor/core/stage.py:279–320` defines both the
   property and the `resolve_model(state)` helper. `s06_api` is the
   only stage that reads `self.model_override` (and even it bypasses
   `resolve_model` — it reads each field off the override directly in
   `_build_request`). Every other stage that could plausibly call an
   LLM (s02 summarizer, s15 reflective) is either a stub or defers
   its LLM work to a callback injected from outside the pipeline.

2. **Three LLM-client shapes, zero uniformity.**
   - `AnthropicProvider` /  `OpenAIProvider` / `GoogleProvider` live
     under `src/geny_executor/stages/s06_api/artifact/{default,openai,google}/providers.py`
     as an `APIProvider` strategy — tightly scoped to s06_api.
   - `anthropic.AsyncAnthropic` is instantiated directly in
     `backend/service/langgraph/agent_session.py:902`.
   - `langchain_anthropic.ChatAnthropic` is instantiated in
     `backend/service/memory/reflect_utils.py:33`.
   A stage that wants to call an LLM has no single, uniform surface
   to reach for.

3. **Geny bypasses the pipeline for memory LLM calls.**
   `backend/service/langgraph/agent_session.py:865–916`
   (`_make_llm_reflect_callback`) constructs a raw `AsyncAnthropic`
   with a hard-coded `claude-haiku-4-5-20251001` and hands it to
   `GenyMemoryStrategy(llm_reflect=...)`. The executor never sees
   this call. Meanwhile `APIConfig.memory_model` already exists but
   flows through a third path (`ChatAnthropic` in curation) and
   never reaches the session flow.

4. **`PipelineState` has no separation between pipeline-owned
   fields, per-stage scratchpads, and free-form shared data.**
   Stages that want to stash working state reuse `state.metadata`,
   which is a single untyped dict. There is no guard against two
   stages clobbering each other, no conventional "global context"
   slot, and no ergonomic way to carry state across iterations
   without reinventing the pattern at every call site.

5. **s02_context SummaryCompactor is a stub.**
   `src/geny_executor/stages/s02_context/artifact/default/compactors.py`
   (the `SummaryCompactor` docstring) explicitly says "actual
   summarization would require an API call. This implementation
   provides the structural framework; integration with the API
   stage would be done at the pipeline level." Six months later,
   integration has not happened — because there is no shared LLM
   client a non-api stage can reach.

## Scope

**In.**
- `PipelineState.shared: Dict[str, Any]` — new global-state dict,
  separate from `metadata`. Pipeline-lifetime, cleared per run.
- `Stage.local_state(state) -> Dict[str, Any]` — convention helper
  returning `state.metadata.setdefault(self.name, {})`. Ergonomic
  per-stage scratchpad without new core fields.
- `Stage.resolve_model_config(state) -> ModelConfig` — upgrade the
  existing `resolve_model` to return the full `ModelConfig` bundle
  (model + sampling + thinking settings) instead of just the model
  string. Keep the old helper as a shim for back-compat.
- **`geny_executor/llm_client/` — new top-level package**
  - `BaseClient` abstract class + `ClientCapabilities` (feature
    flags like `supports_thinking`, `supports_tools`,
    `supports_streaming`).
  - Concrete clients: `AnthropicClient`, `OpenAIClient`,
    `GoogleClient`, `VLLMClient`. Each inherits from `BaseClient`
    and speaks the same method surface. vLLM ships as an
    OpenAI-compatible adapter (OpenAI-style REST surface with a
    configurable `base_url`). Each non-Anthropic client is a thin
    rewrite of the existing provider translators in
    `s06_api/_translate.py` + `s06_api/artifact/<vendor>/providers.py`.
  - `ClientRegistry` — provider-name → client-class lookup with
    optional-dependency handling (same pattern `APIProvider` has
    today, centralized).
  - `state.llm_client: Optional[BaseClient]` — the one handle any
    stage reaches for when it needs an LLM. Optional because not
    every stage uses a model (injection is there for extensibility,
    not as a requirement).
- **s06_api migration onto the unified client.** The per-vendor
  artifact subdirectories (`s06_api/artifact/default/providers.py`,
  `.../openai/providers.py`, `.../google/providers.py`) collapse
  into the new package; s06_api becomes a thin stage that selects
  a client by provider name from config and calls
  `state.llm_client.create_message(...)`. The `APIProvider`
  strategy slot is replaced by a single `provider: str = "anthropic"`
  config field.
- Memory stages take `model_override`:
  - `s02_context` SummaryCompactor replaces its stub with a real
    summarizer that reads `stage.resolve_model_config(state)` and
    calls `state.llm_client`.
  - `s15_memory` Reflective strategy acquires a native LLM
    reflection path; `llm_reflect` callback from Geny becomes
    optional and is no longer the only path.
- Geny migration — retire `_make_llm_reflect_callback` as the
  default; instead build `ModelConfig(memory_model, ...)` from
  `APIConfig`, set it on `s02_context` and `s15_memory` via
  `PipelineMutator.set_stage_model(order, model)`, and construct
  the shared client via `ClientRegistry.get(api_config.provider)`.

**Out.**
- Frontend work. The log panel already renders stage rows (cycle
  20260421_3) — extra metadata surfaces naturally, but we will not
  design new UI in this cycle.
- **Non-Anthropic parity with Anthropic's extended-thinking feature.**
  The `BaseClient` interface exposes `supports_thinking` capability
  and a thinking-config passthrough; clients that don't support it
  (OpenAI, vLLM in most configurations) return a capability flag
  `False` and silently drop the setting. Getting reasoning-model
  parity across vendors is its own cycle.
- Per-stage **API key** overrides. Same api_key for all stages —
  only the model (+ sampling + thinking) varies. (Different clients
  still read their own env var for the key, but per-stage key
  switching is not supported.)
- Token/cost accounting of secondary-model calls in
  `state.token_usage`. Out of scope; the secondary calls will be
  tagged with a `purpose` string so a future cycle can route them
  to a second accumulator.
- Geny-side curation path (`reflect_utils.py` + `curation_engine.py`)
  — keeps using `ChatAnthropic` on its own schedule. Unifying
  offline batch LLM work under the pipeline is its own cycle.

## PR plan (6 PRs)

| PR | Branch | Scope |
|---|---|---|
| PR-1 | `feat/pipeline-state-shared-and-local` | geny-executor: `PipelineState.shared` + `Stage.local_state(state)` helper. Pure core, additive. |
| PR-2 | `feat/stage-resolve-model-config` | geny-executor: `Stage.resolve_model_config(state) -> ModelConfig`. Keep `resolve_model` as alias. Tests pinning override → full bundle. Update `s06_api._build_request` to use the new helper (same behavior). |
| PR-3 | `feat/llm-client-package` | geny-executor: new `geny_executor/llm_client/` package with `BaseClient` + `ClientCapabilities` + `ClientRegistry` + `AnthropicClient` / `OpenAIClient` / `GoogleClient` / `VLLMClient`. `state.llm_client` slot; `attach_runtime(llm_client=...)`; default-client fallback from s06_api's existing provider (for backward compatibility until PR-4 flips s06). **Additive**: s06_api still uses the old artifact mechanism. |
| PR-4 | `feat/api-stage-unified-client` | geny-executor: migrate s06_api onto `geny_executor/llm_client/`. Add `provider: str` + `api_key: str` + `base_url: str` config fields on the stage; delete `s06_api/artifact/{default,openai,google}/providers.py`; remove the `provider` strategy slot. `_build_request` / streaming paths now go via `state.llm_client`. Manifest-v2 migration note: `artifacts["s06_api"]` collapses to a single form. |
| PR-5 | `feat/memory-stages-use-model-override` | geny-executor: s02 SummaryCompactor becomes a real summarizer (reads `resolve_model_config` + `state.llm_client`). s15 Reflective strategy gets a native LLM reflection path with the same helpers. Tests cover both. |
| PR-6 | `feat/geny-memory-model-routing` | Geny: build `ModelConfig` from `APIConfig.memory_model`, apply via `PipelineMutator.set_stage_model(2, ...)` and `set_stage_model(15, ...)`. Pass `llm_client` into `attach_runtime` via `ClientRegistry.get(api_config.provider)`. Make `_make_llm_reflect_callback` optional behind `USE_LEGACY_REFLECT` flag. |

Merge order: PR-1 → PR-2 → PR-3 → PR-4 → PR-5 → PR-6. Each PR is
independently testable; PRs 1–5 can ship to PyPI in one version
bump before Geny adopts them in PR-6.

### Ordering rationale

- **PR-3 is additive.** The `llm_client` package lives alongside
  `s06_api` artifacts without replacing them. This keeps PR-3 a
  low-risk "new module" PR, reviewable on its own.
- **PR-4 is the hard one.** It deletes three vendor artifact
  directories and rewires the `APIStage` construction path. Tests
  for every provider flavor shift to the new clients; manifests
  that name the old `"anthropic"` / `"openai"` / `"google"`
  artifacts keep working via a migration shim that maps them to
  the new provider names. If PR-4 has to be reverted, PR-1–3 stay
  useful on their own.
- **PR-5 depends on PR-3, not PR-4.** Memory stages only need
  `state.llm_client` (shipped in PR-3) — they don't care whether
  s06_api has been migrated yet. PR-4 and PR-5 could in principle
  land in either order; sequencing PR-4 first reduces the risk
  that Geny (PR-6) would need to know about two s06 configurations.

## Documents

- [analysis/01_current_interface_audit.md](analysis/01_current_interface_audit.md) — exhaustive current-state map of the interfaces involved
- [analysis/02_memory_llm_inventory.md](analysis/02_memory_llm_inventory.md) — every place memory work touches (or could touch) an LLM, today and planned; routing table annotated for the unified client
- [analysis/03_state_shape_design_space.md](analysis/03_state_shape_design_space.md) — global/local state options considered + chosen design with rationale; includes note on `state.llm_client` as an optional slot
- [plan/01_pipeline_state_shared_and_local.md](plan/01_pipeline_state_shared_and_local.md) — PR-1 design
- [plan/02_stage_resolve_model_config.md](plan/02_stage_resolve_model_config.md) — PR-2 design
- [plan/03_llm_client_package.md](plan/03_llm_client_package.md) — PR-3 design (llm_client package, BaseClient, adapters)
- [plan/04_api_stage_unified_client.md](plan/04_api_stage_unified_client.md) — PR-4 design (s06_api artifact removal + migration)
- [plan/05_memory_stages_use_model_override.md](plan/05_memory_stages_use_model_override.md) — PR-5 design (s02 summarizer + s15 reflector)
- [plan/06_geny_memory_model_routing.md](plan/06_geny_memory_model_routing.md) — PR-6 design (Geny-side routing)
- progress/ — populated as PRs land

## Relation to other cycles

- **20260421_3 (stage logging).** Landed PR-1..PR-3 (#203/#204/#205)
  yesterday. Frontend and backend now speak "Stage" consistently.
  This cycle builds on that vocabulary — any new events we emit
  from s02/s15 automatically render correctly in the panel.
- **20260420_8 + 20260421_1 (memory continuity).** Established that
  `SessionMemoryManager.record_message` + L0 retriever injection
  are the correctness floor. This cycle does **not** change that
  contract — we only change *which model* runs reflection and
  summarization and *how* it's wired.
- **geny-executor uniformity series (E1).** Progress notes in the
  executor repo (`progress/e1_uniformity.md:62-70`) explicitly list
  "stages that don't use the override today — exposed for future
  model-backed strategies." This cycle is the "future" the note
  refers to, and extends the uniformity thesis to **providers**
  (not just stages): one client interface, many vendors.

## Risks (headline — full treatment in each plan)

1. **Double-charging cost.** Adding new LLM calls in s02/s15 means
   real $/latency. Mitigation: gate every new call behind a
   `model_override is not None` check — never summarize or reflect
   if the stage wasn't explicitly configured with a model.
2. **Reflection quality regression.** Replacing a curated callback
   with a native strategy could change output. Mitigation: keep the
   callback path for one cycle as the "legacy" branch, switch only
   the default.
3. **s06_api migration regression.** Collapsing three artifact
   directories into one client package touches the main API path.
   Mitigation: PR-4 is its own PR; add a parity test suite comparing
   `AnthropicProvider` (old) vs. `AnthropicClient` (new) behavior
   against a fixture-replay recording before deleting the old
   files.
4. **Multi-provider feature drift.** Non-Anthropic clients may not
   support every field in `ModelConfig` (thinking, top_k, etc.).
   Mitigation: `ClientCapabilities` flags; unsupported fields are
   silently dropped with an event `llm_client.feature_unsupported`
   logged so the user sees the drop rather than a silent no-op.
5. **Concurrent state writes.** Stages in the same iteration could
   race on `state.shared`. Not a problem today (stages run
   sequentially within a loop turn) but worth a note in the plan.
