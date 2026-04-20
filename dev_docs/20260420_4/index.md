# 20260420_4 — Environment-first regression sweep

Cycle follow-up to 20260420_3. The environment-only cutover
(`plan/02_default_env_per_role.md` in the prior cycle) successfully
moved session creation onto `EnvironmentManifest`, but the switchover
introduced a set of regressions that the user flagged during actual
use:

> 현재 우리의 아키텍처를 Environment 기반으로 전부 수정하면서 기존
> GENY에서 수행하던 일들이 제대로 작동하지 않는 심각한 버그가 존재해.
> … ENVIRONMENT를 사용한다는 철학까지는 제대로 이식된 것으로 보여,
> 그러나 기존 GENY가 갖고 있던 built-in tool, 외부 도구 등 도구 사용의
> 관점에서 심층적인 조사가 필요해.

Three areas under investigation for this cycle:

1. **Tool execution is silently dropped** (Analysis/01). Default
   manifests emit stage lists with **orders 10 (tool), 11 (agent), and
   14 (emit) missing**. The executor silently bypasses any stage it
   does not find, so every tool call — including the VTuber's
   `geny_send_direct_message` delegation to its Sub-Worker — is parsed
   out of the LLM response and then never executed. **This is the
   headline bug.**

2. **env_id / role invisible in runtime logs** (Analysis/02). The
   SessionInfo API and InfoTab already expose `env_id`, `role`, and
   `session_type`, but the per-turn command/response log entries
   captured by `session_logger` carry none of those fields. Operators
   watching LogsTab cannot tell which environment or role is active
   without cross-referencing InfoTab.

3. **VTuber ↔ Sub-Worker binding audit** (Analysis/03). The binding
   appears to work in the happy path, but a deep audit surfaces two
   concurrency gaps (Sub-Worker result orphaning; trigger preemption
   missing — both already flagged in
   `docs/TRIGGER_CONCURRENCY_ANALYSIS.md`) and one silent-failure gap
   in Sub-Worker creation.

## Structure

```
dev_docs/20260420_4/
├── index.md                                ← you are here
├── analysis/                                research (this PR)
│   ├── 01_missing_stages_tool_execution.md  Stage 10/11/14 bypass → tools broken
│   ├── 02_env_id_role_logging_gap.md        env_id/role not in per-turn logs
│   └── 03_vtuber_sub_worker_binding_audit.md binding verification + concurrency
├── plan/                                    (next — after user review)
└── progress/                                (next — after plan approval)
```

## How to read this

- **Want the critical bug in one page?** Read `analysis/01`. Every
  other issue in this cycle is either a logging gap or a concurrency
  edge case; the stage-bypass is the bug that makes the product feel
  broken today.
- **Debugging a specific tool call that vanished?** `analysis/01` §4
  has the concrete path from LLM output → `pending_tool_calls` →
  silently dropped.
- **Reviewing the binding audit?** `analysis/03` has per-area
  verdicts (OK / BUG / RISK / GAP) with file:line citations.

## Review gate

Per the user directive from 20260420_3:
*"검토 후 진행한다."* Analysis docs are research only. No code has
been changed. Plan docs will be drafted after review of this
analysis, with the PR sequence to land the fixes.

## At a glance

| Finding | Severity | Surface affected | Analysis |
|---------|----------|------------------|----------|
| Stage 10 (tool) never registered for default envs | **CRITICAL** | All tool use on default envs | `analysis/01` |
| Stage 11 (agent), 14 (emit) never registered | **HIGH** | Multi-agent coordination, finalize phase | `analysis/01` |
| env_id/role missing from per-turn log entries | **LOW-MEDIUM** | Observability | `analysis/02` |
| Sub-Worker result can orphan in inbox | **HIGH** | Delegation reliability under load | `analysis/03` |
| Sub-Worker creation failure silently caught | **MEDIUM** | VTuber created without paired worker, no client signal | `analysis/03` |
| One-to-one invariant not enforced | **LOW** | Documented as acceptable; keep as-is | `analysis/03` |
