# 11. Migration Roadmap

**Status:** Draft
**Date:** 2026-04-24
**Horizon:** 8–12 주 (상황에 따라 유연)

06–10 의 설계를 **언제 / 어떤 PR 로 / 어떤 레포에** 적용할지.

---

## 1. 원칙

- **PR 단위는 작게.** 각 PR 은 단독 revert 가능해야 함 (`20260424_*` cycle 의 학습).
- **geny-executor first → Geny follow.** 모든 capability 는 executor 에 먼저 구현·배포. Geny 는 tool provider / manifest 변경 / pin 업데이트로 따라간다. PR cadence 는 항상 **executor PR → PyPI 릴리스 → Geny PR** 쌍으로 진행.
- **Backward compatible 우선.** 새 API 는 optional, 기존 호출 깨지 않음. 1–2 release 뒤에 legacy deprecation.
- **Observability 먼저.** Phase 1 말미에 새 event taxonomy 배포해 이후 phase 의 변경을 추적 가능하게 함.
- **Stage 수 변경은 major bump.** 01 P1 의 완화로 stage 추가가 가능하지만, 진행 시 `0.x → 1.0` / `1.x → 2.0` 같은 major version bump 필수 (Phase 9 참조).

---

## 2. Phase 개요

| Phase | 주제 | 기간 | Priority |
|---|---|---|---|
| **1. Foundation** | Tool ABC + Permission matrix + Event taxonomy | 2–3 주 | P0 |
| **2. Orchestration** | Stage 10 재작성 (partition + streaming + persistence) | 2 주 | P0 |
| **3. Built-in tool catalog** | Web/Agent/Task/Skill/Todo/Schedule/Monitor tool 을 executor 에 내장 | 3–4 주 | P0 |
| **4. Skills system** | SKILL.md + Stage 3/10/11 연동 | 2–3 주 | P0 |
| **5. Subprocess hooks** | PreToolUse / PostToolUse / PermissionRequest | 1–2 주 | P1 |
| **6. MCP uplift** | Transport 확장 + FSM + runtime add/remove | 2 주 | P1 |
| **7. Stage enhancements** | Guard / Parse / Agent / Memory 개선 | 3–4 주 | P1–P2 |
| **8. MCP advanced** | OAuth + Resource/Prompt bridge | 2 주 | P2 |
| **9. Stage addition (required)** | 5 stage 신설 (Tool Review · Task Registry · HITL · Summarize · Persist) + 번호 재조정 + v2 → v3 migration | 3–4 주 | P1 |
| **10. Observability** | Event-based dashboard | 3 주 | P3 |

**총 기대치:** 10–15 주 집중 작업. Phase 3 ↔ 4 는 병렬 가능 (Tool ABC 완료 후).

### 2.1 Phase 3 (Built-in catalog) 을 별도 Phase 로 분리한 이유

06 design 13 절에서 합의된 "geny-executor 가 15–20 종 기본 제공" 목표는 Tool ABC (Phase 1) 와 orchestration (Phase 2) 위에 올라간다. 이 양이 작지 않아 Skills / Hooks / MCP 와 병렬로 큰 단위 phase 가 필요. **executor 레벨 작업이 기본적으로 이 phase 에 몰리고**, Geny 측은 "자기가 구현해뒀던 범용 tool 을 executor 의 내장 대응품으로 교체" 하는 clean-up PR 만 따라붙인다.

---

## 3. Phase 1 — Foundation (P0, 2–3 주)

### 목표
Tool 계약 메타 + Permission rule matrix + 구조화된 Event taxonomy 도입. **나머지 모든 phase 의 선결 조건.**

### PR 리스트 (geny-executor)

