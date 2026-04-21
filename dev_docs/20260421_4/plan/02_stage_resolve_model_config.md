# Plan 02 — PR-2: `Stage.resolve_model_config(state) -> ModelConfig`

**Repo.** `/home/geny-workspace/geny-executor`
**Branch.** `feat/stage-resolve-model-config`
**Depends on.** PR-1 (not strictly — none of PR-2's code touches
`state.shared` or `local_state`, but PR-1 lands first for merge
ordering and so PR-4 can assume both). Merge order:
PR-1 → PR-2.
**Blocks.** PR-4 (s02 summarizer and s15 reflector call
`resolve_model_config`).
**Related analysis.** Analysis 01 §1, §2 for the interface
surface as-is; §5 for the zero-callers evidence.

## 1. Goal

Upgrade the existing `Stage.resolve_model(state)` helper (which
returns just the model identifier string) to
`resolve_model_config(state)` (which returns the full
`ModelConfig` bundle: model + sampling + thinking settings).

Rewire the one existing caller — `s06_api._build_request` — to
use the new helper. No behavioral change for s06_api.

Keep `resolve_model` as a shim (returns the new helper's
`.model`) so any downstream or external caller keeps working.

## 2. Why

Today's `resolve_model` returns only `model: str`. That was
sufficient when only `s06_api` honored overrides, because
`s06_api._build_request` reads every other field
(`max_tokens`, `temperature`, `top_p`, `top_k`, `stop_sequences`,
`thinking_*`) directly off `self.model_override` or falls back
to state (analysis 01 §6, stage.py L208-246).

For PR-4, when a memory stage wants to call the LLM, it needs
the full bundle, not just the model string: a Haiku model at
main-stage `max_tokens=64000` is wasteful, and thinking should
be off for most memory work even when the main stage has it on.
The stage needs *its own override's settings*, not the main
stage's settings.

Returning a `ModelConfig` also standardizes the "how does a
stage know what model+params to use" question: one helper, one
return type, one import.

## 3. Non-goals

- **No new stages call it yet.** PR-2 is pure interface + rewire
  s06_api. PR-4 is where s02 and s15 actually call it.
