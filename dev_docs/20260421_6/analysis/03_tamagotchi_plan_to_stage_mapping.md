# 분석 03 — 다마고치 기획을 16-STAGE 에 올리는 설계 지도

**대상.** 유저가 공유한 "AI VTuber 다마고치 / 관계 시뮬레이션" 기획 전문.
**질문.** 기획의 *각 요소* 를 어떤 stage / strategy / slot / runtime 주입점으로 받을 것인가?
**결과.** 거의 모든 기능이 **기존 확장 표면으로 수용 가능**. 단 4개 항목은 새 인터페이스를
요구 (→ 분석 04 에서 제안).

---

## 0. 기획 요약을 시스템 어휘로 번역

| 기획 용어 | 시스템 어휘 | 물리적 위치 |
|---|---|---|
| "다마고치 상태값" (배고픔, 피로, 스트레스, 애정도, 자존감, 호기심) | **CreatureState** — 수명이 세션을 초월하는 상태 벡터 | 현재 부재; `state.shared` dict 또는 새 slot 필요 |
| "책임감 루프 (밥 → 방치 → 관계 악화)" | **Decay Tick + Penalty Hook** | thinking_trigger 의 형제 서비스 |
| "성장 / 변화" | **Progression = CreatureState 누적 + manifest 전환** | manifest 단계별 분기 |
| "예측 불가능성 (랜덤 이벤트)" | **EventSeed strategy** in s02 context | 새로운 retriever 보조 slot 또는 Block |
| "감정 연결 / 기억" | STM / LTM / Notes + **Emotional-weighted 인덱스** | 기존 `MemoryProvider` 의 `Importance` + frontmatter 활용 |
| "단기 / 장기 / 감정 기억" | STMHandle / LTMHandle / NotesHandle (importance 태그) | executor 가 이미 분리해 둠 |
| "기본 인터랙션 (먹이/놀기/대화/선물)" | s10_tool 의 Tool 들 | GenyToolProvider 에 등록 |
| "확장 인터랙션 (콘텐츠 소비 / 일정 / 감정 케어)" | Tool + Memory 조합 | 기존 표면으로 충분 |
| "표정 / Live2D / 감정 애니메이션" | s14_emit 의 Emitter Chain | 기존 구조로 충분 |
| "LLM 감정 태그 출력" | PromptBlock + Parse 후처리 | PersonaBlock + 후처리 규약 |
| "접속 → 확인 → 상호작용 → 반응 → 변화 → 이탈 → 재접속" | **세션 경계 이벤트** | `session.start / session.end` 훅 (부재 — §9) |
| "방치 페널티 (soft)" | Decay Tick + ConditionalStrategy | tick 엔진 + s02/s03/s15 조건 분기 |
| "접속 보상" | Welcome-back retrieval + PersonaBlock variant | s02 context + s03 system |
| "관계 분기 (친밀 ↔ 거리감)" | RelationshipState → PersonaBlock 선택 | `attach_runtime` 주입점 |
| "수익화 (스킨 / 성격 확장 / 기억 슬롯)" | 다른 manifest 로 스왑, 또는 user_opsidian 확장 | 기존 표면 |
| "MVP" | 최소 manifest + 1 CreatureState + 1 persona | 곧바로 구축 가능 |

---

## 1. 기획 ① 책임감 루프 — "밥 줘야 함, 방치하면 망함"

### 필요 요소

1. **상태값 벡터** (배고픔, 피로, 스트레스, 애정도) — 지속적으로 증감.
2. **Decay** — 시간 경과로 수치가 나빠짐.
3. **Restore** — 사용자 행동 (먹이 주기, 놀아주기) 이 수치 회복.
4. **Penalty** — 수치가 낮아지면 대사 톤 / 행동 가능 범위가 바뀜.

### 현재 시스템에 매핑

