# Cycle A+B Follow-up Plan

**Status as of:** 2026-04-26 (Cycle C audit closed at PR-C.2)

This folder is the execution plan for items intentionally deferred
out of cycles A+B. Each one was deferred for a clear reason
(needs design call, needs ops data, frontend dev env required) —
not because of carelessness.

Read [`../06_cycle_ab_completion_report.md`](../06_cycle_ab_completion_report.md) for the
full closing report. This index focuses on **what's left** and
**how to ship it**.

---

## 1. Total scope

| Plan file | Scope | Estimated PRs | Risk profile |
|---|---|---|---|
| [`01_postgres_backends.md`](01_postgres_backends.md) | Postgres TaskRegistryStore + CronJobStore | 4 | medium — needs Geny SQLAlchemy session model audit first |
| [`02_install_swap_to_settings.md`](02_install_swap_to_settings.md) | swap permission/hooks/skills install.py to settings.json loader | 3 | high — touches the existing yaml flow, regression risk |
| [`03_frontend_completion.md`](03_frontend_completion.md) | nav wiring + skill metadata UI + permission mode toggle + CommandTab autocomplete integration | 4 | low — additive frontend |
| [`04_workspace_depth.md`](04_workspace_depth.md) | executor-side workspace abstraction (B.6.x) | 3 | medium — design exercise, executor minor bump |
| [`05_operational_validation.md`](05_operational_validation.md) | smoke checklists + monitoring queries + ops data review playbook | (no code) | n/a |

**Total estimated:** 14 PRs across 4 work streams plus an ops
playbook.

---

## 2. Recommended execution order

**Phase 1 — Frontend completion** ([03](03_frontend_completion.md))

Lowest risk, highest user-visible value. Lands the TasksTab/CronTab
in the sidebar, exposes `category`/`effort`/`examples` in SkillPanel,
adds the permission mode dropdown, and integrates the slash autocomplete
into CommandTab. After this, every cycle A+B surface has a UI surface.

**Phase 2 — Operational validation** ([05](05_operational_validation.md))

Runs the smoke checklist against the freshly-deployed Phase 1 build,
captures baseline metrics (hook latency, cron miss rate, task throughput),
and authors the ops playbook. No code; outputs are dashboards + a
runbook.

**Phase 3 — Postgres backends** ([01](01_postgres_backends.md))

Once Phase 2 says the InMemory + FileBacked stores are holding up
under real load, add Postgres backends for both TaskRegistry and
CronJobStore. Includes Alembic migration, dual-write reconciliation,
and a rollout flag so operators can flip per-environment.

**Phase 4 — Install.py swap** ([02](02_install_swap_to_settings.md))

Highest regression risk — leave for last. Replace the per-feature
yaml installs (`service/permission/install.py` etc.) with the
unified `settings.json` loader path. Migrator (B.3.3) already
prepares the source files so the swap is purely about the
`install_*` callsites.

**Phase 5 — Workspace depth** ([04](04_workspace_depth.md))

Executor minor bump (1.3.0). Worktree + LSP + sandbox unify into
a `Workspace` abstraction so a sub-agent can spawn into an isolated
worktree with its own LSP context. Standalone executor work — Geny
adoption is a follow-on chore.

---

## 3. Cross-cutting conventions

Every PR in this folder follows the cycle A+B norms:

- single concern per PR (no rolled-up "fixes")
- structured error payloads (`{"error": {"code", "message"}}`) for
  any new tool / endpoint
- `require_auth` on every Geny REST endpoint
- backward compatible (no breaking changes vs the current minor)
- tests in same PR (no "tests follow")
- CHANGELOG entry for executor PRs
- 0 regressions on existing tests

PR title format: `<type>(<scope>): <subject> (PR-D.<n>.<m>)` —
the `D` namespace is reserved for follow-up cycle, distinguishing
from the A/B/C namespaces of the original cycles.

---

## 4. Done definition

The follow-up cycle is complete when:

- [ ] Every PR in plan files 01-04 is merged into its target branch
- [ ] The smoke checklist in 05 passes against the final build
- [ ] Operational metrics from 05 show no regression vs the cycle
      A+B baseline (hook latency, request latency, error rate)
- [ ] `06_cycle_ab_completion_report.md` is updated with a "Cycle D
      closeout" section listing each merged PR
