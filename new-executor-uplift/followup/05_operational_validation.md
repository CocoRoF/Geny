# 05 — Operational validation playbook

**Phase:** 2 (after frontend completion, before Postgres backends)
**PRs:** none (operational doc + dashboards)

---

## Why this exists

The cycle A+B closeout shipped 43 PRs. Some of the new surfaces
(BackgroundTaskRunner, CronRunner, in-process hook handlers,
settings.json loader) only show their behavior under production
load. Before adding the Postgres backends (Phase 3), confirm the
in-memory + file backends are healthy and the new lifespan order
hasn't introduced a slow-leak.

This file is the playbook — what to look at, what to compare
against, what to do when something is off.

---

## 1. Smoke checklist (run after every deploy)

Run these in order against a fresh deploy. Each step is independent;
a failure at one doesn't block the others, but each must be triaged.

### 1.1 Backend boots cleanly

```bash
docker compose logs backend --tail 50 | grep -E '(✅|⚠️|❌)'
```

Expected:
- ✅ task_runtime: BackgroundTaskRunner started
- ✅ notifications + messaging channels wired
- ✅ slash_commands: 12 available  (or higher if discovery dirs populated)
- ✅ cron_runtime: CronRunner started

If any line says ⚠️ or ❌, capture the full log line and triage
before moving on. ⚠️ on slash_commands or cron without task_runtime
is normal (cron gates on task; cycle B doc explains this).

### 1.2 New REST surfaces respond

Replace `<SID>` with an active session id:

```bash
COOKIE='session=...'

# Tasks
curl -s -H "Cookie: $COOKIE" .../api/agents/<SID>/tasks | jq '.tasks | length'
# expect: 0 on a fresh deploy

# Cron
curl -s -H "Cookie: $COOKIE" .../api/cron/jobs | jq 'length'
# expect: 0 on a fresh deploy

# Slash commands
curl -s -H "Cookie: $COOKIE" .../api/slash-commands | jq '.commands | length'
# expect: ≥ 12
```

A 503 means the corresponding runtime didn't install; check 1.1.

### 1.3 Round-trip a real task

```bash
TASK_ID=$(curl -s -X POST -H "Cookie: $COOKIE" \
  -H 'Content-Type: application/json' \
  -d '{"kind":"local_bash","payload":{"command":"echo hello"}}' \
  .../api/agents/<SID>/tasks | jq -r .task_id)

# Wait 2s
sleep 2

curl -s -H "Cookie: $COOKIE" .../api/agents/<SID>/tasks/$TASK_ID | jq .status
# expect: "done"

curl -s -H "Cookie: $COOKIE" .../api/agents/<SID>/tasks/$TASK_ID/output
# expect: "hello\n"
```

### 1.4 Round-trip a slash command

```bash
curl -s -X POST -H "Cookie: $COOKIE" \
  -H 'Content-Type: application/json' \
  -d '{"input_text":"/help"}' \
  .../api/slash-commands/execute | jq '.matched, .content[:80]'
# expect: true, "**Available slash commands**\n\n### Introspection..."
```

### 1.5 Frontend tabs render

Manual:
- visit web UI
- sidebar shows Tasks + Cron tabs (after PR-D.3.1)
- Tasks tab shows the task created in 1.3
- Cron tab shows empty list

---

## 2. Baseline metrics (collect once)

### 2.1 Hook latency: in-process vs subprocess

Goal: confirm cycle B's in-process handler API is actually faster.
Run this once per deploy with hooks enabled (`GENY_ALLOW_HOOKS=1`).

Method:
- enable a single subprocess hook on PRE_TOOL_USE that just `exit 0`
- enable an in-process handler doing the same thing (return None)
- fire 100 tool calls; measure mean wall-clock per fire
- expected: in-process ≤ 1ms per fire; subprocess ≥ 5ms per fire

If subprocess latency creeps above 50ms regularly, the box is
under load — separate ops issue.

### 2.2 Cron miss rate

Goal: confirm CronRunner.no-catch-up semantics aren't dropping
intended fires.

Method:
- create a `* * * * *` job that writes "fire $(date +%s)" to a file
- let it run for 30 minutes
- count actual fires in the file
- expected: 28-30 (allow ±2 for daemon restarts during deploy)

If miss rate >10%, investigate (likely the daemon's cycle_seconds
is set higher than 60).

### 2.3 Task runner throughput

Goal: confirm the asyncio runner doesn't block the FastAPI
request loop.

Method:
- submit 50 `sleep 1` tasks via /api/agents/.../tasks
- in parallel, hit /api/health every second
- expected: health responses unaffected; tasks complete within
  ~7s (with max_concurrent=8 default)

If health latency spikes >100ms during task burst, max_concurrent
might need to be lowered or the runner moved to a separate event
loop.

### 2.4 Slash command dispatch latency

Goal: confirm server-side dispatch is faster than the LLM round
trip it replaces.

Method:
- time `/cost` execute via /api/slash-commands/execute
- expected: <50ms (same machine, no LLM)
- compare against typical `cost` LLM-mediated response: ~2-5s

---

## 3. Monitoring queries (Grafana / similar)

Adapt to your metric backend. Names assume a generic prom/loki
stack.

### 3.1 Lifespan health

Boot success rate over 24h:
```promql
sum(rate(geny_lifespan_install_total{status="ok"}[24h]))
  / sum(rate(geny_lifespan_install_total[24h]))
```

Expected: 1.0. Anything < 0.99 means installs are failing on some
deploys.

### 3.2 Hook latency p99

```promql
histogram_quantile(0.99,
  rate(geny_hook_fire_duration_seconds_bucket[5m]))
```

Expected: < 0.05s for in-process handlers.

### 3.3 Task lifecycle counters

```promql
sum by (status) (rate(geny_task_status_change_total[5m]))
```

Expected: terminal statuses (done / failed / cancelled) sum
roughly equals submission rate.

---

## 4. Triage runbook

| Symptom | First check | Likely cause | Fix |
|---|---|---|---|
| Task stays "running" forever | Is BackgroundTaskRunner still alive? | Worker died; runner.shutdown() not fired | Restart backend |
| Cron fires twice | Two backend instances sharing the same FileBackedCronJobStore | File locking not enforced | Migrate to Postgres backend (Phase 3) |
| Slash command 503 | /api/slash-commands returns the same | get_default_registry() returned None | Check `geny_executor.slash_commands.built_in` import in lifespan log |
| Settings change doesn't take effect | Loader cache | Operator edited file; loader cached | Call `loader.reload()` (no endpoint yet — restart backend) |
| In-process hook handler not firing | `runner.list_in_process_handlers()` returns 0 | install_in_process_handlers wasn't called | Check lifespan order (must run after hook runner install) |

---

## 5. Decision gate for Phase 3 (Postgres backends)

Phase 3 starts when:

- [ ] 1 week of operational data shows zero file-backend corruption
- [ ] cron miss rate stays below 5% in 95% of hours
- [ ] task throughput baseline ≥ 50 tasks/minute sustained
- [ ] no daily error log noise from in-process hook handlers

If any of these fail, fix the underlying issue before adding the
Postgres complexity.

---

## 6. Done definition

This phase is complete when:

- [ ] smoke checklist runs green against the latest deploy
- [ ] all four baseline metrics captured + recorded in this file
- [ ] monitoring queries are deployed to the dashboard
- [ ] triage runbook table is reviewed by an oncall engineer
- [ ] decision gate (§5) is reviewed; phase 3 either starts or
      gets a clear blocker note