| 요소 | 1차 매핑 | 2차 매핑 | 필요한 신규 |
|---|---|---|---|
| 상태값 벡터 | `state.shared["creature_state"]` dict 관례 | — | **`CreatureStateProvider`** (신설) |
| Decay | `thinking_trigger.py` 의 주기 루프 확장 | — | `DecayTicker` 서비스 |
| Restore | Tool (s10_tool) — `feed_tool`, `play_tool` | Tool 의 side-effect 로 `CreatureStateProvider.apply(delta)` | — |
| Penalty | s03_system 의 **AffectBlock** (새 PromptBlock) | s13_loop 의 controller 가 상태를 읽고 루프 중단 | **AffectBlock** (신설), 기존 PromptBlock 인터페이스로 구현 가능 |

### 세부 설계 스케치 (구현은 분석 04)

```python
# attach_runtime 에 추가될 수도 있는 키
attach_runtime(
    ...,
    creature_state=SessionCreatureState(session_id=..., store=...),
)

# s03_system 의 PromptBuilder 체인
ComposablePromptBuilder([
    PersonaBlock(persona_text),
    AffectBlock(creature_state),       # 신설
    DateTimeBlock(),
    MemoryContextBlock(),
])

# s10_tool 의 Tool 구현
class FeedTool(Tool):
    async def execute(self, input, context):
        context.creature_state.apply(hunger=-30, happiness=+5)
        return ToolResult(text="먹이를 주었습니다.")
```

### 왜 이 매핑이 자연스러운가

- **AffectBlock** 은 `PromptBlock` ABC 를 준수한다는 점에서 기존 아키텍처와 정합.
- Tool 의 side effect 로 CreatureState 를 바꾸는 것은 "Tool 은 세계에 영향을 준다" 는 원칙
  그대로.
- Decay 는 "입력이 없을 때" 의 일이므로 thinking_trigger 와 같은 외부 tick 서비스로 가는게 맞다.

---

## 2. 기획 ② 성장 / 변화 — "애기 → 성인, 성격 변화"

### 필요 요소

- 시간 누적 / 상호작용 누적 → **phase 전환** (새끼 / 성장기 / 성체).
- phase 별 외형 · 음성 · 페르소나 · 표정맵 변화.
- 사용자 행동에 따른 **분기된 성격** (차분 / 장난스러움 / 츤데레).

### 현재 시스템에 매핑

**이것은 단일 파이프라인이 아니라 "파이프라인 교체"** 의 일로 봐야 한다.

| 요소 | 매핑 |
|---|---|
| Phase 전환 | **manifest 스왑** — 새끼용 manifest, 성장용 manifest, 성체용 manifest |
| 외형 / Live2D | live2d_model_manager 의 모델 교체 |
| 페르소나 | manifest 안의 `PersonaBlock` 텍스트 혹은 `persona_provider` |
| 성격 분기 | 누적된 상호작용 지표 (RelationshipState, PersonalityState) → manifest 선택 시 주입 |

### 왜 manifest 교체가 맞는가

- 한 파이프라인 안에서 "내가 성체가 되면 s08_think 가 켜진다" 같은 *구조적* 변화를 유발하려면
  하드코드 된 조건문이 필요 — 이건 manifest 의 역할.
- executor 가 이미 제공하는 `EnvironmentManifest` + `Pipeline.from_manifest_async` 가
  이 교체의 자연스러운 축이다.
- "성장 이벤트 발생 → 세션 재시작 → 새 manifest" 플로우가 가장 안정적.

### 신설 필요

- **ProgressionState** — CreatureState 의 서브셋. 세션을 넘어 누적되는 "나이 / 상호작용 횟수
  / 트라우마" 등.
- **ManifestSelector** — ProgressionState 를 보고 올바른 manifest id 를 반환하는 함수.
  `agent_session_manager` 의 `env_id` 해석 단계에 삽입.

### 여기서 중요한 주의점

**"phase 전환 중의 기억 보존".** 새 manifest 로 재시작할 때 STM 은 사라질 수 있어도 LTM /
Notes / CuratedKnowledge 는 보존되어야 한다. 다행히 `MemoryProvider` 가 이미
`Scope=SESSION / USER / GLOBAL` 로 분리되어 있어 이 요구를 수용한다.

