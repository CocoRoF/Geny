# 분석 01 — 16-STAGE 파이프라인 아키텍처 심층 해부

**작성일.** 2026-04-21
**대상.** `geny-executor` v0.29.0 / `Geny` main
**목적.** "16-STAGE 아키텍처가 설계 의도대로 작동하고 있는가, 확장 인터페이스는 어디에 있는가"
를 코드 레벨에서 확정. 이후 분석 02~05의 모든 판단은 이 문서에 선언된 사실 위에서 이뤄진다.

---

## 0. 한 줄 결론

**16-STAGE 테제는 "구조적으로 강제"되어 있다.**
자유롭게 17번째 스테이지를 꽂는 인터페이스는 존재하지 않는다. 대신
*스테이지 안쪽*에서 Strategy / Slot / SlotChain / Builder-Block / Emitter-Chain /
EventBus / Manifest-Preset / Adhoc-Provider 라는 7겹의 확장 레이어가 있고,
사실상 모든 "플러그인"은 이 7겹 중 한 지점으로 귀결된다.

---

## 1. 실행 모델 — 파이프라인은 "3-Phase 사이클"이다

`core/pipeline.py:208-212`:

```python
LOOP_START     = 2
LOOP_END       = 13   # inclusive
FINALIZE_START = 14
FINALIZE_END   = 16   # inclusive
```

이 네 상수가 16-STAGE 테제를 *하드코딩된 수준으로* 고정한다.
실행 함수 `_run_phases` (pipeline.py:806-859) 가 밟는 경로:

| Phase | Order 범위 | 횟수 | 의미 |
|---|---|---|---|
| A. Ingress | 1 | 1회 | 입력 정규화 |
| B. Loop | 2 → 13 | N회 (loop_decision=continue 동안) | 에이전트 본체 |
| C. Egress | 14 → 16 | 1회 | 방출·기억·산출 |

### 핵심 관찰

1. `Pipeline.register_stage(stage)` 자체는 **검증이 없다** (pipeline.py:483-486) —
   `self._stages[stage.order] = stage` 한 줄이 전부.
   → `order=17`, `order=99`인 Stage 를 등록해도 **예외는 안 난다**.
2. 하지만 `_run_phases` 는 `range(LOOP_START, LOOP_END+1)` 과 `range(FINALIZE_START, FINALIZE_END+1)` 만
   순회한다. → **그 바깥 order는 영원히 실행되지 않는다.**
3. 따라서 "17번째 스테이지"는 **등록 API 상으로는 가능하나 실행 경로 상으로는 불가능**.
   *소리 없이 무시되는* 구조다. 이 실패 모드는 플러그인 설계에서 반드시 경계해야 한다
   (→ 분석 04 §3).

### 상태 전파

- Phase A 의 반환값이 Phase B 의 첫 입력이 된다 (pipeline.py:814-831).
- Phase B 의 매 iteration 마다 stage[2]..stage[13] 을 "체인"으로 관통하며,
  각 스테이지의 `execute(input, state) -> out` 반환이 다음 스테이지의 input.
- 공유 데이터는 *모두 mutable `state: PipelineState` 을 통해* 흐른다.
- stage 간 "fan-out / 병렬"은 존재하지 않는다 — 한 iteration 안에서는 **완전 순차**.

### 중단 / 예외 경로

- `_run_stage` (pipeline.py:917-943) 가 모든 stage 실행을 감싼다:
  1. `"stage.error"` 이벤트 emit
  2. `stage.on_error(e, state)` 호출 — None 이면 `StageError` 로 래핑 후 재-raise
  3. None 이 아니면 그 값을 정상 출력으로 간주하고 계속
- 파이프라인 전체 수준에서는 `Pipeline.run()` 이 모든 예외를 잡아
  `PipelineResult.error_result(...)` 로 변환 (pipeline.py:681-683).
- **"stage 하나가 실패해도 루프가 자연스럽게 중단·전환"** 되는 구조 — 감정형 게임에서
  네트워크 실패 / LLM quota 실패 시 "삐짐" 같은 대체 반응으로 갈아끼우기 쉬운 설계다.