| PR | 내용 | 추정 |
|---|---|---|
| E-1.1 | `Tool` ABC + `ToolCapabilities` / `ToolResult` / `PermissionDecision` 타입 신설 | 1 일 |
| E-1.2 | `LegacyToolAdapter` — 기존 BaseTool → 새 Tool ABC 래핑 | 1 일 |
| E-1.3 | `build_tool()` factory | 0.5 일 |
| E-1.4 | Stage 10 에 "tool 이 새 Tool ABC 인 경우" 분기 추가 (기존 동작 유지) | 1 일 |
| E-1.5 | Permission types (`PermissionRule` / `PermissionMode` / `evaluate_permission`) | 1 일 |
| E-1.6 | YAML loader for permissions | 0.5 일 |
| E-1.7 | `HookEvent` enum + Event schema docs | 0.5 일 |
| E-1.8 | geny-executor 릴리스 **0.32.0** | 0.5 일 |

### PR 리스트 (Geny)

| PR | 내용 | 추정 |
|---|---|---|
| G-1.1 | `requirements.txt` `geny-executor >=0.32.0,<0.33.0` | 0.1 일 |
| G-1.2 | `_GenyToolAdapter` 를 LegacyToolAdapter 위에서 다시 구축 | 0.5 일 |
| G-1.3 | `BaseTool` 에 `_capabilities` optional 속성 지원 | 0.5 일 |
| G-1.4 | 3 개 built-in tool (Read-유사 / Bash-유사 / Write-유사) 에 capability 선언 | 1 일 |
| G-1.5 | Permission YAML loader + 기본 rule set (`.geny/permissions.yaml`) | 1 일 |
| G-1.6 | Permission `PLAN` / `BYPASS` mode CLI/env flag | 0.5 일 |

### 성공 기준
- `grep "from geny_executor.tools import Tool"` → 새 API 가 실제 사용됨
- 3 개 tool 이 새 Tool ABC 로 선언, 나머지는 Legacy adapter 로 자동 래핑
- permission CLI: `geny run --permission-mode plan` 가 destructive 호출 시 ask 모드로

### Risk
- 기존 manifest 로 새 engine 로딩 시 tool 목록이 LegacyToolAdapter 로 변환되는지 반드시 round-trip 테스트
- PermissionRule YAML 파싱 에러가 세션 생성 자체를 막지 않게 (graceful fallback)

---

## 4. Phase 2 — Orchestration (P0, 2 주)

### 목표
Stage 10 을 partition + streaming + persistence 기반으로 재작성. Tool ABC 의 혜택이 실제 런타임에서 드러남.

### PR 리스트 (geny-executor)

| PR | 내용 | 추정 |
|---|---|---|
| E-2.1 | `partition_tool_calls()` + `orchestrate_tools()` | 1.5 일 |
| E-2.2 | Stage 10 새 artifact `partition_orchestrator/` + slot 등록 | 1 일 |
| E-2.3 | `StreamingToolExecutor` | 2 일 |
| E-2.4 | Result persistence (`_persist_large_result`) | 1 일 |
| E-2.5 | Tool lifecycle hooks 호출 (on_enter/on_exit/on_error) | 0.5 일 |
| E-2.6 | `max_concurrent` ConfigSchema + 튜닝 event | 0.5 일 |
| E-2.7 | geny-executor 릴리스 **0.33.0** | 0.5 일 |

### PR 리스트 (Geny)

| PR | 내용 | 추정 |
|---|---|---|
| G-2.1 | `geny-executor >=0.33.0,<0.34.0` | 0.1 일 |
| G-2.2 | Read-유사 / Grep-유사 / Glob-유사 tool 에 `read_only=True` / `concurrency_safe=True` 적용 | 0.5 일 |
| G-2.3 | Bash / Write / Edit 에 destructive capability 적용 | 0.5 일 |
| G-2.4 | `tool-results/` 저장 디렉토리 세션 storage 에 연결 | 0.3 일 |

### 성공 기준
- 세 read-only tool 을 동시에 요청하면 병렬 실행 (logs 확인)
- Bash 와 Read 섞여 들어오면 Bash 먼저 직렬, read 들은 그 후 병렬
- 10,000 line 반환하는 tool → `tool-results/{id}.json` 저장 + summary 만 LLM 에 전달