---

## 3. 기획 ③ 예측 불가능성 — "랜덤 이벤트, 이상한 행동"

### 필요 요소

- 지정 확률로 **예상 밖 대사 / 행동** 이 튀어나와야 "살아있음" 이 느껴진다.
- 완전 랜덤이 아니라 CreatureState + 기억 분포에 따라 *확률이 조정된* 이벤트.

### 현재 시스템에 매핑

| 요소 | 매핑 |
|---|---|
| 이벤트 시드 | s02_context 의 **MemoryContextBlock 확장** 또는 **EventSeedBlock** 신설 |
| 확률 조정 | CreatureState 참조 + 랜덤 가중치 |
| 이벤트 풀 (카탈로그) | user_opsidian 의 특수 category 또는 manifest config |

### 세부 설계 스케치

```python
class EventSeedBlock(PromptBlock):
    """가끔 캐릭터의 상태와 기억 분포에 맞는 '발화 시드' 를 심는다."""

    def __init__(self, creature_state, event_pool, rng_seed=None):
        self.creature_state = creature_state
        self.event_pool = event_pool
        self.rng = random.Random(rng_seed)

    def render(self, state):
        if self.rng.random() > self._trigger_probability():
            return ""
        seed = self._sample_seed(state)
        return f"\n(주인이 알 필요 없는 마음속 생각: {seed})\n" if seed else ""

    def _trigger_probability(self):
        # 호기심 ↑ → 확률 ↑ / 피로도 ↑ → 확률 ↓
        return clamp(0.05 + 0.01 * self.creature_state.curiosity - 0.005 * self.creature_state.fatigue, 0.02, 0.25)
```

### 왜 이게 맞는가

- executor 는 이미 "프롬프트 블록을 순서대로 조립" 한다는 규약을 둔다. 랜덤 이벤트는
  *그 조립 안에서* 프롬프트 입력을 변형하는 블록으로 표현하는 게 가장 이질감 없음.
- 이벤트 풀은 메모리 (curated notes) 의 특정 카테고리로 저장 가능 → 기획자 / 유저가
  편집하기 쉬움.

### 경고

**확률의 가시성.** 유저에게 "이게 랜덤이구나" 가 티 나면 몰입이 깨진다. 이벤트가 *맥락과
맞아떨어지는* 방식으로 삽입되도록 — 시드는 최근 STM / 현재 상태값을 보고 골라야 한다.

---

## 4. 기획 ④ 감정 연결 — "이름, 반응, 기억"

**이 항목이 기획의 심장이며 executor 의 강점이 가장 돋보이는 자리다.**

### 필요 요소

- 사용자 이름 인식 / 호명.
- 과거 상호작용 기억 및 거기에 근거한 반응 ("어제 너 나 무시했잖아...").
- 감정의 *비대칭* 기억 — 좋았던 / 싫었던 순간이 다르게 가중.
- 관계 상태 (친밀도) 의 지속적 추적.

### 현재 시스템에 매핑 — 대부분 이미 구축 완료

| 요소 | 현 시스템 |
|---|---|
| 사용자 이름 | user config + `PersonaBlock` 변수 치환 + STM 메타데이터 |
| 과거 상호작용 기억 | **STM / LTM / Notes** — 이미 구축됨, MemoryProvider 로 통일 |
| 감정 가중 기억 | **Importance** enum (CRITICAL / HIGH / MEDIUM / LOW) + note frontmatter 태그 |
| 관계 상태 | **RelationshipState** — 현재 부재, 신설 필요 |

### 신설 필요

- **RelationshipState** — CreatureState 와 구별. 사용자 *개별* 에 대한 감정값 벡터
  (신뢰 / 친밀 / 경계 / 의존). 한 캐릭터가 여러 사용자를 기억한다면 user_id 키.
- **AffectTagger** — 에이전트 출력 후처리에서 **"이 대화가 좋았다 / 싫었다"** 를 label 하고
  해당 STM/Note 에 `importance` 반영. 이미 있는 `GenyMemoryStrategy._reflect()` 의 친척.

