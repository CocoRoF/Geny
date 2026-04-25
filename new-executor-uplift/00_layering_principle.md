# 00. Layering Principle — Built-in Core vs Extensible Interface

> **본 폴더의 가장 중요한 단일 axiom.** 모든 capability matrix · priority bucket · design sketch · PR 분해는 본 원칙에서 파생되고, 본 원칙과 충돌하면 본 원칙이 이김.

이 문서는 사용자의 다음 지시를 형식화한 것:

> "geny-executor 시스템은 built-in 로직 + 개별적인 확장성 있는 인터페이스를 제공하는 강력한 도구. 이 빌드인 부분에서 claude-code-main 을 아주 심층적으로 참고. geny 의 도구와 같은 것은 geny-executor 를 사용하는 서비스 레벨에서 구현. 그것을 확장성 있게 받아주는 인터페이스만 있으면 됨."

---

## 1. 두 레이어

```
┌────────────────────────────────────────────────────────────────────┐
│  Geny (service consuming geny-executor)                            │
│  ────────────────────────────────────────────                      │
│  도메인 / 사용자 / 운영 환경에 종속된 모든 것                       │
│                                                                    │
│  • Domain presets (worker_adaptive / vtuber / character)           │
│  • Service-specific slot impl (memory provider / knowledge /       │
│    skill registry adapter / persona / VTuber tick / etc.)          │
│  • Service-specific tools (web search / browser automation /       │
│    geny platform / send_dm / discord bridge)                       │
│  • REST API adapters (FastAPI controllers)                         │
│  • Frontend (React + Vite + Tailwind)                              │
│  • Storage backends (Postgres / SQLite / file system / MCP)        │
│  • Process lifecycle (FastAPI lifespan / docker compose / nginx)   │
│  • Auth / multi-tenant / billing                                   │
└────────────────────────────────────────────────────────────────────┘
                                │ uses
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│  geny-executor (framework)                                         │
│  ───────────────────────────                                       │
│                                                                    │
│  ▾ EXEC-CORE — built-in 표준 logic                                  │
│    (claude-code-main 을 1차 reference 로 두고 동등 수준 ship)        │
│                                                                    │
│    • 21-stage Pipeline + slot strategy ABC                         │
│    • Tool ABC + ToolCapabilities + ToolSandbox                     │
│    • Permission system (rule / mode / matcher / source hierarchy)  │
│    • Hook system (subprocess + in-process)                         │
│    • MCP transports (stdio/SSE/HTTP/WS/SDK) + FSM + OAuth + URI    │
│    • PartitionExecutor / StreamingRunner / EventBus                │
│    • PromptCache / ThinkingConfig / TokenAccounting / CostBudget   │
│    • Built-in tool catalog ★ claude-code 의 39 stable + 9 gated 중 │
│      Geny 도메인에 의미 있는 것 모두 (35+ 목표)                     │
│    • Slash command registry + parser + discovery hierarchy         │
│    • Standard slash command set (/cost /clear /status /help        │
│      /memory /context /tasks /cancel /compact /config /model)      │
│    • Task lifecycle primitives + background runner                 │
│    • Cron primitives + daemon                                      │
│    • Auto-compaction policy + trigger                              │
│    • Settings.json hierarchy loader (user / project / local)       │
│    • Skill loader (bundled + project + user + MCP)                 │
│    • SKILL.md schema + execution mode (inline + forked)            │
│    • CLAUDE.md / AGENTS.md context loader                          │
│    • Crash recovery (snapshot / restore primitive)                 │
│    • LSP integration                                               │
│    • Worktree integration                                          │
│    • REPL integration                                              │
│                                                                    │
│  ▾ EXEC-INTERFACE — 확장 표면 (서비스가 채워넣는 ABC + register API)│
│                                                                    │
│    • register_tool(ToolCls) — 추가 tool 주입                        │
│    • register_slash_command(SlashCmd) — 서비스 전용 명령             │
│    • SubagentTypeRegistry.register(descriptor) — sub-agent type    │
│    • MemoryProvider ABC + register_memory_provider                 │
│    • KnowledgeProvider ABC + register_knowledge_provider           │
│    • SkillLoader.add_path(Path) — 서비스별 skill 디렉토리 주입       │
│    • MCPManager.register_server(spec) — 런타임 MCP 추가             │
│    • HookRunner.register_in_process(event, handler) — 콜백 주입     │
│    • PermissionRuleSource ABC — 추가 rule source 주입               │
│    • CronJobStore ABC — cron persistence 백엔드 swap                │
│    • TaskRegistryStore ABC — task persistence 백엔드 swap           │
│    • SettingsSectionLoader — 추가 settings section 정의             │
│    • CredentialStore ABC — credential 저장 백엔드 swap               │
│    • PipelineMutator API — 런타임 manifest 수정                     │
│    • EventBus subscription — 옵저버빌리티 hook                      │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. 결정 트리 — "이 capability 는 어느 레이어에?"

```
질문 1: claude-code-main 의 src/ (built-in 영역) 에 존재하는가?
        ├─ YES → EXEC 레이어 강력 후보 (질문 2 로)
        └─ NO  → SERVICE 강력 후보 (질문 4 로)

