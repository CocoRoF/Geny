# 04. Design Sketches — Top Priorities (layer-aware)

각 priority 의 design 을 **(executor-side built-in / extension interface / service-side adoption)** 3 단으로 분리. [`00_layering_principle.md`](00_layering_principle.md) 의 axiom 적용.

---

## P0.1 — Task lifecycle 시스템

### 현 상태

- **executor 측**: `geny_executor.stages.s13_task_registry` 의 `TaskRegistry` Strategy ABC + `InMemoryRegistry` + `TaskPolicy` 3 strategy ship. **하지만 tool 자체는 없음.**
- **executor 측**: `geny_executor.stages.s12_agent` 의 `SubagentTypeOrchestrator` + descriptor / registry ship.
- **Geny 측**: 0건.

---

### 🔧 Layer 1 — geny-executor (built-in core)

```
geny_executor/
├─ tools/built_in/
│   ├─ agent_tool.py             ★ NEW
│   │   - AgentTool: SubagentTypeRegistry 의 type 으로 sub-pipeline spawn
│   │   - input: { subagent_type: str, prompt: str, model?: str }
│   │   - output: sub-pipeline 의 final assistant message
│   │
│   ├─ task_create_tool.py       ★ NEW
│   ├─ task_get_tool.py          ★ NEW
│   ├─ task_list_tool.py         ★ NEW
│   ├─ task_update_tool.py       ★ NEW
│   ├─ task_output_tool.py       ★ NEW
│   └─ task_stop_tool.py         ★ NEW
│       (모두 TaskRegistry slot 에 read/write — 새 ABC 노출)
│
├─ runtime/
│   └─ task_runner.py            ★ NEW
│       - asyncio.Task 기반 background runner
│       - TaskRunner.start_task(record) → asyncio.create_task
│       - Future 추적 + cancellation
│       - graceful shutdown (lifecycle hook)
│
└─ stages/s13_task_registry/
    ├─ store_abc.py              ★ NEW (EXEC-INTERFACE)
    │   class TaskRegistryStore(ABC):
    │       async def put(record: TaskRecord) -> None
    │       async def get(task_id: str) -> TaskRecord
    │       async def list(filter: TaskFilter) -> List[TaskRecord]
    │       async def update(task_id, **fields) -> None
    │       async def delete(task_id) -> None
    │       async def append_output(task_id, chunk: bytes) -> None
    │       async def read_output(task_id, offset?, limit?) -> bytes
    │
    └─ store_impl/
        ├─ in_memory.py          ★ NEW (reference, dev/test)
        └─ file_persister.py     ★ NEW (reference, single-process prod)
```

### 🔌 Layer 2 — Extension interface

`TaskRegistryStore` ABC + `register_task_store(store)` API. 서비스가 자체 backend (Postgres / Redis / SQS 등) 를 구현해서 swap.

`SubagentTypeRegistry.register(descriptor)` API (이미 ship). 서비스가 도메인 페르소나 등록.

### 📦 Layer 3 — Geny (service adoption)

```
Geny/
├─ service/agent_types/                 ★ NEW
│   ├─ __init__.py
│   ├─ registry.py                      
│   │   - 시작 시 SubagentTypeRegistry.register(...) × N
│   │   - "worker", "researcher", "vtuber-narrator", "code-coder" 등
│   └─ descriptors.py
│       - 각 type 의 default_model / default_tools / 1-line 설명
│
├─ service/tasks/                       ★ NEW
│   ├─ __init__.py
│   ├─ install.py
│   │   - install_task_runtime(pipeline, store=...) 
│   │   - executor 의 TaskRunner.start() + register_task_store(store)
│   ├─ store_postgres.py                 (운영 backend, optional)
│   │   - TaskRegistryStore impl using SQLAlchemy + 기존 Postgres
│   └─ lifespan.py
│       - FastAPI lifespan 에서 install_task_runtime 호출 + shutdown
│
├─ controller/agent_controller.py
│   └─ 5 신규 endpoint:
│       POST   /api/agents/{id}/tasks            (TaskCreate 호출 wrap)
│       GET    /api/agents/{id}/tasks            (TaskList 호출 wrap)
│       GET    /api/agents/{id}/tasks/{tid}      (TaskGet)
│       PATCH  /api/agents/{id}/tasks/{tid}      (TaskUpdate)
│       DELETE /api/agents/{id}/tasks/{tid}      (TaskStop)
│       GET    /api/agents/{id}/tasks/{tid}/output  (TaskOutput, streaming)
│
└─ frontend/src/components/tabs/TasksTab.tsx     ★ NEW
    - polling 기반 task list (5s interval)
    - 각 row: status badge / duration / output link
    - row 클릭 → TaskDetailModal (output preview + stop button)
```