### 피드백 루프 — 현재의 약점

**분석 02 §3 에서 언급한 "감정 결과가 다음 턴으로 돌아오지 않는 문제" 가 정확히 이 기획에서
터진다.** 해결:

1. `VTuberEmitter` 혹은 `CallbackEmitter` 에서 감정 태그를 추출 후,
2. **`state.shared["mood"]` 또는 `creature_state.mood` 에 반영**.
3. 다음 turn 의 s02 context retriever / s03 system AffectBlock 이 그 값을 읽음.

이 피드백 루프는 **새 stage 가 필요 없다** — 기존 slot 에서 가능. 다만 공식 규약을 정해야
재사용 가능한 플러그인으로 쓸 수 있다 (→ 분석 04 §4).

### 기억의 "감정적 가중"

현재 `MemoryProvider.retrieve(query)` 는 기본적으로 keyword / vector 유사도로 랭킹.
"좋았던 기억이 더 많이 떠오른다" 를 구현하려면:

- `RetrievalQuery` 에 `importance_boost` 가 이미 있음 (provider.py)
- 추가로 `mood_filter` — 현재 기분과 일치/상반되는 기억을 선호적으로 추출.
- **구현 방법.** `RetrieverStrategy` 를 커스텀하여 `state.shared["mood"]` 를 읽고 쿼리에
  반영. 기존 `GenyMemoryRetriever` 를 확장하면 끝.

---

## 5. 핵심 루프 (게임 플레이 흐름)

기획안:
```
접속 → 상태 확인 → 상호작용 → 반응 → 변화 → 이탈 → 다시 접속
```

### 각 전이의 위치

| 전이 | 현 시스템의 자리 |
|---|---|
| 접속 | `POST /api/agents` (agent_controller) → AgentSessionManager.create_agent_session → `_build_pipeline` |
| 상태 확인 | 첫 자발 발화 — `[SESSION_OPENED]` 트리거 + PersonaBlock/AffectBlock 으로 상태 반영 |
| 상호작용 | 일반 `invoke(input_text)` 루프 — 16-STAGE |
| 반응 | s14_emit (텍스트+감정+TTS+Live2D) |
| 변화 | Tool 의 side-effect 로 CreatureState 갱신 + s15_memory 로 기억 저장 |
| 이탈 | 세션 종료 — 현재 명시적 훅 **없음** (§9 에서 이슈화) |
| 재접속 | 다음 create → 이전 세션의 LTM / Notes 회상 + "Welcome Back" retrieval |

### 병목 — "이탈 훅" 의 부재

현재 Geny 에는 세션이 **명시적으로 종료되었다** 는 신호를 받는 훅이 얄팍하다. 유저가 그냥
브라우저를 닫고 사라질 수 있음. 대응:

- **TTL 기반 soft close** — 일정 시간 activity 없으면 자동으로 `session.closed` 이벤트 emit.
- 그 이벤트를 수신한 `DecayTicker` 가 decay 모드 전환 (접속 중 decay 속도보다 빠름 /
  "걱정" 감정 부상).
- 다음 접속 시 `session.resumed` 이벤트 → Welcome Back 로직.

**구현 위치.** `agent_session_manager.py` 에서 이미 세션 라이프사이클을 관리하므로 자연스
러운 자리.

---

## 6. 중독 요소 설계

### ① 방치 페널티 (Soft)

- 완전 죽음 ❌ — **삭제 / 리셋 금지**.
- 대신 삐짐 / 우울 / 관계 악화 → CreatureState 특정 필드 저하 → PersonaBlock 의 분기.

**매핑.**
- CreatureState: `mood`, `trust_user`.
- DecayTicker: 미접속 시간 → `mood` 점진 하락.
- AffectBlock: `mood < threshold` 이면 페르소나를 "삐진 말투" 로 전환하는 분기 문구 주입.
- 복귀 가능: 사용자가 돌아와 상호작용하면 회복.

### ② 접속 보상

기획안: "오늘 기다렸어", 특별 이벤트.

