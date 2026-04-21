# Plan 06 — PR-6: Geny memory-model routing + unified client wiring

**Repo.** `/home/geny-workspace/Geny`
**Branch.** `feat/geny-memory-model-routing`
**Depends on.** PR-1..PR-5 all landed and published to PyPI as
the next geny-executor version (0.23 or whatever the next bump
is). This is the cycle's integration PR.
**Blocks.** Nothing — this closes the cycle.
**Related analysis.**
- Analysis 02 §1 — `_make_llm_reflect_callback` (the path
  this PR demotes).
- Analysis 02 §3 — `APIConfig.memory_model` (the field this
  PR makes load-bearing).
- Analysis 02 §7 — three LLM shapes in Geny; this PR removes
  shape #2 (`AsyncAnthropic` in-session).

## 1. Goal

Wire the newly shipped executor interfaces from the Geny host so
that:

- `APIConfig.memory_model` actually drives which model runs
  memory work (analysis 02 Site 3 becomes a load-bearing
  knob).
- `APIConfig.provider` (new) drives **which vendor SDK** the
  shared LLM client uses — same provider backs s06_api and
  memory stages. Default is `"anthropic"`, unchanged behavior.
- `s02_context` and `s15_memory` receive explicit `ModelConfig`
  overrides via `PipelineMutator.set_stage_model(2, …)` and
  `(15, …)`.
- The shared `BaseClient` is attached via
  `attach_runtime(llm_client=…)` so memory stages reuse Geny's
  configured credentials, not the manifest default. The same
  client can be used by s06_api at runtime too (PR-4's
  `_resolve_client` prefers `state.llm_client` over its own
  fallback).
- `_make_llm_reflect_callback` is demoted from the default path.
  The executor's native reflection (PR-5) runs by default;
  the callback is kept for one cycle behind an
  `APIConfig.use_legacy_reflect` flag so a problem session can
  A/B against the old behavior without a code revert.

## 2. Non-goals

- **No change to curation scheduler.** `reflect_utils.py` +
  `curation_engine.py` keep their own `ChatAnthropic` path
  (analysis 02 Sites 2, 8–10). They already read
  `APIConfig.memory_model`; PR-6 only unifies the in-session
  path.
- **No deletion of `_make_llm_reflect_callback`.** One-cycle
  deprecation. A follow-up cycle removes it after the native
  path has a few days of production use without regressions.
- **No frontend work.** The "Model" column on the log panel is
  already generic (cycle 20260421_3). Executor events from the
  new memory calls render as rows automatically. A dedicated
  "memory model: haiku-4-5" badge is out of scope.
- **No migration of tests to the native path.** Existing
  `test_llm_reflect_callback`-style tests (if any) keep
  covering the callback path; new tests cover the native path.
- **No multi-vendor production rollout this cycle.** `provider`
  defaults to `"anthropic"` and Geny's docs name only
  `"anthropic"` as supported. OpenAI/Google/vLLM clients exist
  in the executor (PR-3), but shipping them in Geny is a
  follow-up cycle with its own rollout plan.

## 3. Changes

### 3.1 `service/langgraph/agent_session.py` — `_build_pipeline`

Replace the existing L818 line:

```python
llm_reflect = self._make_llm_reflect_callback(api_key)
```

with the new memory-routing block. Insert after `api_key` is
resolved (currently around L781) and before the
`attach_kwargs` dict is assembled:

