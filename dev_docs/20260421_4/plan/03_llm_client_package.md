# Plan 03 — PR-3: `geny_executor/llm_client/` package

**Repo.** `/home/geny-workspace/geny-executor`
**Branch.** `feat/llm-client-package`
**Depends on.** PR-1 (state shape: the new `state.llm_client` slot
lives alongside `state.shared`), PR-2 (`resolve_model_config` is
what every `BaseClient.create_message` call receives). Merge order
PR-1 → PR-2 → PR-3.
**Blocks.** PR-4 (s06_api migration removes the artifact providers
and rewires onto this package), PR-5 (memory stages read
`state.llm_client`).
**Related analysis.**
- Analysis 01 §7 — `AnthropicProvider` is the only production
  provider today; §10 — `attach_runtime` signature; §11 — Geny
  bypass path in `_make_llm_reflect_callback`.
- Analysis 02 §3 — three parallel LLM shapes (AnthropicProvider,
  AsyncAnthropic, ChatAnthropic) that this PR unifies.
- Analysis 03 §8 — `state.llm_client` is optional (not every stage
  uses a model); injection is for extensibility.

## 1. Goal

Create a first-class `geny_executor/llm_client/` package that
is the **one** way any stage reaches for an LLM. Every vendor
adapter (Anthropic, OpenAI, Google, vLLM) inherits from a single
`BaseClient` abstract class, so call sites look identical
regardless of provider:

```python
response = await state.llm_client.create_message(
    model_config=cfg,
    messages=[...],
    system="...",
    purpose="memory.summarize",
)
```

PR-3 is **additive** — it creates the package, the abstract,
the four concrete clients, a registry, and wires the
`state.llm_client` slot + `attach_runtime(llm_client=...)` hook.
It does **not** touch `s06_api/artifact/*`. s06_api's existing
`APIProvider`-strategy path keeps working unchanged. PR-4 is
where s06_api flips over and the old artifact directories
delete.

For the bridging window between PR-3 and PR-4, the
`AnthropicProvider` already-constructed inside `s06_api` is
used to back `state.llm_client` automatically when no explicit
client is attached, so memory-side prototypes (ahead of PR-5)
and the fallback in PR-6 can rely on a non-None client.

## 2. Why

Three bugs in index.md roll up into one: a stage that wants an
LLM today has to choose between three incompatible shapes
(`APIProvider` inside s06_api, `AsyncAnthropic` in Geny's
`_make_llm_reflect_callback`, `ChatAnthropic` in
`reflect_utils.py`). Nobody can write portable stage code.

Design principles:

- **One surface, many vendors.** A stage writes to the
  `BaseClient` contract — the concrete vendor is picked by
  config (`provider="anthropic"` / `"openai"` / `"google"` /
  `"vllm"`) and the stage never imports a vendor SDK.
- **Structural uniformity.** Every `BaseClient` subclass
  exposes the same methods (`create_message`,
  `create_message_stream`), the same inputs (`ModelConfig` +
  canonical messages), the same output (`APIResponse`). The
  `_translate.py` work already done in s06_api is moved into
  the package so canonical↔vendor conversion lives exactly
  where each client needs it.
- **Capabilities are data, not exceptions.** A `VLLMClient`
  asked for `thinking_enabled=True` doesn't blow up — it
  emits a `llm_client.feature_unsupported` event and drops
  the field. `ClientCapabilities` flags make the contract
  introspectable.
- **Optional slot.** `state.llm_client: Optional[BaseClient]`
  is None for pipelines that don't run an LLM (batch-only
  manifests, pure-parse pipelines). Stages that need a
  client assert at execute-time, not at construction-time.

## 3. Non-goals

- **No s06_api migration.** PR-3 leaves `s06_api/artifact/*`
  untouched. PR-4 deletes those directories and rewires
  `APIStage` onto `state.llm_client`.
- **No new stage callers.** PR-5 is where s02/s15 actually
  call `state.llm_client`. PR-3 ends at plumbing + unit tests.
- **No Geny rewire.** PR-6 swaps Geny's `_make_llm_reflect_callback`
  for `ClientRegistry.get(api_config.provider)`. PR-3 only
  adds the registry.
