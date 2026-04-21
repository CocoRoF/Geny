# Plan 04 — PR-4: s06_api migration onto the unified client

**Repo.** `/home/geny-workspace/geny-executor`
**Branch.** `feat/api-stage-unified-client`
**Depends on.** PR-3 (`geny_executor/llm_client/` package must
exist with `AnthropicClient` / `OpenAIClient` / `GoogleClient` /
`VLLMClient` + `ClientRegistry` + the `state.llm_client` slot).
Merge order PR-1 → PR-2 → PR-3 → PR-4.
**Blocks.** PR-5 (memory stages assume `state.llm_client` is
the only LLM path and a single s06 configuration). PR-6 (Geny
configures the API stage by a single `provider` name string).
**Related analysis.**
- Analysis 01 §6 — `s06_api._build_request` branch tree (the
  code this PR simplifies).
- Analysis 01 §7 — `APIProvider` strategy slot mechanism
  (what this PR removes).
- Analysis 02 §3 — three LLM shapes; this PR eliminates shape #1.

## 1. Goal

Finish unification. `s06_api` stops owning a vendor-provider
strategy slot. The stage becomes a thin orchestrator around:

1. `self.resolve_model_config(state)` — full `ModelConfig`.
2. `state.llm_client.create_message(model_config=..., messages=...)`
   — the only way the stage talks to an LLM.

The artifact directories `stages/s06_api/artifact/{default, openai,
google}/` and their `providers.py` files **delete**. The
`APIProvider` strategy interface **deletes**. `_translate.py`
**deletes** (its content already lives under
`llm_client/translators/` after PR-3).

Vendor selection collapses to a single config field:

```python
APIStage(provider="anthropic", api_key="sk-ant-...", base_url=None)
APIStage(provider="openai",    api_key="sk-...",     base_url=None)
APIStage(provider="vllm",      api_key="EMPTY",      base_url="http://localhost:8000/v1")
```

`APIStage.__init__` calls
`ClientRegistry.get(provider)(api_key=api_key, base_url=base_url)`
to build its own default client for the rare case where a pipeline
runs with no `state.llm_client` (the in-s06 fallback during a
transition). Normally `attach_runtime(llm_client=...)` injects the
shared client and s06 uses that.

## 2. Why

Three motivations, in descending order of weight:

1. **One LLM path, one bug surface.** After PR-3 there are two
   parallel paths reaching Anthropic: `s06_api`'s artifact
   `AnthropicProvider` and the new `llm_client.AnthropicClient`.
   Any fix (retry tuning, header handling, error mapping) has
   to land in both. PR-4 collapses them into one.
2. **Manifest simplicity.** Today a manifest for the API stage
   encodes the strategy selection as
   `artifacts["s06_api"] == "anthropic"` (or `"openai"`,
   `"google"`). After PR-4, `artifacts["s06_api"]` is
   irrelevant — the only knob is `config.provider`, a plain
   string. Geny (PR-6) only has to wire one field.
3. **Memory stage parity.** PR-5's s02 summarizer and s15
   reflector call `state.llm_client` directly. If s06_api still
   bypasses `state.llm_client`, the system has an asymmetric
   "main stage uses its private client, memory stages use the
   shared one" architecture. PR-4 makes s06_api play by the
   same rule.

## 3. Non-goals

- **No retry-policy changes.** The `RetryStrategy` slot
  (`ExponentialBackoffRetry`, `NoRetry`, `RateLimitAwareRetry`)
  stays — it's about error recovery, not vendor selection.
  The `_call_with_retry` wrapper continues to wrap the new
  `state.llm_client.create_message` / `create_message_stream`
  calls instead of the provider's.
- **No behavior change for current Anthropic users.**
  `AnthropicClient` is a byte-for-byte behavioral clone of
  `AnthropicProvider`; parity tests (§6.3) pin this.
- **No new features for OpenAI / Google / vLLM clients.**
  The capabilities they advertise are exactly what they had
  as `APIProvider`s — PR-4 is migration only.