---

## 5. Phase 3 — Built-in Tool Catalog (P0, 3–4 주)

### 목표
executor 의 내장 tool 을 6 종 → 15–20 종으로 확장. geny-executor 가 "agent 가 할 법한 일반적인 일" 전부를 기본 제공하게 만든다. Geny 측에서는 플랫폼 특화 tool 만 남김.

### PR 리스트 (geny-executor)

| PR | 내용 | 추정 |
|---|---|---|
| E-3.1 | `built_in/` 디렉토리 재구성 (filesystem / shell / web / agent / task / notebook / workflow / meta) | 0.5 일 |
| E-3.2 | `get_builtin_tools()` + feature-flag 기반 조건 등록 | 0.5 일 |
| E-3.3 | `WebFetch` tool (httpx + markdownify) | 1 일 |
| E-3.4 | `WebSearch` tool (backend 추상: DDG 기본 + 옵션) | 1 일 |
| E-3.5 | `AgentTool` — subagent spawn (inline 모드 먼저) | 2 일 |
| E-3.6 | `SkillTool` — Phase 4 와 맞물림, 기본 구현 먼저 | 1 일 |
| E-3.7 | `TaskCreate / Get / List / Update / Stop / Output` — background task 레지스트리 | 2 일 |
| E-3.8 | `TodoWrite` — state.shared 기반 todo 리스트 | 0.5 일 |
| E-3.9 | `NotebookEdit` — jupyter ipynb 편집 | 1 일 |
| E-3.10 | `Schedule` / `CronCreate` / `CronList` / `CronDelete` — scheduling backend (기본 APScheduler) | 2 일 |
| E-3.11 | `Monitor` — background process 이벤트 스트림 | 1 일 |
| E-3.12 | `ToolSearch` — deferred tool schema fetch | 0.5 일 |
| E-3.13 | `EnterPlanMode` / `ExitPlanMode` — permission mode 전환 | 0.5 일 |
| E-3.14 | `EnterWorktree` / `ExitWorktree` — git worktree 진입·해제 | 1 일 |
| E-3.15 | `ToolProvider` Protocol + `Pipeline.from_manifest_async(tool_providers=[...])` 지원 | 1 일 |
| E-3.16 | 문서: built-in tool 카탈로그 + authoring 가이드 | 1 일 |
| E-3.17 | geny-executor 릴리스 **0.34.0** (Skills 전) — catalog 만 먼저 배포 | 0.5 일 |

### PR 리스트 (Geny)

| PR | 내용 | 추정 |
|---|---|---|
| G-3.1 | `geny-executor >=0.34.0` | 0.1 일 |
| G-3.2 | `GenyPlatformToolProvider` 신설 — `ToolProvider` Protocol 구현 | 1 일 |
| G-3.3 | 기존 `tools/custom/web_search_tools.py`, `web_fetch_tools.py`, `browser_tools.py` **삭제** 또는 deprecated 표시 — executor 의 WebFetch/WebSearch 로 대체 | 0.5 일 |
| G-3.4 | `ToolLoader` 를 provider 에 흡수 — custom tool 발견은 provider 내부로 이동 | 1 일 |
| G-3.5 | `Pipeline.from_manifest_async(tool_providers=[...])` 로 전환 — `adhoc_providers` legacy 는 1–2 릴리스 유지 후 제거 | 1 일 |
| G-3.6 | 플랫폼 특화 tool (feed / play / gift / talk / knowledge_tools / memory_tools / geny_tools) 을 새 Tool ABC 로 재작성 — `LegacyToolAdapter` 벗기기 | 3–5 일 |
| G-3.7 | Frontend: tool 카탈로그 UI 가 executor-built-in vs geny-platform 구분 표시 | 1 일 |

