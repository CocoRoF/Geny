# 05. Gap Analysis

**Status:** Draft
**Date:** 2026-04-24

02 + 03 의 현재-상태를 04 의 참조 패턴과 교차시켜 **우리가 메워야 할 격차** 를 축별로 정리하고 우선순위를 매긴다.

---

## 1. 축별 격차 매트릭스

### 축 A. Tool 계약

| 항목 | Geny | claude-code | 격차 |
|---|---|---|---|
| 이름/설명/스키마 | ✅ (`BaseTool.name/description/parameters`) | ✅ | — |
| 실행 메서드 | ✅ (`run`/`arun`) | ✅ (`call`) | — |
| **Concurrency 안전성 플래그** | ❌ | ✅ (`isConcurrencySafe`) | 🔴 |
| **Read-only 플래그** | ❌ | ✅ (`isReadOnly`) | 🔴 |
| **Destructive 플래그** | ❌ | ✅ (`isDestructive`) | 🔴 |
| **활성/비활성 플래그** | ❌ | ✅ (`isEnabled`) | 🟡 |
| **Permission 매처** | ⚠️ (server-prefix 필터만) | ✅ (input-pattern 매처) | 🔴 |
| **진행 callback** | ❌ | ✅ (`onProgress`) | 🟡 |
| **사용자 친화 이름** | ⚠️ (description) | ✅ (`userFacingName`) | 🟢 |
| **중단 동작** | ❌ | ✅ (`interruptBehavior`) | 🟡 |
| **자동 분류 힌트** | ❌ | ✅ (`searchHint`, `toAutoClassifierInput`) | 🟢 |
| **Result persistence** | ❌ | ✅ (`maxResultSizeChars`) | 🔴 |
| **UI 렌더링 메타** | ❌ | ✅ (React nodes) | 🟡 (Python 에선 다른 수단) |
| **MCP 메타** | ⚠️ (adapter 에 암묵) | ✅ (`isMcp`, `mcpInfo`) | 🟢 |

**종합 판정**: Geny 의 tool 계약은 "이름/스키마/실행" 수준에 머무름. **안전성·권한·예산** 메타데이터가 없어서 Stage 10 orchestration 이 모든 tool 을 동등하게 취급하게 됨.

### 축 B. Tool Orchestration

| 항목 | Geny Stage 10 | claude-code | 격차 |
|---|---|---|---|
| 순차 실행 | ✅ (`SequentialExecutor`) | ✅ | — |
| 병렬 실행 | ✅ (`ParallelExecutor`) | ✅ | — |
| **Tool-level partition** | ❌ (stage 단위 이분화) | ✅ (each tool 의 플래그로) | 🔴 |
| **Streaming tool executor** | ❌ | ✅ (수신 순 emit) | 🟡 |
| **Context modifier 적용** | ❌ | ✅ (`contextModifier`) | 🟡 |
| **Max concurrent cap** | ❌ (병렬이면 전부) | ✅ (기본 10) | 🟡 |
| **Sibling abort 격리** | ❌ | ✅ | 🟡 |

### 축 C. Permission

| 항목 | Geny | claude-code | 격차 |
|---|---|---|---|
| Role → server prefix | ✅ | — | (Geny-only) |
| Input pattern 매칭 | ❌ | ✅ (`preparePermissionMatcher`) | 🔴 |
| Source 계층 (user/project/local) | ❌ | ✅ | 🔴 |
| allow / deny / ask | ❌ (allow/deny 만 암묵) | ✅ | 🟡 |
| Per-tool rule | ⚠️ (frozen set) | ✅ (pattern) | 🟡 |
| Permission mode (plan/auto/bypass) | ❌ | ✅ | 🟡 |

### 축 D. MCP

