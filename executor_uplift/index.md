# Geny Executor Uplift — Master Index

**위치:** `Geny/executor_uplift/`
**목적:** `geny-executor` 의 16-stage 실행 엔진과 Geny 의 통합 레이어 (tool / MCP / skills / prompt / runtime) 를 **확장성 있는 인터페이스** 로 고도화하기 위한 설계 문서 모음.
**참조 레퍼런스:** `claude-code-main` (Anthropic Claude Code CLI 소스, 워크스페이스 루트).

---

## 읽는 순서

이 문서 집합은 하위에서 상위로 — *현재를 이해한 뒤 gap 을 보고, 그 위에서 설계한 뒤 로드맵으로 정리* — 하는 흐름이야. 맥락 없이 설계 문서부터 들어가면 근거가 빠져 보이니 순서대로 읽는 걸 권장.

| 단계 | 문서 | 역할 |
|---|---|---|
| **A. Overview** | [`01_overview.md`](01_overview.md) | 이 uplift 의 goal · 원칙 · 용어 · 성공 기준 |
| **B. Current state** | [`02_current_state_geny_executor.md`](02_current_state_geny_executor.md) | geny-executor 16-stage 아키텍처 전수 스냅샷 |
| | [`03_current_state_geny_integration.md`](03_current_state_geny_integration.md) | Geny 의 tool/MCP/runtime 통합 현재 |
| **C. Reference** | [`04_reference_claude_code.md`](04_reference_claude_code.md) | claude-code-main 의 tool/MCP/skill/hook 패턴 |
| **D. Gap** | [`05_gap_analysis.md`](05_gap_analysis.md) | 02/03 ↔ 04 를 교차해 도출한 결핍·중복·설계 부채 |
| **E. Design** | [`06_design_tool_system.md`](06_design_tool_system.md) | Tool 인터페이스·메타데이터·동시성·permission + 15–20 종 Built-in catalog |
| | [`07_design_mcp_integration.md`](07_design_mcp_integration.md) | MCP transport·auth·tool/prompt/resource 매핑 |
| | [`08_design_skills.md`](08_design_skills.md) | Skill 시스템 신설 — 디스크·MCP·번들 skill 통합 |
| | [`09_design_extension_interface.md`](09_design_extension_interface.md) | config / strategy / slot / hook / mutation 통합 확장 계약 |
| | [`10_design_stage_enhancements.md`](10_design_stage_enhancements.md) | 기존 stage 고도화 + **21-stage 재구성 설계** (§13) |
| **F. Roadmap** | [`11_migration_roadmap.md`](11_migration_roadmap.md) | 10 Phase 실행 계획 · PR cadence · 릴리스 전략 |
| | [`12_detailed_plan.md`](12_detailed_plan.md) | **전체 통합 구현 manual** — 주차별 schedule, PR skeleton, 검증 매트릭스 |
| **G. Appendix** | [`appendix/a_file_inventory.md`](appendix/a_file_inventory.md) | 레포별 핵심 파일:라인 인덱스 |
| | [`appendix/b_terminology.md`](appendix/b_terminology.md) | 용어 정의 (stage · strategy · slot · chain · manifest · ...) |
| | [`appendix/c_prior_art.md`](appendix/c_prior_art.md) | 외부 사례 (LangChain · LlamaIndex · LangGraph · AutoGen · OpenAI Assistants) |

---

## 한눈에 보는 대상 시스템

```
┌────────────────────────────────────────────────────────────────────┐
│ Geny backend (FastAPI)                                             │
│                                                                    │
│  AgentSessionManager  ──── creates ─────▶ AgentSession             │
│     │                                        │                     │
│     │ env_id                                 │ attach_runtime(...) │
│     ▼                                        ▼                     │
│  EnvironmentService ◀── manifest ─── Pipeline ◀────┐               │
│                                                    │               │
└────────────────────────────────────────────────────┼───────────────┘
                                                     │
                                     geny-executor (PyPI) Pipeline
                                                     │
  ┌──────────────────────────────────────────────────┴──────────────┐
  │ 16 Stages (Phase A ingress · Phase B loop · Phase C egress)     │
  │                                                                 │
  │  [1 Input] [2 Context] [3 System] [4 Guard] [5 Cache] [6 API]  │
  │  [7 Token] [8 Think]  [9 Parse]  [10 Tool] [11 Agent]          │
  │  [12 Evaluate] [13 Loop]  ←── loop body 2-13                    │
  │  [14 Emit] [15 Memory] [16 Yield] ←── finalize 14-16            │
  └─────────────────────────────────────────────────────────────────┘

  Extension surfaces (현재):
  - PipelineBuilder · PipelineMutator · PresetRegistry
  - StrategySlot · SlotChain · ConfigField / ConfigSchema
  - EventBus · EnvironmentManifest · attach_runtime kwargs
  - (Geny) ToolLoader · MCPLoader · ToolPolicyEngine · PersonaProvider
```