### Test 전략 (양 repo)

| Repo | Test |
|---|---|
| executor | TaskRegistry 단위 테스트 (in-memory + file 양쪽) |
| executor | AgentTool 통합 테스트 (SubagentTypeRegistry mock) |
| executor | TaskRunner: asyncio.gather + cancellation |
| Geny | Postgres TaskRegistryStore round-trip |
| Geny | `/api/agents/{id}/tasks` endpoint stub |
| Geny | Frontend TasksTab polling state 머신 |

### 위험

- `in_process_teammate` task 는 동일 process 내 다른 session pipeline spawn — 세션 격리 / state 누출 위험. **첫 cycle 에서는 `local_bash` + `local_agent` 만 지원.**

---

## P0.2 — Slash commands 인프라

### 현 상태

- CommandTab 의 textarea 가 `/` prefix 검출 안 함
- SkillPanel 만 `/skill-id` 변환 (pure text replacement)
- `/cost`, `/clear`, `/status` 등 introspection 0개

---

### 🔧 Layer 1 — geny-executor (built-in core)

```
geny_executor/
├─ slash_commands/                      ★ NEW
│   ├─ __init__.py
│   ├─ registry.py
│   │   class SlashCommandRegistry:
│   │       def register(cmd: SlashCommand) -> None
│   │       def discover_paths(path: Path) -> None
│   │       def resolve(name: str) -> SlashCommand
│   │       def list_all() -> List[SlashCommand]
│   ├─ parser.py
│   │   def parse(input_text: str) -> Optional[ParsedSlash]
│   │   - prefix `/` 검출
│   │   - quoted args 처리
│   │   - 명령 이후 text 는 remaining_prompt
│   ├─ types.py
│   │   - SlashCommand dataclass (name / handler / description / category)
│   │   - ParsedSlash (command_name / args / remaining_prompt)
│   │
│   └─ built_in/                        (각 1 파일, 모두 EXEC-CORE)
│       ├─ cost.py        → 현 session token / cost 출력
│       ├─ clear.py       → message history 초기화
│       ├─ status.py      → session info dump
│       ├─ help.py        → 명령 목록
│       ├─ memory.py      → memory_provider.recent() 출력
│       ├─ context.py     → context_loader 가 보고 있는 파일들
│       ├─ tasks.py       → TaskList 의 결과 inline (P0.1 의존)
│       ├─ cancel.py      → pipeline.stop() (G2.5 의 stop API 활용)
│       ├─ compact.py     → Stage 19 manual trigger
│       ├─ config.py      → 현재 manifest active strategies 출력
│       ├─ model.py       → session 의 bound model 변경
│       └─ preset_info.py → 현 preset 의 metadata (값 변경은 Geny 의 /preset)
```

### 🔌 Layer 2 — Extension interface

- `SlashCommandRegistry.register(cmd)` — 서비스 전용 명령 추가
- `SlashCommandRegistry.discover_paths(path)` — 디렉토리 추가 (서비스가 `~/.geny/commands/` 같은 path 주입)
- 디스커버리 우선순위: **executor built-in > register() 호출 순서 > discover_paths 순서**

### 📦 Layer 3 — Geny (service adoption)