```python
# ── Memory model routing (cycle 20260421_4) ──
#
# Build a ModelConfig from APIConfig.memory_model and apply it to the
# memory-related stages via PipelineMutator. An empty memory_model falls
# back to the main model so no new LLM call spins up unexpectedly.
try:
    api_cfg = get_config_manager().load_config(APIConfig)
except Exception:
    api_cfg = APIConfig()
mem_model_name = (api_cfg.memory_model or "").strip() or api_cfg.anthropic_model
memory_cfg = ModelConfig(
    model=mem_model_name,
    max_tokens=2048,
    temperature=0.0,
    thinking_enabled=False,  # memory work does not benefit from extended thinking
)

mutator = PipelineMutator(self._prebuilt_pipeline)
# Stage 2 → context summarization (executor s02).
try:
    mutator.set_stage_model(2, memory_cfg)
except LookupError:
    logger.warning("cycle-4: s02 context stage absent, skipping memory override")
# Stage 15 → memory reflection (executor s15).
try:
    mutator.set_stage_model(15, memory_cfg)
except LookupError:
    logger.warning("cycle-4: s15 memory stage absent, skipping memory override")

# ── Shared LLM client (cycle 20260421_4) ──
#
# Build the shared client once and inject it via attach_runtime. The
# executor's s06_api will reuse the same instance when it calls
# self._resolve_client(state), so we have a single client backing both
# main-stage and memory-stage LLM calls.
provider_name = (getattr(api_cfg, "provider", "") or "anthropic").strip()
client_cls = ClientRegistry.get(provider_name)
llm_client = client_cls(
    api_key=api_key,
    base_url=getattr(api_cfg, "base_url", None) or None,
)

# Legacy reflection callback (kept behind an APIConfig flag for one cycle).
use_legacy_reflect = getattr(api_cfg, "use_legacy_reflect", False)
llm_reflect = (
    self._make_llm_reflect_callback(api_key) if use_legacy_reflect else None
)

# Resolver for the native reflection path (consumed by
# GenyMemoryStrategy when llm_reflect is None).
s15_stage = next(
    (st for st in self._prebuilt_pipeline.stages if st.order == 15),
    None,
)
if s15_stage is not None:
    from geny_executor.memory.strategy import ReflectionResolver
    reflection_resolver = ReflectionResolver(
        resolve_cfg=lambda state, _stage=s15_stage: _stage.resolve_model_config(state),
        has_override=lambda _stage=s15_stage: _stage._model_override is not None,
        client_getter=lambda state: getattr(state, "llm_client", None),
    )
else:
    reflection_resolver = None
```

Then update the `attach_kwargs` assembly around L821:

```python
attach_kwargs: Dict[str, Any] = {
    "system_builder": ComposablePromptBuilder(
        blocks=[
            PersonaBlock(persona_text),
            DateTimeBlock(),
            MemoryContextBlock(),
        ]
    ),
    "tool_context": ToolContext(
        session_id=self._session_id,
        working_dir=working_dir,
        storage_path=self.storage_path,
    ),
    "llm_client": llm_client,  # ← new
}
if self._memory_manager is not None:
    attach_kwargs["memory_retriever"] = GenyMemoryRetriever(
        self._memory_manager,
        max_inject_chars=max_inject_chars,
        enable_vector_search=True,
        curated_knowledge_manager=curated_km,
        recent_turns=6,
    )
    attach_kwargs["memory_strategy"] = GenyMemoryStrategy(
        self._memory_manager,
        enable_reflection=True,
        llm_reflect=llm_reflect,        # None unless use_legacy_reflect=True
        curated_knowledge_manager=curated_km,
        resolver=reflection_resolver,   # ← new
    )
    attach_kwargs["memory_persistence"] = GenyPersistence(
        self._memory_manager
    )

self._pipeline = self._prebuilt_pipeline
self._pipeline.attach_runtime(**attach_kwargs)
```

Imports at top of file:

```python
from geny_executor.core.config import ModelConfig
from geny_executor.core.mutation import PipelineMutator
from geny_executor.llm_client import ClientRegistry
```

(Already imported: `GenyMemoryStrategy`, `GenyMemoryRetriever`,
`GenyPersistence`. The pre-PR-6 imports of
`AnthropicProvider` / `ProviderLLMClient` — if any existed as
direct-from-package imports — are removed; the new path goes
through `ClientRegistry`.)

### 3.2 `service/config/sub_config/general/api_config.py`

Add two new fields: `provider` (so operators can choose which
client backs this session) and `use_legacy_reflect` (rollback
lever for native reflection):

