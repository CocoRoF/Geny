# Plan 00 — PR sequencing overview

A single, authoritative checklist for the 20260420_3 cycle. Every
PR across plans 01/02/03 is listed here in execution order with
its dependencies and its target release.

Use this doc as the master. The per-plan documents
(`01_immediate_fixes.md`, `02_default_env_per_role.md`,
`03_vtuber_worker_binding.md`) hold the technical detail for each
individual PR.

---

## Repos involved

| Repo | Role | Branch policy |
|------|------|---------------|
| `geny-executor` | library; emits events, owns `Pipeline` | PRs against `main`, squash-merge, tag releases `v0.23.0` / `v0.24.0` |
| `Geny` | application; consumes executor | PRs against `main`, squash-merge, one progress-doc PR per code PR |

---

## Master PR sequence

### Phase 1 — Plan/01: unblock VTuber tool calls

| # | Repo | Title | Depends on | Release |
|---|------|-------|------------|---------|
| 1 | Geny | `_GenyToolAdapter` signature-introspects `session_id` | — | — |
| 2 | Geny | progress doc for #1 | #1 | — |
| 3 | executor | add `tool.call_start` / `tool.call_complete` per-call events (additive) | — | **v0.23.0** |
| 4 | executor | CHANGELOG + version bump + tag + GitHub release | #3 | **v0.23.0** |
| 5 | Geny | bump pin to `>=0.23.0,<0.24.0`, switch `agent_session.py` logging to `tool.call_start` | #4 released | — |
| 6 | Geny | progress doc for #5 | #5 | — |

**Exit criterion**: VTuber session calls `news_search`, UI shows
`query=\`<actual query>\`` detail (not `'2'`), and both turns
succeed (not `is_error=True`).

### Phase 2 — Plan/02: environment-only cutover

| # | Repo | Title | Depends on | Release |
|---|------|-------|------------|---------|
| 7 | executor | `Pipeline.attach_runtime(...)` helper + tests | Phase 1 done | **v0.24.0** |
| 8 | executor | CHANGELOG + version bump + tag + GitHub release | #7 | **v0.24.0** |
| 9 | Geny | bump pin to `>=0.24.0,<0.25.0` | #8 released | — |
| 10 | Geny | populate `build_default_manifest.stages` for `worker_adaptive` + `vtuber` + parity tests | #9 | — |
| 11 | Geny | progress doc for #10 | #10 | — |
| 12 | Geny | seed `install_environment_templates` (WORKER/VTUBER), `ROLE_DEFAULT_ENV_ID`, `resolve_env_id` | #11 | — |
| 13 | Geny | progress doc for #12 | #12 | — |
| 14 | Geny | `AgentSessionManager` always resolves env_id; delete `if env_id:` gate and `geny_tool_registry` plumbing | #13 | — |
| 15 | Geny | progress doc for #14 | #14 | — |
| 16 | Geny | `AgentSession._build_pipeline` becomes `attach_runtime`-only; delete `GenyPresets.*` call sites | #15 | — |
| 17 | Geny | progress doc for #16 | #16 | — |

**Exit criterion**: any session type (worker / developer /
researcher / planner / vtuber) with or without explicit `env_id`
goes through the single `from_manifest_async → attach_runtime`
path. `_build_pipeline`'s preset branches are gone.

### Phase 3 — Plan/03: VTuber↔Worker binding

| # | Repo | Title | Depends on | Release |
|---|------|-------|------------|---------|
| 18 | Geny | rename `cli_*` → `bound_worker_*` in `CreateSessionRequest` + all call sites | Phase 2 done | — |
| 19 | Geny | progress doc for #18 | #18 | — |
| 20 | Geny | reshape VTuber auto-pair block in `create_agent_session` (env_id resolution, explicit recursion guard, updated prompt) | #19 | — |
| 21 | Geny | progress doc for #20 | #20 | — |
| 22 | Geny | rewrite `backend/prompts/vtuber.md` delegation paragraph | #21 | — |
| 23 | Geny | progress doc for #22 | #22 | — |
| 24 | Geny | document BoundWorker contract in `backend/docs/` | #23 | — |
| 25 | Geny | progress doc for #24 | #24 | — |

**Exit criterion**: VTuber creation auto-spawns a bound Worker via
the env_id path; `session_type` values are `{"vtuber", "bound",
"solo"}`; delegation via `geny_send_direct_message` works.

---

## Release cadence for `geny-executor`

Two releases in this cycle:

- **v0.23.0** — purely additive. New events, no API surface
  change, no behavior change for consumers who ignore the new
  event types. Shipped during Phase 1.
- **v0.24.0** — adds `Pipeline.attach_runtime` and the
  worker_adaptive / vtuber manifest stage support. Also additive
  — existing env_id manifest consumers are unaffected. Shipped
  during Phase 2.

No v0.22.x patch releases unless a bug surfaces during Phase 1
execution.

---

## Progress doc conventions

Each code PR gets a companion "progress" markdown file in
`dev_docs/20260420_3/progress/`, landed in a **separate PR**
against Geny. Naming: `NN_<slug>.md` matching the sequence above.
The progress doc summarizes:

- What was implemented vs. what the plan said.
- Any deviations from the plan and why.
- What was deferred to a later PR (if anything).
- Pointers to the merged code PR(s) and the relevant test files.

This matches the 20260420_2 cycle's rhythm and keeps the history
auditable without bloating commit messages.

---

## What could go wrong

**A phase-1 revert invalidates phase-2 planning.** If PR #3's
event addition needs to be rolled back, PR #5 has no event to
consume. Mitigation: keep PR #1 and PRs #3/#5 in separate review
passes. PR #1 alone is a full fix for Bug A and can land before
any executor work starts.

**Phase-2 step #14 (delete the `if env_id:` gate) is the
biggest-blast-radius PR in the cycle.** It changes every session
creation. Mitigation: the preceding PRs (#10, #12) populate the
defaults, so by the time #14 lands the manifest path has been
exercised by whatever tests #10-#13 add. Also: #14's PR
description must include a reproduction checklist the reviewer
can run locally for each role.

**Phase-3 rename (#18) risks merge conflicts with long-lived
branches.** Mitigation: announce the rename in the PR
description and land it fast; the change is mechanical and the
PR should not need more than one review round.

---

## Aborting

If at any point the user decides the cutover is too aggressive,
the abort-safe points are:

- After Phase 1 (PR #6): `news_search` works, but the
  dual-path architecture remains. Acceptable long-term state.
- After Phase 2 PR #13: manifest stage templates exist but
  `_build_pipeline` still runs. Code is in an odd "both paths
  populated, preset path still used" state — **do not** stop
  here; push to #14 or revert to #13 cleanly.
- After Phase 2 PR #17: environment-only cutover complete, no
  VTuber binding changes yet. Acceptable long-term state; VTuber
  still works via existing CLI-pair code, which remains.
- After Phase 3: everything shipped.

Worst mid-PR state to avoid: between #13 and #14 (partial
preset-fill without consumption).
