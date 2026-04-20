# Progress/03 — Integration smoke: delegation round-trip

**PR.** `test/delegation-round-trip` (Phase 1 · PR #3 of 9)
**Plan.** `plan/01_tool_execution_fix.md` §PR #3
**Date.** 2026-04-20

---

## What landed

Bootstrapped a backend test layout and added two test modules:

- `backend/tests/conftest.py` — adds the backend source root to
  `sys.path` so tests can import `service.*` (mirrors how the
  app runs in production with cwd = `backend/`).
- `backend/tests/service/langgraph/test_default_manifest.py` —
  unit tests that assert the shape of the manifest the builder
  emits: orders `{10, 11, 14}` present across all presets, slot
  strategies match the executor's defaults, VTuber continues to
  omit Stage 8 (negative control), and a materialized
  `Pipeline.from_manifest` has the three new stages registered.
- `backend/tests/integration/test_delegation_round_trip.py` —
  functional proof that Stage 10, as wired by the manifest,
  actually dispatches a `state.pending_tool_calls` entry to a
  registered tool. Uses a minimal `_RecordingTool` inheriting
  from `Tool`, registers it into the Stage 10 registry, primes
  state with one pending call, runs the stage, and asserts the
  tool's `execute()` ran (call captured, `tool_results`
  populated, `pending_tool_calls` cleared). A second test
  verifies the bypass fast-path when no calls are pending.

Empty `__init__.py` files added throughout so pytest can collect
the tree.

## Why this scope

The plan called for an end-to-end VTuber → Sub-Worker DM
round-trip using a mocked LLM. Going full round-trip requires
stubbing `ClaudeCLIChatModel` / the Anthropic HTTP client *and*
bootstrapping `AgentSessionManager` with its supporting
singletons (SessionStore, EnvironmentService,
ChatConversationStore, InboxManager). That test infrastructure
does not exist in this workspace and standing it up is out of
proportion to the regression protection this PR needs to
provide.

The narrower "Stage 10 actually dispatches the pending call"
test covers the *exact* regression class PR #1 fixed — a
manifest that declares the stages but where the resulting
pipeline silently skips tool calls would fail the integration
test here, not the unit test alone. The wider DM round-trip is
covered by the manual smoke in the Phase 1 verification
checklist.

## Why this is not a duplicate of PR #1 verification

PR #1 verified with a standalone script that `from_manifest`
registers the three new stages. That catches "wrong order
numbers" and "stage module import failures". It does **not**
catch "stage registered but never executes work" — e.g., if a
future change silently swaps the default executor for a stub
that accepts the call list and drops it. `test_tool_stage_
executes_pending_calls_for_worker_manifest` asserts the real
execution path, so that regression becomes visible.

## Verification

- `python3 -m py_compile` on all new test files → OK.
- Tests are written as standard pytest; running them requires
  the backend's production dependencies (`pydantic`, `pytest`,
  `pytest-asyncio`). The local sandbox lacks both, so local
  pytest invocation was deferred. Shape and import correctness
  verified with the PR #1 spec-loader bypass approach used in
  that PR's smoke.

## Out of scope

- Full mocked-LLM VTuber → Sub-Worker round-trip (per rationale
  above).
- Testing other tools (`Read`, `Write`, `Bash`, …). The
  regression class is "Stage 10 is there but non-functional";
  one representative tool dispatch is sufficient.
- Wiring up a CI pytest job. Adding a harness is its own task
  and out of this cycle's scope.

## Rollback

Remove the new files. No code paths touched outside
`backend/tests/`.