- **No cost accounting.** Every call carries a `purpose: str`
  label; aggregating by purpose is a follow-up cycle.
- **No reasoning-feature parity across vendors.** OpenAI's
  `reasoning_effort` and Google's equivalents are out of
  scope — `thinking_*` fields map to the Anthropic contract
  only. Non-Anthropic clients drop them with an event.
- **No retry-policy rework.** `BaseClient.create_message` is
  single-shot; `s06_api`'s `RetryStrategy` wraps its calls at
  the stage level. Memory stages won't retry in PR-5.
  A future cycle can move retry into the client.

## 4. Package layout

```
src/geny_executor/llm_client/
├── __init__.py               # re-exports BaseClient, ClientCapabilities,
│                             # ClientRegistry, get_default_client
├── base.py                   # BaseClient abstract + ClientCapabilities
├── registry.py               # ClientRegistry (provider name → class)
├── types.py                  # canonical request/response types, moved
│                             #  from s06_api/types.py (APIRequest,
│                             #  APIResponse, ContentBlock). s06_api
│                             #  re-exports for back-compat until PR-4.
├── events.py                 # event names + payload dataclasses
│                             # (llm_client.feature_unsupported, ...)
├── errors.py                 # shared error classification helpers
│                             # (extracted from AnthropicProvider's
│                             #  _classify_error; vendors override for
│                             #  their own SDK exception types)
├── anthropic.py              # AnthropicClient(BaseClient)
├── openai.py                 # OpenAIClient(BaseClient)
├── google.py                 # GoogleClient(BaseClient)
├── vllm.py                   # VLLMClient(OpenAIClient subclass)
└── translators/              # canonical ↔ vendor converters
    ├── __init__.py
    ├── anthropic.py          # (canonical is already Anthropic-shaped,
    │                         #  so this is mostly identity + thinking
    │                         #  field massage)
    ├── openai.py             # pulled from s06_api/_translate.py
    └── google.py             # pulled from s06_api/_translate.py
```

Notes:

- `types.py` gets `APIRequest`, `APIResponse`, `ContentBlock`
  moved out of `s06_api/types.py`. `s06_api/types.py` becomes
  a thin re-export (`from geny_executor.llm_client.types import *`)
  until PR-4 deletes it. This keeps every current import of
  `from geny_executor.stages.s06_api.types import APIRequest`
  working during the PR-3→PR-4 bridge.
- `translators/` collapses the current `s06_api/_translate.py`
  (15 KB, canonical↔vendor conversion for OpenAI/Google) into
  per-vendor files alongside the client that uses them.
- `events.py` uses the stage-logging vocabulary from cycle
  20260421_3. Events emitted by clients look like
  `{"type": "llm_client.feature_unsupported", "provider":
  "openai", "field": "thinking_enabled"}` and ride the same
  `state.log_stream` pipe.

## 5. Core types

### 5.1 `BaseClient` abstract

`llm_client/base.py`:

```python
"""Base class for every LLM client.

Implementations adapt a vendor SDK to the canonical APIRequest /
APIResponse shape. Every BaseClient MUST:

  - Accept a ``ModelConfig`` + canonical messages and run the vendor
    call without the caller needing to know which vendor is in use.
  - Drop unsupported fields rather than raising, emitting a
    ``llm_client.feature_unsupported`` event on ``event_sink`` if one
    was provided.
  - Translate vendor exceptions into ``geny_executor.core.errors.APIError``
    with a populated ``ErrorCategory`` so upstream retry/classify logic
    doesn't need to branch on vendor.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from geny_executor.core.config import ModelConfig
from geny_executor.llm_client.types import APIRequest, APIResponse


@dataclass(frozen=True)
class ClientCapabilities:
    """Feature flags a client advertises. Stage code inspects these
    before calling fields that not every vendor supports."""

    supports_thinking: bool = False
    supports_tools: bool = False
    supports_streaming: bool = True
    supports_tool_choice: bool = False
    supports_stop_sequences: bool = True
    supports_top_k: bool = False
    supports_system_prompt: bool = True
    # Aggregated list of fields this client will silently drop if given
    drops: tuple[str, ...] = field(default=())


class BaseClient(ABC):
    """Abstract LLM client. Concrete subclasses live in this package."""

    #: Provider name (stable identifier used by ClientRegistry).
    provider: str = ""

    #: Capabilities advertised by this client. Subclasses override.
    capabilities: ClientCapabilities = ClientCapabilities()

    def __init__(
        self,
        api_key: str = "",
        base_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        event_sink: Optional[Any] = None,  # callable or None
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._default_headers = default_headers
        self._event_sink = event_sink

    # ------------------------------------------------------------------
    # High-level surface used by stages
    # ------------------------------------------------------------------
    async def create_message(
        self,
        *,
        model_config: ModelConfig,
        messages: List[Dict[str, Any]],
        system: Any = "",
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        purpose: str = "",
    ) -> APIResponse:
        """Send a non-streaming request built from a ModelConfig."""
        request = self._build_request(
            model_config=model_config,
            messages=messages,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            stream=False,
        )
        return await self._send(request, purpose=purpose)

    async def create_message_stream(
        self,
        *,
        model_config: ModelConfig,
        messages: List[Dict[str, Any]],
        system: Any = "",
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        purpose: str = "",
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming variant. Default: fall back to non-streaming.

        Overridden by AnthropicClient/OpenAIClient to use vendor streams.
        """
        response = await self.create_message(
            model_config=model_config,
            messages=messages,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            purpose=purpose,
        )
        yield {"type": "message_complete", "response": response}

    # ------------------------------------------------------------------
    # Low-level surface — kept for s06_api parity during PR-3→PR-4 bridge
    # ------------------------------------------------------------------
    @abstractmethod
    async def _send(self, request: APIRequest, *, purpose: str = "") -> APIResponse:
        """Send a pre-built APIRequest. Subclasses implement vendor call."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_request(
        self,
        *,
        model_config: ModelConfig,
        messages: List[Dict[str, Any]],
        system: Any,
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Dict[str, Any]],
        stream: bool,
    ) -> APIRequest:
        """Assemble a canonical APIRequest. Emits feature_unsupported
        events for any field in ``model_config`` that this client drops."""
        request = APIRequest(
            model=model_config.model,
            messages=list(messages),
            max_tokens=model_config.max_tokens,
            system=system,
            temperature=model_config.temperature,
            top_p=model_config.top_p,
            top_k=model_config.top_k,
            tools=tools,
            tool_choice=tool_choice,
            stop_sequences=(
                list(model_config.stop_sequences)
                if model_config.stop_sequences
                else None
            ),
            stream=stream,
        )
        if model_config.thinking_enabled:
            if self.capabilities.supports_thinking:
                thinking: Dict[str, Any] = {"type": model_config.thinking_type}
                if model_config.thinking_type == "enabled":
                    thinking["budget_tokens"] = model_config.thinking_budget_tokens
                if model_config.thinking_display:
                    thinking["display"] = model_config.thinking_display
                request.thinking = thinking
            else:
                self._emit_unsupported("thinking_enabled")

        if model_config.top_k is not None and not self.capabilities.supports_top_k:
            request.top_k = None
            self._emit_unsupported("top_k")

        if tool_choice and not self.capabilities.supports_tool_choice:
            self._emit_unsupported("tool_choice")

        return request

    def _emit_unsupported(self, field: str) -> None:
        if self._event_sink is None:
            return
        self._event_sink(
            {
                "type": "llm_client.feature_unsupported",
                "provider": self.provider,
                "field": field,
            }
        )

    # Configuration knob for vendor SDK construction.
    def configure(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
```

Key points:

- `create_message` accepts a `ModelConfig` directly (output of
  `stage.resolve_model_config(state)`), no `APIRequest`
  boilerplate at the call site.
- `_build_request` is shared by every subclass. It runs the
  capability-filtering logic in one place; vendors only
  implement `_send` + `_parse_response` + `_classify_error`.
- `_send` stays as the low-level hook so `s06_api`'s existing
  `APIStage.execute` (which already builds an `APIRequest`)
  can switch over in PR-4 without changing its request-building
  code path.

### 5.2 `ClientCapabilities` defaults per vendor

