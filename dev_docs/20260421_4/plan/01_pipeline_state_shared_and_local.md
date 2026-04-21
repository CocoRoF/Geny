# Plan 01 — PR-1: `PipelineState.shared` + `Stage.local_state(state)`

**Repo.** `/home/geny-workspace/geny-executor`
**Branch.** `feat/pipeline-state-shared-and-local`
**Depends on.** Nothing. This is the bottom of the stack.
**Blocks.** PR-2 (no hard dep, but PR-2's model-config resolution
ends up stashed in `local_state`). PR-3 (stores `llm_client` on
state but conceptually independent). PR-4 (uses both helpers).
PR-5 (Geny host will lean on `shared`).
**Related analysis.** Analysis 03 (design space) is the rationale;
this plan is the mechanics.

## 1. Goal

Add the two state interfaces the user asked for:

- A pipeline-wide "global" bucket: `PipelineState.shared:
  Dict[str, Any]`, fresh per run.
- A per-stage scratchpad helper: `Stage.local_state(state) ->
  Dict[str, Any]`, backed by `state.metadata[self.name]`.

Both additive, zero migration for the 16 shipped stages.

## 2. Non-goals

- **No consumer in this PR.** The interfaces are plumbed and
  tested but no stage actually uses them yet — PR-2/3/4/5 are
  where consumers land. This keeps the PR easy to review and
  easy to revert if we want to refine the shape later.
- **No typed helpers.** Keys and values stay `Dict[str, Any]`.
  Analysis 03 §7 argues against typing.
- **No concurrency primitives.** Single writer per turn, as
  today. Documented in the dataclass docstring.

## 3. Changes

### 3.1 `src/geny_executor/core/state.py`

Add one field to `PipelineState`, placed next to `metadata` so
the dataclass ordering groups free-form buckets together:

```python
# ── Metadata (free-form per-run scratch; legacy + stage-local storage) ──
metadata: Dict[str, Any] = field(default_factory=dict)

# ── Shared (cross-stage communication for one run) ──
shared: Dict[str, Any] = field(default_factory=dict)
```

Update the `PipelineState` class docstring to document both
buckets' intended use:

```
Accumulates across loop iterations within a single run. Two
free-form buckets are available for stage-authored data:

- ``shared`` — cross-stage communication. Any stage may read
  and write. Resets to ``{}`` at the start of each run. Keys
  are free-form strings; writers and readers cooperate by
  convention. Not an event channel — use ``add_event`` for
  that.
- ``metadata`` — general per-run scratch. Historically used
  for pipeline signals (``needs_reflection``, ``L0_tail``,
  ``cost_breakdown``). New code should prefer ``shared`` for
  cross-stage data and :meth:`Stage.local_state` for per-stage
  bookkeeping; ``metadata`` remains for unconvenent signals.

Within a single loop turn, stages run sequentially, so
``shared`` has one writer at a time. If a future cycle
introduces parallel sub-stages, readers/writers of the same
key will need to add explicit coordination.
```

No other changes to `state.py`. `TokenUsage`, `CacheMetrics`,
and the rest of `PipelineState` stay put.

### 3.2 `src/geny_executor/core/stage.py`

Add one method on `Stage`, next to the existing `resolve_model`
helper (L309) so the "state helpers exposed on Stage" area is
contiguous:

```python
def local_state(self, state: PipelineState) -> Dict[str, Any]:
    """Return this stage's private scratchpad, creating it on first access.

    Per-stage state lives under ``state.metadata[self.name]``. The
    helper ensures the dict exists and returns it; callers read
    and write the dict directly.

    Use this when a stage needs to remember something across
    iterations of the same run (e.g. a summarizer tracking which
    message indices have already been compacted). For values
    shared between stages, use ``state.shared`` instead.

    Do not reach into another stage's local_state — by
    convention, each stage owns its own bucket. If stages need
    to exchange data, publish to ``state.shared``.
    """
    return state.metadata.setdefault(self.name, {})
```