```python
@register_config
@dataclass
class APIConfig(BaseConfig):
    ...
    anthropic_model: str = "claude-sonnet-4-6"
    memory_model: str = "claude-haiku-4-5-20251001"
    provider: str = "anthropic"         # ← new
    base_url: str = ""                  # ← new (optional; "" = default vendor endpoint)
    use_legacy_reflect: bool = False    # ← new
    max_thinking_tokens: int = 31999
    ...

    _ENV_MAP = {
        ...
        "memory_model": "MEMORY_MODEL",
        "provider": "LLM_PROVIDER",                  # ← new
        "base_url": "LLM_BASE_URL",                  # ← new
        "use_legacy_reflect": "USE_LEGACY_REFLECT",  # ← new
        ...
    }
```

And corresponding UI metadata entries in
`get_fields_metadata`, grouped so the related fields appear
together:

```python
ConfigField(
    name="provider",
    field_type=FieldType.ENUM,
    label="LLM Provider",
    description=(
        "Which vendor backs both the main reasoning call and the "
        "memory-side LLM work. Default: anthropic. Changing requires "
        "the matching vendor SDK to be installed."
    ),
    default="anthropic",
    enum=["anthropic", "openai", "google", "vllm"],
    group="api",
    apply_change=env_sync("LLM_PROVIDER"),
),
ConfigField(
    name="base_url",
    field_type=FieldType.STRING,
    label="Base URL",
    description=(
        "Override API endpoint. Required for vllm; optional for "
        "other providers. Leave blank to use the vendor default."
    ),
    default="",
    group="api",
    apply_change=env_sync("LLM_BASE_URL"),
),
ConfigField(
    name="use_legacy_reflect",
    field_type=FieldType.BOOLEAN,
    label="Use legacy LLM reflection (hardcoded Haiku)",
    description=(
        "Off (default): memory reflection runs via the geny-executor "
        "memory stage, using the Memory Model above. "
        "On: falls back to the pre-cycle hardcoded-Haiku callback path. "
        "Use only if the default path is misbehaving."
    ),
    default=False,
    group="api",
    apply_change=env_sync("USE_LEGACY_REFLECT"),
),
```

Positioned just below `memory_model` in the metadata list so
the related fields appear together in the UI.

### 3.3 s06_api config passthrough

The manifest that Geny loads already names the s06_api stage.
After PR-4, that stage accepts `provider: str`. Geny must set
it from the same `APIConfig.provider` so the main and memory
paths are consistent:

```python
# In _build_pipeline, before attach_runtime:
s06_stage = next(
    (st for st in self._prebuilt_pipeline.stages if st.order == 6),
    None,
)
if s06_stage is not None:
    try:
        s06_stage.update_config({
            "provider": provider_name,
            "base_url": getattr(api_cfg, "base_url", "") or "",
        })
    except Exception as exc:
        logger.warning("cycle-4: failed to sync s06 provider: %s", exc)
```

This is defensive — even though `state.llm_client` wins at
execute-time (PR-4 §4.3), we keep s06's fallback client
consistent in case it ever triggers.

### 3.4 `_make_llm_reflect_callback` — docstring update

No code change — just a docstring note:

```python
@staticmethod
def _make_llm_reflect_callback(api_key: str):
    """Create a legacy LLM reflection callback for GenyMemoryStrategy.

    .. deprecated:: cycle 20260421_4
       Since cycle 20260421_4, geny-executor's memory stage runs
       reflection natively using ``APIConfig.memory_model``. This
       callback is retained for one cycle behind the
       ``APIConfig.use_legacy_reflect`` flag so operators can
       A/B-test regressions. It is expected to be removed in the
       cycle after that.

    Returns an async callable: (input_text, output_text) -> List[Dict].
    Uses the Anthropic SDK directly with a hardcoded Haiku model.
    """
    ...
```

Don't delete, don't change behavior. Just mark intent so the
follow-up cycle's removal isn't a surprise.

### 3.5 Session unit tests

Add `backend/tests/service/langgraph/test_memory_model_routing.py`:

```python
"""Verify cycle 20260421_4 memory-model routing.

After _build_pipeline:
  • stages 2 and 15 have a ModelConfig override whose model matches APIConfig.memory_model.
  • state.llm_client is a BaseClient built via ClientRegistry.
  • GenyMemoryStrategy receives a non-None resolver and (by default) llm_reflect=None.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from geny_executor.llm_client import BaseClient
from service.langgraph.agent_session import AgentSession


@pytest.fixture
def _stub_manifest_pipeline(monkeypatch):
    """Install a minimal pipeline double with the two attributes
    _build_pipeline touches: .stages (list of Stage-like objects)
    and .attach_runtime (collecting kwargs for inspection)."""
    captured: dict = {}

    class _StubStage:
        def __init__(self, order):
            self.order = order
            self.name = {2: "context", 6: "api", 15: "memory"}[order]
            self._model_override = None
            self._config: dict = {}

        def resolve_model_config(self, state):
            return self._model_override  # simplified — returns None when no override

        def update_config(self, cfg):
            self._config.update(cfg)

    stages = [_StubStage(2), _StubStage(6), _StubStage(15)]

    class _StubPipeline:
        def __init__(self):
            self.stages = stages  # type: ignore[assignment]
            self._attach_calls = []

        def attach_runtime(self, **kwargs):
            self._attach_calls.append(kwargs)
            captured.update(kwargs)

    return _StubPipeline(), captured, stages


def _make_session(stub_pipeline):
    session = AgentSession(session_id="s-test", session_name="T")
    session._prebuilt_pipeline = stub_pipeline
    session._env_id = "env"
    session._memory_manager = MagicMock()
    session._working_dir = "/tmp/test-session"
    session._role = session._role.__class__.WORKER
    return session


def test_stage_overrides_use_memory_model(_stub_manifest_pipeline, monkeypatch):
    stub, captured, stages = _stub_manifest_pipeline
    session = _make_session(stub)

    # Fake api config.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MEMORY_MODEL", "claude-haiku-4-5-20251001")

    session._build_pipeline()

    s2, _s6, s15 = stages
    assert s2._model_override is not None
    assert s2._model_override.model == "claude-haiku-4-5-20251001"
    assert s15._model_override is not None
    assert s15._model_override.model == "claude-haiku-4-5-20251001"


def test_attach_runtime_receives_base_client(_stub_manifest_pipeline, monkeypatch):
    stub, captured, _ = _stub_manifest_pipeline
    session = _make_session(stub)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    session._build_pipeline()

    assert "llm_client" in captured
    assert isinstance(captured["llm_client"], BaseClient)
    # Default provider is anthropic.
    assert captured["llm_client"].provider == "anthropic"


def test_provider_env_var_selects_different_client(_stub_manifest_pipeline, monkeypatch):
    stub, captured, _ = _stub_manifest_pipeline
    session = _make_session(stub)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")  # explicit

    session._build_pipeline()
    assert captured["llm_client"].provider == "anthropic"


def test_s06_stage_config_synced(_stub_manifest_pipeline, monkeypatch):
    stub, captured, stages = _stub_manifest_pipeline
    session = _make_session(stub)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_BASE_URL", "https://custom.example")

    session._build_pipeline()
    _s2, s6, _s15 = stages
    assert s6._config.get("provider") == "anthropic"
    assert s6._config.get("base_url") == "https://custom.example"


def test_memory_strategy_has_resolver_and_no_callback_by_default(
    _stub_manifest_pipeline, monkeypatch
):
    stub, captured, _ = _stub_manifest_pipeline
    session = _make_session(stub)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    session._build_pipeline()

    strategy = captured.get("memory_strategy")
    assert strategy is not None
    assert strategy._llm_reflect is None  # default (no legacy flag)
    assert strategy._resolver is not None


def test_legacy_flag_restores_callback(_stub_manifest_pipeline, monkeypatch):
    stub, captured, _ = _stub_manifest_pipeline
    session = _make_session(stub)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("USE_LEGACY_REFLECT", "1")

    session._build_pipeline()
    strategy = captured.get("memory_strategy")
    assert strategy._llm_reflect is not None
    # Resolver still present — but callback takes precedence at runtime.
    assert strategy._resolver is not None


def test_empty_memory_model_falls_back_to_main(_stub_manifest_pipeline, monkeypatch):
    stub, captured, stages = _stub_manifest_pipeline
    session = _make_session(stub)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MEMORY_MODEL", "")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    session._build_pipeline()
    s2, _s6, s15 = stages
    assert s2._model_override.model == "claude-sonnet-4-6"
    assert s15._model_override.model == "claude-sonnet-4-6"


def test_missing_stage_is_warning_not_failure(monkeypatch, caplog):
    """Session with a manifest that lacks s02 or s15 must not hard-fail."""
    captured: dict = {}

    class _OnlyS06:
        def __init__(self):
            self.stages = []  # no stages at all
            self._attach_calls = []

        def attach_runtime(self, **kwargs):
            captured.update(kwargs)

    session = AgentSession(session_id="s", session_name="T")
    session._prebuilt_pipeline = _OnlyS06()
    session._env_id = "env"
    session._memory_manager = MagicMock()
    session._working_dir = "/tmp/x"
    session._role = session._role.__class__.WORKER
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    session._build_pipeline()  # should not raise
    assert "llm_client" in captured
    assert "cycle-4: s02 context stage absent" in caplog.text
    assert "cycle-4: s15 memory stage absent" in caplog.text
```

