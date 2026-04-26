# Cycle A + B Completion Report

**Period:** new-executor-uplift cycle A (executor 1.1.0) + cycle B (executor 1.2.0) + cycle C audit (PR-C.1).

**Total merged PRs:** 42 across two repositories.
- `geny-executor`: 26 PRs (A.* 19 + B.* 5 + release tags 2 + audit 1)  → tags `v1.1.0`, `v1.2.0`
- `Geny`: 16 PRs (A.* 11 + B.* 4 + frontend 3 — A.5.5 / A.6.2 / A.8.3 frontend)

**Test suite (executor):** 2706 passing, 8 skipped. Net +500+ tests since v1.0.0.
**Test suite (Geny):** new modules syntax-checked (`python3 -m py_compile`); CI runs unit tests in pipeline.

---

## What shipped

### Executor 1.1.0 (Cycle A)

Built-in tool catalog **13 → 33** (+20 tools across 4 priority buckets).

| Bucket | Adds |
|---|---|
| P0.1 Task lifecycle | TaskRegistry filter+streaming surface; FileBackedRegistry with tombstones; `geny_executor.runtime` (BackgroundTaskRunner + LocalBash/LocalAgent executors); AgentTool; six task tools |
| P0.2 Slash commands | SlashCommandRegistry + parser + types; 12 built-in commands (cost / status / help / memory / context / clear / cancel / compact / config / model / preset-info / tasks); markdown template loader for project / user discovery paths |
| P0.3 Tool catalog | AskUserQuestion / PushNotification / 4 MCP wrappers / 2 Worktree / LSP / REPL / Brief / Config / Monitor / SendUserFile / SendMessage; plus NotificationEndpointRegistry + `geny_executor.channels` (UserFile + SendMessage ABC + reference impls) |
| P0.4 Cron | CronJobStore ABC + InMemory + FileBacked impls; CronCreate/Delete/List tools; CronRunner asyncio daemon with idempotent fire semantics |

### Executor 1.2.0 (Cycle B)

| Bucket | Adds |
|---|---|
| P1.1 In-process hooks | `HookRunner.register_in_process(event, handler)` + `list_in_process_handlers`. In-process handlers run BEFORE subprocess hooks; blocking outcome short-circuits the spawn |
| P1.2 Auto-compaction | `FrequencyPolicy` ABC + `NeverPolicy` / `EveryNTurnsPolicy` / `OnContextFillPolicy` + `FrequencyAwareSummarizerProxy` |
| P1.3 Settings.json | `geny_executor.settings.SettingsLoader` (hierarchical JSON cascade with deep merge) + `register_section` schema registry |
| P1.4 Skill schema | `SkillMetadata.{category,effort,examples}` |
| P1.5 PLAN modes | `PermissionMode.ACCEPT_EDITS` + `PermissionMode.DONT_ASK` ASK→ALLOW promotion |

### Geny Cycle A adoption

| PR | What |
|---|---|
| A.5.0 | chore(deps): pin geny-executor 1.1.x |
| A.5.1 | SubagentType seed (worker / researcher / vtuber-narrator) |
| A.5.3 | `service/tasks/install.py` + lifespan attach + 10s graceful shutdown |
| A.5.4 | `controller/agent_tasks_controller.py` — 5 endpoints under `/api/agents/{sid}/tasks/` |
| A.5.5 | `frontend/src/components/tabs/TasksTab.tsx` + `backgroundTaskApi` client |
| A.6.1 | `service/slash_commands/install.py` — auto-installs 12 framework commands + discovery paths |
| A.6.2 | `controller/slash_commands_controller.py` (REST) + `frontend/src/components/SlashCommandAutocomplete.tsx` + `slashCommandApi` |
| A.7.1 | `service/notifications/install.py` — endpoint registry from yaml/env |
| A.7.2 | `service/notifications/install.py:install_send_message_channels` |
| A.8.2 | `service/cron/install.py` + lifespan ordering (cron BEFORE task on shutdown) |
| A.8.3 | `controller/cron_controller.py` (REST) + `frontend/src/components/tabs/CronTab.tsx` + `cronApi` |

### Geny Cycle B adoption

| PR | What |
|---|---|
| B.0  | chore(deps): pin geny-executor 1.2.x |
| B.1.3 | `service/hooks/in_process.py` — three observer handlers (permission_denied / high_risk_tool_call / observe_post_tool_use) + 256-slot ring buffer |
| B.3.3 | `service/settings/migrator.py` — one-shot YAML→settings.json with .bak per source |
| B.3.5 | `service/settings/install.py` + `PresetSection` + `VTuberSection` schemas |

### Cycle C audit