### 조건부 스킵 — `should_bypass(state)`

- `Stage.should_bypass(state) -> bool` (stage.py:131-133) 훅.
- 예: `ThinkStage` 는 `state.thinking_enabled == False` 면 bypass.
- **이 훅은 Tamagotchi 의 "피곤하면 생각 비활성화"/"삐졌을 때 tool 안 쓰기" 같은
  감정-게이트된 행동 변화를 구현할 유력한 자리** (→ 분석 03 §4).

---

## 2. 이중 추상 — Stage(용기) × Strategy(내용물)

이 분리가 16-STAGE 설계의 가장 큰 자산이다.

### Stage — 위치와 책임

`core/stage.py:85-191` 의 `Stage[T_In, T_Out]` ABC:

- `name / order` — 파이프라인 상의 좌표 (1..16)
- `async execute(input, state) -> out` — 본체
- `on_enter / on_exit / on_error` — 라이프사이클 훅
- `should_bypass(state)` — 조건부 스킵
- `get_strategy_slots() / get_strategy_chains()` — 하위 전략 선언
- `describe() -> StageDescription` — 자기소개

**Stage 는 "해야 할 일의 종류 (컨텍스트 준비, 도구 실행, 기억 저장 ...)"** 를 고정한다.

### Strategy — 구현 교체 지점

`core/stage.py:39-83` 의 `Strategy` ABC:

- `name: str` — 이 구현의 식별자
- `config_schema() / configure(cfg) / get_config()` — UI 노출 가능한 설정
- 추상 메서드는 **stage 별로 다르다** — `PromptBuilder.build`, `Emitter.emit`,
  `MemoryRetriever.retrieve`, `ToolExecutor.execute` 등.

**Strategy 는 "그 일을 어떻게 할지"** 를 교체 가능하게 만든다.

### 어떤 stage 가 어떤 슬롯을 갖는가

| # | 모듈 | Stage 이름 | 단일 슬롯 | Chain 슬롯 | 교체성 평가 |
|---|---|---|---|---|---|
| 1 | s01_input | Input | validator, normalizer | — | ★★★ |
| 2 | s02_context | Context | strategy, compactor, **retriever** | — | ★★★★ |
| 3 | s03_system | System | **builder** | — (Block 은 builder 내부 조합) | ★★★★ |
| 4 | s04_guard | Guard | — | **guards** | ★★★★ |
| 5 | s05_cache | Cache | strategy | — | ★★ |
| 6 | s06_api | API | provider, retry | — | ★★★ |
| 7 | s07_token | Token | — | — | ★ (내장) |
| 8 | s08_think | Think | processor | — | ★★ |
| 9 | s09_parse | Parse | — | — | ★ (내장) |
| 10 | s10_tool | Tool | executor, router | — | ★★★ |
| 11 | s11_agent | Agent | — | — | ★★ |
| 12 | s12_evaluate | Evaluate | evaluator | — | ★★★ |
| 13 | s13_loop | Loop | controller | — | ★★★ |
| 14 | s14_emit | Emit | — | **emitters** | ★★★★ |
| 15 | s15_memory | Memory | **strategy**, **persistence** | — | ★★★★ |
| 16 | s16_yield | Yield | — | — | ★ (내장) |

**★★★★ 은 외부 주입 가능한 실질적 확장점** — Geny 가 `attach_runtime()` 으로 꽂는
memory_retriever / memory_strategy / memory_persistence / system_builder 와
정확히 일치한다 (pipeline.py:509-518).

### 체인 슬롯 (Chain) — 순서 있는 복수 전략

- `SlotChain` (core/slot.py) — 이름표 + 순서가 있는 Strategy 리스트.
- 현재 두 자리:
  - **Guard (s04)** — `guards` chain: 토큰버짓 · 비용 · 반복 · 권한 가드를
    원하는 순서로 쌓는다.
  - **Emit (s14)** — `emitters` chain: Text → Callback → VTuber → TTS 순으로
    fan-out.
