# 03. Priority Buckets — 권장 cycle 구조 (양 repo PR 분리)

**Source:** `02_capability_matrix.md` 의 53 항목을 의존성 그래프 + 영향도 + 사용자 도메인 적합도로 분류 + [`00_layering_principle.md`](00_layering_principle.md) 의 axiom 적용.

**핵심 변경 (이전 분석 대비):**
- PR 분해를 **(geny-executor PR / Geny PR)** 양 컬럼으로 명시
- 거의 모든 framework concern (tool 추가 / parser / daemon / loader) 을 **executor 측으로 이동**
- Geny PR 은 **register / wire / REST / UI / 운영 backend** 에 집중

---

## P0 — 다음 cycle 의 critical path

가장 큰 4개 격차. 본 cycle 부터 양 repo 동시 진행.

### P0.1 — Task lifecycle 시스템 ⭐ 단연 1순위

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** (1.1.x) | AgentTool built-in 추가 | 1 |
| **geny-executor** | TaskCreate/Get/List/Update/Output/Stop 6 tool built-in | 2 (3개씩 묶음) |
| **geny-executor** | TaskRunner (asyncio + Future tracking) + lifecycle hook | 1 |
| **geny-executor** | TaskRegistryStore ABC + in-memory + file backend (reference impl) | 1 |
| **geny-executor** subtotal | | **5** |
| **Geny** | SubagentTypeRegistry seed (worker / researcher / vtuber-narrator descriptor) | 1 |
| **Geny** | Postgres TaskRegistryStore (운영 backend) — optional, in-memory 로 시작 | 1 |
| **Geny** | `/api/agents/{id}/tasks` 5 endpoint (REST 어댑터) | 1 |
| **Geny** | TasksTab.tsx (frontend polling + status badge) | 1 |
| **Geny** | FastAPI lifespan attach (TaskRunner start/stop) | 1 (작은 변경, 다른 PR 과 합칠 수 있음) |
| **Geny** subtotal | | **5** |
| **합계** | | **10** |

**의존성**: executor 5 PR 모두 머지 → Geny 의 pyproject.toml 1.1.x 채택 → Geny PR 5 개.
**위험**: `in_process_teammate` task 는 첫 cycle 에서 deferred (세션 격리 미해결). `local_bash` + `local_agent` 만 ship.

---

### P0.2 — Slash commands 인프라

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | SlashCommandRegistry + parser + discovery hierarchy ABC | 1 |
| **geny-executor** | 12 introspection 명령 built-in (`/cost /clear /status /help /memory /context /tasks /cancel /compact /config /model /preset-info`) | 2 (6개씩 묶음) |
| **geny-executor** | project / user 디렉토리 디스커버리 path 주입 API | 1 |
| **geny-executor** subtotal | | **4** |
| **Geny** | SlashCommandRegistry 등록 + Geny 전용 명령 (`/preset`, `/skill-id` dispatch) | 1 |
| **Geny** | `~/.geny/commands/` + `.geny/commands/` 디렉토리 path 주입 | (위와 합침) |
| **Geny** | `/api/slash-commands` endpoint + CommandTab.tsx 의 `/` prefix 자동완성 | 1 |
| **Geny** subtotal | | **2** |
| **합계** | | **6** |

**의존성**: 없음 (P0.1 과 독립). executor 4 PR → Geny 2 PR.
**디자인 결정**:
- **server-side dispatch** — claude-code 처럼 LLM 안 거치고 server 가 직접 실행
- **출력 = system message** — chat 흐름 안 깸
- discovery hierarchy: **executor built-in > project > user**

---

### P0.3 — Built-in tool catalog 확장 (HIGH/MED)

P0.1 / P0.2 / P0.4 와 겹치지 않는 잔여 tool 들. **모두 EXEC-CORE → executor PR**.

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | AskUserQuestionTool (HITL slot 활용) | 1 |
| **geny-executor** | PushNotificationTool (webhook URL config) | 1 |
| **geny-executor** | MCPTool wrapper 4종 (MCPTool / ListMcpResources / ReadMcpResource / McpAuth) | 1 |
| **geny-executor** | Worktree 2 tool (Enter / Exit) | 1 |
| **geny-executor** | LSP / REPL / Brief / Config / Monitor / SendUserFile 6 tool | 2 (3개씩 묶음) |
| **geny-executor** | SendMessageTool ABC + reference channel | 1 |
| **geny-executor** subtotal | | **7** |
| **Geny** | webhook URL / channel impl config 주입 (settings.json section) | 1 |
| **Geny** | SendMessage channel impl (기존 send_dm 통합) | 1 |
| **Geny** subtotal | | **2** |
| **합계** | | **9** |

**의존성**: executor 7 PR → Geny 2 PR.

---