| Client           | thinking | tools | streaming | tool_choice | top_k | stop_sequences |
|---               |---       |---    |---        |---          |---    |---             |
| AnthropicClient  | ✅       | ✅    | ✅        | ✅          | ✅    | ✅             |
| OpenAIClient     | ❌       | ✅    | ✅        | ✅          | ❌    | ✅             |
| GoogleClient     | ❌       | ✅    | ✅        | ✅ (partial)| ✅    | ✅             |
| VLLMClient       | ❌       | ✅ *  | ✅        | ✅ *        | ❌    | ✅             |

`*` — vLLM server must be started with a tool-calling-capable
model for these to work; otherwise the flag is `False` at
runtime (see §6.4).

### 5.3 `ClientRegistry`

`llm_client/registry.py`:

```python
"""Provider-name → client-class lookup with lazy imports.

Each adapter's vendor SDK is optional — ``AnthropicClient`` is the only
client whose SDK is a hard dependency of geny-executor. Others are
lazily imported so a user installing only the anthropic extras isn't
forced to pip-install google-generativeai.
"""
from __future__ import annotations

from typing import Callable, Dict, Type

from geny_executor.llm_client.base import BaseClient


class ClientRegistry:
    _factories: Dict[str, Callable[[], Type[BaseClient]]] = {}

    @classmethod
    def register(cls, provider: str, factory: Callable[[], Type[BaseClient]]) -> None:
        cls._factories[provider] = factory

    @classmethod
    def get(cls, provider: str) -> Type[BaseClient]:
        if provider not in cls._factories:
            raise ValueError(
                f"Unknown LLM client provider: {provider!r}. "
                f"Registered: {sorted(cls._factories)}"
            )
        return cls._factories[provider]()

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._factories)


def _anthropic_factory() -> Type[BaseClient]:
    from geny_executor.llm_client.anthropic import AnthropicClient
    return AnthropicClient


def _openai_factory() -> Type[BaseClient]:
    try:
        from geny_executor.llm_client.openai import OpenAIClient
    except ImportError as e:
        raise ImportError(
            "OpenAI client requires the 'openai' package. "
            "Install with: pip install geny-executor[openai]"
        ) from e
    return OpenAIClient


def _google_factory() -> Type[BaseClient]:
    try:
        from geny_executor.llm_client.google import GoogleClient
    except ImportError as e:
        raise ImportError(
            "Google client requires 'google-generativeai'. "
            "Install with: pip install geny-executor[google]"
        ) from e
    return GoogleClient


def _vllm_factory() -> Type[BaseClient]:
    # vLLM uses the OpenAI SDK pointed at a local base_url.
    from geny_executor.llm_client.vllm import VLLMClient
    return VLLMClient


ClientRegistry.register("anthropic", _anthropic_factory)
ClientRegistry.register("openai", _openai_factory)
ClientRegistry.register("google", _google_factory)
ClientRegistry.register("vllm", _vllm_factory)
```

Call sites use `ClientRegistry.get(provider)(api_key=..., base_url=...)`.
The registry is deliberately side-effect-free at import time
except for the four `register(...)` lines; vendor SDKs are
imported inside the factory, not at module top level.

## 6. Concrete clients

### 6.1 `AnthropicClient`

