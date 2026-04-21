# 분석 05 — 격차 · 리스크 · 로드맵

**목적.** 분석 01~04 에서 발견한 격차를 *엔지니어링 우선순위* 와 *리스크 가중* 으로 재정렬.
어떤 사이클을 어느 순서로 돌릴지, 각 사이클이 무엇을 깨뜨릴 수 있는지 명시.

**이 문서는 구현 계획이 아니다.** 각 사이클의 *분석 + 계획* 은 이후 사이클 폴더에서 별도 작성.

---

## 0. 격차 목록 — 9개

분석 02, 03 에서 확인된 이슈 (I1..I9) 를 세 카테고리로 재분류:

### 카테고리 Ⅰ — 런타임 상태 모델의 빈 공간

- **I1.** `PipelineState` 에 감정 / 관계 / 상태값 1급 필드 없음.
- **I7.** Progression / Phase 전환 공식 훅 없음.
- **I8.** `attach_runtime` kwargs 고정 — 신 주입점 추가 시 executor 수정 필요.

### 카테고리 Ⅱ — 피드백 · 순환성의 부재

- **I2.** 감정 추출 결과 → 다음 턴 피드백 훅 부재 (현재 단방향).
- **I3.** PersonaBlock late-binding 불가 (`_system_prompt` 사이드도어 3곳).
- **I9.** 기분 기반 기억 retrieval 가중 없음.

### 카테고리 Ⅲ — 라이프사이클 · 오케스트레이션의 얄팍함

- **I4.** 세션 lifecycle 이벤트 체계 얄팍 (session.resumed / abandoned / closed 등).
- **I5.** Tick 엔진 통일 부재 — thinking_trigger 하나만 존재.
- **I6.** 이벤트 풀 카탈로그 표준 없음 (이건 기획 트랙이므로 본 사이클 범위 밖).

---

## 1. 리스크 매트릭스

각 격차가 다마고치 기획을 *얼마나 막는가* + 해결이 *얼마나 어려운가* + 잘못 만들면
*얼마나 위험한가*.

| # | 격차 | 기획 블로킹 정도 | 해결 난이도 | 잘못 만들 시 위험 | 우선순위 |
|---|---|---|---|---|---|
| I3 | PersonaBlock late-binding | 🟥 높음 — 관계 분기 불가 | 🟢 낮음 (B 제안) | 🟢 낮음 (사이드도어 제거) | **1** |
| I4 | 세션 lifecycle 이벤트 | 🟥 높음 — 접속보상/방치 불가 | 🟡 중 (E 제안) | 🟡 중 (잘못된 이벤트 시멘틱) | **2** |
| I5 | Tick 엔진 통일 | 🟥 높음 — decay/event 둘 다 필요 | 🟡 중 (F 제안) | 🟡 중 (concurrency bug) | **3** |
| I1 | CreatureState 1급 모델 | 🟧 중 — MVP 는 dict 가능 | 🟡 중 (A 제안) | 🟧 중 (스키마 고착) | **4** |
| I2 | 감정 피드백 | 🟧 중 — MVP 없어도 OK | 🟢 낮음 (D 제안) | 🟢 낮음 | **5** |
| I9 | 기분 기반 retrieval | 🟨 낮음 — v2 이후 | 🟢 낮음 (C 제안) | 🟢 낮음 | **6** |
| I7 | Progression 훅 | 🟨 낮음 — 초기 MVP 는 단일 phase | 🟢 낮음 (G 제안) | 🟡 중 (manifest 폭증) | **7** |
| I8 | attach_runtime 확장 | 🟨 낮음 — ToolContext 우회 가능 | 🟢 낮음 | 🟡 중 (하위호환) | **8** |
| I6 | 이벤트 풀 | 🟨 낮음 — 기획 트랙 | — | — | 트랙 외 |

**우선순위 1~3** 은 기획의 *핵심 감정 루프* 를 직접 막으므로 먼저. 이 셋은 **서로 부분적으로
엮여 있다** — PersonaBlock late-binding 은 SessionLifecycleBus 의 신호를 소비, TickEngine
은 SessionLifecycleBus 의 .resumed/.abandoned 를 구독. 따라서 한 사이클에서 통합 설계를 잡고
세 PR 로 나눠 내는 편이 품질에 유리.

---

## 2. 리스크 — "잘못 만들면 무엇이 깨지는가"

### 2-1. CreatureState 스키마를 너무 일찍 고정할 리스크

- vitals 를 (hunger, fatigue, stress) 3개로 잡고 MVP 릴리즈 → "자존감 / 호기심 을 추가하려면
  저장소 migration" 이 필요해짐.
- **완화.** MVP 에서는 `vitals: Dict[str, float]` 의 free-form 으로 두고, UI / 게임 로직이
  이름을 선언적으로 관리. 저장소 스키마는 JSON blob 로 시작.
- **궁극.** frontend UX 안정 후 정식 dataclass 필드로 승격.

### 2-2. 감정 피드백 루프가 발산할 리스크

