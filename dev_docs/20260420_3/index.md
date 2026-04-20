# 20260420_3 — VTuber failure fix + environment-only cutover

Cycle follow-up to 20260420_2. Started as a bug investigation
(VTuber sessions with no `env_id` fail on `news_search`), escalated
to a full architectural cutover per the user's directive:

> Geny의 모든 sessions 생성은 이제 전부 ENVIRONMENT 기반으로 바꿀거야
> (하위 호환성 신경쓰지 않아도 됨). VTuber는 대화를 위한 경량적
> ENVIRONMENT고, 나머지는 WORKER로 제대로 된 업무 수행을 위한 것이야.
> VTUBER는 이러한 Worker를 하나씩 자신과 BIND하여 가지고 있고, 그것을
> 활용할 수 있는 능력이 있는 것이 우리 GENY의 기본 철학이야.

Three outcomes for this cycle:

1. **Fix the VTuber `news_search` failure** (Plan/01) — two
   independent bugs, one in the Geny tool bridge, one in the
   executor's event vocabulary. Executor releases as v0.23.0.
2. **Cut session creation over to environment-only** (Plan/02) —
   no backward compatibility. Every session, regardless of role
   or entry point, is built from an `EnvironmentManifest`. Only
   two seed environments exist: `template-worker-env` and
   `template-vtuber-env`. Executor releases as v0.24.0 to add the
   `Pipeline.attach_runtime` helper this requires.
3. **Formalize the VTuber ↔ Worker binding** (Plan/03) — rename
   the existing "CLI-pair" scaffolding to `bound_worker`, wire it
   through the env_id resolver, define lifecycle invariants.

## Structure

```
dev_docs/20260420_3/
├── index.md                              ← you are here
├── analysis/                              research
│   ├── 01_vtuber_tool_failure.md         Bug A (session_id injection) + Bug B (logger)
│   └── 02_default_env_design_gap.md      why role→env default is missing today
└── plan/                                  proposed work (review-gated)
    ├── 00_overview.md                    master PR sequence across all plans
    ├── 01_immediate_fixes.md             Plan/01: PRs #1–#6 (unblock VTuber)
    ├── 02_default_env_per_role.md        Plan/02: PRs #7–#17 (env-only cutover)
    └── 03_vtuber_worker_binding.md       Plan/03: PRs #18–#25 (bound Worker)
```

## How to read this

- **Just want the fix for today's bug?** Read `analysis/01` and
  Plan/01. PR #1 alone restores `news_search` to working.
- **Planning the architecture change?** Start at `plan/00_overview.md`
  (the master checklist), then `plan/02` for the env cutover and
  `plan/03` for the VTuber binding.
- **Reviewing the proposal?** Every plan doc has a "non-goals"
  section at the bottom listing what is deliberately *not*
  changed. Check there first if something feels missing.

## Dependencies at a glance

```
Plan/01 PR #1 (Geny tool_bridge fix) ─┐
                                      │
Plan/01 PR #3 (executor v0.23.0) ─────┤
Plan/01 PR #5 (Geny pin + consumer) ──┘
                                      │
                          exit Phase 1 (news_search works)
                                      │
Plan/02 PR #7 (executor v0.24.0) ─────┤
Plan/02 PR #9 (Geny pin) ─────────────┤
Plan/02 PRs #10–#17 (env cutover) ────┘
                                      │
                          exit Phase 2 (no _build_pipeline)
                                      │
Plan/03 PRs #18–#25 (bound Worker) ───┘
                                      │
                          exit Phase 3 (cycle complete)
```

Two executor releases: `v0.23.0` (events only, additive) then
`v0.24.0` (attach_runtime + manifest stage templates, additive).
Neither is a breaking change.

## Review gate

Per the user: *검토 후 진행한다.* Planning documents are proposals.
No code has been written against any of these PRs yet. Approve
Plan/00's PR sequence before Phase 1 starts; re-approve between
phases if scope has drifted.