Existing `test_default_manifest.py` and integration tests must
pass without changes — none of them pin `_llm_reflect is not
None` directly; they assert on pipeline behavior, not
internals.

### 3.6 Integration smoke test

Under `backend/tests/integration/`, add a smoke test that:

1. Constructs a real manifest-based pipeline with a mock
   client injected via `attach_runtime(llm_client=MockClient(...))`.
2. Confirms a session that produces a completed turn emits a
   `memory.reflection.native` event (or
   `memory.reflection_queued` when the test disables the
   override — to cover the no-cost branch).

This guards against silent regressions where the attach
succeeds but the native path never fires.

## 4. Documentation

Update `backend/service/langgraph/README.md` (if present) or add
a short `AGENTS.md`-style note in the session module:

> Memory model routing: the memory-side LLM runs the model
> configured in `APIConfig.memory_model` (empty → main model).
> The routing is applied in `_build_pipeline` via
> `PipelineMutator.set_stage_model(2, …)` and `(15, …)` and is
> consumed natively by geny-executor's s02 / s15 stages
> starting in cycle 20260421_4.
>
> Provider: `APIConfig.provider` controls which vendor SDK
> backs the session. Default `anthropic`. To roll back to the
> pre-cycle hardcoded-Haiku callback path, set
> `APIConfig.use_legacy_reflect = True`.

## 5. Risks

1. **Manifest without s02 or s15.** `set_stage_model` looks up
   the stage by order; if absent, it raises (analysis 01 §8).
   Mitigation: the per-stage `set_stage_model` calls are
   wrapped in `try / except LookupError` that log a warning
   and continue. A session with no memory stage shouldn't
   hard-fail at attach time.

2. **Unknown provider name.** `ClientRegistry.get(name)`
   raises `ValueError` for unknown providers. Mitigation:
   `APIConfig.provider` uses an enum UI widget (PR §3.2) that
   limits values at the UI layer, and `ClientRegistry`'s
   error message lists registered names. For direct env-var
   setters, the error propagates out of `_build_pipeline` and
   marks the session as failed at startup rather than
   misbehaving later.

3. **Credential drift between main and memory paths.** The
   shared client is constructed with `api_key` +
   `APIConfig.base_url`. s06_api reuses the same client via
   `state.llm_client` (PR-4 §4.3), so there is no drift by
   construction. Non-Anthropic providers may need a different
   env var for the key (`OPENAI_API_KEY`, `GOOGLE_API_KEY`);
   this PR does **not** add that mapping — it assumes
   `api_key` is whatever the `provider` expects. Documented
   in the README note above.

