# PR-1 Progress — `PipelineState.shared` + `Stage.local_state`

**Status.** Opened 2026-04-21.
**PR.** https://github.com/CocoRoF/geny-executor/pull/37
**Branch.** `feat/pipeline-state-shared-and-local` → `main`
**Plan.** `plan/01_pipeline_state_shared_and_local.md`

## What shipped

- `PipelineState.shared: Dict[str, Any]` field (default `{}`), placed
  next to `metadata` in `src/geny_executor/core/state.py`. Class
  docstring rewritten to distinguish the two buckets and note the
  single-writer-per-turn invariant.
- `Stage.local_state(state) -> Dict[str, Any]` method in
  `src/geny_executor/core/stage.py`, adjacent to `resolve_model`.
  Implementation is one line: `return state.metadata.setdefault(self.name, {})`.
- `tests/unit/test_state_shared_and_local.py` — 8 tests (all passing).

## Deviations from the plan

- **Test directory.** Plan §4 assumed `tests/core/`; the repo
  actually uses `tests/unit/` for state/pipeline tests (checked:
  `tests/unit/test_phase1_pipeline.py`, `tests/unit/test_phase1_foundation.py`,
  etc. — there is no `tests/core/` directory). Placed the new test
  file under `tests/unit/` to match convention. Functionally
  identical; the plan's path was aspirational.
- **Test stub for `Stage`.** Plan §4 showed `super().__init__(name=..., order=...)`
  but `Stage` has abstract `name` / `order` properties (no init
  taking those kwargs). Implemented the stub with `_name`/`_order`
  attributes and concrete property overrides, which is the
  idiomatic ABC pattern.

## Verification

- `pytest tests/unit/test_state_shared_and_local.py -v` — 8/8 pass.
- `pytest tests/` — 1061 passed, 18 skipped (no regressions against
  the shipped stages).
- `ruff check` and `ruff format --check` on all three touched files
  — clean.

## Next

PR-2 is unblocked and will stash the resolved `ModelConfig` under
`Stage.local_state(state)`. See `plan/02_stage_resolve_model_config.md`.