### P0.4 — Cron / scheduling

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | CronJobStore ABC + file-backed reference impl | 1 |
| **geny-executor** | CronCreate / Delete / List 3 tool built-in | 1 |
| **geny-executor** | Cron daemon (asyncio + croniter) + lifecycle hook | 1 |
| **geny-executor** subtotal | | **3** |
| **Geny** | Postgres CronJobStore (운영 backend) — optional, file 로 시작 | 1 |
| **Geny** | `/api/cron/jobs` 4 endpoint | 1 |
| **Geny** | CronTab.tsx (frontend) | 1 |
| **Geny** | FastAPI lifespan attach (Cron daemon start/stop) | (위와 합침) |
| **Geny** subtotal | | **3** |
| **합계** | | **6** |

**의존성**: executor 3 PR → Geny 3 PR. P0.1 의 background runner pattern 과 공유 (executor 내부에서 통합).
**위험**: Daemon 죽으면 cron miss → keepalive (FastAPI lifespan + cycle check). 동일 cron 중복 fire → registry `last_fired_at`.

---

### P0 합계

| Repo | PR 수 |
|---|---|
| geny-executor | 19 |
| Geny | 12 |
| **합계** | **31** |

→ **2 cycle 분할 권장** (cycle A = executor 위주, cycle B = Geny 위주).

---

## P1 — 후속 cycle

### P1.1 — In-process hook callbacks

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | HookRunner.register_in_process(event, handler) API + 직렬 실행 + fail-isolation | 1 |
| **geny-executor** | 단위 테스트 (in-process 가 blocked=True 반환 → subprocess skip) | 1 |
| **geny-executor** subtotal | | **2** |
| **Geny** | 운영 use case (Permission denied logger / TaskCreate Future trigger) wiring | 1 |
| **합계** | | **3** |

### P1.2 — Auto-compaction trigger

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | Stage 19 frequency policy 에 `on_context_fill` (>80%) 추가 | 1 |
| **Geny** | 변경 없음 (자동 동작) | 0 |
| **합계** | | **1** |

### P1.3 — Settings hierarchy 통일 (settings.json 패턴)

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | settings.json loader (user / project / local cascade) + section schema (permissions / hooks / skills / model / telemetry) | 1 |
| **geny-executor** | `register_section(name, schema)` ABC | 1 |
| **geny-executor** subtotal | | **2** |
| **Geny** | 기존 4 YAML → settings.json migrator (1회 실행 + backup) | 1 |
| **Geny** | 기존 install.py 들 (`service/permission`, `service/hooks` 등) 을 `loader.get_section()` 호출로 swap | 1 |
| **Geny** | Geny 전용 section (preset / vtuber config) register | 1 |
| **Geny** subtotal | | **3** |
| **합계** | | **5** |

### P1.4 — Skill 시스템 폼 풍부화

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | SKILL.md schema 확장 (category / examples / effort field) | 1 |
| **geny-executor** | execution mode `forked` impl (sub-process 격리 + state 마샬링) | 1 |
| **geny-executor** | MCP→skill 자동 변환 loader (advisory → 실작동) | 1 |
| **geny-executor** subtotal | | **3** |
| **Geny** | bundled skill 3 종 frontmatter 갱신 + frontend 의 새 field 표시 | 1 |
| **합계** | | **4** |

### P1.5 — Permission PLAN mode 확장

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | acceptEdits / dontAsk mode + flag/policy/session source ABC | 2 |
| **Geny** | 새 mode 의 frontend toggle + preset 의 default 정의 | 1 |
| **합계** | | **3** |

### P1.6 — Worktree + LSP integration depth

P0.3 의 단일 tool 로는 부족한 dev environment 통합.

| Layer | 작업 | PR 수 |
|---|---|---|
| **geny-executor** | Worktree 의 SubagentTypeOrchestrator 통합 (sub-agent 가 격리된 worktree 에서 실행) | 1 |
| **geny-executor** | LSP 의 multi-language adapter (pyright / tsc / rust-analyzer) | 1 |
| **Geny** | 코드 작업 worker preset 의 default Worktree 정책 | 1 |
| **합계** | | **3** |

**P1 합계**: ~19 PR (executor 11 + Geny 8). 1 cycle.

---

## P2 — long-tail

| 항목 | 작업 | Layer | PR 수 |
|---|---|---|---|
| E.16 — WebSocket transport for MCP | executor | EXEC-CORE | 1 |
| E.24 — SDK-managed MCP (InProcess plugin) | executor | EXEC-CORE | 2 |
| I.32 — tool 별 전용 web renderer | Geny | SERVICE | 8-10 |
| I.33 — spinner / progress hint UX | BOTH | EXEC-CORE (metadata) + SERVICE (wiring) | 2 |
| O.48 — WebFetch domain allowlist | executor | EXEC-CORE | 1 |
| K.40 — session 단위 model override | BOTH | 1 + 1 | 2 |
| R.51 — Coordinator mode (shared scratchpad) | executor | EXEC-CORE | 4 |
| S.52 — Plugin system (bundled plugin loader) | BOTH | EXEC-INTERFACE + SERVICE | 6-8 |
| K.41 — telemetry opt-out 검증 + section UI | BOTH | 1 + 1 | 2 |