- **No Mock / Recording provider removal.** `MockProvider` and
  `RecordingProvider` stay in-tree for tests, but move from
  `stages/s06_api/artifact/default/providers.py` to
  `tests/fixtures/mock_clients.py` (subclass `BaseClient`).
- **No s06_api deletion.** The stage stays; just the artifact
  subtree underneath it deletes.

## 4. Changes

### 4.1 Delete

Remove these files entirely:

- `src/geny_executor/stages/s06_api/interface.py` → only
  `RetryStrategy` survives; `APIProvider` is gone. `RetryStrategy`
  moves to `src/geny_executor/stages/s06_api/retry.py` (where it
  always belonged — alongside its concrete subclasses).
- `src/geny_executor/stages/s06_api/artifact/default/providers.py`
- `src/geny_executor/stages/s06_api/artifact/default/stage.py`
  (the content collapses into the top-level stage file, see §4.3).
- `src/geny_executor/stages/s06_api/artifact/default/retry.py`
  (moves to `s06_api/retry.py`; already referenced by PR-3 analysis).
- `src/geny_executor/stages/s06_api/artifact/default/__init__.py`
- `src/geny_executor/stages/s06_api/artifact/openai/providers.py`
- `src/geny_executor/stages/s06_api/artifact/openai/__init__.py`
- `src/geny_executor/stages/s06_api/artifact/google/providers.py`
- `src/geny_executor/stages/s06_api/artifact/google/__init__.py`
- `src/geny_executor/stages/s06_api/artifact/__init__.py`
- The entire `src/geny_executor/stages/s06_api/artifact/` tree.
- `src/geny_executor/stages/s06_api/_translate.py` (the per-vendor
  translators now live in `llm_client/translators/`; PR-3 kept
  both copies; PR-4 removes the s06_api copy).
- `src/geny_executor/stages/s06_api/types.py` shim (PR-3 left it
  as a re-export; PR-4 deletes it and updates any in-repo
  import paths to `geny_executor.llm_client.types`).

### 4.2 Move

- `AnthropicProvider` logic is **already** in
  `llm_client/anthropic.py` as `AnthropicClient` (PR-3).
- `MockProvider` and `RecordingProvider` → `tests/fixtures/mock_clients.py`,
  rewritten as `MockClient(BaseClient)` and
  `RecordingClient(BaseClient)`. Stage and integration tests
  import from the fixtures path.
- Retry classes: `ExponentialBackoffRetry`, `NoRetry`,
  `RateLimitAwareRetry` → `src/geny_executor/stages/s06_api/retry.py`.
  `RetryStrategy` ABC moves into the same file.

### 4.3 `src/geny_executor/stages/s06_api/stage.py` — new home

Replace `stages/s06_api/artifact/default/stage.py` with a
simplified top-level stage file. Key changes:

```python
"""Stage 6: API — calls an LLM via the shared ``state.llm_client``."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from geny_executor.core.errors import APIError, ErrorCategory
from geny_executor.core.schema import ConfigField, ConfigSchema
from geny_executor.core.slot import StrategySlot
from geny_executor.core.stage import Stage
from geny_executor.core.state import PipelineState
from geny_executor.llm_client import BaseClient, ClientRegistry
from geny_executor.llm_client.types import APIRequest, APIResponse
from geny_executor.stages.s06_api.retry import (
    ExponentialBackoffRetry,
    NoRetry,
    RateLimitAwareRetry,
    RetryStrategy,
)


class APIStage(Stage[Any, APIResponse]):
    """Stage 6: API.

    Talks to an LLM exclusively via ``state.llm_client``. Provider
    selection (anthropic / openai / google / vllm) is controlled by
    the ``provider`` config field, which the host passes in at
    construction time and which maps through ``ClientRegistry`` to
    the right client class.

    Retains the retry-strategy slot because retry behavior is about
    error recovery, not vendor selection.
    """

    def __init__(
        self,
        *,
        provider: str = "anthropic",
        api_key: str = "",
        base_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        retry: Optional[RetryStrategy] = None,
        stream: bool = True,
        timeout_ms: Optional[int] = None,
    ) -> None:
        self._provider_name = provider
        self._api_key = api_key
        self._base_url = base_url
        self._default_headers = default_headers or {}
        self._stream_default = stream
        self._timeout_ms = timeout_ms

        self._slots: Dict[str, StrategySlot] = {
            "retry": StrategySlot(
                name="retry",
                strategy=retry or ExponentialBackoffRetry(),
                registry={
                    "exponential_backoff": ExponentialBackoffRetry,
                    "no_retry": NoRetry,
                    "rate_limit_aware": RateLimitAwareRetry,
                },
                description="Retry strategy on API errors",
            ),
        }

    @property
    def name(self) -> str:
        return "api"

    @property
    def order(self) -> int:
        return 6

    @property
    def category(self) -> str:
        return "execution"

    # ------------------------------------------------------------------
    # Config surface
    # ------------------------------------------------------------------
    def get_strategy_slots(self) -> Dict[str, StrategySlot]:
        return self._slots

    def get_config_schema(self) -> ConfigSchema:
        return ConfigSchema(
            name="api",
            fields=[
                ConfigField(
                    name="provider",
                    type="string",
                    label="Provider",
                    description="LLM provider to use for this stage.",
                    default="anthropic",
                    enum=sorted(ClientRegistry.available()),
                ),
                ConfigField(
                    name="base_url",
                    type="string",
                    label="Base URL",
                    description="Override API endpoint (vLLM / proxy / mock server).",
                    default="",
                ),
                ConfigField(
                    name="stream",
                    type="boolean",
                    label="Stream",
                    description="Use streaming when the provider supports it.",
                    default=True,
                    ui_widget="toggle",
                ),
                ConfigField(
                    name="timeout_ms",
                    type="integer",
                    label="Timeout (ms)",
                    description="Per-request timeout in milliseconds. 0 = provider default.",
                    default=0,
                    min_value=0,
                ),
            ],
        )

    def get_config(self) -> Dict[str, Any]:
        return {
            "provider": self._provider_name,
            "base_url": self._base_url or "",
            "stream": self._stream_default,
            "timeout_ms": self._timeout_ms or 0,
        }

    def update_config(self, config: Dict[str, Any]) -> None:
        if "provider" in config:
            self._provider_name = str(config["provider"]) or "anthropic"
        if "base_url" in config:
            self._base_url = str(config["base_url"]) or None
        if "stream" in config:
            self._stream_default = bool(config["stream"])
        if "timeout_ms" in config:
            value = int(config["timeout_ms"])
            self._timeout_ms = value if value > 0 else None

    # ------------------------------------------------------------------
    # Client resolution
    # ------------------------------------------------------------------
    def _resolve_client(self, state: PipelineState) -> BaseClient:
        """Return the effective client.

        Preference:
          1. ``state.llm_client`` if injected — the host's shared client
             wins. Memory stages share the same instance.
          2. A stage-local fallback built from ``ClientRegistry`` using
             this stage's own ``provider`` + ``api_key`` + ``base_url``.
             Constructed lazily and cached.
        """
        if state.llm_client is not None:
            return state.llm_client
        if self._local_client is None:
            client_cls = ClientRegistry.get(self._provider_name)
            self._local_client = client_cls(
                api_key=self._api_key,
                base_url=self._base_url,
                default_headers=self._default_headers,
                event_sink=getattr(state, "log_stream", None),
            )
        return self._local_client
```

`self._local_client` is a new optional field (None by default,
set on first use). It exists so that early-lifecycle test code
that never calls `attach_runtime` still works (the stage's
constructor took an `api_key` and can build its own client).
In production code paths `state.llm_client` is populated by
`attach_runtime` and the fallback never triggers.