질문 2: 다른 (가상의) 서비스 — 예: "claude-cli-2", "lemur-agent" — 가
        geny-executor 를 채택한다 했을 때, 그 서비스도 동일 capability
        를 필요로 하는가?
        ├─ YES → EXEC 레이어 (질문 3 로)
        └─ NO  → SERVICE (이 도메인의 특수 사항)

질문 3: 표준 동작이 명확한가? (= reference impl 이 의미가 있는가)
        ├─ YES → EXEC-CORE (built-in 으로 ship)
        └─ NO  → EXEC-INTERFACE (ABC + register API 만 노출, 구현은 서비스)

질문 4: 데이터 저장소 / IO 가 도메인 특화 (Postgres schema /
        VTuber state / character profile / 운영 디렉토리 이름) 인가?
        ├─ YES → SERVICE
        └─ NO  → 다시 질문 2 로 (놓친 framework 기능 가능성)

질문 5: REST endpoint / 웹 UI / FastAPI lifespan / 인증 / 멀티테넌트 인가?
        ├─ YES → SERVICE (Geny 의 어댑터 레이어)
        └─ NO  → EXEC 레이어
```

---

## 3. 분류 가이드 — 케이스별 정답

| Capability | 결정 | 사유 |
|---|---|---|
| **Tool & catalog** | | |
| Tool ABC + ToolCapabilities | EXEC-CORE | 모든 executor 사용자가 필요 |
| Read / Write / Bash / Edit / Grep / Glob / NotebookEdit | EXEC-CORE built-in | framework 표준 라이브러리 |
| AskUserQuestionTool | EXEC-CORE built-in | 표준 LLM→user 질문 (HITL slot 활용) |
| AgentTool | EXEC-CORE built-in | sub-agent spawn 표준 |
| TaskCreate / Get / List / Update / Output / Stop | EXEC-CORE built-in | 표준 task lifecycle |
| MCPTool / ListMcpResources / ReadMcpResource / McpAuth | EXEC-CORE built-in | MCP 는 framework 책임 |
| CronCreate / Delete / List | EXEC-CORE built-in | scheduling primitive |
| Worktree (Enter / Exit) / LSP / REPL | EXEC-CORE built-in | dev environment standard |
| Brief / Config / Monitor | EXEC-CORE built-in | introspection standard |
| PushNotificationTool | EXEC-CORE built-in (webhook abstract) | 표준 notification |
| SendUserFile | EXEC-CORE built-in (file slot 활용) | 표준 user IO |
| `register_tool()` API | EXEC-INTERFACE | 서비스가 도메인 tool 주입 |
| Geny 의 web_search / browser / send_dm / 캐릭터 tool | SERVICE | 도메인 / 외부 API 종속 |
| Geny 의 메모리 tool (memory_add / memory_search) | SERVICE | SQLite + 도메인 메타 |
| **Slash commands** | | |
| Parser + registry + discovery hierarchy | EXEC-CORE | framework concern |
| Bundled command set (`/cost /clear /status /help /memory /context /tasks /cancel /compact /config /model`) | EXEC-CORE built-in | introspection on executor state |
| `register_slash_command()` API | EXEC-INTERFACE | 서비스가 추가 |
| `/preset`, `/skill-id` dispatch | SERVICE | "preset" 과 skill list 는 도메인 개념 |
| `~/.geny/commands/` 디스커버리 디렉토리 이름 | SERVICE | "geny" 가 서비스 이름 |
| 디스커버리 메커니즘 (loader.add_path) | EXEC-INTERFACE | framework 의 path 주입 API |
| **Tasks** | | |
| Task lifecycle ABC + background runner (asyncio) | EXEC-CORE | framework runtime |
| TaskRegistryStore ABC | EXEC-INTERFACE | persistence 백엔드 swap |
| In-memory + file persister TaskRegistryStore | EXEC-CORE built-in | 표준 backend reference |
| Geny 의 Postgres TaskRegistryStore | SERVICE | 운영 데이터베이스 |
| `/api/agents/{id}/tasks` endpoint | SERVICE | REST 어댑터 |
| TasksTab.tsx | SERVICE | 웹 UI |
| FastAPI lifespan 에서 background runner 시작 | SERVICE | 프로세스 라이프사이클 |
| **Subagent** | | |
| SubagentTypeOrchestrator + descriptor schema | EXEC-CORE | framework |
| SubagentTypeRegistry.register() | EXEC-INTERFACE | 등록 API |
| "vtuber-narrator" / "worker-coder" descriptor | SERVICE | 도메인 페르소나 |
| **Cron** | | |
| Cron daemon (asyncio + croniter) + ABC | EXEC-CORE | framework runtime |
| CronJobStore ABC | EXEC-INTERFACE | persistence swap |
| File-backed CronJobStore (`~/.executor/cron.json`) | EXEC-CORE built-in | 표준 backend |
| Geny 의 Postgres CronJobStore | SERVICE | 운영 DB |
| `/api/cron/jobs` endpoint | SERVICE | REST 어댑터 |
| CronTab.tsx | SERVICE | 웹 UI |
| **Permissions** | | |
| Rule / mode / matcher / source hierarchy | EXEC-CORE | framework |
| `register_rule_source()` ABC | EXEC-INTERFACE | 추가 source 주입 |
| acceptEdits / dontAsk PLAN variants | EXEC-CORE | framework mode 확장 |
| Geny preset 의 default rule set | SERVICE | preset 별 정책 |
| **Hooks** | | |
| Subprocess + in-process runner | EXEC-CORE | framework |
| `register_in_process(event, handler)` | EXEC-INTERFACE | 콜백 주입 |
| 운영 audit.sh / Slack 알림 hook 설정 | SERVICE | 운영 도구 |
| **Skills** | | |
| SKILL.md schema + loader + execution mode (inline / forked) | EXEC-CORE | framework spec |
| SkillLoader path 주입 API | EXEC-INTERFACE | 서비스 디렉토리 추가 |
| `~/.geny/skills/` 디렉토리 이름 | SERVICE | "geny" 가 서비스 이름 |
| Bundled skill 3 종 (현재) | SERVICE | 서비스가 ship 할 skill 결정 |
| **MCP** | | |
| Transport (stdio/SSE/HTTP/WS/SDK) + FSM + OAuth + URI | EXEC-CORE | framework |
| `MCPManager.register_server(spec)` | EXEC-INTERFACE | 런타임 server 추가 |
| Geny 의 MCP 서버 목록 / OAuth credential | SERVICE | 도메인 + 운영 |
| **Settings** | | |
| settings.json hierarchy loader (user / project / local) | EXEC-CORE | framework |
| Section schema (permissions / hooks / skills / model / telemetry) | EXEC-CORE | framework standard |
| `register_section(name, schema)` | EXEC-INTERFACE | 서비스가 section 추가 |
| `~/.geny/settings.json` 디렉토리 이름 | SERVICE | "geny" |
| 기존 4 YAML → settings.json migrator | SERVICE (Geny 만 그 YAML 가짐) | 서비스 마이그레이션 |
| **Memory & Context** | | |
| MemoryProvider ABC + KnowledgeProvider ABC | EXEC-INTERFACE | 서비스가 backend 채움 |
| CLAUDE.md / AGENTS.md / .cursorrules 자동 로드 | EXEC-CORE | framework context loader |
| 자동 발견 paths 의 priority 순서 | EXEC-CORE | framework |
| Geny 의 SQLite memory backend | SERVICE | 운영 데이터 |
| **Auto-compaction** | | |
| Stage 19 + frequency policy (`on_context_fill`) | EXEC-CORE | framework |
| **Crash recovery** | | |
| Snapshot serialise / restore primitive | EXEC-CORE | framework |
| Snapshot store path (`~/.geny/agent_sessions/`) | SERVICE | "geny" |

---

## 4. 본 원칙이 priority 에 미치는 영향 (이전 추정 vs 수정)

| 항목 | 이전 (잘못된) 추정 | 수정 |
|---|---|---|
| AgentTool 추가 | Geny 의 `tools/built_in/agent_tool.py` 신설 | **geny-executor 의 built-in catalog 에 추가**. Geny 는 등록만. |
| Task* 6 tool | Geny 의 `tools/built_in/task_*_tool.py` × 6 | **geny-executor built-in × 6**. Geny 는 SubagentTypeRegistry seed + REST + UI. |
| Cron* 3 tool + daemon | Geny `service/cron/` 신설 | **geny-executor built-in tool × 3 + 표준 daemon ABC**. Geny 는 storage backend (file→Postgres swap) + lifespan attach + REST + UI. |
| Slash command parser + registry | Geny `service/slash_commands/` 신설 | **geny-executor 에 신설**. Geny 는 서비스 전용 명령 (`/preset`) 만 register. |
| 12 introspection 명령 (`/cost`, `/clear`, …) | Geny 의 12 핸들러 | **geny-executor built-in commands**. Geny 는 0건. |
| Worktree / LSP / REPL / Brief / Config / Monitor | Geny 의 8 tool 직접 구현 | **geny-executor built-in 으로 8 추가**. Geny 는 0건. |
| AskUserQuestion / PushNotification / MCP wrapper | executor PR 필요 (이전 분석에서 일부만 인지) | **모두 geny-executor 에**. Geny 는 webhook URL config 만. |
| Settings.json 패턴 | Geny `service/settings/loader.py` 신설 | **geny-executor 에 통합 loader + section ABC**. Geny 는 migrator + Geny 전용 section. |
| In-process hook | executor PR (이전과 동일) | 변동 없음 |
| Auto-compaction trigger | executor PR (이전과 동일) | 변동 없음 |
| Skill 풍부화 (category / examples / effort) | Geny 의 skill 로직 수정 | **geny-executor 의 SKILL.md schema 확장**. Geny 는 추가 field 사용처 wiring. |

**거시 효과**:
- 이전 추정: P0 14 PR 중 ~12 개가 Geny PR
- 수정 추정: P0 18 PR (executor 표면 늘어남) 중 **~12 개가 executor PR, ~6 개가 Geny PR**
- 의미: 다음 cycle 의 무게중심이 **geny-executor 레포로 이동**. Geny 측 작업은 "register / wire / UI / REST" 에 가까움.

---

## 5. 본 원칙이 누리는 두 이점

### 이점 1 — Reusability

`geny-executor` 가 강력한 framework 가 되면, Geny 외의 서비스 (사내 다른 서비스 / 사외 OSS 사용자) 도 동일 capability 를 즉시 누림. 모든 표준 tool / slash command / task lifecycle 을 register API 한 줄 없이 사용.

### 이점 2 — Service 의 단순성

Geny 는 본질적으로 도메인 (VTuber / character / worker preset) 에 집중. "Read tool 의 sandbox 처리" 같은 framework concern 이 service 코드를 오염시키지 않음.

---

## 6. Cross-repo cycle 운영 권장

1. **Executor PR → Geny PR 순서로 머지**: 의존성 한 방향 (Geny 가 executor 를 채택).
2. **Executor 의 minor bump (1.x → 1.x+1)** 단위로 묶음. Geny 의 `pyproject.toml` 에 새 minor 명시하는 동일 cycle 안에서 양 repo 작업.
3. **Executor PR description 에 "consumed by Geny PR #XXX" 표기** — 양방향 추적.
4. **Audit cycle 도 양 repo 동시 실행** — executor side 의 새 surface 도 audit 대상 (테스트 / docstring / API doc 갱신).
5. **Executor PR template 갱신**: "어떤 기존 EXEC-INTERFACE 를 추가/수정하는지 / 왜 EXEC-CORE 인지 / 왜 ABC 가 아니라 built-in 인지" 의 명시 항목.

---

## 7. 본 원칙의 anti-pattern (= 본 원칙 위반 신호)

다음을 발견하면 즉시 리뷰:

- **Geny 의 `tools/built_in/` 에 framework standard tool 추가** (Read / Bash / Worktree 등). 거의 항상 executor 로 가야 함.
- **Geny 에 slash command parser / dispatcher 자체 구현**. 거의 항상 executor 로.
- **Geny 가 `geny_executor.stages.s12_agent` 같은 internal 모듈을 직접 import 해서 mutating**. 거의 항상 EXEC-INTERFACE 가 부족하다는 신호 → executor 에 register API 추가.
- **Executor 에 "geny" 또는 도메인 단어 (vtuber / character / preset) 가 등장**. 거의 항상 SERVICE 로 가야 함.
- **Executor 의 ABC 가 Geny 외 서비스에서 의미 없는 method 포함**. 도메인 누출 — refactor 필요.

---

## 8. 다음 문서

- [`01_overview.md`](01_overview.md) — 본 원칙을 P0 (axiomatic) 로 추가, P7 갱신
- [`02_capability_matrix.md`](02_capability_matrix.md) — 53 항목에 Layer 컬럼 추가
- [`03_priority_buckets.md`](03_priority_buckets.md) — PR 분해를 (executor / Geny) 양 컬럼으로
- [`04_design_sketches.md`](04_design_sketches.md) — 각 design 을 (executor-side / interface / service-side) 3 단으로
