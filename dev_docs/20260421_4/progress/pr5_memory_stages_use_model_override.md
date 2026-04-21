# PR-5 progress — memory stages honour per-stage model override

- Branch: `feat/memory-stages-use-model-override`
- Base: `feat/api-stage-unified-client` (PR #40, PR-4)
- Upstream PR: https://github.com/CocoRoF/geny-executor/pull/41
- Commit: `3a5fca1 feat(memory): s02/s15 honour per-stage model override via unified client`
- Plan: `Geny/dev_docs/20260421_4/plan/05_memory_stages_use_model_override.md`

## What shipped

s02 Context and s15 Memory can now consume a per-stage model override
by routing their LLM work through `state.llm_client` with the stage's
resolved `ModelConfig`. Both paths are **gated** — without an override
(or without a client) behavior is byte-identical to before.

### s02 Context — `LLMSummaryCompactor`

New compactor class in
`src/geny_executor/stages/s02_context/artifact/default/compactors.py`
extends the existing placeholder `SummaryCompactor`:

```python
class LLMSummaryCompactor(SummaryCompactor):
    def __init__(self, keep_recent=10, summary_text="", *,
                 resolve_cfg=None, has_override=None, client_getter=None):
        ...
```

Three closures keep the compactor decoupled from the stage class:

- `resolve_cfg(state) -> ModelConfig` — normally
  `lambda s: stage.resolve_model_config(s)`.
- `has_override() -> bool` — normally
  `lambda: stage._model_override is not None`.
- `client_getter(state) -> Optional[BaseClient]` — defaults to
  `lambda s: getattr(s, "llm_client", None)`.

Behavior in `compact()`:

1. If `keep_recent >= len(messages)` → no-op (unchanged).
2. If no override **or** no client → emit the placeholder summary
   line (unchanged pre-PR-5 output).
3. Otherwise build a transcript prompt, call
   `client.create_message(model_config=cfg, messages=[...], purpose="s02.compact")`,
   replace the dropped tail with the returned summary, and emit a
   `memory.compaction.summarized` event carrying the model name.
4. Exceptions fall back to the placeholder **and** emit
   `memory.compaction.llm_failed`.

Exported from `stages/s02_context/__init__.py` and the `artifact/default/__init__.py`.

### s15 Memory — `ReflectionResolver` + native `_reflect`

New `ReflectionResolver` dataclass in
`src/geny_executor/memory/strategy.py`:

```python
@dataclass
class ReflectionResolver:
    resolve_cfg: Callable[[Any], ModelConfig]
    has_override: Callable[[], bool]
    client_getter: Callable[[Any], Optional[Any]] = \
        field(default=lambda s: getattr(s, "llm_client", None))
```

`GenyMemoryStrategy.__init__` grew an optional
`resolver: Optional[ReflectionResolver] = None`. `_reflect()` now
resolves in priority order:

1. **User callback** (`llm_reflect=cb`) — unchanged legacy path.
2. **Native resolver** (resolver set **and** `has_override()` **and**
   client non-None) — build JSON prompt, call
   `client.create_message(model_config=cfg, messages=[...], purpose="s15.reflect")`,
   strip ` ``` ` fences, parse JSON, respect `should_save`, save
   insights via the existing `_save_insights` helper. Emits
   `memory.reflection.native` on success,
   `memory.reflection.llm_failed` on parse/transport error.
3. **Deferred** — set `state.metadata["needs_reflection"] = True`
   and emit `memory.reflection_queued` (unchanged pre-PR-5 behavior
   when no resolver is passed).

`ReflectionResolver` is re-exported from `geny_executor.memory` so
hosts (Geny) can construct one in `_build_pipeline`.

### Introspection capability flags

`_STAGE_CAPABILITIES` in `src/geny_executor/core/introspection.py`
gained two entries so UIs can honestly surface a model-selector on
the stages that actually consume the override:

```python
_STAGE_CAPABILITIES = {
    "s02_context": {"tool_binding": False, "model_override": True},
    "s06_api":     {"tool_binding": False, "model_override": True},
    "s10_tool":    {"tool_binding": True,  "model_override": False},
    "s15_memory":  {"tool_binding": False, "model_override": True},
}
```

The preceding comment block now documents that s02 consumes the
override via `LLMSummaryCompactor` and s15 via `GenyMemoryStrategy`
native reflection.

## Tests

- `tests/unit/test_llm_summary_compactor.py` — **6 new tests**:
  no override → placeholder, override+client → LLM call + event,
  client failure → placeholder + failure event, below `keep_recent`
  → no-op, no client → placeholder, legacy `SummaryCompactor`
  still usable by name.
- `tests/unit/test_strategy_native_reflect.py` — **7 new tests**:
  native runs when callback missing + override set, skipped when no
  override, skipped when no client, callback still wins, should_save
  False records zero, JSON parse error emits `llm_failed`, no
  resolver → pre-cycle queue behavior.
- `tests/unit/test_introspection.py` — extended
  `_MODEL_OVERRIDE_STAGES = {"s02_context", "s06_api", "s15_memory"}`
  and added positive assertions for s02 and s15.

Full suite: **1111 passed, 18 skipped** (up from 1098 — 13 new tests).
Lint + format: clean across all touched files.

## Events reference

| event type | emitted by | payload keys |
|------------|------------|--------------|
| `memory.compaction.summarized` | s02 LLMSummaryCompactor success | `model`, `dropped`, `kept` |
| `memory.compaction.llm_failed` | s02 LLMSummaryCompactor exception | `model`, `error` |
| `memory.reflection.native` | s15 GenyMemoryStrategy native path success | `model`, `saved`, `should_save` |
| `memory.reflection.llm_failed` | s15 native path parse/transport error | `model`, `error` |
| `memory.reflection_queued` | s15 deferred / legacy path | `reason` (for deferral diagnostic) |

## What's next (PR-6)

Per `Geny/dev_docs/20260421_4/plan/06_geny_memory_model_routing.md`:

- Geny's `APIConfig` grows `provider` / `base_url` /
  `use_legacy_reflect` / `memory_model` fields.
- `_build_pipeline` uses `ClientRegistry.get(cfg.provider)` to
  build the unified client, `attach_runtime(llm_client=...)`, and
  calls `set_stage_model(2, ...)` / `set_stage_model(15, ...)`
  from the `memory_model` field when set.
- Geny constructs a `ReflectionResolver` from its own `APIConfig`
  and passes it to `GenyMemoryStrategy`.
- Back-compat mode: `use_legacy_reflect=True` keeps the existing
  Geny callback wiring, no resolver installed.