4. **Native path output divergence from callback.** The
   native prompt is copied verbatim from
   `_make_llm_reflect_callback`, so the produced insights
   should match. Differences come from the Haiku model
   occasionally picking different phrasings. The legacy flag
   is the rollback lever.

5. **`ReflectionResolver` captures `s15_stage` by closure.**
   If a caller re-attaches a new `memory_strategy` on a second
   `attach_runtime` call, the resolver from the first call
   still references the stage from pipeline build time —
   which is the same object, so no bug. Listed so future
   maintainers who touch the closure understand why it's a
   lambda with default-arg capture (`_stage=s15_stage`)
   rather than a free variable.

6. **Memory calls now count against the provider rate limit.**
   Before this cycle, memory reflection used one session's
   worth of Haiku budget *silently* per turn (Site 1 already
   called Haiku — just without telling anyone). After this
   cycle, the call is explicit but the behavior is the same:
   one Haiku call per terminal turn, gated on an override
   being set. No net increase unless a user explicitly turns
   on s02 compaction (which is the point).

## 6. Acceptance criteria

- A fresh session in the dev environment, with
  `MEMORY_MODEL=claude-haiku-4-5-20251001` and a normal
  run that completes a turn, produces a
  `memory.reflection.native` event (visible in the log panel
  courtesy of cycle 20260421_3's generic event handling).
- Running the same flow with `MEMORY_MODEL=""` falls back to
  the main model for memory calls (main + secondary both on
  the same model — the native path still runs, the override
  value just happens to match the main).
- `USE_LEGACY_REFLECT=1` brings back the callback path and
  suppresses the native event (callback still emits the
  pre-cycle `memory.insights_saved` event on success).
- `LLM_PROVIDER=anthropic` (explicit) produces the same
  runtime behavior as not setting it at all.
- Setting `LLM_PROVIDER` to an unregistered name produces a
  clear session-startup error with the provider list.
- A session whose manifest has no s02/s15 stages still boots
  (warnings in log; no exception).
- The curation scheduler still works (it uses a separate
  path per analysis 02 §6).
- No test added in earlier PRs regresses.
- Cycle 20260421_3's log-panel terminology stays correct; no
  "Graph" labels reappear.

## 7. Rollout

1. Publish `geny-executor` to PyPI with PR-1..PR-5 bundled
   (single version bump).
2. Open PR-6 against `Geny/main`, bumping the
   `geny-executor` pin in `pyproject.toml` (or equivalent
   dependency file) to that version.
3. After merge, keep `USE_LEGACY_REFLECT=1` available for
   one week in production; if no incidents, open a
   follow-up cycle to remove `_make_llm_reflect_callback`
   and the flag.
4. Keep `LLM_PROVIDER` pinned to `"anthropic"` for at least
   this cycle's production rollout. A future cycle will
   cover the operational story (installing extras, per-vendor
   credential routing, monitoring) for flipping providers.

## 8. File map

Files modified:

- `backend/service/langgraph/agent_session.py` — memory
  routing block in `_build_pipeline`; s06 config sync;
  docstring on `_make_llm_reflect_callback`; new imports
  (`ClientRegistry`, `ModelConfig`, `PipelineMutator`).
- `backend/service/config/sub_config/general/api_config.py` —
  `provider`, `base_url`, `use_legacy_reflect` fields + env
  map + UI metadata entries.
- `pyproject.toml` (or `requirements.txt`) — bump
  `geny-executor` version.
- `backend/tests/service/langgraph/test_memory_model_routing.py`
  — new test module (§3.5).
- `backend/tests/integration/test_native_reflection_smoke.py`
  — new (§3.6).

Files **not** modified:

- `backend/service/memory/reflect_utils.py` — keeps its own
  `ChatAnthropic` lifecycle.
- `backend/service/memory/curation_engine.py` — batch path
  unchanged.
- Any frontend file — event rendering already generic.