```
Geny/
├─ service/slash_commands/              ★ NEW (얇은 wrapper)
│   ├─ __init__.py
│   ├─ install.py
│   │   - install_slash_commands(registry):
│   │       registry.register(PresetCommand())          # /preset worker_adaptive
│   │       registry.register(SkillDispatchCommand())   # /skill-id (기존 SkillPanel 통합)
│   │       registry.discover_paths(Path("~/.geny/commands/").expanduser())
│   │       registry.discover_paths(Path(".geny/commands/"))
│   └─ commands/
│       ├─ preset.py       → SessionManager.switch_preset(name)
│       └─ skill_dispatch.py → 기존 skill_tool 호출
│
├─ controller/slash_command_controller.py  ★ NEW
│   GET  /api/slash-commands             — 사용 가능한 명령 목록
│   POST /api/agents/{id}/slash-commands — 명령 실행 (server-side dispatch)
│
└─ frontend/src/components/tabs/CommandTab.tsx
    - textarea onChange 에 `/` prefix 검출
    - 자동완성 드롭다운 (`/api/slash-commands` 결과)
    - 명령 실행 시 결과를 ExecutionTimeline 에 system message 로 inline render
```

### 디자인 결정

- **server-side dispatch** — claude-code 처럼 LLM 안 거치고 server 가 직접. 빠르고 cost 0.
- **출력 = system message 형태** — chat 흐름 안 깸.
- **discovery 우선순위**: executor built-in > Geny register > project (`.geny/commands/`) > user (`~/.geny/commands/`).
- **project / user 커스텀**: bash 스크립트 또는 prompt template (`.md` with frontmatter).

### 위험

- `/cancel` race condition — pipeline mid-stage 시 cancellation (이미 G2.5 의 cancel_pending_hitl 패턴).
- SkillPanel 의 `/skill-id` 와 충돌 — 명령 이름 namespace 분리 (built-in 짧은 이름, skill 은 일반 명사).

### Test 전략

| Repo | Test |
|---|---|
| executor | parser 단위 (다양한 prefix / arg 패턴) |
| executor | 12 built-in command 각각의 endpoint 테스트 |
| executor | discovery 우선순위 (built-in > register > path 순서) |
| Geny | `/preset` 명령이 SessionManager 에 정확히 도달 |
| Geny | `/api/slash-commands` 응답 shape |

---

## P0.3 — Built-in tool catalog 확장 (HIGH/MED 14개)

P0.1 (Agent / Task), P0.4 (Cron) 와 겹치지 않는 잔여 tool. **모두 EXEC-CORE → executor 측**.

### 🔧 Layer 1 — geny-executor (built-in core)

```
geny_executor/tools/built_in/
├─ ask_user_question_tool.py    ★ NEW
│   - HITL slot 활용 — Stage 15 의 awaiting_user_input 상태 trigger
│   - input: { question: str, options?: List[str] }
│   - output: user 의 response (REST 어댑터가 supply)
│
├─ push_notification_tool.py    ★ NEW
│   - webhook URL 호출 (settings.json:notifications.endpoints 에서 등록)
│   - retry policy / back-off 표준
│
├─ mcp_tool.py                  ★ NEW (MCP wrapper 4종)
├─ list_mcp_resources_tool.py   ★ NEW
├─ read_mcp_resource_tool.py    ★ NEW
├─ mcp_auth_tool.py             ★ NEW
│   - MCPManager API 의 LLM-facing wrapper
│   - input mcp:// URI 또는 server name + resource id
│
├─ enter_worktree_tool.py       ★ NEW
├─ exit_worktree_tool.py        ★ NEW
│   - git worktree add/remove + cd 안전성 (process cwd 비변경, sandbox 활용)
│
├─ lsp_tool.py                  ★ NEW
│   - pyright / tsc / rust-analyzer adapter
│   - input: { language: "python", action: "diagnostics" | "hover" | "definition", file, line, col }
│
├─ repl_tool.py                 ★ NEW
│   - python -c subprocess (sandbox 적용)
│   - timeout / output cap
│
├─ brief_tool.py                ★ NEW
│   - Stage 19 manual trigger 의 LLM-facing wrapper
│   - 자동 trigger 는 P1.2
│
├─ config_tool.py               ★ NEW
│   - PipelineMutator 의 LLM-facing wrapper
│   - 권한 가드 (settings.json:permissions 가드)
│
├─ monitor_tool.py              ★ NEW
│   - EventBus 구독 + filtered output
│
└─ send_user_file_tool.py       ★ NEW
    - file slot 표준 통과 (sandbox + size cap)
    - REST 어댑터가 user 에게 전달 (서비스가 channel 구현)
```

### 🔌 Layer 2 — Extension interface