`llm_client/anthropic.py` is a near-verbatim copy of
`s06_api/artifact/default/providers.py` `AnthropicProvider`
(the code in §4 of this plan's repo audit), restructured to:

- inherit from `BaseClient` instead of `APIProvider`;
- set `provider = "anthropic"` and the full-caps
  `ClientCapabilities`;
- move `_build_kwargs` body into `_send`;
- keep `_parse_response` and `_classify_error` byte-identical.

During the PR-3→PR-4 bridge, `s06_api`'s
`AnthropicProvider` keeps existing (the artifact directories
are still present). The `AnthropicProvider` is what
`get_default_client` falls back to (see §7.2) so the bridge
is transparent.

### 6.2 `OpenAIClient`

`llm_client/openai.py` re-homes the OpenAI provider that
lives today under `s06_api/artifact/openai/providers.py`.
It uses `llm_client/translators/openai.py` (= content of
`s06_api/_translate.py:to_openai_*`/`from_openai_*`) for the
canonical↔vendor conversion.

Capability profile: no thinking, no top_k; everything else
supported.

### 6.3 `GoogleClient`

Same pattern as OpenAI — `s06_api/artifact/google/providers.py`
+ `s06_api/_translate.py:to_google_*` move into the package.
Capability profile: no thinking; top_k supported; partial
`tool_choice` support (Google's function-call mode maps to
`auto`/`any`/`none` only).

### 6.4 `VLLMClient`

vLLM exposes an **OpenAI-compatible** REST surface, so
`VLLMClient` is an `OpenAIClient` subclass with:

- `provider = "vllm"`,
- a required `base_url` (no public SaaS endpoint),
- capability flags that DO NOT assume tool-calling by default
  (resolved at runtime from a `capabilities_probe` config key —
  see test §8.4).

Users configure vLLM via:

```python
client = ClientRegistry.get("vllm")(
    api_key="EMPTY",
    base_url="http://localhost:8000/v1",
)
```

## 7. Integration into the pipeline

### 7.1 `PipelineState.llm_client`

`src/geny_executor/core/state.py` grows one field:

```python
@dataclass
class PipelineState:
    # ...existing fields...

    # Runtime-only: injected by Pipeline.attach_runtime. None when the
    # pipeline has not attached a client (batch / parse-only pipelines).
    llm_client: Optional["BaseClient"] = field(default=None, repr=False)
```

Typing note: `BaseClient` is forward-referenced as a string
to avoid an import cycle (core → llm_client → core.config).

`PipelineState.copy()` must carry the `llm_client` reference
forward unchanged (no deep copy — it's a long-lived object
with network connections). Tests pin this (§8.2).

### 7.2 `Pipeline.attach_runtime(..., llm_client=None)`

`src/geny_executor/core/pipeline.py` gains one param:

```python
def attach_runtime(
    self,
    *,
    session_id: str,
    api_key: str,
    llm_client: Optional[BaseClient] = None,
    **kwargs: Any,
) -> None:
    # ...existing behavior...
    if llm_client is None:
        llm_client = self._build_default_client()
    self._state.llm_client = llm_client
```

`_build_default_client` prefers, in order:

1. An **explicitly passed** `llm_client` — used verbatim.
2. The `AnthropicProvider` already constructed by s06_api
   (pre-PR-4 bridge): wrap it in a tiny
   `ProviderBackedClient(BaseClient)` adapter that forwards
   `_send` to `provider.create_message`. This means Geny's
   existing `Pipeline.attach_runtime(...)` calls (no
   `llm_client=` kwarg) automatically get a working client
   backed by the same Anthropic SDK instance s06_api uses,
   with zero re-config.
3. If s06_api isn't present (custom pipelines): construct
   `AnthropicClient(api_key=api_key)` directly.

Path (2) deletes in PR-4 — after the migration, s06_api no
longer owns an `AnthropicProvider`; the default-client fallback
becomes just path (3).

### 7.3 `__init__.py` exports

`geny_executor/llm_client/__init__.py`:

```python
from geny_executor.llm_client.base import BaseClient, ClientCapabilities
from geny_executor.llm_client.registry import ClientRegistry
from geny_executor.llm_client.types import APIRequest, APIResponse, ContentBlock

__all__ = [
    "BaseClient",
    "ClientCapabilities",
    "ClientRegistry",
    "APIRequest",
    "APIResponse",
    "ContentBlock",
]
```

Top-level `geny_executor/__init__.py` re-exports `BaseClient`
and `ClientRegistry` for ergonomics (same as current top-level
exports for `Pipeline`, `Stage`, `ModelConfig`).

### 7.4 Back-compat re-exports in `s06_api/types.py`

After the move, the file becomes:

```python
"""Kept as re-export shim until PR-4 removes the s06_api artifact path.
New code should import from geny_executor.llm_client.types.
"""
from geny_executor.llm_client.types import (
    APIRequest,
    APIResponse,
    ContentBlock,
)

__all__ = ["APIRequest", "APIResponse", "ContentBlock"]
```

PR-4 deletes the file entirely and bumps callers to the new
import path.

## 8. Tests

New test tree: `tests/llm_client/`.

### 8.1 `test_base_client.py` — capability filtering

- `test_drops_thinking_when_not_supported` — a fake client with
  `capabilities.supports_thinking = False` + a `ModelConfig`
  with `thinking_enabled=True` → request built has
  `thinking is None`, event sink received one
  `llm_client.feature_unsupported` with `field="thinking_enabled"`.
- `test_keeps_thinking_when_supported` — same but
  `supports_thinking=True` → request has a populated
  `thinking` dict; no event emitted.
- `test_drops_top_k_when_not_supported` — same pattern.
- `test_builds_request_with_all_model_config_fields` — round
  trip via a minimal fake `_send` that echoes the request.

### 8.2 `test_state_slot.py` — state integration

- `test_state_llm_client_default_none` — a fresh
  `PipelineState()` has `llm_client is None`.
- `test_state_copy_carries_llm_client_reference` — copy/clone
  must NOT re-instantiate; client is the same object by identity.
- `test_attach_runtime_accepts_explicit_client` — passing
  `llm_client=X` to `attach_runtime` stores it verbatim on state.
- `test_attach_runtime_falls_back_to_s06_provider` — pipeline
  built with no explicit client + s06_api stage → state gets a
  `ProviderBackedClient` whose `_send` path reaches the
  s06_api-owned `AnthropicProvider`.
- `test_attach_runtime_constructs_anthropic_when_no_s06` —
  minimal pipeline (no s06_api) + api_key only → state gets a
  bare `AnthropicClient`.

### 8.3 `test_registry.py` — registry behavior

- `test_get_returns_anthropic_class` — always present.
- `test_get_openai_raises_on_missing_dep` — simulate missing
  `openai` module (use `monkeypatch` on `sys.modules`) → the
  factory raises `ImportError` with the pip extras hint.
- `test_unknown_provider_raises_value_error` — lists
  registered names in the message.
- `test_register_new_provider` — user can add a fifth provider.

### 8.4 `test_clients_parity/` — per-vendor parity

Four sibling files, each a near-mirror of the others.
Structure:

```
tests/llm_client/test_clients_parity/
├── __init__.py
├── fixtures/
│   ├── anthropic_response.json
│   ├── openai_response.json
│   └── google_response.json
├── test_anthropic.py
├── test_openai.py
├── test_google.py
└── test_vllm.py
```

Per-vendor tests cover:

- `_build_request` fills the vendor-specific request shape
  correctly (from a recorded fixture).
- `_parse_response` returns a canonical `APIResponse` whose
  `.text`, `.tool_calls`, `.thinking_blocks` all match the
  fixture.
- `_classify_error` maps each vendor SDK's exception type to
  the correct `ErrorCategory`.

No network calls — every test uses fixture replay.

### 8.5 `test_s06_bridge.py` — the PR-3-only bridge path

- Build a pipeline that has `s06_api` (with its existing
  `AnthropicProvider`) and call `attach_runtime()` without
  `llm_client=`. Assert `state.llm_client is not None` and
  `await state.llm_client.create_message(model_config=cfg,
  messages=[...])` routes through the s06_api provider
  (verify via a `MockProvider` injected into s06_api).
- **This test DELETES in PR-4** (the bridge path goes away
  when the artifacts delete). It's marked with a
  `@pytest.mark.deprecated_in_pr4` decorator so the PR-4
  author knows which tests to reap.

## 9. Performance & cost impact

- Client objects are constructed once per `attach_runtime`
  and reused across stages. No per-call instantiation.
- `_build_request` is a thin dataclass build + a handful of
  capability checks. Negligible vs. network round trip.
- `_emit_unsupported` fires only when a user configures a
  feature a vendor doesn't support. Rate-limited by the
  frequency of config; not a per-call cost.
- PR-3 does not add any new LLM calls — the default client
  exists but nothing in the pipeline calls it until PR-5.

## 10. Risks

1. **Bridge path `ProviderBackedClient` is load-bearing for
   exactly one PR.** If someone lands a change to s06_api
   between PR-3 and PR-4 that changes the shape of
   `AnthropicProvider.create_message`, the bridge breaks.
   Mitigation: PR-3 tests (`test_s06_bridge`) import
   `AnthropicProvider` and assert its method signature; any
   change would fail the bridge tests before review.
2. **`state.llm_client: Optional[BaseClient]` is a new hot
   cache field.** `PipelineState.copy()` already carries
   forward by-reference for runtime-injected fields
   (`api_key`, `session_id`); adding one more reference is
   safe but the copy path gains a line.
3. **Optional-import pattern in `ClientRegistry` factories.**
   If a user types `ClientRegistry.get("openai")` without the
   extras installed, they get an `ImportError` at lookup
   time, not at application start. Trade-off: start-up
   independence vs. late failure. Mitigation: the error
   message names the exact pip extras command.
4. **Moving `APIRequest`/`APIResponse` out of `s06_api/types.py`.**
   External callers (tests, custom stages) importing from the
   old path keep working via the re-export shim. PR-4 is
   the breakage boundary; a migration note goes in the PR-4
   changelog.
5. **`event_sink` wiring.** `state.log_stream` is the
   intended sink, but `BaseClient` is constructed in
   `attach_runtime` before `state.log_stream` is guaranteed
   populated. Mitigation: `_emit_unsupported` is None-safe;
   tests verify that a client constructed with
   `event_sink=None` is fully functional (just silently
   drops events).

## 11. Acceptance criteria

- `geny_executor/llm_client/` package exists with the layout in §4.
- `BaseClient` is abstract; `AnthropicClient` / `OpenAIClient` /
  `GoogleClient` / `VLLMClient` each inherit from it and set
  `provider` + `capabilities` appropriately.
- `ClientRegistry.get(name)` returns the right class for each
  of `"anthropic"`, `"openai"`, `"google"`, `"vllm"`.
- `state.llm_client` exists as `Optional[BaseClient]`, default None.
- `Pipeline.attach_runtime(llm_client=...)` stores the client on
  state; default falls back to the s06_api provider when no
  explicit client is passed.
- All tests in §8 pass: `pytest tests/llm_client -v`.
- Existing `tests/stages/test_s06_api.py` still passes (s06_api
  untouched in PR-3).
- No change to any stage's `StageIntrospection.model_override_supported`.
- `APIRequest`/`APIResponse`/`ContentBlock` imports from
  `geny_executor.stages.s06_api.types` keep working via shim.

## 12. File map

Files **created**:

- `src/geny_executor/llm_client/__init__.py`
- `src/geny_executor/llm_client/base.py` — `BaseClient`,
  `ClientCapabilities`
- `src/geny_executor/llm_client/registry.py` — `ClientRegistry`
- `src/geny_executor/llm_client/types.py` — moved from
  `s06_api/types.py`
- `src/geny_executor/llm_client/events.py`
- `src/geny_executor/llm_client/errors.py`
- `src/geny_executor/llm_client/anthropic.py` — `AnthropicClient`
- `src/geny_executor/llm_client/openai.py` — `OpenAIClient`
- `src/geny_executor/llm_client/google.py` — `GoogleClient`
- `src/geny_executor/llm_client/vllm.py` — `VLLMClient`
- `src/geny_executor/llm_client/translators/{__init__,anthropic,openai,google}.py`
- `tests/llm_client/test_base_client.py`
- `tests/llm_client/test_state_slot.py`
- `tests/llm_client/test_registry.py`
- `tests/llm_client/test_s06_bridge.py`
- `tests/llm_client/test_clients_parity/{anthropic,openai,google,vllm}.py`
  + fixtures

Files **modified**:

- `src/geny_executor/core/state.py` — add
  `llm_client: Optional[BaseClient]` field.
- `src/geny_executor/core/pipeline.py` — `attach_runtime`
  gains `llm_client` kwarg + default-client fallback.
- `src/geny_executor/__init__.py` — re-export `BaseClient`,
  `ClientRegistry`.
- `src/geny_executor/stages/s06_api/types.py` — becomes
  re-export shim.

Files **NOT modified** (deliberately — that's PR-4's scope):

- `src/geny_executor/stages/s06_api/artifact/default/providers.py`
- `src/geny_executor/stages/s06_api/artifact/openai/providers.py`
- `src/geny_executor/stages/s06_api/artifact/google/providers.py`
- `src/geny_executor/stages/s06_api/interface.py` (`APIProvider`
  stays alive through PR-3)
- `src/geny_executor/stages/s06_api/stage.py`
- `src/geny_executor/stages/s06_api/_translate.py` (translator
  copy lives in both places during the bridge; PR-4 deletes
  the s06_api copy)
