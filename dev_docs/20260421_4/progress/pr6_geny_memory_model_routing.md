# PR-6 progress — Geny memory-model routing + unified client wiring

- Branch: `feat/geny-memory-model-routing`
- Plan: `Geny/dev_docs/20260421_4/plan/06_geny_memory_model_routing.md`
- Depends on: `geny-executor` PR-1..PR-5 (merged into the executor's PR
  chain, pending a single `0.29.0` publish)
- Blocking: nothing — this closes cycle 20260421_4

## What shipped

Cycle 20260421_4's executor-side work (`state.llm_client`,
`Stage.resolve_model_config`, `PipelineMutator.set_stage_model`,
`LLMSummaryCompactor`, `ReflectionResolver`) is now actually load-bearing
in Geny. The host wires it from `APIConfig` via `_build_pipeline`.

### Config — `service/config/sub_config/general/api_config.py`

Three new fields + env-map entries + UI metadata:

| Field | Default | Env var | UI type |
|-------|---------|---------|---------|
| `provider` | `"anthropic"` | `LLM_PROVIDER` | SELECT (anthropic/openai/google/vllm) |
| `base_url` | `""` | `LLM_BASE_URL` | STRING (optional; required for vllm) |
| `use_legacy_reflect` | `False` | `USE_LEGACY_REFLECT` | BOOLEAN (rollback lever) |

The plan called for `FieldType.ENUM`; this repo uses `FieldType.SELECT`
with explicit `{"value", "label"}` options — so `PROVIDER_OPTIONS` is
defined next to `MODEL_OPTIONS` at module top.

### Session — `service/langgraph/agent_session.py`

`_build_pipeline` grows a memory-model routing block that replaces the
old unconditional `llm_reflect = self._make_llm_reflect_callback(...)`
line. The block runs in this order:

1. **Build memory `ModelConfig`**: `APIConfig.memory_model` (empty →
   `APIConfig.anthropic_model`) → `ModelConfig(..., max_tokens=2048,
   temperature=0.0, thinking_enabled=False)`.
2. **Apply per-stage override** via `PipelineMutator.set_stage_model(2, cfg)`
   and `(15, cfg)`. Each call is wrapped in `try/except MutationError`
   that logs a warning — a manifest without s02 or s15 boots cleanly
   with the warning instead of raising.
3. **Build the shared `BaseClient`** via
   `ClientRegistry.get(api_cfg.provider)(api_key=..., base_url=...)`.
   Unknown providers raise at session-build time (clear error, listed
   registered names) rather than failing silently mid-session.
4. **Sync s06's own `provider`/`base_url` config** for the rare case
   where `state.llm_client` goes None at runtime and s06 needs to
   build its own fallback — no credential drift by construction.
5. **Build `ReflectionResolver`** bound to the s15 stage handle — its
   `resolve_cfg` reads the live `_model_override` at reflect time, so
   the override set in step 2 actually takes effect. `has_override`
   gates the native path on the override being present.
6. **Pick callback vs. native**: `use_legacy_reflect=True` restores
   the pre-cycle callback; otherwise `llm_reflect=None` and the
   executor-side `ReflectionResolver` drives reflection.
7. **`attach_runtime(**attach_kwargs)`** now includes
   `llm_client=<BaseClient>` so the executor's s06/s02/s15 all route
   through the same client instance.

### Dependency pin — `backend/pyproject.toml`

Bumped `geny-executor>=0.28.0,<0.29.0` → `>=0.29.0,<0.30.0`. The
`0.29.0` release bundles PR-1..PR-5 of cycle 20260421_4. Until the
executor publishes `0.29.0`, `pip install -e .` in this branch will
fail — the publish step is part of the rollout (plan §7 item 1), not
part of this PR's code.

### Docstring — `_make_llm_reflect_callback`

No behavior change, just a deprecation notice pointing at
`APIConfig.use_legacy_reflect` and flagging this for removal in the
next cycle.

## Tests

New: `backend/tests/service/langgraph/test_memory_model_routing.py`
(8 tests, all passing):