**P2 합계**: ~30 PR. 큰 cycle 또는 분할.

---

## P3 — Out of scope (영구 제외)

| 항목 | 사유 |
|---|---|
| E.22 XAA (Cross-App Access) | Anthropic enterprise |
| E.23 SSE-IDE transport | standalone web app, IDE 확장 아님 |
| 16 Anthropic-internal tools | USER_TYPE='ant' gated |
| Coordinator mode 의 dream task | KAIROS-only |
| Ink TTY rendering | 웹 UI |
| PowerShellTool | Geny 는 Linux only |

---

## 권장 cycle 구조 (cross-repo)

```
Cycle A — new-executor-uplift / 20260426_1 (executor-heavy)
─────────────────────────────────────────────────────────────
geny-executor 레포 (모두 1.1.x bump 안에서):
  P0.1 executor portion             [5 PR]  ──┐
  P0.2 executor portion             [4 PR]    │── 18 executor PR
  P0.3 executor portion             [7 PR]    │   (~10일)
  P0.4 executor portion             [3 PR]  ──┘   release 1.1.0
                                              ─→  Geny pyproject.toml bump
Geny 레포:
  P0 Geny portion                  [12 PR]   ── 12 Geny PR
                                              (~7일, executor release 후)

Cycle 합계: 31 PR (executor 19 + Geny 12)


Cycle B — new-executor-uplift / 20260427_1 (mixed)
─────────────────────────────────────────────────────────────
geny-executor (1.2.x bump):
  P1.1 in-process hooks             [2 PR]   
  P1.2 auto-compaction trigger      [1 PR]   ── 11 executor PR
  P1.3 settings.json loader+ABC     [2 PR]   
  P1.4 skill schema 확장             [3 PR]   
  P1.5 PLAN mode 확장                [2 PR]   
  P1.6 Worktree/LSP depth           [1 PR]   
                                              ─→  Geny 1.2.x bump
Geny:
  P1 Geny portion                   [8 PR]   ── 8 Geny PR

Cycle 합계: 19 PR (executor 11 + Geny 8)


Cycle C — audit + carve-outs
─────────────────────────────────────────────────────────────
양 repo 의 audit cycle (executor_uplift/20260425_3 패턴 유지):
  - executor side audit (새 surface 의 테스트 / docstring / API doc)
  - Geny side audit (새 endpoint / UI / lifespan 의 회귀 검증)
  - 운영 데이터 1주 누적 후 감지된 결함 fix
```

각 cycle 종료마다 audit cycle 1번씩 — `executor_uplift/20260425_3` 의 패턴 유지.

---

## Cross-repo 운영 가이드 ([`00_layering_principle.md`](00_layering_principle.md) §6 참조)

1. **Executor PR 먼저 머지 → Geny 가 새 minor 채택**: 의존성 한 방향.
2. **Executor minor bump (1.x → 1.x+1)** 단위로 묶음. Geny `pyproject.toml` 에 새 minor 명시.
3. **Executor PR description 에 "consumed by Geny PR #XXX" 표기** — 양방향 추적.
4. **Audit cycle 도 양 repo 동시 실행**.
5. **Executor PR template 갱신**: "어떤 EXEC-INTERFACE 추가/수정인지 / 왜 EXEC-CORE 인지" 명시 항목.

---

## 실제 실행 시 고려할 외부 변수

1. **사용자 도메인 우선순위** — VTuber + worker 가 양분. 코드 worker (Worktree / LSP) 가 핵심이 아니면 P1.6 deferred. VTuber 가 핵심이면 P0.4 cron 우선순위 ↑.
2. **운영 데이터** — cycle 1+2 가 prod 떠 있으니 1주 운영 데이터 보고 시작 권장.
3. **claude-executor 의 다음 major bump** — 본 분석은 1.0.0 기준. P0/P1 에서 1.1 / 1.2 minor 두 번 발행.
4. **1 cycle 안에 양 repo 머지 부담** — executor PR 5+ 개를 동시 review 받기 어렵다면 P0 을 cycle A1 (executor) + cycle A2 (Geny) 로 더 분할.

다음 문서 [`04_design_sketches.md`](04_design_sketches.md) 에서 P0 의 4 묶음 + P1.1 / P1.3 의 layer 별 design sketch.
