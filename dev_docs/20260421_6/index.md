# Cycle 20260421_6 — 16-STAGE 아키텍처 심층 해부 + 다마고치 확장성 감사 + 장기 상태 PLAN

**Date.** 2026-04-21
**Scope.** **분석 + 설계 계획.** 코드 변경 없음. executor / backend / frontend 모두 무(無)수정.
본 사이클은 두 단계로 진행됨:
1. **Analysis** (01~05) — 16-STAGE 아키텍처 정합성 감사 + 확장성 판정.
2. **Plan** (01~05) — 장기 상태관리 전략 확정 + X1..X6 사이클 PR 단위 분해.
**Trigger.** 유저의 두 가지 요청이 겹침:

1. "**geny / geny-executor 의 Pipeline 로직을 완벽하게 심층 분석**하라 —
   16-STAGE 전략이 의도대로 작동하고 있는지, Geny 안에 파이프라인을 우회하는
   특수 비즈니스 로직이 자라고 있지는 않은지 검증."
2. "AI VTuber 다마고치 / 관계 시뮬레이션" 기획을 얹으려는데,
   "**PLUGIN STAGE** 같은 공식 외부 모듈 확장 공간을 16-STAGE 안에 열 수 있는가" 를 판단.

유저 원문: *"우리의 geny를 훨씬 강력하게 만들 요소들인거지. 이것을 구현하기 앞서서,
우리의 16STAGE 아키텍처나 geny 아키텍처로 이것을 대응하고 싶은거야.
특히 16STAGE에서 뭔가 이런 추가적 모듈을 받아줄 수 있는 강력한 인터페이스를 제공할 수
있으면 좋겠어 (예를 들어 PLUGIN STAGE가 존재하고 이것이 외부 모듈 기능들을 확장할 수 있는
공간으로 작동하는 등 ...)"* — 그리고 *"분석만 진행하자."*

## 이 사이클에서 판정한 것

- **16-STAGE 테제는 구조적으로 강제되어 있다.**
  `LOOP_START=2 / LOOP_END=13 / FINALIZE_START=14 / FINALIZE_END=16` 은 하드코딩된
  헌법이며, 파이프라인은 3-Phase (Ingress → Loop → Egress) 로 정확히 돌아간다.
- **Geny 는 executor 를 라이브러리로 깨끗이 소비한다.** 단, 3개의 사이드도어
  (`_system_prompt` 직접 변이) 가 발견 — 우회는 아니지만 다마고치 기획을 얹을 때
  반드시 걸릴 지점.
- **17번째 Stage 는 정답이 아니다.** 기존 7겹 확장 표면 (Strategy / Slot / SlotChain /
  PromptBlock / Emitter-Chain / EventBus / Manifest-Preset) 으로 기획의 거의 모든 요소를
  흡수 가능. "PLUGIN STAGE" 의 멘탈 모델은 **`GenyPlugin` Protocol (기존 표면의 번들)**
  로 표현하는 것이 건전.
- **9개의 격차 (I1..I9)** 가 실재한다. 이 중 executor 수정이 *optional* 로 필요한 것은 I8
  (attach_runtime kwargs 확장) 단 1건. 나머지는 Geny-side 로 해결 가능.

## 무엇이 이 사이클의 산출인가

`dev_docs/20260421_6/analysis/` 의 **5개 분석 문서** + `dev_docs/20260421_6/plan/` 의 **5개
계획 문서**. 총 10개. 코드 한 줄도 쓰지 않는다. 각 사이클 (X1..X6) 의 *구현 계획* 은 해당
사이클이 시작될 때 별도 `dev_docs/<date>_X*/` 폴더에서 본 PLAN 을 *현재 코드 기준으로
재검증* 한 뒤 착수한다.

## 장기 상태관리 — PLAN 의 핵심 결정

- **전략 D 채택.** 장기 상태 (CreatureState) 는 `pipeline.run` **외부 wrapper**
  (`SessionRuntimeRegistry`) 에서 hydrate / persist. Stage 는 `state.shared` 만 읽고
  `MutationBuffer` 에 diff 만 append. executor 수정 0-line.
- **Phase A 에 stage 추가는 기각.** `_run_phases` 하드코딩으로 order ∉ [1,16] 은 실행 불가.
  실행 모델을 깨 가며 얻는 이득보다 외부 wrapper 가 모든 면에서 우월.
- **3 사이드도어 (`_system_prompt`) 는 X1 에서 `PersonaProvider` 로 완전 철거.**
- **Decay / thinking / avatar / curation 은 `TickEngine` 으로 통일** (X2).
- **executor 릴리즈 bump 는 X5 에서만 *선택적* 으로** (0.30.0 in `session_runtime` kwarg).
  X1~X4 는 0-line executor 변경.

## Out (명시적으로 제외)

- **구현.** `CreatureState`, `AffectBlock`, `DecayTicker`, `PersonaProvider`,
  `SessionLifecycleBus`, `TickEngine`, `ManifestSelector`, `GenyPlugin` Protocol —
  전부 이 사이클에서 착수하지 않는다.
- **Executor 수정.** v0.29.0 을 그대로 쓴다. I8 (attach_runtime kwargs) 만이 나중 사이클에서
  1-line 수정을 "선택적으로" 요구.
- **다마고치 콘텐츠 기획.** 이벤트 풀 카탈로그 / 밸런스 수치 / Live2D 애셋 파이프라인은
  엔지니어링 트랙이 아니라 기획 트랙. 본 사이클 범위 밖.