**매핑.**
- `session.resumed` 훅 수신 → "welcome back seed" 를 STM 의 맨 앞에 삽입.
- 이 시드는 s02 context 가 읽고, s03 system 이 "이번 턴은 특별한 재회" 컨텍스트를 생성.
- 이벤트 풀에서 **접속 기간 정합 이벤트** 샘플링 (예: 3일만이면 "진짜 오랜만이다", 30분
  지나서 돌아오면 "금방 왔네?").

### ③ 관계 분기

기획안:
- 친해지면: 더 솔직, 더 의존.
- 멀어지면: 거리감, 냉정.

**매핑.** 이것은 **PersonaBlock 의 late-binding** 이 있어야 깨끗. 방법:

- `PersonaBlock` 이 고정 문자열 대신 `Callable[[state], str]` 을 받아 매 turn 렌더.
- 그 callable 은 RelationshipState 를 읽고 **tone preset** 을 반환. ("friendly_v1",
  "cold_v1", "clingy_v1" 등)
- tone preset 카탈로그는 manifest 에 포함 (재현성).

→ **분석 04 §4 에서 PersonaProvider 인터페이스 제안.**

---

## 7. 리스크 대응 — LLM 비용, 반복성, 과몰입

### ① LLM 비용 폭발

**대응 레버:**

- 캐시 breakpoint — s05_cache 의 aggressive_cache 전략. 다마고치 페르소나·affect 블록을
  고정해 prompt cache 에 얹으면 대폭 절감.
- memory_model 라우팅 — 이미 구축됨 (cycle 20260421_4). Haiku 급 경량 모델로 reflection /
  context compaction. 다마고치의 경우 *대다수 발화* 에도 경량 모델 적용 가능 — AffectBlock +
  최근 STM + 도구 호출이 문맥의 대부분.
- `should_bypass` 활용 — "너무 지쳐서 tool 사용 안 함" 같은 상태에서 s10_tool 을 bypass.
- **이벤트 드리븐 발화** — 유저 매 입력마다 full pipeline 돌리지 말고, "진짜 할 말 있을 때만"
  전체 16-STAGE. 짧은 reaction 은 별도 lite-pipeline (input→api→parse→yield 만) manifest.

### ② 반복성

**대응:**

- CreatureState + RelationshipState + EventSeed 조합이 문맥을 매 턴 변화시킴.
- Notes 의 `importance` 기반 retrieval 다양성.
- RAG 쿼리의 `mood_filter` — 같은 기억을 매번 떠올리지 않게 가중 분산.

### ③ 과몰입

**대응:**

- 페르소나 레벨에서 "의존적 말투" 방지 규칙 명시 (RulesBlock 으로).
- CreatureState 의 `trust_user` 가 너무 높으면 역설적으로 캐릭터가 **자립성** 을 드러내는
  분기 (장기적 건강한 관계 유도) — 기획 레벨 결정.
- 사용자 통제 UI — 플레이 시간 제한 / 알림 off / soft reset.

이 대응들은 전부 **기존 확장 표면** 으로 구현 가능 — 신규 stage 필요 없음.

---

## 8. MVP 범위 — 최소로 출발

### 제안: "1 캐릭터, 3 상태값, 텍스트+표정, 하루 5~10분"

**필요 최소 구축:**

| 항목 | 필요 작업 | 신규 vs 재사용 |
|---|---|---|
| 1 캐릭터 | Live2D 모델 1종 + persona.md | 재사용 |
| 3 상태값 (배고픔, 기분, 애정도) | **CreatureState** 타입 + 저장소 | 신규 (분석 04 §1) |
| 4 기본 tool (먹이, 놀기, 대화, 선물) | GenyToolProvider 확장 | 재사용 (툴 프레임워크) |
| 단기 기억 | STMHandle | 재사용 |
| 장기 기억 | LTMHandle + Notes (importance 태그) | 재사용 |
| 감정 태그 | `EmotionExtractor` (이미 있음) | 재사용 |
| 표정 변화 | avatar_state_manager | 재사용 |
| 방치 페널티 (soft) | DecayTicker | 신규 — `thinking_trigger` 형제 |
| 접속 보상 | `session.resumed` 훅 + welcome seed | 신규 — 훅 레이어 확장 |