| 항목 | Geny | claude-code | 격차 |
|---|---|---|---|
| stdio transport | ✅ | ✅ | — |
| HTTP transport | ✅ | ✅ | — |
| SSE transport | ✅ (legacy) | ✅ | — |
| **WebSocket transport** | ❌ | ✅ | 🟡 |
| **SDK-managed transport** | ❌ | ✅ (google-drive, github 등) | 🟡 |
| **Connection FSM** | ❌ (성공/실패 2상태) | ✅ (5상태) | 🟡 |
| **런타임 add/remove** | ❌ (프로세스 재시작) | ✅ (동적) | 🔴 |
| **OAuth 자동 흐름** | ❌ (`${TOKEN}` 만) | ✅ (callback port) | 🟡 |
| **XAA (Cross-app access)** | ❌ | ✅ | 🟢 |
| **Resource 지원** | ⚠️ (tool 만) | ✅ (tool + resource + prompt) | 🔴 |
| **Prompt 지원** | ❌ | ✅ (MCP skill bridge) | 🔴 |
| **재연결 로직** | ❌ | ✅ (reconnectAttempt) | 🟡 |
| **헬스체크** | ❌ | ⚠️ (연결 상태로 추적) | 🟡 |

### 축 E. Skills

| 항목 | Geny | claude-code | 격차 |
|---|---|---|---|
| 번들 skill 개념 | ❌ | ✅ (`registerBundledSkill`) | 🔴 |
| 디스크 skill (`.md` frontmatter) | ❌ | ✅ (`loadSkillsDir`) | 🔴 |
| MCP prompt → skill bridge | ❌ | ✅ | 🔴 |
| allowedTools 제한 | ❌ | ✅ | 🟡 |
| disable_model_invocation (즉시 실행) | ❌ | ✅ | 🟡 |
| `context: fork` (isolation) | ❌ | ✅ | 🟡 |
| whenToUse discovery hint | ❌ | ✅ | 🟢 |
| argumentHint | ❌ | ✅ | 🟢 |

**종합 판정**: Geny 에는 Skill 개념 자체가 없음. 최우선 고도화 항목.

### 축 F. Hooks

| 이벤트 | Geny | claude-code | 격차 |
|---|---|---|---|
| SessionStart | ⚠️ (`CREATED`) | ✅ | 🟢 |
| UserPromptSubmit | ❌ | ✅ | 🟡 |
| **PreToolUse** | ❌ | ✅ | 🔴 |
| **PostToolUse** | ❌ | ✅ | 🔴 |
| PostToolUseFailure | ❌ | ✅ | 🟡 |
| **PermissionRequest** | ❌ | ✅ | 🔴 |
| PermissionDenied | ❌ | ✅ | 🟡 |
| Stop / StopFailure | ❌ | ✅ | 🟡 |
| Notification | ❌ | ✅ | 🟢 |
| SubagentStart | ❌ | ✅ | 🟡 |
| FileChanged | ❌ | ✅ | 🟢 |

**인터페이스**: Geny 는 in-process Python callable. claude-code 는 subprocess + JSON I/O.

### 축 G. Agent / Task coordination

| 항목 | Geny | claude-code | 격차 |
|---|---|---|---|
| Subagent 개념 | ⚠️ (VTuber↔Sub-Worker pairing) | ✅ (`subagent_type`) | 🟡 |
| Background task | ⚠️ (`start_command_background`) | ✅ (`LocalAgentTask`) | 🟡 |
| **Worktree 격리** | ❌ | ✅ | 🔴 |
| **Task lifecycle FSM** | ⚠️ (status enum) | ✅ (pending/running/completed/failed/killed) | 🟡 |
| Subagent 권한 모드 override | ❌ | ✅ (`mode`) | 🟡 |
| Scratchpad 디렉토리 | ❌ | ✅ (옵션) | 🟢 |
| SendMessage 주소 지정 | ❌ | ✅ (`name` field) | 🟡 |

### 축 H. Observability

| 항목 | Geny | claude-code | 격차 |
|---|---|---|---|
| Event bus | ✅ | ✅ | — |
| 구조화된 event schema | ⚠️ (free-form dict) | ⚠️ (동일) | 🟡 |
| 실시간 UI | ❌ | ✅ (React ink) | 🟡 |
| 세션 히스토리 persistence | ⚠️ (session_logger) | ✅ (structured assistant log) | 🟢 |
| Mutation audit log | ✅ (`PipelineMutator.change_log`) | — | Geny 가 우위 |
| Stage introspection | ✅ (`introspect_all`) | — | Geny 가 우위 |