- Mutator 가 `add_to_chain / remove_from_chain / reorder_chain` 을 지원 (mutation.py).
- **다마고치 설계에서 s14 emitters chain 은 매우 중요해진다** — "감정 태그 추출" /
  "Live2D 표정 갱신" / "TTS 재생" / "상태값 변동 기록" 이 여기에 순서대로 쌓여야 하기 때문.

---

## 3. PipelineState — 공유 지형

`core/state.py` 의 단일 거대 dataclass. 모든 stage 가 읽고 쓰는 "방".

### 이미 타입으로 존재하는 필드 (요약)

| 범주 | 필드 | 요점 |
|---|---|---|
| 식별 | `session_id, pipeline_id` | — |
| 메시지 | `system, messages` | 대화 이력 |
| 실행 | `iteration, max_iterations, current_stage, stage_history` | 루프 상태 |
| 모델 | `model, max_tokens, temperature, top_p, top_k, tools, tool_choice, stop_sequences` | 호출 파라미터 |
| Extended Thinking | `thinking_enabled, thinking_budget_tokens, thinking_type, thinking_history` | — |
| 토큰·비용 | `token_usage, turn_token_usage, total_cost_usd, cost_budget_usd` | — |
| 캐시 | `cache_metrics` | hit/miss 계측 |
| 컨텍스트 | `memory_refs, context_window_budget` | 주입된 기억 참조 |
| 루프 | `loop_decision, completion_signal, completion_detail` | continue/complete/error/escalate |
| 도구 | `pending_tool_calls, tool_results` | — |
| 에이전트 | `delegate_requests, agent_results` | 서브 에이전트 |
| 평가 | `evaluation_score, evaluation_feedback` | — |
| 출력 | `final_text, final_output, last_api_response` | — |
| 메타 | `metadata: Dict`, `shared: Dict`, `events: List` | 자유 필드 |
| 런타임 | `_event_listener, llm_client` | 주입된 객체 |

### 존재하지 *않는* 것 — 감정형 게임 관점에서 구멍

- **mood / affect / vitals / relationship** 전용 타입 필드가 **없다**.
- 현재는 두 개의 자유 dict 로 우회:
  - `state.metadata["..."]` — stage-local 스크래치 (stage.py:355-371 `local_state()` 헬퍼가 stage 이름으로 네임스페이스).
  - `state.shared["..."]` — 스테이지 간 free-form 공유, **매 `run()` 시작 시 초기화된다**.
- `state.events` — 이벤트 로그, append-only.

### 이 공백이 의미하는 바

다마고치 기획안의 **"상태값 (배고픔·피로·스트레스·애정도·자존감·호기심)"** 은
현재 구조에서 `metadata` 혹은 `shared` dict 의 관례적 키 로만 표현 가능하다.
→ 타입 안전성 없음, 슬롯 교체로 교체 불가, 직렬화 경로 없음.
→ **분석 04 에서 "CreatureState 1급 필드 vs dict 관례" 의 선택지 제시**.

---

## 4. 확장 표면 7겹 — 17번째 stage 없이도 가능한 것들

### 4-1. Artifact 오버라이드 (스테이지 구현 교체)

- 모든 stage 모듈은 `stages/sXX_name/artifact/default/` 에 기본 구현을 둔다.
- 제3자는 `stages/sXX_name/artifact/custom_v2/` 를 따로 패키징해 export 가능
  (core/artifact.py:135-150 `create_stage("s05_cache", artifact="custom_v2")`).
- **효과:** 스테이지의 "종류" 는 안 바뀌고, 그 스테이지의 *전체 본체* 를 갈아끼움.
- **단점:** 16 중 하나를 통째로 대체 — 스트래티지 수준보다 무겁고, 보통은 과도함.

### 4-2. Strategy 슬롯 스왑 (PipelineMutator)

- `PipelineMutator(pipeline).swap_strategy(stage_order, slot_name, impl_name, config)`
  (mutation.py).