- **No API-key override per stage.** Index.md §Scope Out: same
  api_key for all stages. `ModelConfig` already doesn't carry
  `api_key` (it's on `PipelineConfig`), so no temptation.
- **No provider-agnosticism.** `ModelConfig` is Anthropic-shaped
  (thinking fields, etc.). Future cycles may generalize.

## 4. Changes

### 4.1 `src/geny_executor/core/stage.py`

Replace the existing `resolve_model` with:

```python
def resolve_model_config(self, state: PipelineState) -> ModelConfig:
    """Return the effective :class:`ModelConfig` for this stage.

    When :attr:`model_override` is set, returns the override verbatim —
    it IS the effective config. Otherwise builds a config from the
    pipeline-wide fields on ``state`` (the pre-override defaults from
    :meth:`PipelineConfig.apply_to_state`).

    Model-using stages (API, agent sub-pipelines, evaluators, memory
    summarizers, memory reflectors) should call this helper instead of
    reading ``state.model`` / reading ``self.model_override`` field-by-field
    so the override is honored uniformly and so stages get the full
    sampling + thinking bundle together.

    Returns:
        ModelConfig: Always a non-None bundle. When no override is set,
        the returned config reflects the pipeline defaults currently on
        ``state``; mutations to the returned object do not back-propagate.
    """
    override = self._model_override
    if override is not None:
        return override
    return ModelConfig(
        model=state.model,
        max_tokens=state.max_tokens,
        temperature=state.temperature,
        top_p=state.top_p,
        top_k=state.top_k,
        stop_sequences=list(state.stop_sequences) if state.stop_sequences else None,
        thinking_enabled=state.thinking_enabled,
        thinking_budget_tokens=state.thinking_budget_tokens,
        thinking_type=getattr(state, "thinking_type", "enabled"),
        thinking_display=getattr(state, "thinking_display", None),
    )


def resolve_model(self, state: PipelineState) -> str:
    """Legacy shim — returns the effective model identifier.

    Equivalent to ``self.resolve_model_config(state).model``. Retained
    for downstream callers that only need the model string; new code
    should call :meth:`resolve_model_config` to get the full bundle.
    """
    return self.resolve_model_config(state).model
```

Imports (top of file): add `ModelConfig` from
`geny_executor.core.config`. Today's `stage.py` imports
`PipelineState` from `core.state`; add a sibling import for
`ModelConfig`.

The legacy `resolve_model` stays because:
- It's a public method (no underscore prefix); external callers
  may use it.
- Analysis 01 §5 showed zero callers *inside* the repo — but
  downstream plugin stages or test code could exist outside our
  view. Keeping the shim is cheap insurance.

### 4.2 `src/geny_executor/stages/s06_api/artifact/default/stage.py`

Update `_build_request` (L198-246) to call
`resolve_model_config`:

```python
def _build_request(self, state: PipelineState) -> APIRequest:
    """Build APIRequest from pipeline state.

    Follows Anthropic API constraints:
      - Use EITHER temperature OR top_p, not both.
      - thinking.budget_tokens must be < max_tokens when type="enabled".

    Honors per-stage overrides via :meth:`Stage.resolve_model_config`
    so all sampling + thinking fields are resolved together.
    """
    cfg = self.resolve_model_config(state)
    request = APIRequest(
        model=cfg.model,
        messages=list(state.messages),
        max_tokens=cfg.max_tokens,
        system=state.system,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        top_k=cfg.top_k,
        stop_sequences=cfg.stop_sequences,
    )

    if state.tools:
        request.tools = state.tools
    if state.tool_choice:
        request.tool_choice = state.tool_choice

    if cfg.thinking_enabled:
        thinking_type = cfg.thinking_type
        thinking: dict = {"type": thinking_type}
        if thinking_type == "enabled":
            thinking["budget_tokens"] = cfg.thinking_budget_tokens
        if cfg.thinking_display:
            thinking["display"] = cfg.thinking_display
        request.thinking = thinking

    return request
```

This is a direct translation of the existing branch-heavy code
into one `cfg.*` read per field. **Behavior is identical** —
`resolve_model_config` returns the override when set (same
field values as the old direct-read), or builds from state
when not set (same fallback as before).

The tests that pin s06_api's override behavior keep passing
because the inputs (a `ModelConfig` assigned to
`stage.model_override`) and outputs (the `APIRequest` fields)
are unchanged.

### 4.3 `src/geny_executor/core/stage.py` capability flag

`StageIntrospection.model_override_supported` (analysis 01 §9)
is set per-stage today; only `s06_api` reports True. That
changes in PR-4 for s02 and s15 — noted here so PR-2's change
doesn't accidentally flip the flag. **PR-2 does not change any
stage's `model_override_supported`.**

## 5. Tests

### 5.1 New tests

Add `tests/core/test_resolve_model_config.py`:

```python
"""Tests for Stage.resolve_model_config — full ModelConfig resolution."""

from geny_executor.core.config import ModelConfig
from geny_executor.core.state import PipelineState
from geny_executor.core.stage import Stage


class _StubStage(Stage):
    def __init__(self, name: str = "stub", order: int = 99) -> None:
        super().__init__(name=name, order=order)

    async def execute(self, input, state):
        return input


def test_resolve_no_override_returns_state_defaults():
    state = PipelineState(model="claude-sonnet-4-6", max_tokens=4096, temperature=0.3)
    stage = _StubStage()
    cfg = stage.resolve_model_config(state)
    assert cfg.model == "claude-sonnet-4-6"
    assert cfg.max_tokens == 4096
    assert cfg.temperature == 0.3


def test_resolve_override_wins_completely():
    state = PipelineState(model="claude-sonnet-4-6", max_tokens=64000, temperature=0.7)
    stage = _StubStage()
    stage.model_override = ModelConfig(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        temperature=0.0,
    )
    cfg = stage.resolve_model_config(state)
    assert cfg.model == "claude-haiku-4-5-20251001"
    assert cfg.max_tokens == 2048
    assert cfg.temperature == 0.0
    assert cfg is stage.model_override  # override returned verbatim


def test_resolve_thinking_fields_from_state_when_no_override():
    state = PipelineState(
        thinking_enabled=True,
        thinking_budget_tokens=5000,
        thinking_type="adaptive",
    )
    stage = _StubStage()
    cfg = stage.resolve_model_config(state)
    assert cfg.thinking_enabled is True
    assert cfg.thinking_budget_tokens == 5000
    assert cfg.thinking_type == "adaptive"


def test_resolve_thinking_fields_from_override():
    state = PipelineState(thinking_enabled=True, thinking_budget_tokens=10000)
    stage = _StubStage()
    stage.model_override = ModelConfig(
        model="claude-haiku-4-5-20251001",
        thinking_enabled=False,  # force-off for a cheap memory stage
    )
    cfg = stage.resolve_model_config(state)
    assert cfg.thinking_enabled is False


def test_legacy_resolve_model_returns_string():
    state = PipelineState(model="claude-sonnet-4-6")
    stage = _StubStage()
    assert stage.resolve_model(state) == "claude-sonnet-4-6"
    stage.model_override = ModelConfig(model="claude-haiku-4-5-20251001")
    assert stage.resolve_model(state) == "claude-haiku-4-5-20251001"


def test_resolve_stop_sequences_copied_not_shared():
    state = PipelineState(stop_sequences=["END"])
    stage = _StubStage()
    cfg = stage.resolve_model_config(state)
    assert cfg.stop_sequences == ["END"]
    # mutating returned config's stop_sequences should not affect state
    cfg.stop_sequences.append("STOP")
    assert state.stop_sequences == ["END"]
```

### 5.2 Existing test suite

`tests/stages/test_s06_api.py` (or whatever the real filename
is — grep for s06_api override tests) should continue to pass.
Those tests set `stage.model_override` and assert the resulting
`APIRequest` fields; the values come from the same source so
the tests are unchanged.

Run `pytest tests/stages/ -v` as part of the PR verification
step.

## 6. Risks

1. **Subtle behavioral change if `ModelConfig` defaults drift
   from `PipelineState` defaults.** Example: `ModelConfig`
   default `thinking_type="enabled"`, but `PipelineState`
   default `thinking_type="enabled"` — they match today, but a
   future change to one without the other would diverge.
   Mitigation: the no-override branch builds a *fresh*
   `ModelConfig` from `state` values, so defaults never apply —
   state values always win. Covered by the test that verifies
   state→cfg roundtrip on default-state.

2. **`list(state.stop_sequences)` copy.** Cheap defensive copy
   (avoid aliasing). Only cost is a list copy on every stage
   enter that reads the config. Negligible vs. the API call
   itself.

3. **`getattr(state, "thinking_type", "enabled")` still used
   inline.** Index.md §scope pins that fields live on
   `PipelineState`; `thinking_type` is declared on state so the
   getattr is defensive (against future removal or a state
   subclass that drops it). Keeps the old behavior s06_api had
   before this PR.

## 7. Acceptance criteria

- `Stage.resolve_model_config` exists and returns a
  `ModelConfig` (never None).
- `Stage.resolve_model` exists and returns a `str`, equal to
  `resolve_model_config(state).model`.
- `s06_api._build_request` uses the new helper; all fields in
  the built `APIRequest` are pulled from the returned config.
- New tests in `tests/core/test_resolve_model_config.py` pass.
- Existing `tests/stages/` suite passes without edits.
- No change to any stage's `StageIntrospection.model_override_supported`.

## 8. File map

Files modified:

- `src/geny_executor/core/stage.py` — replace `resolve_model`
  with two methods (new `resolve_model_config`, shim
  `resolve_model`); add `ModelConfig` import.
- `src/geny_executor/stages/s06_api/artifact/default/stage.py`
  — rewrite `_build_request` body to call the new helper.
- `tests/core/test_resolve_model_config.py` — new file,
  ~70 lines.

Files **not** modified:

- Any other stage. PR-2's rewire is limited to s06_api because
  it's the only current caller; PR-4 adds the new callers
  (s02, s15).
- `core/state.py`, `core/config.py`, `core/pipeline.py`,
  `core/mutation.py`. `ModelConfig` stays shape-identical.