- `notifications.endpoints` settings section (서비스가 webhook URL 주입)
- `SendMessageChannel` ABC (서비스가 Discord / Slack / send_dm 등 채널 구현)
- `UserFileChannel` ABC (서비스가 download URL 발행 / 직접 push 등)

### 📦 Layer 3 — Geny (service adoption)

```
Geny/
├─ settings.json (또는 분산 YAML 의 P1.3 통일 후)
│   notifications:
│     endpoints:
│       - { name: "vtuber-alert", url: "https://discord.com/api/webhooks/..." }
│
├─ service/channels/
│   ├─ send_message_channel.py          ★ NEW
│   │   - 기존 send_dm tool 의 채널 layer 분리 후 SendMessageChannel ABC impl
│   └─ user_file_channel.py             ★ NEW
│       - presigned URL or 직접 응답 stream
│
└─ frontend/
    - PushNotification 의 in-app banner 컴포넌트 (선택)
    - SendUserFile 결과 의 download UI
```

### Test 전략

- 각 tool 의 단위 테스트 (executor)
- AskUserQuestionTool 은 HITL flow 와 결합 — integration test (양 repo)

---

## P0.4 — Cron / scheduling

### 현 상태

ScheduleCronTool / CronCreate / Delete / List 0개. asyncio 기반 background runner 0개.

---

### 🔧 Layer 1 — geny-executor (built-in core)

```
geny_executor/
├─ cron/                        ★ NEW
│   ├─ __init__.py
│   ├─ types.py
│   │   - CronJob (name / cron_expr / target / payload / last_fired_at)
│   │   - ParsedCron (next fire time 계산)
│   ├─ store_abc.py             (EXEC-INTERFACE)
│   │   class CronJobStore(ABC):
│   │       async def put(job)
│   │       async def get(name)
│   │       async def list()
│   │       async def delete(name)
│   │       async def mark_fired(name, when)
│   ├─ store_impl/
│   │   ├─ in_memory.py
│   │   └─ file_backed.py       (~/.executor/cron.json — 디렉토리 이름은 framework 표준)
│   ├─ runner.py
│   │   - asyncio + croniter 로 다음 fire time 계산
│   │   - cycle check (idempotent fire — last_fired_at 비교)
│   │   - fire 시 TaskRunner 위임 (P0.1 통합)
│   └─ lifecycle.py
│       - start() / stop() — 서비스 lifespan 에서 호출
│
└─ tools/built_in/
    ├─ cron_create_tool.py      ★ NEW
    ├─ cron_delete_tool.py      ★ NEW
    └─ cron_list_tool.py        ★ NEW
```

### 🔌 Layer 2 — Extension interface

- `CronJobStore` ABC — 서비스가 운영 backend (Postgres) 로 swap
- `register_cron_store(store)` API
- `croniter` 의존성 — executor pyproject.toml 에 추가

### 📦 Layer 3 — Geny (service adoption)

```
Geny/
├─ service/cron/                       ★ NEW
│   ├─ __init__.py
│   ├─ install.py
│   │   - install_cron(store=PostgresCronStore())
│   │     → executor 의 register_cron_store + lifecycle.start()
│   ├─ store_postgres.py                (운영 backend, optional)
│   │   - SQLAlchemy table for cron_jobs
│   │   - 기존 Postgres connection 재사용
│   └─ lifespan.py
│       - FastAPI lifespan 에서 install_cron + shutdown
│
├─ controller/cron_controller.py       ★ NEW
│   GET    /api/cron/jobs
│   POST   /api/cron/jobs
│   DELETE /api/cron/jobs/{name}
│   POST   /api/cron/jobs/{name}/run-now    — adhoc trigger
│
└─ frontend/src/components/tabs/CronTab.tsx
    - 각 job: 다음 fire time / 마지막 실행 결과 / enable toggle
    - "Add job" 모달 (cron expression validator + prompt textarea)
```

### Cron daemon lifecycle

- main.py 의 lifespan 컨텍스트에서 시작 (서비스 책임)
- shutdown 시 graceful cancel (executor 의 lifecycle.stop)
- 신규 job 추가 시 in-memory registry 에 즉시 반영 (file watch 불필요)

### 위험