### 성공 기준
- `from geny_executor.tools.built_in import get_builtin_tools` → 15 종 이상
- Geny `backend/tools/custom/` 에 web_search/web_fetch/browser 파일 없음 (executor 대응품으로 대체됨)
- Geny `GenyPlatformToolProvider.list_tools()` 이 10 종 이하 (플랫폼 특화만)
- 기존 VTuber / worker 세션이 새 tool 셋으로 정상 동작 — regression 0

### Risk
- R3.1 `WebSearch` 의 DDG 백엔드가 rate limit 걸리면 기본 경험 나쁨 → `WebSearch` 에서 provider 를 pluggable 로 설계 (DDG / Brave / Tavily 등 교체 가능)
- R3.2 `Schedule` / `Cron` 의 scheduling backend 가 외부 프로세스 의존 (APScheduler) → executor 프로세스 재시작 시 pending job 이 사라짐. 영속화는 별도 Phase 로 미룸 (in-memory 기본).
- R3.3 Geny 기존 custom tool 삭제가 사용자 code 에 영향 → deprecated warning 로 1 릴리스 유예 후 제거

---

## 6. Phase 4 — Skills System (P0, 2–3 주)

### 목표
Skill 시스템 전체. **이번 uplift 의 사용자 체감 가장 큰 변화.**

### PR 리스트 (geny-executor)

| PR | 내용 | 추정 |
|---|---|---|
| E-4.1 | Skill 타입 + `SkillRegistry` + `register_bundled_skill` | 1 일 |
| E-4.2 | Frontmatter 파서 + `load_skills_dir` | 1.5 일 |
| E-4.3 | `SkillTool` Tool ABC 구현 (Phase 3 의 기본 구현을 확장) | 1.5 일 |
| E-4.4 | Stage 3 (`SkillCatalogSection`) + 시스템 프롬프트 통합 | 1 일 |
| E-4.5 | Stage 11 — Skill fork 경로 (Pipeline sub-spawn) | 2 일 |
| E-4.6 | 번들 skill 3 개 (`summarize-session`, `search-web-and-summarize`, `draft-pr`) | 2 일 |
| E-4.7 | geny-executor 릴리스 **0.35.0** | 0.5 일 |

### PR 리스트 (Geny)

| PR | 내용 | 추정 |
|---|---|---|
| G-4.1 | geny-executor upgrade | 0.1 일 |
| G-4.2 | `AgentSession` 에 `SkillRegistry` 주입 + user/project skill 디렉토리 로드 | 1 일 |
| G-4.3 | Slash command 파싱 (`/skill_name args`) → `SkillTool` 호출 | 0.5 일 |
| G-4.4 | Chat controller 가 slash 먼저 시도 → 실패 시 일반 broadcast | 0.5 일 |
| G-4.5 | Skill 관리 UI (minimal): 등록된 skill 목록 조회 API | 1 일 |

### 성공 기준
- `~/.geny/skills/my-skill.md` 파일 추가 후 재시작 없이 다음 세션에서 `/my-skill` 동작
- LLM 이 `SkillTool(skill="summarize-session")` 으로 자동 호출 가능
- `context: fork` skill 이 제한된 tool 집합으로 서브파이프라인 실행

---

## 7. Phase 5 — Hooks (P1, 1–2 주)

### PR 리스트 (geny-executor)

| PR | 내용 |
|---|---|
| E-5.1 | `HookRunner` + `HookOutcome` 구현 |
| E-5.2 | Stage 10 에 `PreToolUse` / `PostToolUse` fire |
| E-5.3 | Stage 4 (Guard) 에 `HookGateGuard` (`PermissionRequest` 이벤트) |
| E-5.4 | `load_hooks_config` YAML 로더 + 기본 disabled |
| E-5.5 | Hook audit log (`.geny/hooks-audit.log`) |

### PR 리스트 (Geny)

| PR | 내용 |
|---|---|
| G-5.1 | `GENY_ALLOW_HOOKS=1` 환경 변수 지원 |
| G-5.2 | 예제 hook 스크립트 3 종 (audit_log.sh, bash_pre_check.sh, slack_notify.sh) |
| G-5.3 | Hook admin API: `/api/hooks/list`, `/api/hooks/reload` |