- 런타임에 열려있다 — 파이프라인 실행 **전에는** 자유롭게 교체, 실행 중에는 잠김
  (`MutationLocked` 예외).
- **다마고치 설계에서 중심이 될 레이어** — "피곤 상태면 retrieval 전략을 'lazy' 로",
  "삐진 상태면 emitter chain 에서 TTS 제거" 같은 감정-기반 전략 전환이 모두 여기.

### 4-3. ComposablePromptBuilder 의 Block 조합 (s03)

- s03 의 기본 전략 `ComposablePromptBuilder` 는 `PromptBlock` 리스트를 받아 순서대로 렌더링
  (builders.py:131+).
- 기본 블록: `PersonaBlock, RulesBlock, DateTimeBlock, MemoryContextBlock,
  ToolInstructionsBlock, CustomBlock`.
- **PromptBlock 은 공식 ABC** — 제3자가 `AffectBlock`, `RelationshipBlock`,
  `CreatureVitalsBlock` 같은 것을 추가하는 비용이 거의 영.
- 다마고치 설계에서 "현재 캐릭터의 기분/관계/상태값" 을 system 프롬프트에 집어넣는
  표준 진입점이 된다 (→ 분석 03 §5).

### 4-4. Emitter Chain (s14)

- 현 executor 가 이미 제공하는 기본 emitter:
  `TextEmitter / CallbackEmitter / VTuberEmitter / TTSEmitter`
  (stages/s14_emit/artifact/default/emitters.py).
- `VTuberEmitter` 는 **키워드 기반 감정 분류** — Geny 의 real-world 요구(LLM 추출, Live2D
  expression index 매핑)에는 약함. Geny 는 자체 `emotion_extractor.py` 를 따로 두고 있음
  (→ 분석 02 §3).
- 확장 벡터: `MoodDeltaEmitter`, `VitalsDecayEmitter`, `RelationshipTickEmitter` 등을
  순차 chain 에 삽입.

### 4-5. EventBus — 비침습 관찰·반응 채널

`events/bus.py` 의 `EventBus`:

```python
pipeline.on("stage.enter", handler)      # 정확 매칭
pipeline.on("*", handler)                # 전체
pipeline.on("stage.*", handler)          # 프리픽스
```

- 동기/비동기 핸들러 모두 지원.
- 핸들러 예외가 파이프라인을 죽이지 않음 (bus.py:77-79).
- **"stage 를 추가하지 않고 tap" 하는 공식 경로** — 다마고치의 "매 iteration 끝날 때
  피로도 +1", "API 호출할 때마다 비용 누적해 '지쳐함' 플래그 세움" 같은 것은 모두
  여기서 해결 가능.
- Stage 자체가 emit 하는 이벤트: `pipeline.start / pipeline.complete / pipeline.error /
  stage.enter / stage.exit / stage.bypass / stage.error`. 사용자 정의 이벤트는
  `state.add_event(type, data)` (state.py:162-176).

### 4-6. Preset Registry — 플러그인 pipeline 공장

`core/presets.py`:

- 내장 preset: `minimal / chat / agent / evaluator / geny_vtuber`.
- 엔트리포인트 그룹: `"geny_executor.presets"` (presets.py:22) — 제3자가 패키지의
  `pyproject.toml` 에 등록하면 `PresetRegistry.discover()` 가 자동 로드.
- `@register_preset("name", description=..., tags=[...])` 데코레이터도 제공.
- **Geny 쪽에서 "tamagotchi_vtuber", "idle_simulator" 같은 자체 preset 을 외부 의존 없이
  공급하기에 가장 가벼운 길.**

### 4-7. attach_runtime — 세션-스코프 런타임 주입

`Pipeline.attach_runtime(**kwargs)` (pipeline.py:509-518) 가 현재 허용하는 키:

```
memory_retriever   → Stage 2 (Context), slot=retriever
memory_strategy    → Stage 15 (Memory), slot=strategy
memory_persistence → Stage 15 (Memory), slot=persistence
system_builder     → Stage 3 (System), slot=builder
tool_context       → Stage 10 (Tool), _context 속성
llm_client         → state.llm_client (전역)
```

- **정확히 6개로 고정** — manifest 가 표현할 수 없는 세션-스코프 객체의 주입점.
- "감정 provider / vitals provider / relationship provider" 를 추가하고 싶다면,
  executor 의 `attach_runtime` 시그니처를 **1회 확장** 하거나
  (메이저 풋프린트) `tool_context` 처럼 우회 주입이 필요.
- 후자의 경우 `ToolContext.metadata: Dict[str, Any]` 를 이미 자유 스크래치로 쓸 수 있음
  (→ 분석 04 §4).

---

## 5. Manifest-First 빌드와 런타임 합일

### 두 갈래 빌드 경로

1. **프로그램적 빌드** — `PipelineBuilder("name").with_tools(...).build()` (builder.py).
2. **선언적 빌드** — `Pipeline.from_manifest_async(manifest, api_key=..., adhoc_providers=...)`
   (pipeline.py).

Geny 가 택한 것은 **선언적 빌드 + attach_runtime** 패턴 (→ 분석 02 §1).
`EnvironmentManifest` 가 stage 구성·strategy 선택·설정값·model_override 를 **직렬화된 파일로** 갖고,
세션이 시작될 때 manifest 를 파이프라인으로 실체화 + 세션별 런타임 객체를 붙인다.

### 이 분리가 주는 것

- **Pipeline 자체는 serializable** — 환경 버저닝 / diff / snapshot / 복원 가능 (core/diff.py).
- **Runtime 객체는 per-session 수명** — LLM client, memory manager, tool context 등은
  절대 파일에 안 들어감.
- 다마고치 설계에 대입하면: "기본 VTuber 페르소나, 상태값 슬롯, 감정 emitter 체인" 은
  manifest 에 고정하고, "이번 세션의 캐릭터 이름 / 사용자-캐릭터 관계 상태 / 지금의 기분" 은
  attach_runtime 에 태워 넣는 구조가 된다.

---

## 6. PipelineMutator — 런타임 변형의 일관 API

`core/mutation.py` 가 허용하는 연산:

| 메서드 | 대상 |
|---|---|
| `swap_strategy(order, slot, impl, config)` | 단일 슬롯 구현 교체 |
| `update_stage_config(order, cfg)` | Stage 자체 config 수정 |
| `update_strategy_config(order, slot, cfg)` | Strategy config 만 수정 |
| `set_stage_model(order, model_cfg)` | **stage 별 모델 오버라이드** |
| `set_stage_active(order, bool)` | 비활성화 (bypass 와 다름 — 완전 끔) |
| `replace_stage(order, new_stage)` | stage 통째 교체 |
| `add_to_chain / remove_from_chain / reorder_chain(order, chain, ...)` | chain 조작 |
| `register_hook(order, event, callback)` | stage-scoped 이벤트 구독 |
| `update_model_config(changes)` | 전역 모델 config |
| `update_pipeline_config(changes)` | `PipelineConfig` 수정 |

- 모든 변형은 `_change_log` 에 기록되고 `_lock` 으로 보호 (mutation.py:96-97).
- 파이프라인 실행 중에는 잠김 (`MutationLocked`) — 안전한 디자인.
- **감정-기반 런타임 교체의 축이다** — "애정도가 낮으면 loop controller 를 'cold' 로",
  "스트레스 100 이면 Guard chain 에 'refuse_interaction' 추가" 같은 동역학이 여기로 떨어짐.

---

## 7. 설계 평가 — 무엇이 훌륭하고 무엇이 제약인가

### 훌륭한 점

1. **Phase 경계의 명료함** — Input → Loop → Egress 의 3-phase 가 읽고 가르치기 쉽다.
   새 스테이지를 넣고 싶다는 유혹이 시작부터 줄어든다.