PR-C.1 ships 60+ parametric importability checks for every cycle A/B public surface plus explicit attribute checks for `HookRunner.register_in_process`, `SkillMetadata.{category,effort,examples}`, `PermissionMode.{ACCEPT_EDITS,DONT_ASK}`, `EDIT_TOOLS`, and the BUILT_IN_TOOL_CLASSES + BUILT_IN_TOOL_FEATURES enumerations. Catches `__init__.py` re-export drift before adopters chase a broken import.

---

## What did NOT ship (deferred)

| Bucket | Status |
|---|---|
| A.5.2 PostgresTaskRegistryStore | Deferred — InMemory + FileBacked cover dev / single-host prod; Postgres backend belongs in a follow-up that audits Geny's existing SQLAlchemy session management |
| A.8.1 PostgresCronJobStore | Same — InMemory + FileBacked are the reference impls shipped |
| B.3.4 install.py swap to settings.json | Deferred — migrator (B.3.3) ships, but rewriting `service/permission/install.py` + `service/hooks/install.py` to consume the loader is intentionally a separate PR that needs careful regression testing against the existing yaml flow |
| B.4.4 frontend skill metadata UI | Deferred — schema is on the backend (B.4.1); SkillPanel UI consumption is a small follow-up |
| B.5.3 frontend permission mode toggle | Deferred — modes are on the backend (B.5.1); UI dropdown is a small follow-up |
| B.6.x Worktree+LSP integration depth | Deferred — A.3.4 (Worktree tools) + A.3.5 (LSP tool) shipped; deeper executor-side workspace abstraction is its own design exercise |
| TabNavigation entries for TasksTab + CronTab | Deferred — components shipped; navigation wiring is a one-line follow-up that the operator can route alongside existing tabs |

None of the deferrals are blocking; each is a clean follow-up with no breaking-change risk.

---

## Operational deployment

### geny-executor

Two new minor releases tagged. No breaking changes vs 1.0.x — adopters can pin `geny-executor[web,cron]>=1.2.0,<1.3.0` and get every Cycle A+B surface.

`cron` extra (croniter) is opt-in: deployments that don't use the scheduling daemon stay lean.

### Geny backend

`backend/main.py` lifespan now wires (in this order on startup; reverse on shutdown):

1. Background task runtime (BackgroundTaskRunner) — ENV: `GENY_TASK_BACKEND=memory|file`, `GENY_TASK_STORE_PATH=...`, `GENY_TASK_MAX_CONCURRENT=8`
2. Notification + SendMessage channel registries (StdoutSendMessageChannel default + endpoint registry from `~/.geny/notifications.json` / `.geny/notifications.json` / `NOTIFICATION_ENDPOINTS` env)
3. Slash commands (auto-install of 12 + discovery paths under `~/.geny/commands/` and `.geny/commands/`)
4. Cron runtime (gated on task runner alive) — ENV: `GENY_CRON_BACKEND=memory|file`, `GENY_CRON_STORE_PATH=...`, `GENY_CRON_CYCLE_SECONDS=60`

New REST routers mounted:
- `agent_tasks_router` → `/api/agents/{sid}/tasks/...`
- `cron_router` → `/api/cron/jobs/...`
- `slash_router` → `/api/slash-commands` + `/api/slash-commands/execute`

All require `require_auth`. 503 surfaces when the corresponding runtime didn't install (e.g. broken backend).

### Geny frontend

Three new modules; nav wiring is a one-line follow-up:
- `components/tabs/TasksTab.tsx`
- `components/tabs/CronTab.tsx`
- `components/SlashCommandAutocomplete.tsx`

### Settings migration

Operators who currently use `~/.geny/permissions.yaml` / `hooks.yaml` / `notifications.yaml` should run the migrator once before bumping to executor 1.2.0:

```python
from service.settings.migrator import migrate_yaml_to_settings_json
print(migrate_yaml_to_settings_json())
```

The migrator backs up every source file (`.bak`) and the existing `~/.geny/settings.json` (`.json.bak`) so a rollback is one `mv` away.

### Smoke after deploy

```bash
docker compose build --no-cache backend
docker compose up -d backend
docker compose up -d --force-recreate nginx

# Quick smokes (replace SID with an active session id):
curl -X POST .../api/agents/<SID>/tasks \
     -H 'Cookie: session=...' \
     -d '{"kind":"local_bash","payload":{"command":"echo hi"}}'

curl .../api/cron/jobs

curl .../api/slash-commands
```

---

## Next cycle

Suggested cycle C+1 scope (after operating cycles A+B for ~1 week):

1. Postgres backends for TaskRegistry + CronJobStore (A.5.2 + A.8.1).
2. `install.py` swap to settings.json loader (B.3.4).
3. Frontend nav wiring for TasksTab + CronTab + SlashCommandAutocomplete in CommandTab.
4. Operational data audit: check ring buffer growth, cron miss rate, in-process hook latency vs subprocess baseline.
5. Worktree+LSP integration depth on the executor side (B.6.1).
