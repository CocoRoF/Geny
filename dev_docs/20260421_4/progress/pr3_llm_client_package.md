# PR-3 progress — llm_client package scaffold

- Branch: `feat/llm-client-package`
- Base: `feat/stage-resolve-model-config` (PR #38, PR-2)
- Upstream PR: https://github.com/CocoRoF/geny-executor/pull/39
- Commit: `239640c feat(llm_client): unified client package + state slot + s06 bridge`
- Plan: `Geny/dev_docs/20260421_4/plan/03_llm_client_package.md`

## What shipped

New `src/geny_executor/llm_client/` package — the canonical LLM client
surface for the whole 16-stage pipeline, independent of `stages/s06_api`:

- `types.py` — `APIRequest` / `APIResponse` / `ContentBlock` moved here from
  `stages/s06_api/types.py`. The s06_api module is now a re-export shim.
- `base.py` — `BaseClient` (ABC) + `ClientCapabilities` (frozen dataclass,
  7 boolean flags + `drops` tuple). `create_message` /
  `create_message_stream` build an `APIRequest`, silently drop unsupported
  fields, emit `llm_client.feature_unsupported` events on the optional
  `event_sink` callback, then delegate to abstract `_send`.
- `registry.py` — `ClientRegistry` class with `_factories`, `register`,
  `get`, `available`. Built-in lazy factories for
  `anthropic` / `openai` / `google` / `vllm`. Raises `ValueError` on
  unknown provider (lists the registered names in the error).
- `anthropic.py` / `openai.py` / `google.py` / `vllm.py` — vendor-specific
  clients. Body ported verbatim from `stages/s06_api/artifact/*/provider.py`
  for behavior parity. `VLLMClient` inherits from `OpenAIClient`, enforces
  `base_url`, and exposes `configure_capabilities(**overrides)` for local
  models that support tools / top_k / thinking.
- `translators/__init__.py` — thin re-export layer over
  `stages/s06_api/_translate` so vendor clients (openai / google / vllm)
  don't have to cross-import from s06_api directly. PR-4 inverts this
  (translators live in llm_client; s06_api imports from there).
- `bridge.py` — `ProviderBackedClient` wraps an s06_api `APIProvider` as a
  `BaseClient`. Auto-selects capabilities from `provider.name`
  (`anthropic` / `openai` / `google` / fallback for `mock` etc.).
  This is the compatibility shim that lets existing pipelines
  get a `state.llm_client` value even before PR-4 lands.

Wiring:

- `PipelineState.llm_client: Optional[Any] = None` — new slot.
- `Pipeline.attach_runtime(llm_client=...)` — new kwarg. Stores on
  `self._attached_llm_client`.
- `Pipeline._resolve_llm_client()` — returns the attached client if set;
  otherwise walks registered stages, finds the `api` stage, grabs its
  provider (via `_provider` or the `provider` slot), wraps in
  `ProviderBackedClient`. Returns `None` if no api stage is present.
- `Pipeline._init_state` — after state construction, populates
  `state.llm_client` from `_resolve_llm_client()` if still `None`.

## Tests

All under `tests/unit/` (same convention as PR-1 / PR-2 — see
deviation note below):

- `test_llm_client_base.py` (7) — capability filtering for `thinking`,
  `top_k`, `tool_choice`; event emission; `event_sink=None` safety;
  full request-build round-trip.
- `test_llm_client_registry.py` (7) — 4 built-ins listed, class lookup,
  `ValueError` on unknown (lists registered names), custom registration
  with cleanup, vLLM `base_url` enforcement + success path.
- `test_llm_client_state.py` (5) — fresh state has `llm_client is None`,
  `attach_runtime(llm_client=client)` wiring, explicit client lands on
  state during run, auto-bridge from s06_api provider when no explicit
  client, no-api-stage leaves client `None`.

Full suite: **1086 passed, 18 skipped**. No regressions.

`ruff check` + `ruff format --check` clean on all touched files.

## Deviations from plan

1. **Test location** — plan placed tests under `tests/core/` and
   `tests/llm_client/`; the repo actually uses flat `tests/unit/`.
   Placed new tests in `tests/unit/test_llm_client_*.py` to match
   existing convention (same deviation as PR-1 / PR-2).
2. **Translator direction inverted during bridge** — plan had
   `llm_client/translators/` as canonical with s06_api importing from
   there. To keep PR-3's diff minimal and avoid touching the four
   existing s06_api artifact providers, PR-3 leaves the translator
   bodies in `stages/s06_api/_translate.py` and has
   `llm_client/translators/__init__.py` re-export from there. **PR-4
   inverts this** (moves bodies into llm_client, deletes s06_api
   artifact/ subdir entirely).
3. **`state.llm_client` typed as `Optional[Any]`, not `BaseClient`** —
   typing it as the class would create a circular import between
   `core/state.py` and `llm_client/base.py`. Documented the actual
   shape in the field's docstring; usage sites enforce it implicitly.
4. **Attach-runtime stash** — plan wrote directly to `self._state`,
   but `Pipeline` constructs state fresh per `run()` in `_init_state`.
   Stash the client on `self._attached_llm_client` and propagate during
   `_init_state` instead.

## What's next (PR-4)

Migrate `stages/s06_api` onto the unified client:
- Delete `artifact/{default,openai,google}/` subdirectories entirely.
- `APIStage.execute` reads `state.llm_client` (falling back to
  `ClientRegistry.get(provider_name)` if no explicit client attached).
- Move canonical translator bodies from `stages/s06_api/_translate.py`
  into `llm_client/translators/` and drop the re-export shim.
- Add a manifest-migration shim so v2 manifests referencing the old
  artifact names keep working.
- Parity tests verify APIStage + AnthropicClient produces identical
  output to the pre-PR-4 APIStage + AnthropicProvider path.