### 4.4 `execute` → route through the client

```python
async def execute(self, input: Any, state: PipelineState) -> APIResponse:
    cfg = self.resolve_model_config(state)
    client = self._resolve_client(state)
    use_stream = self._resolve_stream(state)

    state.add_event(
        "api.request",
        {
            "model": cfg.model,
            "provider": client.provider,
            "message_count": len(state.messages),
            "has_tools": bool(state.tools),
            "has_thinking": cfg.thinking_enabled,
            "stream": use_stream,
        },
    )

    if use_stream:
        response = await self._call_streaming_with_retry(client, cfg, state)
    else:
        response = await self._call_with_retry(client, cfg, state)

    state.last_api_response = response
    assistant_content = self._build_assistant_content(response)
    state.add_message("assistant", assistant_content)

    state.add_event(
        "api.response",
        {
            "stop_reason": response.stop_reason,
            "text_length": len(response.text),
            "tool_calls": len(response.tool_calls),
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    )

    return response
```

`_call_with_retry` / `_call_streaming_with_retry` are the
existing methods, retargeted from `self._provider.create_message`
to `client.create_message(model_config=cfg, messages=list(state.messages),
system=state.system, tools=state.tools, tool_choice=state.tool_choice,
purpose="api")`. The retry wrapper shape stays identical; only
the underlying call changes.

The retry methods' signatures become:

```python
async def _call_with_retry(
    self, client: BaseClient, cfg: ModelConfig, state: PipelineState,
) -> APIResponse: ...

async def _call_streaming_with_retry(
    self, client: BaseClient, cfg: ModelConfig, state: PipelineState,
) -> APIResponse: ...
```

`APIRequest` is no longer built at the stage level — the client
builds it internally via `BaseClient._build_request`. This is
what eliminates the duplicate "assemble thinking dict from
state/override" logic currently in `_build_request` L198-246.

### 4.5 `StageIntrospection.model_override_supported`

`APIStage.model_override_supported` is already `True` today and
stays `True`. No change.

### 4.6 Manifest migration shim

`src/geny_executor/core/manifest.py` (or wherever the manifest
loader lives — the exact module is `pipeline_builder.py` per
analysis 01 §12) grows a small shim for old manifests:

```python
_S06_ARTIFACT_TO_PROVIDER = {
    "default": "anthropic",   # old name for the anthropic artifact
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
}

def _migrate_s06_manifest(manifest: dict) -> dict:
    """Old manifests encoded provider as artifacts['s06_api'] = 'openai'.
    New manifests set config.s06_api.provider = 'openai'. Shim maps old
    to new so manifests checked in before PR-4 still load.
    """
    artifacts = manifest.get("artifacts", {})
    old = artifacts.pop("s06_api", None)
    if old and old in _S06_ARTIFACT_TO_PROVIDER:
        config = manifest.setdefault("config", {}).setdefault("s06_api", {})
        config.setdefault("provider", _S06_ARTIFACT_TO_PROVIDER[old])
    return manifest
```

Called once in `load_manifest()` before dispatching to the
stage factories. Emits a `manifest.migrated` event when the
shim fires so integration tests can pin when it's running vs.
not. Targeted for removal in a follow-up cycle once all
committed manifests are re-exported.

### 4.7 `PipelineBuilder` / `attach_runtime` defaults

PR-3 path (2) — `_build_default_client` falling back to the
s06 provider — **deletes** in PR-4, because s06 no longer owns
a provider to fall back to. The fallback becomes:

1. Explicit `attach_runtime(llm_client=...)` → used verbatim.
2. Otherwise construct
   `ClientRegistry.get(s06_stage.get_config()["provider"])(
       api_key=s06_stage._api_key,
       base_url=s06_stage._base_url,
   )`. This is the same client s06 would build itself via
   `_resolve_client`, materialized once at `attach_runtime`
   time and shared with memory stages.

`tests/llm_client/test_s06_bridge.py` (marked
`deprecated_in_pr4` in PR-3) **deletes** here.

