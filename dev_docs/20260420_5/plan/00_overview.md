# Plan 00 — Overview

Four PRs. Each merges before the next starts, matching the
durable continuous-PR-cadence instruction.

## PR sequence

| # | Branch | Scope | Gating |
| --- | --- | --- | --- |
| 1 | `fix/manifest-tool-roster` | Make seed env templates declare every Geny-provider tool (builtin + custom) in `manifest.tools.external`. Kill the dead `_DEFAULT_BUILT_IN_TOOLS` list. | Unit test: `create_worker_env` / `create_vtuber_env` rosters include `geny_send_direct_message`, `memory_read`, `knowledge_search`. |
| 2 | `fix/role-default-tool-rosters` | Give VTuber + Worker symmetric Geny-platform access (DM, inbox, memory, knowledge) while keeping the web-tool subset VTuber-specific via a narrower custom whitelist. | Unit test: `create_vtuber_env` includes platform tools but not `browser_*`; `create_worker_env` includes both. |
| 3 | `fix/controller-process-attr` | Replace all six `.process` references in `agent_controller.py` with modern `AgentSession.storage_path` + inline prompt assignment. | Controller test: `GET /sessions/{id}/files` returns 200 against a manifest-built session. |
| 4 | `test/tool-use-e2e-validation` | Regression harness: assert `pipeline.tool_registry` contains the expected roster after `from_manifest_async` for both roles; add a VTuber → Sub-Worker delegation integration test that exercises `geny_send_direct_message` end-to-end. | All existing tests + new harness green. |

## PR cadence

Per the durable instruction:

1. Create branch off latest `main`.
2. Implement.
3. Self-review diff, run relevant tests, write `progress/NN_*.md`
   with the root-cause walkthrough.
4. Commit with `Co-Authored-By: Claude Opus 4.7`.
5. Push and open PR via `gh pr create`.
6. Wait for merge signal before starting the next PR.

## Dependencies between PRs

- PR #2 depends on #1 for the `build_default_manifest` signature
  shift (so the vtuber factory can take `all_names` not just a
  hardcoded 3-tuple).
- PR #3 is independent of #1/#2 but sequenced *after* them so
  the end-to-end validation in PR #4 covers a state where file
  endpoints work.
- PR #4 depends on #1-#3.

## Non-goals for this cycle

- Session-manager linking / display-name drift (analysis/02
  notes this is latent but not actively broken today).
- Executor-side `.built_in` consumption (future cleanup; see
  analysis/01's discussion of option 2).
- Frontend tool-error rendering improvements (separate UX PR).

## Completion criteria (repeat from index)

1. VTuber + Sub-Worker can use DM, inbox, memory, knowledge
   tools.
2. `/sessions/{id}/files` returns 200.
3. Regression test prevents future roster regressions.
