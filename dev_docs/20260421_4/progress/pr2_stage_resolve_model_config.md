# PR-2 Progress — `Stage.resolve_model_config` + s06_api rewire

**Status.** Opened 2026-04-21.
**PR.** https://github.com/CocoRoF/geny-executor/pull/38
**Branch.** `feat/stage-resolve-model-config` → `feat/pipeline-state-shared-and-local` (stacked on PR-1)
**Plan.** `plan/02_stage_resolve_model_config.md`

## What shipped

- `Stage.resolve_model_config(state) -> ModelConfig` — returns the
  override verbatim when set, otherwise builds a fresh bundle from
  `state.model` / `state.max_tokens` / `state.temperature` / …
  including the thinking fields with `getattr` defaults for
  forward-compatibility.
- `Stage.resolve_model(state) -> str` kept as a legacy shim
  (`return self.resolve_model_config(state).model`).
- `ModelConfig` imported at module level in `core/stage.py` —
  no circular risk (config.py imports nothing from state.py or
  stage.py).
- `s06_api._build_request` rewritten to read every field off a
  single `cfg = self.resolve_model_config(state)` call. Branching
  (override vs state) is now encapsulated in the helper.

## Deviations from the plan

- Test file placed at `tests/unit/test_resolve_model_config.py`
  instead of `tests/core/...` — same rationale as PR-1 (the repo
  uses `tests/unit/` for this category).
- Test stub uses ABC property-override pattern for `name` / `order`
  instead of the plan's `super().__init__(name=..., order=...)`.

## Verification

- `pytest tests/unit/test_resolve_model_config.py -v` — 6/6 pass.
- `pytest tests/` — 1067 passed, 18 skipped. No regressions in
  s06_api integration suite or elsewhere.
- `ruff check` and `ruff format --check` clean on all three
  touched files.

## Next

PR-3 (`geny_executor/llm_client/` package scaffold) is the next
layer. It introduces `BaseClient` + `ClientRegistry` + vendor
clients, which PR-4 then consumes when deleting
`s06_api/artifact/{default,openai,google}/`.