- Daemon 죽으면 모든 cron miss → keepalive (FastAPI lifespan + cycle check)
- 동일 cron 중복 fire → `last_fired_at` 으로 idempotent

---

## P1.1 — In-process hook callbacks

### 현 상태

`geny_executor.hooks.HookRunner` 가 subprocess 만 실행. claude-code 의 `registerHookEventHandler` 같은 in-process API 없음.

---

### 🔧 Layer 1 — geny-executor (built-in core, 작은 변경)

```python
# geny_executor/hooks/runner.py 에 추가
class HookRunner:
    def __init__(self, ...):
        self._in_process_handlers: Dict[HookEvent, List[Callable]] = {}
        # 기존 self._subprocess_entries: ...

    def register_in_process(self, event: HookEvent, handler: Callable):
        """Register in-process handler. Called serially before subprocess.
        Handler can return HookOutcome(blocked=True) to short-circuit.
        Handler exceptions are isolated — other handlers continue.
        """
        self._in_process_handlers.setdefault(event, []).append(handler)

    async def fire(self, event: HookEvent, payload: HookPayload) -> HookOutcome:
        # 1. in-process handler 들 직렬 실행 (block 가능)
        for handler in self._in_process_handlers.get(event, []):
            try:
                outcome = await _maybe_await(handler(payload))
            except Exception as e:
                logger.error("in_process_hook_failed", handler=handler, error=e)
                continue   # fail-isolation
            if outcome and outcome.blocked:
                return outcome
        # 2. subprocess (기존 로직)
        return await self._fire_subprocess(event, payload)
```

### 🔌 Layer 2 — Extension interface

`HookRunner.register_in_process(event, handler)` 자체가 EXEC-INTERFACE.

### 📦 Layer 3 — Geny (use case wiring)

- Permission denied event 에 in-process logger 등록 (subprocess 보다 latency 1000x ↓)
- TaskCreate 의 task 시작 시 in-process Future 등록 → subprocess 안 거치고 즉시 trigger
- Skill 실행 전 sandbox 검증 hook (subprocess 비용 절약)

### Test 전략

- in-process handler blocked=True → subprocess skip
- handler raise → 다른 handler 계속 실행 (fail-isolation)
- in-process / subprocess 순서 보장

---

## P1.3 — Settings hierarchy 통일 (settings.json 패턴)

### 현 상태

Geny 측 4 분산 source:
- `~/.geny/permissions.yaml`
- `~/.geny/hooks.yaml`
- `~/.geny/credentials.json`
- `~/.geny/skills/<id>/SKILL.md`

claude-code 는 단일 `~/.claude/settings.json` + project / local 위계.

---

### 🔧 Layer 1 — geny-executor (built-in core)

```
geny_executor/settings/                ★ NEW
├─ __init__.py
├─ loader.py
│   class SettingsLoader:
│       def __init__(self, paths: List[Path])
│       def load(self) -> SettingsDict
│       def get_section(name) -> Any
│       def reload(self) -> None
│   - 우선순위: local > project > user
│   - JSON merge (deep), array 는 concat or override (section spec 결정)
├─ schema.py
│   - 표준 sections:
│     • permissions (B 의 schema)
│     • hooks (C 의 schema)
│     • skills (user_skills_enabled 등)
│     • model (default / session_overrides)
│     • telemetry (enabled / endpoint)
│     • notifications (endpoints — P0.3 활용)
└─ section_registry.py            (EXEC-INTERFACE)
    def register_section(name: str, schema: Type[BaseModel]) -> None
```

### 🔌 Layer 2 — Extension interface

`register_section(name, schema)` — 서비스가 도메인 section 추가.

### 📦 Layer 3 — Geny (service adoption)