**새로 만들어야 하는 핵심 3가지**
1. **CreatureState** (타입 + 저장소 + `attach_runtime` 주입점)
2. **AffectBlock** (PromptBlock 서브클래스)
3. **DecayTicker** (thinking_trigger 와 같은 형태의 background service)

나머지는 전부 기존 구조로 해결.

---

## 9. 명시적 이슈 리스트

| # | 이슈 | 현 상태 | 다음 행동 |
|---|---|---|---|
| I1 | `PipelineState` 에 감정·관계·상태값 1급 필드 없음 | dict 관례 | 분석 04 §1 에서 설계 |
| I2 | 감정 추출 결과 → 다음 턴 피드백 훅 없음 | 부재 | 분석 04 §4 |
| I3 | `PersonaBlock` late-binding 불가 — 고정 문자열 | `_system_prompt` 사이드도어로 우회 중 | 분석 04 §4 |
| I4 | 세션 종료 / 재개 이벤트 얄팍 | `agent_session_manager` 에 일부 | 분석 04 §5 |
| I5 | Tick 엔진 통일 부재 (thinking_trigger 하나만 존재) | 단일 | 분석 04 §6 |
| I6 | 이벤트 풀 카탈로그 표준 없음 | 부재 | 기획 트랙 — 이 사이클 범위 밖 |
| I7 | Progression / Phase 전환 훅 없음 | 부재 | 분석 04 §7 |
| I8 | executor 의 `attach_runtime` kwargs 고정 — 신규 주입점 추가 시 executor 수정 필요 | fixed | 분석 04 §2 에서 확장 방식 논의 |
| I9 | 감정 기반 retrieval 가중 없음 | 기본 vector/keyword | 분석 04 §3 |

---

## 10. 기획-스테이지 최종 대응표

| 기획 기능 | 주 스테이지 | 보조 | 신규 구성요소 |
|---|---|---|---|
| 상태값 표시 | s03_system | attach_runtime | CreatureStateProvider, AffectBlock |
| 상태값 변동 (tool) | s10_tool | — | side-effect 규약 |
| 기본 대화 | s02→s03→s06→s09→s14 | 메모리 | — |
| 방치 감지 | (외부 tick) | s02 retrieval | DecayTicker |
| 접속 보상 | (외부 훅) → s02 | s03 persona 분기 | session.resumed 훅 |
| 감정 출력 | s14_emit | EmotionExtractor | 피드백 훅 |
| 관계 분기 | s03_system | attach_runtime | PersonaProvider |
| 랜덤 이벤트 | s03_system | CreatureState | EventSeedBlock |
| 기억 저장 | s15_memory | — | AffectTagger 연장 |
| 기억 회상 | s02_context | — | mood_filter retrieval |
| 성장 (phase) | manifest 스왑 | AgentSessionManager | ProgressionState + ManifestSelector |
| Live2D 표정 | s14_emit callback | avatar_state_manager | — |
| TTS | s14_emit callback | TTS 서비스 | — |
| 수익화 - 스킨 | live2d_model_manager | — | — |
| 수익화 - 성격 팩 | manifest 추가 | user_opsidian | — |
| 수익화 - 기억 슬롯 확장 | MemoryProvider 설정 | — | — |

**요지:** 다마고치의 90% 는 *이미 있는 stage / slot / runtime 에* 수용된다. 새로 만들 것은
**상태값 소재 (CreatureState) + 상태값 렌더 (AffectBlock) + 상태값 감소자 (DecayTicker) +
감정 피드백 훅 + 관계 분기 (PersonaProvider) + phase 전환 (ManifestSelector)** — 6개
컴포넌트가 전부. 전부 executor 의 기존 확장 표면 안에서 조립 가능 (단 I8 은 `attach_runtime`
확장이 필요 — 분석 04 §2 에서 선택지 제시).
