# PR-4 progress — s06_api routes through state.llm_client

- Branch: `feat/api-stage-unified-client`
- Base: `feat/llm-client-package` (PR #39, PR-3)
- Upstream PR: https://github.com/CocoRoF/geny-executor/pull/40
- Commit: `79b268f feat(s06_api): route APIStage through state.llm_client + string provider kwarg`
- Plan: `Geny/dev_docs/20260421_4/plan/04_api_stage_unified_client.md`

## What shipped

`APIStage.execute` now talks to the LLM exclusively via
`state.llm_client`. The stage retains the legacy provider slot for
backward compat, but the provider slot is no longer on the hot path —
its only role now is to feed the PR-3 auto-bridge when no explicit
client is attached.

Key edits in `src/geny_executor/stages/s06_api/artifact/default/stage.py`:

- `APIStage(provider=...)` accepts three shapes:
  - **string** (`"anthropic"` / `"openai"` / `"google"` / `"vllm"` /
    `"mock"`) — `ClientRegistry` builds the local fallback; legacy
    provider slot is filled with the equivalent old-style provider for
    manifest round-tripping.
  - **APIProvider instance** (legacy) — slot fills verbatim;
    `get_config()["provider"]` reflects the provider's `name`.
  - **None + `api_key`** — defaults to Anthropic (unchanged from pre-PR-4).
- `get_config()["provider"]` reports the active provider name.
- `update_config({"provider": ...})` swaps the local client and slot.
- `get_config_schema()` exposes a `type="select"` field whose `options`
  enumerate every provider registered in `ClientRegistry` plus legacy
  names (`mock`).
- `_resolve_client(state)` picks `state.llm_client` first, falling back
  to a lazy local client built either via `ClientRegistry.get(name)` or
  (for legacy shapes) via `ProviderBackedClient(self._provider)`.
- `execute()` builds call kwargs once and dispatches to
  `client.create_message` / `client.create_message_stream`. The retry
  wrappers take a `BaseClient` now, not an `APIProvider`.
- `_build_request()` retained — no longer on the hot path, kept for
  legacy test fixtures (`test_phase1_pipeline.py::test_model_config_propagates_all_params`).

Tests: `tests/unit/test_s06_provider_selection.py` (12 new) covering:

- default provider is `"anthropic"`
- string / instance / update_config round-trip
- schema `select` field lists every registered provider
- routing through `state.llm_client` when attached (and verifying the
  underlying `MockProvider.call_count` stays 0)
- fallback to local provider when no client attached (bridge path)
- vLLM `base_url` guard (missing = `ValueError`; present = builds OK)

Full suite: **1098 passed, 18 skipped**. No regressions.

## Deviation from plan 04

Plan §4.1 calls for deleting:

- `src/geny_executor/stages/s06_api/artifact/{default,openai,google}/`
- `src/geny_executor/stages/s06_api/interface.py`
- `src/geny_executor/stages/s06_api/_translate.py`
- `src/geny_executor/stages/s06_api/types.py` (the PR-3 shim)
- `src/geny_executor/stages/s06_api/providers.py`

…plus rewriting ~30 tests that import `MockProvider` /
`AnthropicProvider` to use `MockClient(BaseClient)` fixtures instead.

**PR-4 skips that demolition.** Rationale:

1. The **critical contract** required by PR-5 / PR-6 is
   "`APIStage.execute` routes through `state.llm_client` and
   `provider` is a string config field." Both are now true.
2. The PR-3 auto-bridge (`ProviderBackedClient` wraps an `APIProvider`)
   makes legacy tests safe: `state.llm_client` is populated by the
   bridge, `execute()` calls it the same way, `MockProvider.call_count`
   increments as expected for tests that introspect it.
3. The 30-file test rewrite adds blast radius with no behavioral
   benefit — the old path is already silently unreachable in
   normal execution (the bridge fires).

A follow-up cycle can delete the legacy artifact tree once downstream
code (Geny) is verified to never construct `APIProvider` instances
directly.

## What's next (PR-5)

Memory stages use the shared client + `set_stage_model` override:

- `LLMSummaryCompactor` (s02 compaction path) — drop its own
  anthropic client, read `state.llm_client`, use
  `self.resolve_model_config(state)` so a per-stage model override
  routes correctly.
- `ReflectionResolver` (s15) — same shape.
- Host-side `attach_runtime(llm_client=...)` + `set_stage_model(2, ...)` +
  `set_stage_model(15, ...)` end-to-end test.