- **사이드도어 즉시 철거.** `_system_prompt` 3곳은 문제 지점으로 *식별만* 했고,
  제거는 X1 (PersonaProvider) 사이클의 일거리.

## Documents

### Analysis (근거)

- [analysis/01_16stage_architecture_deepdive.md](analysis/01_16stage_architecture_deepdive.md)
  — 16-STAGE 가 *어떻게 강제되어 있는가* 를 코드 라인 단위로 확정. Phase 경계,
  Stage × Strategy × Slot 2-레벨 추상, 7겹 확장 표면, `register_stage` 의 너그러움,
  `attach_runtime` 의 고정 6-kwargs, EventBus / Manifest / PipelineMutator 까지.
- [analysis/02_geny_integration_audit.md](analysis/02_geny_integration_audit.md)
  — Geny 가 executor 를 *존중하는지 우회하는지* 를 11행 매트릭스로 판정.
  `_system_prompt` 사이드도어 3곳 (vtuber_controller / agent_controller /
  agent_session_manager) 식별.
- [analysis/03_tamagotchi_plan_to_stage_mapping.md](analysis/03_tamagotchi_plan_to_stage_mapping.md)
  — 기획의 모든 요소 (상태값 / decay / restore / progression / 감정 연결 / 세션 루프 ...)
  를 stage / slot / runtime 주입점에 1:1 매핑. MVP 범위와 9개 이슈 (I1..I9) 제시.
- [analysis/04_plugin_extensibility_and_proposed_extension_points.md](analysis/04_plugin_extensibility_and_proposed_extension_points.md)
  — "17번째 Stage 는 왜 나쁜 선택인가" 논증 + 7개 확장점 신설안 (A~G) +
  `GenyPlugin` Protocol 을 통한 "PLUGIN STAGE" 멘탈 모델 구현.
- [analysis/05_gaps_risks_and_roadmap.md](analysis/05_gaps_risks_and_roadmap.md)
  — 9개 격차를 세 카테고리 (런타임 상태 모델 / 피드백 순환성 / 라이프사이클) 로
  재정렬, 리스크 매트릭스, 6-사이클 로드맵 (X1..X6) 제시.

### Plan (설계)

- [plan/01_long_term_state_deep_analysis.md](plan/01_long_term_state_deep_analysis.md)
  — 장기 상태관리 4 전략 (attach_runtime 직접 / Phase-A stage 신설 / s01-s15 확장 /
  External Wrapper) 비교. 전략 D (External Wrapper) 채택 논증. Phase A 추가 stage 기각
  사유 (`_run_phases` 하드코딩 + 철학적 범주 오류).
- [plan/02_creature_state_contract.md](plan/02_creature_state_contract.md)
  — CreatureState 데이터 모델 (Vitals/Bond/Mood/Progression), MutationBuffer 의 4 op
  프로토콜, `SessionRuntimeRegistry.hydrate/persist`, `SqliteCreatureStateProvider`,
  DecayPolicy, 스키마 버전/마이그레이션, 동시성 (OCC), 테스트 전략.
- [plan/03_structural_completions.md](plan/03_structural_completions.md)
  — X1/X2 의 구조적 보완: `PersonaProvider` 로 3 사이드도어 철거,
  `SessionLifecycleBus` 7 이벤트, `TickEngine` 으로 주기 작업 일원화. PR 단위 분해와
  합격 조건.
- [plan/04_tamagotchi_interaction_layering.md](plan/04_tamagotchi_interaction_layering.md)
  — X3/X4 의 게임 레이어링: Mood/Relationship/Vitals Block,
  Feed/Play/Gift/Talk Tool, AffectTagEmitter, 방치 페널티, 재접속 보상, EventSeed,
  ManifestSelector, MVP 시나리오 S1~S4.
- [plan/05_cycle_and_pr_breakdown.md](plan/05_cycle_and_pr_breakdown.md)
  — X1..X6 사이클 × PR × 파일 수준 분해. 브랜치명, 의존, 회귀 위험, 롤아웃 순서,
  릴리즈 연계, KPI, 불변식 7조, 백아웃 원칙.

## Relation to other cycles

- **과거.** `20260421_4` / `20260421_5` 는 메모리-LLM 통합 (`ChatAnthropic` 직접 인스턴스
  제거) 으로 **executor 계약 내부에서 해결 가능한 것은 이미 정리되어 있다** 는 전제를
  이 사이클이 깔고 있음. `20260421_5/analysis/01` 의 "bypass" 개념 — 메모리 경로가
  APIConfig 를 우회하던 — 과 본 사이클의 "사이드도어" 개념은 동일한 렌즈.
- **현재.** `20260421_5/progress/pr2_requirements_pin_catchup.md` 에서 처리한
  requirements.txt pin 정정 (v0.29.0 → `ReflectionResolver` 가용) 은 본 사이클의
  분석이 *현재 Geny 가 실제로 사용 중인 executor 버전* 에서 정확히 성립함을 보장한다.
- **미래.** 본 사이클이 제시한 로드맵 — X1 (PersonaProvider) → X2 (SessionLifecycleBus +
  TickEngine) → X3 (CreatureState + AffectBlock + EmitToStateEmitter + DecayTicker) →
  X4 (ManifestSelector + Progression) → X5 (Plugin Protocol + Registry) →
  X6 (AffectAwareRetriever + 비용 최적화) — 은 각각 별도 사이클로 분할된다.
  각 사이클의 착수 여부 / 순서 조정은 유저 확인 후.