| Test | Pins |
|------|------|
| `test_stage_overrides_use_memory_model` | s02/s15 receive the memory_model override |
| `test_empty_memory_model_falls_back_to_main` | empty memory_model → anthropic_model is used |
| `test_attach_runtime_receives_base_client` | `llm_client=BaseClient(provider="anthropic")` on attach |
| `test_unknown_provider_surfaces_at_build_time` | bogus `LLM_PROVIDER` raises at build time |
| `test_s06_stage_config_synced` | s06 stage's own config mirrors provider + base_url |
| `test_memory_strategy_has_resolver_and_no_callback_by_default` | default path = native (resolver set, callback None) |
| `test_legacy_flag_restores_callback` | `USE_LEGACY_REFLECT=1` reinstalls the callback |
| `test_missing_memory_stages_is_warning_not_failure` | manifest without s02/s15 boots with warnings, not raises |

The test fixture resets the `get_config_manager()` singleton **and**
redirects `ConfigManager.__init__` at a per-test `tmp_path`, so each
test gets fresh env-var-driven defaults and does not leak through
the on-disk `api.json`. Without that reset, whichever test ran first
poisoned the rest.

Full regression run for `backend/tests/service/langgraph/`:
**95 passed** — including this module's 8 new tests and all
pre-existing `test_agent_session_memory.py` / `test_default_manifest.py`
tests.

Broader backend suite: 5 pre-existing failures outside the langgraph
subtree remain (VTuber template tool propagation, text-sanitizer TTS
shim). These failed on `main` before this cycle and are out of scope.

## Plan deviations

- **FieldType.ENUM → FieldType.SELECT**. The plan's metadata snippet
  used `FieldType.ENUM` with an `enum=[...]` list, which does not
  exist in this repo's `base.py`. Switched to `FieldType.SELECT` with
  explicit `options=[{"value":..., "label":...}]` to match every
  other select field in the same module (e.g. `anthropic_model`).
- **`MutationError` instead of `LookupError`**. The plan expected
  `set_stage_model` to raise `LookupError`; in practice it raises
  `geny_executor.core.errors.MutationError` from
  `PipelineMutator._get_stage`. The `try/except` uses the real
  exception class now.
- **No integration smoke test shipped in this PR**. Plan §3.6 calls
  for a manifest-based integration test asserting
  `memory.reflection.native` events; deferred because the executor
  `0.29.0` isn't published yet, so running a real pipeline in the
  Geny backend CI would need a path-installed executor. Covered by
  the unit tests listed above plus the executor's own
  `test_strategy_native_reflect.py` / `test_llm_summary_compactor.py`
  (PR-5). Ship the integration smoke in the cycle that removes the
  legacy callback.

## Rollout reminders (plan §7)

1. **Publish `geny-executor 0.29.0`** with PR-1..PR-5 merged. The pin
   bump in this PR is a pre-commitment — merge order must be
   executor-first.
2. Merge this PR.
3. Keep `USE_LEGACY_REFLECT=1` available for one production week.
4. Follow-up cycle removes `_make_llm_reflect_callback` and the flag
   once the native path has soaked without regressions.
5. Provider defaults pinned to `anthropic`. OpenAI/Google/vLLM
   rollout is a separate cycle (credential routing, extras install
   docs, monitoring).

## Acceptance checks

- [x] `APIConfig` has `provider`, `base_url`, `use_legacy_reflect`
      with env-var mapping and UI metadata.
- [x] `_build_pipeline` calls `set_stage_model(2, …)` and
      `set_stage_model(15, …)` with the `memory_model`-derived config.
- [x] `attach_runtime(llm_client=…)` is called with a `BaseClient`
      built via `ClientRegistry.get(provider)`.
- [x] `GenyMemoryStrategy` receives `resolver=<ReflectionResolver>`
      by default; `llm_reflect` is `None` unless `use_legacy_reflect`.
- [x] Missing s02/s15 stages warn but do not raise.
- [x] Unknown provider raises at build time with a clear error.
- [x] s06's own config mirrors the session's provider/base_url
      (defensive fallback path).
- [x] `_make_llm_reflect_callback` has a deprecation docstring
      pointing at `APIConfig.use_legacy_reflect`.
- [x] pyproject bump to `>=0.29.0,<0.30.0`.
- [x] 8 new unit tests passing; no new failures in the langgraph
      subtree.