### 성공 기준
- `GENY_ALLOW_HOOKS=1` 환경에서 Bash 실행 전 `pre_check.sh` 호출
- Hook 이 `{"continue": false}` 반환 시 tool 실행 block
- Timeout 시 hook 실패로 기록하되 tool 실행 계속 (기본 fail-open)

---

## 8. Phase 6 — MCP Uplift (P1, 2 주)

### PR 리스트 (geny-executor)

| PR | 내용 |
|---|---|
| E-6.1 | `MCPTransport` ABC + stdio / http / sse 재구성 |
| E-6.2 | WebSocket / SDK-managed transport 구현 |
| E-6.3 | `MCPConnection` FSM |
| E-6.4 | `MCPManager.register_server` / `unregister_server` / `disable` / `enable` |
| E-6.5 | MCP annotation → ToolCapabilities 자동 매핑 |
| E-6.6 | `attach_runtime(mcp_manager=...)` kwarg 추가 |

### PR 리스트 (Geny)

| PR | 내용 |
|---|---|
| G-6.1 | `MCPLoader.build_manager` 신설 |
| G-6.2 | `AgentSession._build_pipeline` 에서 manager 주입 |
| G-6.3 | Runtime MCP admin API (`POST /api/mcp/servers` 등) |
| G-6.4 | Frontend: MCP 서버 상태 리스트 (기본 조회) |

### 성공 기준
- 실행 중 `POST /api/mcp/servers {name, config}` → 해당 세션에서 새 tool 사용 가능 (다음 턴부터)
- MCP 서버 연결 실패 시 해당 tool 만 invisible, 다른 서버에 영향 없음
- `mcp.server.state` 이벤트가 UI 로 흐름

---

## 9. Phase 7 — Stage Enhancements (P1–P2, 3–4 주)

10 design 의 stage 별 개선 중 **비교적 독립적** 인 것들을 우선 작업. 각 PR 은 해당 stage 의 slot / strategy 추가 또는 chain 확장.

순서 (의존성 고려):

1. **Stage 3** — `PersonaSection` executor 내장 (Geny DynamicPersonaSystemBuilder 를 executor 로 승격)
2. **Stage 2** — `MCPResourceRetriever` (Phase 5 완료 후)
3. **Stage 9** — Structured output schema contract
4. **Stage 4** — `PermissionRuleMatrixGuard` (Phase 1 완료 의존)
5. **Stage 11** — `SubagentTypeOrchestrator` (Skill fork 와 공용 인프라)
6. **Stage 12** — Evaluator chain 격상
7. **Stage 13** — Multi-dimensional budget
8. **Stage 6** — Adaptive model router
9. **Stage 15** — Structured reflection schema
10. **Stage 8** — Adaptive thinking budget
11. **Stage 14** — Emitter ordering + backpressure
12. **Stage 16** — Multi-format yield

각 stage 개선은 1–3 일 규모 PR. 병렬 가능.

---

## 10. Phase 8 — MCP Advanced (P2, 2 주)

| PR | 내용 |
|---|---|
| E-8.1 | `OAuthFlow` 구현 (callback port + state) |
| E-8.2 | Keychain 기반 credential 저장 (OS 별) |
| E-8.3 | `MCPResource` 지원 + `mcp://` URI 해석 |
| E-8.4 | `mcp_prompts_to_skills` bridge (Phase 4 Skill 과 연동) |
| G-8.1 | Frontend: OAuth authorize URL 노출 UI |

### 성공 기준
- Google Drive MCP 서버 연결 시 브라우저 consent → 성공
- MCP prompt 로 정의된 skill 이 `SkillRegistry` 에 자동 등록

---

## 11. Phase 9 — Stage Addition (P1, 3–4 주) — **필수 phase**

10 design §13 의 결론에 따라 5 stage 를 모두 승격. 기존 16 → 21 stage 체제로 전환하는 **이번 uplift 의 최대 단일 변경**. major bump (`0.x → 1.0.0`) 의 계기이자 v2 → v3 manifest migration 의 boundary.