## 5. Compat risks & mitigations

### 5.1 External subclasses of `APIProvider`

Downstream code outside this repo could subclass
`APIProvider` to plug in a custom provider. PR-4 deletes the
interface. Mitigation: the migration note in the PR description
says "subclass `BaseClient` from `geny_executor.llm_client`
instead; register via `ClientRegistry.register('your_name', ...)`".
No runtime shim — the breakage is intentional and the fix is
one-line.

### 5.2 Imports of `geny_executor.stages.s06_api.types`

Already covered by the re-export shim in PR-3, which PR-4 now
deletes. Any test that still uses the old path breaks. Fix is
mechanical: find-and-replace the import. A
`scripts/migrate_imports_pr4.sh` shipped in the PR does the
rewrite for any vendored copy.

### 5.3 Imports of `geny_executor.stages.s06_api.interface.APIProvider`

Same pattern — rewritten to
`from geny_executor.llm_client import BaseClient`. The only
in-repo consumers are the files PR-4 deletes.

### 5.4 Test doubles

Any test that monkeypatches
`geny_executor.stages.s06_api.artifact.default.providers.AnthropicProvider`
breaks. Migration: the new path is
`geny_executor.llm_client.anthropic.AnthropicClient`. The
fixtures file (`tests/fixtures/mock_clients.py`) centralizes
the usual doubles so most test edits are one-line import
rewrites.

## 6. Tests

### 6.1 Restructure existing `tests/stages/test_s06_api.py`

- Replace every `provider=MockProvider(...)` argument with
  `attach_runtime(llm_client=MockClient(...))` on the
  surrounding pipeline fixture.
- Replace `APIStage(provider=AnthropicProvider(api_key="..."))`
  with `APIStage(provider="anthropic", api_key="...")`.
- Keep every behavioral assertion intact — input/output
  invariants are unchanged.

### 6.2 New `tests/stages/test_s06_provider_selection.py`

Covers the new `provider` config axis:

- `test_default_provider_is_anthropic` — `APIStage()` (no
  kwargs) has `get_config()["provider"] == "anthropic"`.
- `test_provider_openai_constructs_openai_client` — stub
  `ClientRegistry.get("openai")` to return a sentinel class;
  assert `_resolve_client` returns a sentinel instance.
- `test_provider_vllm_requires_base_url` — construction with
  `provider="vllm"` and no `base_url` raises a helpful error
  at first-use time (not at construction, to allow late-bind).
- `test_unknown_provider_fails_with_listed_options` — the
  error message names the four registered providers.
- `test_update_config_switches_provider` — change
  `provider="anthropic"` → `"openai"` via `update_config`;
  next `_resolve_client` call returns a new (OpenAI) client.

### 6.3 Parity tests `tests/stages/test_s06_parity.py`

Before deleting `AnthropicProvider`, capture a set of fixture
replays (already available in `tests/fixtures/anthropic/*.json`
— the same recordings `RecordingProvider` produced) and assert
that `AnthropicClient` (new) produces the same canonical
`APIResponse` for each fixture.

The parity harness is a parametrized test:

```python
@pytest.mark.parametrize("fixture", ANTHROPIC_FIXTURES)
async def test_anthropic_parity(fixture):
    request = APIRequest(**fixture["request"])
    old_response = await _OldAnthropicProvider().create_message(request)
    new_response = await AnthropicClient()._send(request)
    assert old_response == new_response
```

`_OldAnthropicProvider` is a frozen copy of the pre-PR-4
implementation vendored into `tests/fixtures/legacy/anthropic_provider.py`
for this one test file. When PR-4 merges, the parity test
stays in tree for one cycle as a regression guard, then the
legacy copy deletes.

Same pattern for `test_openai_parity.py`,
`test_google_parity.py`. vLLM has no fixture recordings yet —
its parity test uses `MockClient` until a recording is captured.

### 6.4 Retry wrapper test

