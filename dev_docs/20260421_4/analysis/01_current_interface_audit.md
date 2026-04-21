# Analysis 01 — Current interface audit

Complete map of every piece of the stage / model / state machinery
that this cycle touches, with file:line references. If the plan PRs
say "change X" you can trace X here to the exact source.

## 1. `Stage` base class surface

**File.** `src/geny_executor/core/stage.py`

```python
class Stage(ABC, Generic[T_In, T_Out]):
    # L83

    # ── Identity ─────────────────────────────────────────
    @property
    @abstractmethod
    def name(self) -> str: ...                       # L~110
    @property
    @abstractmethod
    def order(self) -> int: ...                      # L~118
    @property
    def category(self) -> str: return "execution"    # L~125

    # ── Lifecycle ────────────────────────────────────────
    async def on_enter(self, state: PipelineState): ...
    @abstractmethod
    async def execute(self, input: T_In, state: PipelineState) -> T_Out: ...
    async def on_exit(self, result: T_Out, state: PipelineState): ...
    async def on_error(self, error: Exception, state: PipelineState): return None
    def should_bypass(self, state: PipelineState) -> bool: return False

    # ── Introspection ────────────────────────────────────
    def describe(self) -> StageDescription: ...
    def list_strategies(self) -> List[StrategyInfo]: ...
    def get_strategy_slots(self) -> Dict[str, StrategySlot]: return {}
    def get_strategy_chains(self) -> Dict[str, SlotChain]: return {}

    # ── Config ───────────────────────────────────────────
    def get_config_schema(self) -> Optional[ConfigSchema]: return None
    def get_config(self) -> Dict[str, Any]: return {}
    def update_config(self, config: Dict[str, Any]) -> None: pass

    # ── Model override (THE UNUSED-ELSEWHERE SURFACE) ────
    _model_override: Optional[Any] = None            # L95

    @property
    def model_override(self) -> Any:                 # L279
        return self._model_override

    @model_override.setter
    def model_override(self, value: Any) -> None:    # L284
        self._model_override = value

    def resolve_model(self, state: PipelineState) -> Any:  # L309
        if self._model_override is not None:
            return getattr(self._model_override, "model", state.model)
        return state.model
```

**Key observations for this cycle.**

- `resolve_model` returns **just the model string**, not the full
  `ModelConfig`. If a non-api stage wants to override `max_tokens`
  or `temperature` it has to reach into `self._model_override`
  directly. That is the gap PR-2 fills.
- The override property is typed `Any` rather than
  `Optional[ModelConfig]` so a future caller could smuggle in any
  type — defensive but not self-documenting.
- No method on the Stage base currently returns a "full effective
  config" that merges override with state — each caller has to do
  its own merge (see s06_api below).

## 2. `ModelConfig` dataclass

**File.** `src/geny_executor/core/config.py:13–80`

```python
@dataclass
class ModelConfig:
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    temperature: float = 0.0
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None

    thinking_enabled: bool = False
    thinking_budget_tokens: int = 10000
    thinking_type: str = "enabled"
    thinking_display: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig": ...
```

**Already good.** This is the canonical bundle. No change needed —
every place that needs "a model configuration" should take exactly
this type.

## 3. `PipelineConfig` — top-level shape

**File.** `src/geny_executor/core/config.py:83–150`

```python
@dataclass
class PipelineConfig:
    name: str = "default"
    model: ModelConfig = field(default_factory=ModelConfig)   # pipeline-wide
    api_key: str = ""
    base_url: Optional[str] = None
    # ...
```

`PipelineConfig.model` is unpacked into individual `PipelineState`
fields at pipeline init time — so `state.model` is a string, not a
`ModelConfig`. (Why? historical: `PipelineState` predates
`ModelConfig`.) This cycle **does not** fold `ModelConfig` back into
`PipelineState`; it keeps the unpacked fields and introduces a
*reader* helper (`resolve_model_config`) that reassembles them.

## 4. `PipelineState` — shape and the state dilemma

**File.** `src/geny_executor/core/state.py:52–139`

Key fields for this cycle:

| Field | Type | Role today | Role in this cycle |
|---|---|---|---|
| `model` | `str` | pipeline-wide model | unchanged |
| `max_tokens`, `temperature`, `top_p`, `top_k`, `stop_sequences` | individual primitives | pipeline-wide sampling | unchanged |
| `thinking_*` | primitives | extended thinking knobs | unchanged |
| `messages` | `List[Dict]` | conversation | unchanged |
| `memory_refs` | `List[Dict]` | retrieved memory chunks | unchanged |
| `metadata` | `Dict[str, Any]` | **everything else** — currently a kitchen sink | **PR-1 disaggregates**: per-stage scratchpad lives under `metadata[stage.name]` via `Stage.local_state(state)` |
| `events` | `List[Dict]` | event log | unchanged |
| *(new in PR-1)* `shared` | `Dict[str, Any]` | — | **global state, deliberately separate from `metadata`** |
| *(new in PR-3)* `llm_client` | `Optional[LLMClient]` | — | shared LLM client handle, attached at runtime |