### PR 리스트 (geny-executor)

| PR | 내용 | 추정 |
|---|---|---|
| E-9.1 | **Stage 번호 재조정 scaffolding** — 빈 `s11_tool_review`, `s13_task_registry`, `s15_hitl`, `s19_summarize`, `s20_persist` 디렉토리 + Pass-through 기본 strategy | 2 일 |
| E-9.2 | **기존 stage rename**: `s11_agent → s12_agent`, `s12_evaluate → s14_evaluate`, `s13_loop → s16_loop`, `s14_emit → s17_emit`, `s15_memory → s18_memory`, `s16_yield → s21_yield` (git mv + import 치환) | 1 일 |
| E-9.3 | `core/pipeline.py` — `LOOP_END=16`, `FINALIZE_START=17`, `FINALIZE_END=21` 상수 + `_run_phases` 21-stage 경로 | 1 일 |
| E-9.4 | `core/introspection.py` — `_STAGE_CAPABILITY_MATRIX` 21 entry 확장 | 0.5 일 |
| E-9.5 | **Stage 11 Tool Review 구현** — SchemaReviewer / SensitivePatternReviewer / DestructiveResultReviewer / NetworkAuditReviewer / SizeReviewer + slot chain | 3 일 |
| E-9.6 | **Stage 13 Task Registry 구현** — InMemoryRegistry / EagerWait·FireAndForget·TimedWait policy + `state.tasks_by_status` | 3 일 |
| E-9.7 | **Stage 15 HITL 구현** — NullRequester (기본) + `Pipeline.resume(token, decision)` API + timeout policy | 4 일 |
| E-9.8 | **Stage 19 Summarize 구현** — RuleBasedSummarizer / LLMSummarizer + `state.turn_summary` + importance classifier | 2 일 |
| E-9.9 | **Stage 20 Persist 구현** — FilePersistStrategy / NoPersistStrategy + `Pipeline.resume_from_checkpoint` | 2 일 |
| E-9.10 | **Manifest v2 → v3 migration** — 자동 변환 + "migrated_from_v2" 메타 + backward compat loader (v2 입력도 load 가능) | 3 일 |
| E-9.11 | **기본 preset 전면 regen** — vtuber / worker_adaptive / worker_easy / default + 성장 단계 preset 들이 21-stage v3 로 저장 + 동작 검증 | 2 일 |
| E-9.12 | **새 이벤트 타입** — 5 개 신설 stage 의 stage.enter/exit · `task.registered` · `hitl.request` · `summary.written` · `checkpoint.written` | 0.5 일 |
| E-9.13 | **Capability tests** — 각 신설 stage 의 unit + integration + v2→v3 round-trip | 4 일 |
| E-9.14 | **Documentation sync** — Appendix A 파일 인덱스, 02 의 16→21 transition section, README | 1 일 |
| E-9.15 | geny-executor **1.0.0** 릴리스 (major bump) + CHANGELOG | 0.5 일 |

### PR 리스트 (Geny)

| PR | 내용 | 추정 |
|---|---|---|
| G-9.1 | `geny-executor >=1.0.0,<2.0.0` pin | 0.1 일 |
| G-9.2 | Geny 저장 preset 자동 migration 검증 — env store 의 기존 `data/environments/*.json` 전체를 v2 로 식별 → load 시 v3 자동 변환 | 1 일 |
| G-9.3 | Task Registry 의 `PostgresRegistry` strategy 구현 — Geny DB 에 background task 저장 | 2 일 |
| G-9.4 | HITL 의 `UIRequester` strategy 구현 — WebSocket 이벤트 방출 + 프런트 approval 페이로드 | 2 일 |
| G-9.5 | Persist 의 `PostgresPersistStrategy` strategy 구현 — Geny session_store 와 연동 | 2 일 |
| G-9.6 | `AgentSession.attach_runtime` — `hitl_requester`, `task_registry`, `checkpoint_persister` kwargs 추가 | 0.5 일 |
| G-9.7 | Frontend: stage 수 하드코딩 제거 — `len(introspect_all())` 로 동적 조회 | 1 일 |
| G-9.8 | Frontend: HITL 승인 UI (approve / reject / modify) | 2 일 |
| G-9.9 | Frontend: Task Registry 대시보드 (running / completed / failed 탭) | 2 일 |
| G-9.10 | Migration playbook 문서 — 운영자가 기존 Geny 배포를 1.0.0 로 업그레이드할 때 주의사항 | 1 일 |