- 매 턴 `mood["sad"] += 0.1` 반복 → 몇 턴 만에 확정 우울.
- **완화.**
  - 감쇠 계수 (decay) 를 CreatureStateProvider 내부에 내재화.
  - `apply()` 가 아닌 `set()` 을 EmitToStateEmitter 쪽에서 쓸 수 있도록 구분.
  - mood 를 확률 분포로 보고 유지 (sum=1) → softmax 정규화 규약.

### 2-3. Manifest 폭증 리스크

- phase 마다, 성격 분기마다, 커스터마이즈마다 manifest 파일이 기하급수적으로 늘어남.
- **완화.**
  - `manifest inheritance` — base manifest + overlay 패턴.
  - `ManifestSelector` 는 dimension 별로 식별 (phase, persona_pack, progression) 하고
    자동 조합.
  - 유저-생성 manifest 는 `user_opsidian` 처럼 별도 공간에.

### 2-4. Tick 엔진의 동시성 리스크

- 복수 ticker 가 creature_state 를 동시에 apply → race.
- **완화.**
  - `CreatureStateProvider` 내부 `asyncio.Lock` per session.
  - delta 적용은 반드시 transactional.
  - 감사 로그 (reason field) 를 필수화해 원인 추적.

### 2-5. `PersonaProvider` 의 persona 전환이 무절제해질 리스크

- 매 턴 다른 톤 → 몰입 붕괴.
- **완화.**
  - tone 전환에 `stickiness` — 한 번 바뀐 톤은 최소 N턴 유지.
  - 전환은 상태의 *누적 임계값* 이 넘어서야 발동 (기분의 순간값이 아니라 EMA).
  - tone 카탈로그를 좁게 유지 (3~5개).

### 2-6. LLM 비용 폭증 리스크

- 다마고치는 *저 iteration, 고 빈도* — 한 유저가 하루에 20~50회 invoke 가능.
- 만약 매 invoke 가 풀 16-STAGE + memory reflection 이면 비용 비참.
- **완화.**
  - "reaction pipeline" manifest 신설 — s02 context (축소) + s03 system (AffectBlock 포함) +
    s06 api (Haiku) + s09 parse + s14 emit + s16 yield. 7개 stage 만.
  - 사용자 입력이 "진짜 용건" 인지 "가벼운 반응 유도" 인지 s01_input 의 validator 가 분류.
  - 용건이 가벼우면 reaction manifest 로 라우팅.
  - 무거운 경우만 풀 16-STAGE.

### 2-7. executor v0.30 으로 가기 전 결정사항 누적 리스크

- 카테고리 Ⅰ 대부분의 이슈는 executor 수정을 *요구하지 않지만*, I8 (`attach_runtime` 확장) 은
  결국 필요해질 수 있음.
- **완화.** 당분간 ToolContext.metadata 경유로 우회, 2개 이상의 신규 런타임 객체가 필요해지는
  시점에 executor 0.30 에서 한 번에 확장 (deprecation cycle 없이 가능 — 새 kwarg 는 옵션).

---

## 3. 로드맵 — 5 사이클 개관

**본 사이클 (20260421_6)** 은 분석만. 이후 사이클 구성:

### 사이클 X1 — PersonaProvider + DynamicPersonaBlock (I3)

- **범위.** Geny only, executor 변경 없음.
- **PR 수.** 1~2개.
  - PR-1: Geny 에 `PersonaProvider` Protocol + `DynamicPersonaBlock` 구현.
  - PR-2: 사이드도어 3곳을 `PersonaProvider.append_character()` 등으로 rewire.
- **성공 기준.** `grep _system_prompt` 결과가 `AgentSession.__init__` 의 저장 한 곳으로 수렴.
- **리스크.** prompt 정확도 regression — 기존 텍스트 concat 과 비트 단위로 같은 결과가
  나오는지 회귀 테스트 필요.

### 사이클 X2 — SessionLifecycleBus + TickEngine (I4, I5)

- **범위.** Geny only.
- **PR 수.** 2~3개.
  - PR-1: `SessionLifecycleBus` 구축 + 기존 `agent_session_manager` 훅 migration.
  - PR-2: `TickEngine` + `Ticker` Protocol 신설.
  - PR-3: 기존 `thinking_trigger` 를 Ticker 로 rewrite.
- **성공 기준.** 새 Ticker 추가 시 스케줄링 / cooldown / cleanup 을 직접 다루지 않아도 됨.
- **리스크.** thinking_trigger 의 886 줄 복잡도 → 행동 변화 없는 리팩터가 핵심.

### 사이클 X3 — CreatureState + AffectBlock (I1, I2)

- **범위.** Geny only (MVP — ToolContext.metadata 우회).
- **PR 수.** 3~4개.
  - PR-1: `CreatureStateProvider` Protocol + `SessionCreatureState` 구현 + 저장소.
  - PR-2: `AffectBlock` (PromptBlock 구현).
  - PR-3: `EmitToStateEmitter` (감정 피드백).
  - PR-4: `DecayTicker` (X2 의 Ticker 구현체).