---

## 이 uplift 가 답하려는 질문

1. **Tool 인터페이스** — 지금은 "이름·설명·스키마·handler" 수준. 동시성 안전성, 파괴성, permission 매처, lifecycle hook, UI render 메타 등 claude-code 가 가진 풍부한 계약을 어떻게 흡수할까?
2. **Built-in tool 카탈로그** — executor 가 6 종 (Read/Write/Edit/Bash/Glob/Grep) 만 내장. WebFetch / WebSearch / AgentTool / SkillTool / TaskTool / TodoWrite / Schedule / NotebookEdit 등 범용 tool 을 executor 가 **기본 제공** 하도록. Geny 는 그 위에 플랫폼 특화 tool (게임·세션·캐릭터) 만 얹는다.
3. **MCP 통합** — 정적 JSON 로더에 머물러 있음. 런타임 등록·헬스체크·여러 transport (stdio/SSE/HTTP/WS/SDK) · OAuth 통합을 어떻게 표준화할까?
4. **Skills** — Geny 는 "role prompt" 로 skill 역할을 대신하고 있음. claude-code 스타일의 `SKILL.md` 프론트매터 기반 skill 이 있으면 사용자 확장 friction 이 어떻게 줄어들까?
5. **16-stage 확장 포인트의 일관성** — `attach_runtime(...)` kwargs, Stage-level `*_override`, `state.shared` dict, manifest, event bus 등 **여러 확장 메커니즘이 동거** 하고 있음. 하나의 통합된 "Extension Interface" 로 정리 가능한가?
6. **Stage별 고도화** — 각 Stage (특히 Tool(10), Agent(11), Guard(4), Memory(15)) 가 claude-code 의 어떤 성숙도에 비해 어떤 단계에 있고, 다음 수준으로 가기 위한 구체적 변경은? 그리고 **필요 시 stage 를 16 → 17 로 늘릴 수도 있는가** (major version bump 조건부로)?

각 질문의 답은 06–10 의 design 문서에 담겨.

## 이 uplift 의 두 방향성

1. **geny-executor first, Geny follows.** 모든 capability 계약·구현은 executor 에 먼저 자리잡고, Geny (그리고 앞으로 등장할 타 프로젝트) 는 executor 를 소비하는 쪽. 같은 범용 tool 을 여러 호스트가 각자 구현하는 것을 막는 원칙.
2. **16 → 21 stage 재구성 (필수).** 5 개 신설 stage (Tool Review · Task Registry · HITL · Summarize · Persist) 모두 승격. 한 번의 `1.0.0` major bump 로 흡수. 10 design §13 + 11 roadmap Phase 9 + 12 detailed plan 에서 구현 manual 제공.

---

## 산출물 요약 (우선 완성 목표)

- [ ] 01 Overview — 우리의 설계 원칙 + 성공 기준
- [ ] 02 Current state (geny-executor) — 16-stage 표 + core primitives + 확장 포인트 매트릭스
- [ ] 03 Current state (Geny integration) — tool/MCP/persona/memory wiring
- [ ] 04 Reference patterns — claude-code Tool 계약 / MCP transport / Skill 로드 / Hook 이벤트 / Permission
- [ ] 05 Gap analysis — 결핍·중복 top list + 우선순위
- [ ] 06 Tool system design
- [ ] 07 MCP integration design
- [ ] 08 Skills system design
- [ ] 09 Extension interface design
- [ ] 10 Stage-by-stage enhancements
- [ ] 11 Migration roadmap
- [ ] Appendix A / B / C

## 문서 상태

작성 진행은 `dev_docs/` cycle 패턴과 별개로 이 폴더 안에서만 관리함. 각 문서 상단에 버전·작성일·상태(Draft / Review / Final) 메모를 넣어 향후 업데이트 추적.