### 성공 기준

- 기존 v2 preset 전부 v3 로 자동 migration 되어 동일 실행 결과 (round-trip regression 0)
- 21 stage 각각이 EventBus 로 enter/exit 이벤트 방출
- Tool Review 가 민감 패턴 (API key 등) 을 실제 차단 시나리오 1 개 이상
- Summarize 가 LTM 에 `SummaryRecord` 기록 → 다음 세션의 Context 가 retrieve
- Persist 가 crash 복구 시나리오 — SIGKILL 후 resume → 동일 상태
- HITL 이 승인 UI 이벤트 + resume API 동작

### Risk

- R9.1 — **Stage rename 과정에서 import 누락** → 빌드 실패. `grep -rn "from geny_executor.stages.s1[1-6]" ` 로 누락 탐지, CI 에 smoke test 포함.
- R9.2 — **v2 preset 자동 migration 실패** → 기존 사용자 세션 복구 불가. **Dry-run migration + backup** 필수. 문제 발생 시 v2 load 가 explicit error 로 상위 surfacing.
- R9.3 — **Resume API 의 race** — HITL 이 대기 중에 세션이 재시작되면 `resume_token` 이 손실될 수 있음. Persist (20) 가 HITL 대기 상태도 checkpoint 에 포함해야 complete recovery.
- R9.4 — **Phase 9 의 rollback 난이도** — PR 15+ 를 한 번에 되돌리기 어려움. Phase 9 를 2 subphase 로 분할: 9a (scaffolding + rename + no-op stage) / 9b (각 stage 실제 구현). 9a 가 main 에 들어간 상태에서 9b 를 PR 단위로 끊어 실행.

---

## 12. Phase 10 — Observability (P3, 3 주, 선택)

별도 frontend 프로젝트로 독립 가능.

- 실시간 이벤트 스트림 (WebSocket)
- Stage 상태 시각화 (16 Stage 그리드)
- Tool 실행 타임라인
- Token / cost 실시간 그래프
- Mutation audit log

**우선순위 가장 낮음** — 이번 uplift 의 핵심은 internal architecture. UI 는 별개 cycle 로 넘길 수 있음.

---

## 13. 의존성 그래프

```
Phase 1 (Foundation) ────┬──▶ Phase 2 (Orchestration)
                         │           │
                         │           ▼
                         │      Phase 3 (Built-in catalog) ─────┐
                         │           │                           │
                         │           ▼                           │
                         │      Phase 4 (Skills) ────────────────┤
                         │                                       │
                         ├──▶ Phase 5 (Hooks)                    │
                         │                                       │
                         └──▶ Phase 6 (MCP uplift) ──────────┬───┤
                                                              │   │
                                    ┌─────────────────────────┘   │
                                    ▼                             │
                              Phase 8 (MCP Advanced) ◀─────────────┘
                                    ▲
                                    │
                          Phase 7 (Stage Enhancements) — 병렬 가능
                                    │
                                    ▼
                          Phase 9 (Stage Addition — optional)
                                    │
                                    ▼
                              Phase 10 (Observability) — 선택
```