### 축 I. 16-stage 고유 사항

claude-code 에는 없는 우리만의 자산:

- Phase A/B/C 분리, Loop boundary 명시적
- Strategy slot + Slot chain
- Stage 단위 mutation audit
- Environment manifest 직렬화
- 4축 메모리 모델 (Layer × Capability × Scope × Importance)

이들은 **유지** 가 원칙. 단, 01 P1 의 완화에 따라 새 stage 삽입은 주요 version bump 와 migration tool 을 조건으로 허용 (cf. 10 design 의 "새 Stage 도입 가능성").

### 축 J. Built-in tool 카탈로그 (신설 축)

| Tool | Geny-executor 현재 | claude-code | 격차 |
|---|---|---|---|
| Read (파일 읽기) | ✅ | ✅ FileReadTool | — |
| Write (파일 작성) | ✅ | ✅ FileWriteTool | — |
| Edit (diff 기반 수정) | ✅ | ✅ FileEditTool | — |
| Bash | ✅ | ✅ BashTool | — |
| Glob (파일 패턴 매칭) | ✅ | ✅ GlobTool | — |
| Grep (내용 검색) | ✅ | ✅ GrepTool | — |
| **AgentTool** (subagent spawn) | ❌ | ✅ | 🔴 |
| **SkillTool** (skill 호출) | ❌ | ✅ | 🔴 |
| **TaskTool** (background task) | ❌ | ✅ TaskCreate/Get/List/Update/Output/Stop | 🔴 |
| **WebFetch** (URL 콘텐츠 가져오기) | ❌ | ✅ | 🔴 |
| **WebSearch** (검색엔진 질의) | ❌ | ✅ | 🔴 |
| **NotebookEdit** (jupyter) | ❌ | ✅ | 🟡 |
| **Todo list** (세션 내 todo 추적) | ❌ | ✅ TodoWrite | 🟡 |
| **Schedule/Cron** (스케줄링) | ❌ | ✅ CronCreate/List/Delete | 🟡 |
| **Monitor** (process 관찰) | ❌ | ✅ | 🟡 |
| **EnterPlanMode** (permission mode 전환) | ❌ | ✅ | 🟡 |
| **RemoteTrigger / Notification** | ❌ | ✅ | 🟢 |
| **MCPTool** (메타) | ⚠️ (manager 에 내장) | ✅ 일급 tool | 🟡 |
| **ToolSearch** (deferred tool fetch) | ❌ | ✅ | 🟢 |

**현재:** geny-executor 내장 6 종 / 호스트 (Geny) 가 추가 16 종 내외 주입 (web_search, browser, geny_tools, knowledge_tools, memory_tools, game tools 등).
**목표:** executor 내장 15–20 종 / 호스트 주입은 플랫폼 특화만 (세션·게임·캐릭터 관리).

**종합 판정:** 범용 tool 의 **소스 일원화** 가 핵심. 같은 웹 검색 로직을 Geny 가 구현하면, executor 를 쓰는 다른 프로젝트가 다시 구현해야 함. executor 에 올리면 한 번 구현으로 모두가 혜택.

---

## 2. 우선순위 매트릭스

각 gap 을 `(impact, effort, risk)` 로 평가.