**Why a separate `shared` dict instead of just using `metadata`?**
Because `metadata` is already the per-stage scratchpad. If global
state goes in the same dict, two stages that both write under
`"context"` (one as their local scratchpad, one as a global fact)
collide silently. Discussed in depth in
[analysis/03_state_shape_design_space.md](03_state_shape_design_space.md).

## 5. `Stage.resolve_model` — exhaustive caller list

**Grep result (`rg "resolve_model" src/`).**

```
src/geny_executor/core/stage.py:309    # definition
```

That's it. **Nothing calls it.** `s06_api` reads
`self.model_override` directly:

```python
# src/geny_executor/stages/s06_api/artifact/default/stage.py:208–230
override = self.model_override
request = APIRequest(
    model=override.model if override else state.model,
    max_tokens=override.max_tokens if override else state.max_tokens,
    temperature=override.temperature if override else state.temperature,
    top_p=override.top_p if override else state.top_p,
    top_k=override.top_k if override else state.top_k,
    stop_sequences=(override.stop_sequences if override else state.stop_sequences),
)
```

This is the entire override consumer base in the executor today.
PR-2 replaces this ad-hoc merge with
`self.resolve_model_config(state)`.

## 6. `APIStage` — the only existing LLM caller

**File.** `src/geny_executor/stages/s06_api/artifact/default/stage.py`

- `__init__` at L40: takes either `provider: APIProvider` or
  `api_key: str`. If `api_key` is given, builds an
  `AnthropicProvider(api_key=...)` eagerly.
- `_provider` attribute (line ~83) exposed as a read-only property.
- `execute()` at ~L158 calls `_build_request(state)` then hands it
  to `self._provider.create_message(request)` (non-stream) or
  `create_message_stream(request)` (stream).
- `_build_request` (L198–246) is the override-reading path
  discussed above.

**Design constraint.** One APIStage = one provider = one Anthropic
client (lazily instantiated on first call). Re-using *this* provider
from s02/s15 is fine *iff* the provider accepts per-call
`ModelConfig` — which it already does, because `APIRequest.model`
is a per-call field. That is the unlock PR-3 takes advantage of.

## 7. `AnthropicProvider` — the shared-client candidate

**File.** `src/geny_executor/stages/s06_api/artifact/default/providers.py:15–186`

```python
class AnthropicProvider(APIProvider):
    def __init__(self, api_key, base_url=None, default_headers=None): ...
    def _get_client(self) -> anthropic.AsyncAnthropic: ...  # lazy
    async def create_message(self, request: APIRequest) -> APIResponse: ...
    async def create_message_stream(self, request) -> AsyncIterator[...]: ...
```

Per-call fields live on `APIRequest`, which means **the same
provider can serve calls with different models, different
max_tokens, different thinking settings** — the client is agnostic.
PR-3 exploits this: publish one provider to state; other stages
hand it their own `ModelConfig` → `APIRequest`.

## 8. `PipelineMutator.set_stage_model`

**File.** (referenced in progress/e1_uniformity.md:62–70) —
`src/geny_executor/core/mutator.py` (or similar).

```python
PipelineMutator(pipeline).set_stage_model(order: int, model: Optional[ModelConfig])
```

This method **already exists and round-trips through the manifest**
(tests pin it in `tests/unit/test_pipeline_from_manifest.py:87–109`).
Geny will call this from the session manager once per LLM-using
secondary stage.

## 9. `StageIntrospection.model_override_supported`

**File.** (tests cover this in `tests/unit/test_introspection.py:63–86`)

```python
def test_capability_flags_api_stage_only_allows_model_override():
    insp = introspect_stage("s06_api", "default")
    assert insp.model_override_supported is True

def test_capability_flags_default_false_elsewhere(order, module_name):
    insp = introspect_stage(module_name, "default")
    assert insp.model_override_supported is False
```

PR-5 flips `model_override_supported = True` for s02_context and
s15_memory (default artifacts). The assertion-loop test is
parametrized over every non-api module — it has to be updated in
lockstep so it doesn't fail when s02/s15 become True.

## 10. `Pipeline.attach_runtime`

**File.** `src/geny_executor/core/pipeline.py:~508`

Current signature:

```python
def attach_runtime(
    self,
    memory_retriever=None,
    memory_strategy=None,
    memory_persistence=None,
    system_builder=None,
    tool_context=None,
) -> None: ...
```

Adds entries to stage strategy slots. PR-3 adds one more parameter:

```python
    llm_client=None,   # NEW: sets state.llm_client for the run
```

Semantics: this doesn't live on a stage slot — it lives on
`PipelineState.llm_client` (new field, PR-1 adds `shared`; PR-3
adds `llm_client` separately because a typed protocol is clearer
than a dict key).

## 11. Geny — the bypass path for memory LLM calls

**File A.** `backend/service/langgraph/agent_session.py:818, 865–916`