Imports: `Dict`, `Any` are already imported in `stage.py`
(they're used elsewhere). No new imports needed.

No other changes to `stage.py`. `model_override`,
`resolve_model`, `tool_binding` all remain untouched —
PR-2 will modify `resolve_model`.

### 3.3 Exports

`src/geny_executor/__init__.py` already re-exports
`PipelineState`. No re-export needed for `local_state` (it's a
method on the public `Stage` class).

`src/geny_executor/core/__init__.py` — verify `PipelineState` and
`Stage` are both exported (they are, per a grep done in the
audit). No change.

## 4. Tests

Add `tests/core/test_state_shared_and_local.py` (new file,
alongside existing `tests/core/test_pipeline_state.py`-style
tests):

```python
"""Tests for PipelineState.shared and Stage.local_state helper."""

from geny_executor.core.state import PipelineState
from geny_executor.core.stage import Stage


class _StubStage(Stage):
    """Minimal Stage subclass for testing helpers — does not execute."""

    def __init__(self, name: str, order: int) -> None:
        super().__init__(name=name, order=order)

    async def execute(self, input, state):
        return input


def test_shared_defaults_empty():
    state = PipelineState()
    assert state.shared == {}


def test_shared_is_isolated_per_state():
    s1 = PipelineState()
    s2 = PipelineState()
    s1.shared["x"] = 1
    assert s2.shared == {}  # no shared mutable default


def test_shared_roundtrip():
    state = PipelineState()
    state.shared["context_summary"] = "hello"
    assert state.shared["context_summary"] == "hello"


def test_local_state_creates_on_first_access():
    state = PipelineState()
    stage = _StubStage(name="context", order=2)
    ls = stage.local_state(state)
    assert ls == {}
    ls["compacted_at_iteration"] = 3
    assert state.metadata["context"]["compacted_at_iteration"] == 3


def test_local_state_idempotent_on_repeat():
    state = PipelineState()
    stage = _StubStage(name="memory", order=15)
    first = stage.local_state(state)
    first["count"] = 7
    second = stage.local_state(state)
    assert second is first
    assert second["count"] == 7


def test_local_state_disjoint_between_stages():
    state = PipelineState()
    a = _StubStage(name="context", order=2)
    b = _StubStage(name="memory", order=15)
    a.local_state(state)["k"] = "A"
    b.local_state(state)["k"] = "B"
    assert a.local_state(state)["k"] == "A"
    assert b.local_state(state)["k"] == "B"


def test_shared_and_metadata_are_separate_buckets():
    state = PipelineState()
    state.shared["s"] = 1
    state.metadata["m"] = 2
    assert "s" not in state.metadata
    assert "m" not in state.shared


def test_local_state_does_not_touch_shared():
    state = PipelineState()
    stage = _StubStage(name="context", order=2)
    stage.local_state(state)["k"] = "v"
    assert state.shared == {}
```

Also extend `tests/core/test_pipeline_state.py` (or whatever
existing state-shape test lives there) with one sanity check
that `PipelineState()` still constructs without any extra args —
there's no test regression from the new field.

## 5. Documentation

- The dataclass docstring (§3.1) is the primary artefact —
  auto-rendered by Sphinx if the repo has docs; readable at
  source otherwise.
- `Stage.local_state` docstring (§3.2) is self-explanatory.
- `progress/e1_uniformity.md` in the executor repo has a running
  notes file; add a short bullet mentioning PR-1 landed but
  hold on writing it until PR-5 closes (the uniformity work
  isn't done until Geny adopts the interfaces).
- No separate design doc needed — Analysis 03 is the design doc.

## 6. Risks

1. **Signature growth of `PipelineState`.** The dataclass gets
   one new field. External callers instantiating `PipelineState(
   ...kwargs)` positionally would break if they pass 30+
   positional args in order — no caller does this (all use
   keyword args), but note it.
2. **Developer confusion between `shared` / `metadata` /
   `local_state`.** Mitigated by docstrings. The naming
   (`shared` for cross-stage, `metadata` for legacy free-form,
   `local_state` for per-stage) is the teaching device.
3. **Key collision in `shared`.** If two stages both write
   `state.shared["summary"]` without coordinating, the later
   writer wins. No runtime check is possible — this is the
   same risk as two stages both writing `state.metadata["foo"]`
   today. The fix for systemic collision is *convention*
   (prefix the key with your stage name for namespaced writes:
   `state.shared["s02.context_summary"]`). Documented in the
   docstring.

## 7. Acceptance criteria

- `state.py` adds one new field; existing fields unchanged.
- `stage.py` adds one new method; existing methods unchanged.
- New tests pass in isolation and alongside the existing
  `tests/core/` suite.
- `python -c "from geny_executor import PipelineState; s = PipelineState(); print(s.shared)"`
  prints `{}`.
- No changes to any of the 16 stages in `stages/`. The shipped
  test suite passes without modification.

## 8. Rollout

- PR is self-contained; lands against `main`.
- Published to PyPI as part of the next geny-executor release
  alongside PR-2 and PR-3 (this cycle bundles 4 executor PRs
  into one version bump — coordinated in PR-5 notes).

## 9. File map

Files modified:

- `src/geny_executor/core/state.py` — 1 new field, docstring.
- `src/geny_executor/core/stage.py` — 1 new method.
- `tests/core/test_state_shared_and_local.py` — new file,
  ~60 lines.

Files **not** modified:

- All 16 stage modules under `src/geny_executor/stages/`.
- `core/config.py`, `core/pipeline.py`, `core/mutation.py`.
- Memory, events, history, security, session, tools modules.