| Gap | Impact | Effort | Risk | Priority |
|---|---|---|---|---|
| Tool ABC 메타 확장 (concurrency/destructive/permission/render) | 🔴 High | 🟡 Mid | 🟢 Low | **P0** |
| Tool-level partition orchestration (Stage 10) | 🔴 High | 🟡 Mid | 🟢 Low | **P0** |
| Result persistence budget | 🟡 Mid | 🟢 Low | 🟢 Low | P1 |
| Permission rule matrix (source × pattern) | 🔴 High | 🟡 Mid | 🟡 Mid | **P0** |
| Skills 시스템 (bundled + disk + MCP bridge) | 🔴 High | 🔴 High | 🟢 Low | **P0** |
| Subprocess hooks (PreToolUse / PostToolUse 등) | 🔴 High | 🟡 Mid | 🟡 Mid | P1 |
| MCP 런타임 add/remove | 🟡 Mid | 🟡 Mid | 🟢 Low | P1 |
| MCP transport 확장 (WS/SDK) | 🟢 Low | 🟡 Mid | 🟢 Low | P2 |
| MCP OAuth 자동화 | 🟡 Mid | 🔴 High | 🟡 Mid | P2 |
| MCP resource + prompt 지원 | 🟡 Mid | 🟡 Mid | 🟢 Low | P1 |
| Connection FSM | 🟢 Low | 🟢 Low | 🟢 Low | P2 |
| Subagent worktree 격리 | 🟡 Mid | 🔴 High | 🟡 Mid | P2 |
| Task lifecycle 통합 | 🟡 Mid | 🟡 Mid | 🟢 Low | P1 |
| Adaptive model routing | 🟡 Mid | 🟡 Mid | 🟢 Low | P1 |
| Structured output 계약 | 🟡 Mid | 🟢 Low | 🟢 Low | P1 |
| Streaming granularity (token level) | 🟢 Low | 🟡 Mid | 🟡 Mid | P2 |
| Human-in-the-loop approval | 🟡 Mid | 🔴 High | 🟡 Mid | P2 |
| Event schema taxonomy | 🟡 Mid | 🟢 Low | 🟢 Low | P1 |
| `state.shared` 스키마화 | 🟡 Mid | 🟢 Low | 🟢 Low | P1 |
| Live dashboard / UI | 🟢 Low | 🔴 High | 🟢 Low | P3 |

### P0 (Foundation — 반드시 먼저)

1. **Tool ABC 메타 확장**
2. **Tool-level partition orchestration**
3. **Permission rule matrix**
4. **Skills 시스템**
5. **Built-in tool 카탈로그 확장** (축 J) — Tool ABC 위에 얹혀야 하므로 1 완료 직후 시작

이 다섯 항목이 나머지 대부분의 선결 조건.

### P1 (Core capabilities)

5. Result persistence
6. Subprocess hooks
7. MCP runtime dynamism
8. MCP resource/prompt
9. Task lifecycle
10. Adaptive model routing
11. Structured output
12. Event schema taxonomy
13. `state.shared` 스키마화

### P2 (Expansion)

14. MCP transport 확장
15. MCP OAuth
16. Connection FSM 개선
17. Worktree 격리
18. Streaming granularity
19. HITL approval

### P3 (Polish)

20. Live dashboard UI

---

## 3. 의존성 그래프

```
         ┌──── Tool ABC 메타 ────┐
         │                      ├─▶ Stage 10 partition orchestration
         │                      ├─▶ Permission rule matrix
         │                      └─▶ Result persistence budget
         │
         │                          Skills 시스템 ─────┐
         │                                              ├─▶ 사용자 확장 friction 감소
         ├─▶ Subprocess hooks ───▶ Permission UI       │
         │                                              │
MCP runtime dynamism ──▶ MCP OAuth ──▶ MCP transport 확장
         │
         └──▶ MCP resource/prompt ──▶ Skill MCP bridge ─┘

Event schema taxonomy ──▶ Live dashboard
state.shared 스키마 ──▶ 모든 설계 문서의 근간
```

**Bottom-up 원칙**: Tool ABC (P0) 가 완료되지 않으면 Stage 10 partition 을 제대로 구현할 수 없고 (concurrency flag 읽을 곳이 없음), Permission rule 도 tool 의 메타 없이는 매처를 만들 수 없음.

---

## 4. 안 하기로 한 것 (Explicitly out of scope)

이 uplift 는 execution engine 에 집중. 다음은 **별도 cycle** 또는 **미결** 로 남김:

| 항목 | 이유 |
|---|---|
| React / ink UI | Python 백엔드 중심 고도화. 프론트는 별개 사이클. |
| Anthropic OAuth 2.0 대규모 자동화 | MCP 측만 OAuth 도입 (tier P2). Anthropic API 자체는 API key 모델 유지. |
| 분산 / multi-node orchestration | 현재 단일 프로세스. K8s 등 분산은 먼 미래 사이클. |
| Memory provider 구체 구현 (SQL, Redis, Vector) | 인터페이스만 이번 cycle. 구체 backend 는 이후. |
| Streaming STT / ASR 통합 | TTS 는 있지만 STT 는 미구현. 별개 범위. |
| A/B test framework | 일부 preset 에 유용하지만 실험 인프라 전체는 별개. |
| Multi-tenant / 사용자 격리 | 세션 단위 격리까지만. 테넌트 관리는 별개. |

### 4.1 이번 cycle 에서 **범위 내로 당긴 것** — 21-stage 재구성
- 10 design §13 의 5 개 후보 stage (Tool Review, Task Registry, HITL, Summarize, Persist) **전부 승격**.
- 16 → 21 stage 전환은 11 roadmap **Phase 9 (필수)** + 12 detailed plan 의 주차별 구현으로 수행.
- major version bump (`1.0.0`) 의 계기. v2 manifest auto-migration 포함.
- 근거: 기존 stage 에 두 책임 섞이는 구조적 부담 (Memory 에 summary 포함, Tool 에 review 포함 등) 을 한 번에 해소. 향후 5–10 년 운영 동안 "또 stage 추가 필요" 를 막는 보험.

---

## 5. 구조적 위험 (Design-level Risks)

### R1. Tool ABC 확장 시 기존 BaseTool 호환성
**위험**: 60+ 기존 built-in / custom tool 을 전부 새 ABC 로 마이그레이션하면 regression 가능성.

**완화**: 06 design 에서 **어댑터 전략** — 기존 BaseTool 은 기본값 (fail-closed concurrency=false 등) 으로 새 Tool ABC 에 자동 매핑. 점진적 opt-in.

### R2. Permission rule 도입 시 기존 세션 깨짐
**위험**: rule matrix 적용 기본값이 "deny" 면 기존 작업 중단.

**완화**: 초기 배포는 **warn-only mode** — rule 불일치 시 경고만, 실제 거부는 옵트인. 2–3 주 관찰 후 enforce.

### R3. Subprocess hook 보안 노출
**위험**: 사용자가 `settings.json` 에 임의 command 등록 → RCE.

**완화**:
- Hook 등록은 기본 **비활성** (opt-in per repo)
- 환경 변수 `GENY_ALLOW_HOOKS=1` 필수
- 로컬 파일 시스템 경로만 허용 (URL 스크립트 실행 금지)
- hook 이 입력 수정 시 diff 로그

### R4. MCP 런타임 add/remove 시 상태 일관성
**위험**: 실행 중인 세션이 참조하는 MCP 서버가 제거되면 tool call 실패.

**완화**:
- 서버 제거는 **graceful** (in-flight 요청 완료 대기)
- 제거 후 해당 서버의 tool 은 `isEnabled() → False` 로 soft-disable
- 다음 turn 부터 LLM 에 노출 안 됨

### R5. Skills 시스템의 LLM 오사용
**위험**: 사용자가 작성한 skill 이 의도치 않게 모든 턴에서 호출됨.

**완화**:
- `whenToUse` 프론트매터 필수 (명확한 trigger 힌트)
- `userInvocable: true` 기본값 → `/skill_name` 명시적 호출만
- 자동 trigger 는 `disableModelInvocation: false` + `userInvocable: false` 조합 시만

---

## 6. 다음 문서

- [`06_design_tool_system.md`](06_design_tool_system.md) — P0-1, P0-2, P1-result-persistence 를 담는 통합 설계
- [`07_design_mcp_integration.md`](07_design_mcp_integration.md) — P1~P2 의 MCP 항목
- [`08_design_skills.md`](08_design_skills.md) — P0-4 Skills 시스템
- [`09_design_extension_interface.md`](09_design_extension_interface.md) — hooks / permission / event / state.shared 통합
- [`10_design_stage_enhancements.md`](10_design_stage_enhancements.md) — Stage 별 고도화 (P1-adaptive model routing, structured output 등)
- [`11_migration_roadmap.md`](11_migration_roadmap.md) — P0 → P1 → P2 → P3 실행 순서