2. **Stage-Strategy 2중 추상** — 바꿀 만 한 지점은 대부분 Strategy 쪽에서 해결된다.
3. **Slot / SlotChain 타입의 명시성** — "여기는 하나, 저기는 여러 개" 가 시그니처에 박혀 있다.
4. **Manifest + attach_runtime 분리** — 재현성과 세션 특이성의 밸런스가 좋다.
5. **EventBus 의 존재** — stage 추가 없이도 observation / side-effect 가 공식화.
6. **Preset entry-point 발견 메커니즘** — 외부 패키지가 pipeline 공장을 주입할 수 있다.

### 인식된 제약

1. **하드코딩된 Phase 경계 (`LOOP_START/END`, `FINALIZE_START/END`)** — 진짜 "17번째 stage"
   는 불가. 이 제약 자체는 *나쁘지 않다* (테제가 명료해지는 효과), 그러나 플러그인 UX
   설계 시 "아니, 못 해요" 메시지를 친절하게 보여줄 책임이 있다.
2. **`attach_runtime` 의 fixed kwargs** — 새 runtime-scope 객체를 추가하려면 executor
   본체를 수정해야 한다. `**extras: Dict[str, Any]` 같은 free-form 확장이 없다.
3. **`PipelineState` 에 감정·관계·상태값 1급 타입이 없음** — dict 관례에 의존.
4. **`PromptBlock` 은 있으나 "모든 block 을 순서대로 render" 이외의 조합(조건부,
   가중치, A/B) 이 없음** — 상태값에 따라 block 을 동적으로 넣고 빼는 것은 block
   내부 로직으로 해야 함.
5. **단일 파이프라인 순차 실행** — VTuber 화자 대사 생성과 배경 상태값 계산을
   동시에 돌리는 fan-out 이 공식 경로상 없음. "tick" 은 EventBus 나 별도 background
   service 로만 가능 (Geny 의 thinking_trigger 가 이 형태).
6. **Artifact 단위 교체는 너무 거칠다** — 16 중 하나를 통째 대체하는 일은 현실적으로 드물
   어야 하고, 대부분 Strategy 교체로 끝나야 한다.

### 결론

**16-STAGE 아키텍처는 "용기는 고정, 내용물은 풍부하게 교체" 철학이 관철된 좋은 설계다.**
다마고치 / VTuber / 감정 시뮬레이션의 대부분 요구사항은 **이 7겹 확장 표면으로 흡수 가능**.
다만 몇 지점에서 그 흡수가 자연스럽지 않다 (특히 §7.2, §7.3, §7.5) — 이것이
분석 04의 초점이 된다.

---

## 부록 A — 파일 라인 인덱스 (근거)

| 주장 | 파일 | 라인 |
|---|---|---|
| Phase 경계 상수 | `core/pipeline.py` | 209-212 |
| `register_stage` 무검증 | `core/pipeline.py` | 483-486 |
| Phase 실행 루프 | `core/pipeline.py` | 806-859 |
| Stage 예외 핸들링 | `core/pipeline.py` | 933-943 |
| `Stage` ABC | `core/stage.py` | 85-191 |
| `Strategy` ABC | `core/stage.py` | 39-83 |
| `should_bypass` | `core/stage.py` | 131-133 |
| `local_state` 헬퍼 | `core/stage.py` | 355-371 |
| `PipelineState` 필드 | `core/state.py` | 전체 |
| 커스텀 이벤트 훅 | `core/state.py` | 162-176 |
| `attach_runtime` 시그니처 | `core/pipeline.py` | 509-518 |
| `PromptBuilder` / `PromptBlock` ABC | `stages/s03_system/interface.py` | 12-35 |
| `ComposablePromptBuilder` | `stages/s03_system/artifact/default/builders.py` | 131+ |
| 기본 Emitters | `stages/s14_emit/artifact/default/emitters.py` | 12-127 |
| `EventBus` | `events/bus.py` | 21-83 |
| Preset entry-point 그룹 | `core/presets.py` | 22 |
| Mutator 메서드 | `core/mutation.py` | 전체 |
