# 01. Overview — Goals · Principles · Success Criteria

**Status:** Draft
**Date:** 2026-04-24

---

## 1. Uplift 의 목표

Geny + geny-executor 는 이미 "16-stage 듀얼 추상화" 라는 견고한 뼈대를 갖고 있음. 이번 uplift 의 목표는 **뼈대를 바꾸는 것이 아니라**, 그 위에 다음을 얹는 것:

1. **풍부한 Tool 계약** — 동시성·파괴성·permission·lifecycle·UI 메타를 한 곳에 품은 단일 Tool ABC
2. **Built-in tool 카탈로그 확장** — 현재 executor 에 내장된 6 종 (Read/Write/Edit/Bash/Glob/Grep) 을 claude-code 수준 (15–20 종) 으로 확장. WebFetch, WebSearch, AgentTool, SkillTool, TaskTool, NotebookEdit, Todo, Schedule/Cron, Monitor 등 "범용" tool 은 executor 가 기본 제공
3. **성숙한 MCP 통합** — stdio/SSE/HTTP/WS/SDK 전송 + OAuth + 런타임 재연결 + health
4. **Skill 시스템** — 코드 수정 없이 프롬프트·도구 묶음을 추가할 수 있는 `SKILL.md` 기반 확장점
5. **통합 Extension Interface** — config / strategy / slot / mutation / event / hook / runtime-attach 가 일관된 멘탈 모델로 묶임
6. **각 Stage 별 고도화** — Guard(4), Tool(10), Agent(11→12), Memory(15→18) 등 실행 품질이 직접 걸리는 Stage 를 한 단계 올림
7. **21-stage 재구성** — 10 design §13 의 5 개 신설 stage (Tool Review · Task Registry · HITL · Summarize · Persist) 전원 승격. 한 번의 `1.0.0` major bump 로 흡수 (P1 원칙 + 11 roadmap Phase 9)

이 목표는 **claude-code-main** 이 보여준 성숙한 패턴을 참조하지만 — *그대로 복사하는 것이 아니라* — 16-stage 모델의 이점 (stage 별 mutate · strategy 교체 · manifest 서밍) 과 맞물려 재해석.

---

## 2. 설계 원칙

### P1. 16 → 21 stage 재구성 — 한 번의 major bump 로 흡수

- **기본 궤적**: 기존 16 stage 구조를 유지하며 내부 (strategy / slot / config) 를 고도화.
- **이번 cycle 의 확장**: 10 design §13 의 후보 5 종 — **Tool Review (11), Task Registry (13), HITL (15), Summarize (19), Persist (20)** — 전부 승격. 최종 **21 stage** 체제로 전환.
- **규칙**:
  - Stage 수 변경은 **`0.x → 1.0.0` major version bump** 의 계기 (이번 cycle 에서 유일한 기회)
  - v2 manifest → v3 auto migration tool 제공 (누락 stage 는 pass-through default 로 채움)
  - 부분 적용 금지 — 21-stage 전환은 한 번에 완료
  - 이후 또 stage 추가가 필요하면 `1.x → 2.0.0` 에서 동일 절차 반복
- **이 결정의 이유**: 기존 Stage 하나에 두 책임이 섞여 있는 불편 (Memory 의 raw persist vs summary, Stage 10 의 실행 + review) 을 한 번에 해소. 나중에 하나씩 추가하면 매번 major bump · migration 이 필요한데, 한 번에 묶으면 breakage 표면이 1 회로 압축.
- 상세 구현: [`10_design_stage_enhancements.md`](10_design_stage_enhancements.md) §13 + [`11_migration_roadmap.md`](11_migration_roadmap.md) Phase 9 + [`12_detailed_plan.md`](12_detailed_plan.md) 전체 구현 계획.

### P2. 단일 진실의 원천 (Single Source of Truth)
같은 정보를 두 레이어가 각자 저장하지 않음. 예:
- Tool schema 는 Tool ABC 에 한 번만
- Prompt 는 `PromptBuilder` 가 생성 → Stage 3 system_builder slot 이 소비 (이중 가공 금지)
- MCP 설정 읽기는 `MCPLoader` 한 곳
현재 duplicated 지점은 05 gap analysis 에서 목록화.

### P3. 확장 friction 최소화
"새 X 추가하기" 의 수정해야 할 파일 수 = N. 다음 use-case 각각에 대한 현재 N 과 목표 N 을 구체적으로 정량:

| Use-case | 현재 N | 목표 N |
|---|---|---|
| built-in tool 추가 | 1–2 | 1 |
| MCP 서버 등록 | 2–3 | 1 (config 만) |
| role / persona 추가 | 4–6 | 2 |
| pipeline preset 추가 | 1–2 | 1 |
| memory provider 추가 | 2–4 | 2 |
| **Skill 추가 (신규)** | n/a | 1 (SKILL.md 파일) |

### P4. 실행 품질 (동시성 · permission · budget)
Tool 실행이 "loose dict list" 가 아니라 **런타임 속성 (concurrency-safe / read-only / destructive / result budget) 기반으로 orchestration** 됨. 이는 claude-code 의 `toolOrchestration.ts` 의 핵심 교훈.

### P5. 관측 가능성 (Observability)
Stage 진입·퇴장·mutation·tool invocation·hook 실행 전부를 **EventBus 이벤트 한 종류로 통일**. 새 이벤트 타입을 추가할 때마다 UI 보드가 자동으로 보여줌. 특수 debug 경로 없음.

### P6. 하위 호환성
각 단계의 변경은 **현재 동작을 깨지 않는 additive** 로 우선 설계. 기존 `attach_runtime(tools=...)` 호출은 그대로 작동, 새 `Tool` ABC 는 옵트인. Strategy 교체 API 는 현재 호출 패턴 유지.

### P7. geny-executor first — capability 의 single source of truth
- Tool / MCP / Skill / Hook / Permission 등 **capability 계약** 은 전부 geny-executor 가 정의한다. Geny (또는 다른 호스트) 는 **소비자** 다.
- 공통으로 쓸 만한 것은 executor 에 **built-in** 으로 들어가야 하고, 호스트 고유의 것만 호스트 측에서 구현 → `AdhocToolProvider` 같은 **주입 채널** 로 executor 에 넣는다.
- 결과적으로 "executor 만 쓰는 다른 프로젝트" 도 Geny 와 동등한 기본 기능을 얻는다.
- 이번 uplift 의 코드 변경 순서는 항상 **executor 먼저 → PyPI 릴리스 → Geny pin 업데이트** 가 된다 ([11 migration roadmap](11_migration_roadmap.md) 참조).

### P8. Rich built-in catalog
- 개발자·사용자가 일반적 워크플로에서 필요로 하는 tool 은 executor 가 **기본 제공**.
- 현재 executor 내장: Read / Write / Edit / Bash / Glob / Grep — 6 종.
- 목표: **15–20 종** 수준. 구체 카탈로그는 [06 Tool system design](06_design_tool_system.md) 의 "Built-in tool catalog" 섹션.
- 호스트 (Geny) 는 이 기본 위에 **플랫폼 특화 tool** 만 덧붙이면 됨: 세션 관리, 게임 상태 조작, 캐릭터 persona 변경 등.

---

## 3. 범위 (In scope / Out of scope)

### In scope
- `/home/geny-workspace/geny-executor/` 의 core (pipeline, state, stage, slot, mutation, builder, environment, presets, introspection) + 각 Stage artifact
- `/home/geny-workspace/Geny/backend/` 의 `service/executor/`, `service/tool_*`, `service/mcp_loader.py`, `service/environment/`, `service/prompt/`, `service/persona/`, `tools/`
- `claude-code-main` 에서 읽어들일 수 있는 구조적 패턴 (Tool ABC, MCP transport, Skill loader, Hook JSON 프로토콜, Permission rule matcher)

### Out of scope (별도 cycle)
- 프론트엔드 상세 UI 재구성 (단, tool metadata 가 UI 를 위해 필요하다는 점은 고려)
- TTS / VTuber / Live2D 렌더링
- Creature state / Tamagotchi 게임 규칙
- Memory provider 구현체 (인터페이스 + Stage 통합만 다루고, SQL/Redis 등 구체적 backend 는 별개)

---

## 4. 성공 기준

