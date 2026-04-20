# Plan/00 — Overview & PR sequence

Master checklist for the 20260420_4 cycle. Nine PRs across three
phases, each mapped to an Analysis document. Every PR is small,
atomic, and has its own progress doc on merge.

**Cycle goal.** Make tool execution work again on the
environment-based architecture, then make runtime behaviour
observable, then harden the VTuber ↔ Sub-Worker binding for
concurrent load.

**Non-goals.** No schema changes, no UI redesigns, no executor
protocol changes. The executor (v0.24.0+) is already correct;
the fix is entirely in Geny's manifest builder and surrounding
glue. No backwards-compatibility compromises — per prior cycle
directive *"하위 호환성 신경쓰지 않아도 됨"*.

---

## Phase 1 — Unblock tool execution (CRITICAL)

Fix `analysis/01_missing_stages_tool_execution.md`. Without this,
every subsequent observability/binding fix is cosmetic — the
system cannot take actions.

| # | PR subject | Branch | Progress doc |
|---|------------|--------|--------------|
| 1 | `default_manifest.py`: include stages 10 / 11 / 14 | `fix/manifest-tool-stages` | `progress/01_manifest_tool_stages.md` |
| 2 | Seed-env overwrite on boot (zero users → no preservation needed) | `fix/seed-env-overwrite` | `progress/02_seed_env_overwrite.md` |
| 3 | Integration smoke: end-to-end delegation round-trip test | `test/delegation-round-trip` | `progress/03_delegation_smoke.md` |

**Exit condition.** A fresh VTuber session can call
`geny_send_direct_message` and the Sub-Worker actually receives
the DM, executes, and replies. `Read` / `Write` / `Bash` work
from any worker role on `template-worker-env`.

Details: `plan/01_tool_execution_fix.md`.

---

## Phase 2 — Observability

Fix `analysis/02_env_id_role_logging_gap.md`. Lets the operator
tell *which environment and role* every log line came from —
essential for debugging the multi-agent flow and for confirming
Phase 1 stays fixed in production.

| # | PR subject | Branch | Progress doc |
|---|------------|--------|--------------|
| 4 | Creation event: add env_id / role / session_type / linked_session_id | `obs/creation-event-enrich` | `progress/04_creation_event_enrich.md` |
| 5 | Per-turn logs: thread env_id / role through `log_command` / `log_response` | `obs/per-turn-env-role` | `progress/05_per_turn_env_role.md` |
| 6 | LogsTab: sticky header showing session env / role / session_type | `obs/logstab-header` | `progress/06_logstab_header.md` |
| 7 | Delegation events: emit `delegation.sent` / `delegation.received` | `obs/delegation-events` | `progress/07_delegation_events.md` |

**Exit condition.** Opening any session's LogsTab shows env_id,
role, and session_type in a header band; every per-turn entry
carries env_id + role metadata; VTuber → Sub-Worker delegation
appears as explicit events, not buried in message text.

Details: `plan/02_observability.md`.

---

## Phase 3 — Binding hardening

Fix `analysis/03_vtuber_sub_worker_binding_audit.md`. Two real
defects exist under concurrent load; this phase closes them.

| # | PR subject | Branch | Progress doc |
|---|------------|--------|--------------|
| 8 | Atomize VTuber+Sub-Worker creation (rollback partial VTuber) | `fix/atomic-vtuber-pair` | `progress/08_atomic_vtuber_pair.md` |
| 9 | Inbox auto-drain in `execute_command()` finally block | `fix/inbox-auto-drain` | `progress/09_inbox_auto_drain.md` |

**Exit condition.** If Sub-Worker creation fails, the VTuber is
not left in a half-created state. If a Sub-Worker reply arrives
while the VTuber is busy, the reply is drained from inbox and
executed automatically on completion of the current turn.

Details: `plan/03_binding_hardening.md`.

---

## Dependencies

```
PR #1  (manifest stages) ─┐
                          │
PR #2  (seed migration) ──┼─→ exit Phase 1 (tools work)
                          │
PR #3  (smoke test) ──────┘
                          │
PR #4  (creation event) ──┐
PR #5  (per-turn logs) ───┼─→ exit Phase 2 (observable)
PR #6  (LogsTab header) ──┤
PR #7  (delegation events)┘
                          │
PR #8  (atomic pair) ─────┐
PR #9  (inbox drain) ─────┴─→ exit Phase 3 (concurrent-safe)
```

Phase 1 must merge in order (2 depends on 1's builder producing
the new shape; 3 depends on both). Phase 2 and Phase 3 PRs are
mutually independent within each phase and can be parallelized
in review.

---

## Review gate

Per the user's directive carried from 20260420_3: *"검토 후
진행한다."* This overview plus the three phase plans constitute
the proposal. No code has been written against any of these
PRs. Approve the PR sequence before PR #1 opens; re-approve
between phases if scope drifts.

Continuous-PR cadence applies per the user's durable instruction
— each PR lands with its own progress doc in a single push.

---

## Out of scope for this cycle

- Trigger-abort mechanism (Scenario A in
  `TRIGGER_CONCURRENCY_ANALYSIS.md`). User-messages being
  rejected as "busy" during thinking-triggers is real but
  separable from tool execution; owns its own cycle.
- One-to-one binding enforcement at the session manager.
  Documented as acceptable in `backend/docs/SUB_WORKER.md:27–28`;
  revisit only if a misuse is observed in logs.
- Manifest schema bump / version field. The existing
  `manifest.version = "2.0"` is untouched; migrations key off the
  presence/absence of the three tool stages directly.
- OpenTelemetry / distributed tracing. Too big for this cycle.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-04-20 | Initial plan drafted from analysis/01–03. |