```
Geny/
├─ service/settings/                   ★ NEW
│   ├─ install.py
│   │   - install_settings():
│   │       loader = SettingsLoader([
│   │           Path("~/.geny/settings.json").expanduser(),
│   │           Path(".geny/settings.json"),
│   │           Path(".geny/settings.local.json"),
│   │       ])
│   │       register_section("preset", PresetSection)
│   │       register_section("vtuber", VTuberSection)
│   ├─ migrator.py
│   │   - 기존 4 YAML/JSON 자동 감지 → settings.json 생성 + backup
│   │   - 1회 실행, idempotent
│   └─ sections.py
│       - PresetSection / VTuberSection 정의
│
├─ service/permission/install.py       (수정)
│   - 기존 yaml.load 호출 → loader.get_section("permissions")
├─ service/hooks/install.py            (수정)
│   - 기존 yaml.load 호출 → loader.get_section("hooks")
├─ service/skills/install.py           (수정)
│   - GENY_ALLOW_USER_SKILLS env → loader.get_section("skills").user_skills_enabled
└─ service/credentials/install.py      (수정)
    - 기존 credentials.json → loader.get_section("credentials") 또는 별도 keep
```

### 단일 settings.json 예시

```json
// ~/.geny/settings.json (user)
// .geny/settings.json (project, optional, takes precedence)
// .geny/settings.local.json (local, gitignored, highest precedence)
{
  "permissions": {
    "mode": "advisory",
    "allow": [{ "tool": "web_fetch", "pattern": "*" }],
    "deny": [{ "tool": "memory_delete", "pattern": "*", "reason": "destructive" }]
  },
  "hooks": {
    "enabled": true,
    "entries": {
      "pre_tool_use": [{ "command": ["bash", "/path/to/audit.sh"], "timeout_ms": 500 }]
    }
  },
  "skills": { "user_skills_enabled": true },
  "model": { "default": "claude-haiku-4-5-20251001", "session_overrides": {} },
  "telemetry": { "enabled": false },
  "notifications": { "endpoints": [{ "name": "vtuber-alert", "url": "..." }] },
  "preset": { "default": "worker_adaptive" },           // Geny section
  "vtuber": { "tick_interval_seconds": 30 }              // Geny section
}
```

### Migration 정책

- migrator 가 기존 YAML 들 감지 → settings.json 으로 일회성 변환 + `.bak` 생성 + log warning
- 6개월 deprecation window 후 기존 YAML loader 제거
- env var (`GENY_ALLOW_USER_SKILLS` 등) 은 backward-compat 으로 유지 (settings.json 보다 우선)

### 위험

- 기존 운영 환경 YAML 들이 깨지면 안 됨 → migrator 가 1회 실행 후 backup 생성
- project / local 위계 도입 → multi-tenant 서비스라면 tenant별 격리 필요 (Geny 는 single-tenant 가정)

---

## 종합 (PR 수 / cycle / 양 repo 분포)

| Priority | 묶음 | executor PR | Geny PR | 합계 | cycle | 의존성 |
|---|---|---|---|---|---|---|
| P0.1 | Task lifecycle | 5 | 5 | 10 | A | Stage 12+13 (이미 ship) |
| P0.2 | Slash commands | 4 | 2 | 6 | A | 없음 |
| P0.3 | Tool catalog 14개 | 7 | 2 | 9 | A | MCPManager (이미 ship) |
| P0.4 | Cron + scheduling | 3 | 3 | 6 | A | P0.1 의 TaskRunner 와 통합 |
| **P0 합계** | | **19** | **12** | **31** | **A** | — |
| P1.1 | In-process hooks | 2 | 1 | 3 | B | — |
| P1.2 | Auto-compaction trigger | 1 | 0 | 1 | B | — |
| P1.3 | Settings.json 통일 | 2 | 3 | 5 | B | — |
| P1.4 | Skill schema 풍부화 | 3 | 1 | 4 | B | — |
| P1.5 | PLAN mode 확장 | 2 | 1 | 3 | B | — |
| P1.6 | Worktree+LSP depth | 2 | 1 | 3 | B | P0.3 |
| **P1 합계** | | **12** | **7** | **19** | **B** | — |
| **P0+P1 총합** | | **31** | **19** | **50** | **A+B** | |

**무게중심**: executor 31 PR (62%) / Geny 19 PR (38%). 거의 모든 framework concern 이 executor 로 이동.

**Top design** 후 capability matrix 의 wired 비율: ~85% → ~98% (P3 OUT_OF_SCOPE 제외).

---

다음 문서 [`05_appendix_inventory.md`](05_appendix_inventory.md) — claude-code-main 전체 surface inventory. P0/P1 외 항목 검토 시 lookup 용도.