### 기술적 성공 기준
1. **Tool ABC 의 마이그레이션** — 기존 `tools/built_in/*` 의 80% 이상이 새 Tool ABC 로 재작성 완료. 나머지 20% 는 명시적 호환성 어댑터로 감쌈.
2. **Built-in 카탈로그 배증 (6 → 15+)** — executor 레포에 AgentTool, SkillTool, TaskTool, WebFetch, WebSearch, NotebookEdit, Todo, Monitor, Schedule 등이 일급 built-in 으로 존재. Geny 는 이것들을 쓰기 위해 어떤 추가 코드도 작성할 필요 없음.
3. **MCP 런타임 등록** — `.mcp.json` 재시작 없이 서버 추가·제거 가능. 연결 실패 서버가 전체 pipeline 을 죽이지 않고 graceful degradation.
4. **Skill 3 개 이상** — 실제로 사용 가능한 bundled skill 3 개 (예: `search-web`, `summarize-session`, `draft-pr`). 각 skill 의 프롬프트 + 허용 tool 리스트만으로 동작.
5. **호스트 tool 주입 friction 최소** — Geny 가 플랫폼 특화 tool (feed/play/gift/talk 등) 을 executor 에 주입하는 데 수정해야 할 파일: 1 (tool module) + 1 (registration call). 그 외 모든 tool 은 executor built-in 으로 충당.
6. **Extension interface 문서화** — "당신이 X 를 바꾸려면 Y 를 해야 합니다" 의 결정 트리 문서 (09_design_extension_interface.md) 가 존재하고, 새 개발자가 그것만 보고 새 preset·tool·skill 을 추가할 수 있음.
7. **Observability** — 모든 Stage 진입·퇴장·mutation·tool invocation 이 EventBus 에 구조화된 이벤트로 도달. UI 대시보드 (또는 CLI subscriber) 가 실시간 표시 가능.

### 운영적 성공 기준
1. **릴리스 cadence** — PR 단위로 끊어 **작은 단위로 롤아웃**. 각 PR 은 단독 revert 가능.
2. **회귀 0** — 기존 VTuber / worker / developer 세션 동작이 유지. 기존 manifest·preset 파일 모두 그대로 로딩됨.
3. **문서 동기화** — code 변경이 있을 때마다 이 uplift 문서가 최신 상태를 반영 (stale "…현재는 X…" 같은 구절이 실제와 불일치하지 않게).

---

## 5. 핵심 용어 (요약)

상세 정의는 [`appendix/b_terminology.md`](appendix/b_terminology.md) 참조.

- **Stage** — 파이프라인의 16 개 실행 단위 (`sXX_YYY`). 하나의 `Stage` 서브클래스가 한 단계를 책임짐.
- **Strategy** — Stage 내부에서 교체 가능한 로직 (예: `DefaultNormalizer` vs `MultimodalNormalizer`). 여러 Strategy 가 한 slot 을 채움.
- **StrategySlot** — Stage 가 가진 *1:1* 교체 지점 (예: Stage 1 의 `validator` slot 과 `normalizer` slot).
- **SlotChain** — Stage 가 가진 *ordered list* 확장 지점 (예: Stage 4 Guard 의 `guards` chain, Stage 14 Emit 의 `emitters` chain).
- **Artifact** — Stage 의 구체 구현 (e.g. `s01_input/artifact/default/`). Strategy 만 바꾸는 것이 아니라 Stage 전체를 바꿀 때 사용.
- **Manifest** — Pipeline 전체 구성 (stage 배열 + strategy 선택 + config + tool 목록) 을 YAML/JSON 으로 직렬화한 것. `EnvironmentManifest` 가 그 구현.
- **Runtime attach** — `Pipeline.attach_runtime(llm_client, tools, system_builder, memory_*, tool_context, session_runtime)` — Pipeline 이 build 된 후 런타임 의존성 주입.
- **Tool ABC** — geny-executor 의 `Tool` 추상 베이스 (name/description/input_schema/execute). 이번 uplift 에서 훨씬 풍부해질 인터페이스.
- **MCP** — Model Context Protocol. 외부 프로세스가 tool / resource / prompt 를 노출하는 표준.
- **Skill** — (신설 예정) SKILL.md 프론트매터 + 프롬프트 본문으로 이뤄진 **코드 수정 없이 추가 가능한 capability 단위**.
- **PipelineMutator** — build 후 런타임에 strategy 교체·stage 추가/삭제 등 변경을 감사 로그와 함께 수행하는 객체.

---

## 6. 문서 읽기 힌트

- **개발자로서 코드를 바꾸는 관점** — 06 → 07 → 08 → 09 → 10 → 11 순.
- **설계자로서 왜 이렇게 하는지를 알고 싶은 관점** — 01 → 05 → 06–10 순.
- **새 파이프라인 preset 을 설계하려는 관점** — 02 → 10 → 11 순.
- **tool / skill 작성자 관점** — 06 → 08 → 부록 A (파일 인덱스) 순.