- **성공 기준.** 캐릭터가 배고프면 대사 톤이 바뀌고, 놀아주면 회복.
- **리스크.** 감정 루프 발산 → §2-2 의 완화책 필수.

### 사이클 X4 — ManifestSelector + Progression (I7)

- **범위.** Geny only.
- **PR 수.** 2개.
  - PR-1: `ManifestSelector` + `ProgressionState`.
  - PR-2: 새끼/성장/성체 manifest 3종 + 전환 이벤트.
- **성공 기준.** `session.phase_changed` 에 반응해 파이프라인 재빌드 가능.
- **리스크.** manifest 폭증 → §2-3 완화책 필수.

### 사이클 X5 — Plugin Protocol + Registry (추론적, I8 연동)

- **범위.** Geny + 선택적 executor 확장.
- **PR 수.** 2~3개.
  - PR-1: `GenyPlugin` Protocol + `PluginRegistry` + entry-point 로딩.
  - PR-2: `geny-tamagotchi-core` 플러그인으로 기존 로직 재패키징 (선택).
  - PR-3 (선택): executor `attach_runtime` 확장.
- **성공 기준.** 외부 패키지 1개 설치로 캐릭터 변형이 주입 가능.
- **리스크.** Plugin API 를 너무 일찍 고정할 리스크 → α~γ phase (분석 04 §10) 처럼 점진.

### 사이클 X6 — AffectAwareRetriever + 비용 최적화 (I9, 2-6)

- **범위.** Geny only.
- **PR 수.** 1~2개.
  - PR-1: `AffectAwareRetriever` decorator.
  - PR-2: "reaction pipeline" manifest + input router.
- **성공 기준.** 가벼운 reaction 경로에서 LLM 비용 50% 이상 감소.
- **리스크.** router 오분류 (진짜 용건을 reaction 으로) → validator 튜닝 필수.

---

## 4. 사이클 X1~X3 의 통합 관찰

### X1 → X2 → X3 은 하나의 긴 여정

- X1 이 PersonaProvider 로 "관계가 페르소나를 결정" 의 인프라를 깔아줌.
- X2 가 SessionLifecycleBus + TickEngine 으로 "무엇이 언제 일어나는가" 를 규약화.
- X3 가 CreatureState 로 "무엇이" 의 구체 내용을 채움.

따라서 X1~X3 은 **하나의 통합 사이클 (혹은 밀접한 연속 사이클 3개)** 로 보는 편이 좋다.
각각 독립 배포는 가능하지만, 각 사이클이 *다음 사이클의 hook 을 미리 남긴다*:

- X1 의 `PersonaProvider.pick_tone(snap)` 에서 `snap` 인자를 `Optional[CreatureStateSnapshot]`
  로 미리 선언 (나중에 채워도 되도록).
- X2 의 `TickEngine` 은 `creature_state=Optional[...]` 로 받아 X3 에서 사용.
- X3 의 모든 변경이 X1/X2 의 인터페이스에 *가공* 만 함 — 구조 변경 없이.

### 전-사이클 공통 원칙

1. **executor 수정은 최대한 미룬다.**
2. **신규 인터페이스는 Protocol 로 시작** — ABC 로 잠그지 않음.
3. **사이드도어를 열지 않는다** — `_system_prompt` 같은 private attribute 수정 금지.
4. **리팩터와 기능추가를 같은 PR 에 섞지 않는다.**
5. **Progress 노트에 *감정 루프* 회귀 테스트 결과를 기록** — behavioral test 는 이 도메인에서
   가장 쉽게 깨짐.

---

## 5. 이 사이클에서 **하지 않을** 것들

분석 작업의 스코프를 명확히 하기 위해:

- ❌ 구현 코드 작성.
- ❌ executor 수정 (v0.30 분기 생성도 하지 않음).
- ❌ PR 개설.
- ❌ 기획 내용의 *업데이트* — 기획 원안을 수정하지 않음, 시스템에 매핑만.
- ❌ 이벤트 풀 카탈로그 / 감정 태그 어휘 설계 — 이는 기획 트랙.

**이 사이클의 유일한 산출은 `dev_docs/20260421_6/analysis/` 의 5개 문서.**

---

## 6. 완료 기준

- [x] 16-STAGE 아키텍처의 각 확장점이 파일 라인 수준 근거와 함께 문서화.
- [x] Geny 의 통합 지점 (clean + side-door) 이 전수 식별.
- [x] 다마고치 기획의 모든 기능이 stage/slot/runtime 주입점으로 매핑.
- [x] 17번째 stage 없이 플러그인 UX 를 제공할 설계 제안.
- [x] 6개 사이클 로드맵 초안.

다음 진입점은 **사이클 X1 (PersonaProvider)** 의 `analysis/plan` 단계.
그 때까지 이 분석들은 *decisional bedrock* 으로 남는다 — 구현 중 판단이 필요할 때
돌아올 레퍼런스.