- `test_retry_wraps_client_call_not_provider` — the retry
  wrapper receives a `BaseClient`, not an `APIProvider`.
  Simulate an `APIError(category=RATE_LIMITED)` from the
  client's `create_message`; assert `attempt` count and the
  `api.retry` events emitted match the pre-PR-4 behavior.

### 6.5 Manifest migration test

- `test_manifest_with_old_s06_artifact_name_loads_as_provider`
  — a manifest with `"artifacts": {"s06_api": "openai"}`
  still loads and the resulting `APIStage` has
  `get_config()["provider"] == "openai"`. Assert a
  `manifest.migrated` event fired.

## 7. Performance & cost impact

- No new per-call overhead. `_resolve_client` is a one-time
  state read (or a lazy construction that caches). Retry
  wrapper unchanged.
- Saving: two call sites collapse to one
  (`AnthropicProvider.create_message` + `AnthropicClient.
  create_message` → just the latter). Fewer bytes loaded,
  fewer import cycles to resolve at startup.

## 8. Acceptance criteria

- `src/geny_executor/stages/s06_api/artifact/` does not exist.
- `APIProvider` symbol does not exist anywhere in the repo
  (grep for it must return zero hits).
- `APIStage.__init__` accepts `provider: str = "anthropic"`,
  `api_key`, `base_url`, `default_headers`, and builds its
  own fallback client via `ClientRegistry`.
- `APIStage.execute` routes through `state.llm_client` when
  set, fallback otherwise.
- `StrategySlot("provider", ...)` is gone from `APIStage`;
  only `StrategySlot("retry", ...)` remains.
- `tests/stages/test_s06_api.py` updated and passing.
- `tests/stages/test_s06_provider_selection.py` new, passing.
- Parity suite in `tests/stages/test_s06_parity.py` passes
  for Anthropic / OpenAI / Google.
- Manifest migration test passes.
- `pytest tests/ -v` is green overall.
- Existing `tests/llm_client/test_s06_bridge.py` from PR-3 is
  deleted.
- `scripts/migrate_imports_pr4.sh` exists and is executable.

## 9. File map

Files **created**:

- `src/geny_executor/stages/s06_api/stage.py` (top-level, new
  — replaces `artifact/default/stage.py`).
- `src/geny_executor/stages/s06_api/retry.py` — pulled up
  from `artifact/default/retry.py`; adds `RetryStrategy` ABC
  from the old `interface.py`.
- `tests/stages/test_s06_provider_selection.py`
- `tests/stages/test_s06_parity.py`
- `tests/fixtures/mock_clients.py` — `MockClient`,
  `RecordingClient`, `RecordingReplayClient`.
- `tests/fixtures/legacy/anthropic_provider.py` — vendored
  frozen copy for parity.
- `scripts/migrate_imports_pr4.sh` — find-and-replace helper.

Files **deleted**:

- `src/geny_executor/stages/s06_api/artifact/` (entire tree).
- `src/geny_executor/stages/s06_api/interface.py` (content
  survives in `retry.py`; the file itself goes).
- `src/geny_executor/stages/s06_api/_translate.py`
- `src/geny_executor/stages/s06_api/types.py` (was a re-export
  shim from PR-3).
- `tests/llm_client/test_s06_bridge.py` (PR-3 bridge path).

Files **modified**:

- `src/geny_executor/core/pipeline.py` — remove the s06-backed
  fallback in `_build_default_client`; replace with
  registry-based construction.
- `src/geny_executor/core/pipeline_builder.py` (or
  `core/manifest.py`, wherever `load_manifest` lives) — add
  `_migrate_s06_manifest` and call it from the loader.
- `tests/stages/test_s06_api.py` — switch to the new
  construction and `state.llm_client` patterns.
- Any test file that imported from
  `geny_executor.stages.s06_api.types` or
  `geny_executor.stages.s06_api.interface` — rewritten to
  `geny_executor.llm_client.*`. Mechanical, scripted.