- Phase 3 (Built-in catalog) 과 Phase 4 (Skills) 는 직렬 — SkillTool 은 Phase 3 의 `AgentTool`/`TaskTool` 과 공용 인프라 사용
- Phase 5 (Hooks) / Phase 6 (MCP uplift) 은 Phase 1 (Foundation) 후 독립 진행 가능
- Phase 7 (Stage Enhancements) 이 Phase 9 (Stage Addition) 의 선결 — 기존 stage 개선으로도 해결 가능한 문제가 남는지 먼저 확인

---

## 14. 릴리스 전략

### geny-executor 버전

| 릴리스 | 내용 | Phase |
|---|---|---|
| `0.32.0` | Tool ABC + Permission matrix + Event taxonomy | 1 |
| `0.33.0` | Partition orchestrator + streaming executor + persistence | 2 |
| `0.34.0` | Built-in tool catalog 확장 (15–20 종) + ToolProvider 프로토콜 | 3 |
| `0.35.0` | Skill 시스템 | 4 |
| `0.36.0` | Subprocess hooks | 5 |
| `0.37.0` | MCP transport 확장 + FSM + runtime dynamism | 6 |
| `0.38.x` | Stage enhancements (여러 minor 릴리스) | 7 |
| `0.39.0` | MCP OAuth + Resource + Prompt bridge | 8 |
| **`1.0.0`** | **21-stage 전환 + v2→v3 migration** (major bump) | 9 |
| `1.1.x` | Observability + 안정화 | 10 (선택) |

### Geny 버전

Geny 자체는 semver 적용 엄격하지 않지만, `geny-executor` pin 을 updateable range 로 유지:
- Phase 1 후: `>=0.32.0,<0.33.0`
- Phase 2 후: `>=0.33.0,<0.34.0`
- ...
- 1.0 후: `>=1.0.0,<2.0.0`

각 pin 업데이트는 별도 PR + CI smoke 테스트 통과 후 머지.

---

## 15. 성공 메트릭 (Cycle-level)

- [ ] 기존 preset 전부 새 engine 으로 동작 (VTuber / worker_adaptive / worker_easy / default)
- [ ] 기존 built-in tool 100% 가 Legacy adapter 위에서 동작
- [ ] 30% 이상의 built-in tool 이 새 Tool ABC 로 재작성
- [ ] **executor 내장 tool 15 종 이상** — AgentTool / SkillTool / TaskTool / WebFetch / WebSearch / NotebookEdit / TodoWrite / Schedule / Monitor 등 포함
- [ ] Geny `backend/tools/custom/` 의 web 계열 도구 제거 (executor 대응품으로 대체)
- [ ] Geny `GenyPlatformToolProvider.list_tools()` 개수가 **플랫폼 특화 10 종 이하**
- [ ] 번들 skill 3 개 이상 + 사용자 디스크 skill 로딩 가능
- [ ] Subprocess hook 최소 1 시나리오 동작 (PreToolUse audit)
- [ ] MCP 서버 runtime add/remove 가능
- [ ] Permission matrix 동작 (plan mode 에서 destructive ask)
- [ ] 전체 regression 0 (기존 세션 재현 가능)

---

## 16. 관리 지침

- **각 Phase 시작 전** — 해당 Phase 의 "design 재확인" PR (docs 업데이트)
- **각 PR** — 이 문서의 PR ID 참조 (예: commit msg 에 `[E-1.2]`)
- **각 Phase 종료** — `executor_uplift/progress/phase_N_summary.md` 작성
- **문서 sync** — 실제 구현 시 design 에서 벗어나면 즉시 해당 design 문서 update
- **Geny 쪽 PR 은 executor 쪽 릴리스에 종속** — executor PyPI 퍼블리시 되기 전에는 Geny 측 대응 PR 을 머지하지 않음

---

## 17. 다음 문서

- Appendix:
  - [`appendix/a_file_inventory.md`](appendix/a_file_inventory.md) — 레포별 파일 경로 인덱스
  - [`appendix/b_terminology.md`](appendix/b_terminology.md) — 용어 정의 전체
  - [`appendix/c_prior_art.md`](appendix/c_prior_art.md) — LangChain / LangGraph / LlamaIndex / AutoGen 비교