```python
llm_reflect = _make_llm_reflect_callback(api_key)  # L818 roughly
# ...
attach_kwargs["memory_strategy"] = GenyMemoryStrategy(
    self._memory_manager,
    enable_reflection=True,
    llm_reflect=llm_reflect,   # L~845
    curated_knowledge_manager=curated_km,
)
```

`_make_llm_reflect_callback`:

```python
def _make_llm_reflect_callback(api_key: str):
    # L865–916
    client = anthropic.AsyncAnthropic(api_key=api_key)   # own client
    async def _reflect(input_text: str, output_text: str) -> list[dict]:
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",           # hardcoded
            max_tokens=1024,
            messages=[...],
        )
        # parses JSON → list of insight dicts
    return _reflect
```

Problems:
- Hard-coded model. `APIConfig.memory_model` exists but isn't read.
- Own Anthropic client — separate connection pool from the
  executor's own client, not reused.
- Invisible to token_usage / cost accounting / session_logger
  events emitted by the pipeline.
- Lives outside the stage system so `model_override`,
  `StageIntrospection`, and the log panel's stage rows never see
  it.

**File B.** `backend/service/memory/reflect_utils.py:15–41`

```python
def get_memory_model():
    api_cfg = get_config_manager().load_config(APIConfig)
    mem_model = api_cfg.memory_model  # "claude-haiku-4-5-20251001"
    return ChatAnthropic(model=mem_model, api_key=api_key, ...)
```

This *does* read `memory_model` from config — but it's used for
session-summary generation in the legacy memory layer, not for the
executor's reflection. **Two separate code paths for "the cheap
memory model."**

**File C.** `backend/service/config/sub_config/general/api_config.py:34–36`

```python
anthropic_model = "claude-sonnet-4-6"
vtuber_default_model = "claude-haiku-4-5-20251001"
memory_model = "claude-haiku-4-5-20251001"
```

`memory_model` is already in the config. The plumbing is missing, not
the configuration.

## 12. GenyMemoryStrategy — where reflection actually happens

**File.** (in `geny-executor` per the explorer, wrapping
`SessionMemoryManager`)
`src/geny_executor/memory/strategy.py` (referenced L191 in the
explorer report).

Current behavior: called on terminal state, if `enable_reflection`
and `llm_reflect` is set, invokes the callback with
(user_input, output_text) and stores the returned insights.

**Plan touch points (PR-5).** Replace the single callback with a
native path: `GenyMemoryStrategy.reflect(state)` builds its own
prompt and calls `state.llm_client.create_message(ModelConfig, ...)`
using the stage's `model_override`. Keep the callback as a fallback
when no `model_override` is set (so existing deployments don't break).

## 13. s02_context SummaryCompactor — the stub

**File.** `src/geny_executor/stages/s02_context/artifact/default/compactors.py`

Quoted docstring (from the explorer scan):

> Replace old messages with a summary placeholder.
> Note: actual summarization would require an API call.
> This implementation provides the structural framework;
> integration with the API stage would be done at the pipeline level.

This is the canonical example of "the interface was built but no
one wired up the LLM." PR-5 replaces this with a real implementation
that:
- Reads `stage.resolve_model_config(state)` (with the override
  cycle Geny sets).
- Builds a compaction prompt from the messages slated for truncation.
- Calls `state.llm_client.create_message(...)`.
- Writes the summary into `state.memory_refs` as a
  `{"source": "context.summary", ...}` chunk.

## 14. Introspection capability flags — test implications

Tests to update (PR-5):
- `tests/unit/test_introspection.py:63–86` — add s02_context and
  s15_memory to the `model_override_supported = True` set,
  parametrize the "default false" test to exclude them.
- `tests/contract/test_stage_uniformity.py:144–152` — unchanged
  (the roundtrip test is generic).

## Summary of what exists vs what is missing

| Piece | Exists? | Used? | Where |
|---|---|---|---|
| `ModelConfig` dataclass | ✅ | ✅ (s06_api) | `core/config.py:13-80` |
| `Stage.model_override` property | ✅ | ❌ (only s06_api) | `core/stage.py:279-285` |
| `Stage.resolve_model()` helper | ✅ | ❌ (zero callers) | `core/stage.py:309-320` |
| `PipelineMutator.set_stage_model()` | ✅ | ✅ (tests only, no production caller) | mutator + manifest |
| `StageIntrospection.model_override_supported` | ✅ | ✅ | introspection module |
| `AnthropicProvider` | ✅ | ✅ (s06_api only) | `providers.py:15-186` |
| `PipelineState.shared` (global state) | ❌ | — | — |
| `Stage.local_state()` (per-stage scratchpad helper) | ❌ | — | — |
| `Stage.resolve_model_config()` (full ModelConfig) | ❌ | — | — |
| `PipelineState.llm_client` (shared LLM client) | ❌ | — | — |
| s02_context SummaryCompactor real impl | ❌ (stub) | — | `compactors.py` |
| s15_memory native reflection (no callback) | ❌ | — | — |
| Geny applies `APIConfig.memory_model` to stages | ❌ (bypass path) | — | `agent_session.py:865-916` |

**Six ❌ rows** — the work this cycle does.
