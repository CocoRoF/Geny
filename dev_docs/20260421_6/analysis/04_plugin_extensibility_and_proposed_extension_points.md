# 분석 04 — 플러그인 인터페이스 평가 & 확장점 제안

**질문.** 유저의 요청 — "**PLUGIN STAGE** 같은 공식적인 외부 모듈 확장 공간을 열어 둘 수
있는가?"
**결론 미리.** **17번째 stage 를 여는 것은 반대.** 대신 기존 확장 표면을 *정리하고 이름을
주어* 플러그인처럼 쓸 수 있게 만드는 편이 모든 면에서 유리하다.
이 문서는 **4개의 확장점을 신설·정리하는 설계안** 을 제시한다 (코드 없이, 인터페이스 수준만).

---

## 0. 왜 "17번째 Stage" 가 나쁜 선택인가

### 설계 관점

1. **Phase 경계의 의미를 흐린다.** `LOOP_START=2 / LOOP_END=13 / FINALIZE_START=14 /
   FINALIZE_END=16` 은 "이 파이프라인이 정확히 무엇을 한다" 를 표현하는 *헌법*.
   17번째 stage 는 그것이 "무엇을 한다" 는 정의를 잃게 한다.
2. **데이터 계약 확산.** 모든 stage 는 `input, state` 을 받고 `out` 을 돌려준다.
   17번째 stage 는 어떤 input 을 받는가? 어떤 out 을 돌려주는가? 표준 답이 없다.
   → 각 플러그인마다 다른 규약 → 사용자 혼돈.
3. **순서 지옥.** 1..16 은 엄격한 의미 순서 (ingress→loop→egress). 17은 어디에 붙는가?
   13.5? 14.5? 복수 플러그인이 있을 때 순서가 누구의 책임인가?
4. **이벤트와 이중화.** 이미 EventBus 가 있다 — stage 변화마다 이벤트가 emit 된다.
   side-effect 를 원하면 EventBus 가 정답.
5. **대체재 존재.** 지금까지 요청된 모든 "17번째 stage 후보" (감정 후처리, 상태값 decay,
   텔레메트리, 분석 수집 ...) 는 **전부 기존 7겹 표면 중 하나로 표현 가능**.

### 경험적 증거

분석 02 에서 Geny 가 파이프라인에 *덧붙이고 싶었던* 모든 기능 (EmotionExtractor,
avatar_state_manager, thinking_trigger, CurationEngine) 은 *실제로* 파이프라인 외부 혹은
기존 slot 내부로 깨끗하게 들어갔다. 17번째가 있어야 했던 경우가 하나도 없다.

---

## 1. 신설 제안 A — **CreatureStateProvider** (attach_runtime 확장)

### 문제 — I1, I2, I7 (분석 03)

- `PipelineState` 는 감정·관계·상태값 1급 필드 없음.
- `state.shared["..."]` dict 관례는 타입 안전성 없음, 직렬화 경로 없음, stage 교체로
  규약 공유 불가.
- 다마고치에서는 이것이 **전 스테이지 공통 의존 데이터** — dict 관례로 두면 모든
  AffectBlock / Tool / EventSeedBlock / AffectTagger 가 제각각 키 규약을 만든다 → 혼돈.

### 제안 (인터페이스 수준)

```python
# geny_executor/state/creature.py (신설)

@runtime_checkable
class CreatureStateProvider(Protocol):
    """세션-수명 영속 상태 벡터.

    MemoryProvider 와 구별:
      - MemoryProvider 는 '무엇을 경험했는가' (기억).
      - CreatureStateProvider 는 '지금 어떤 존재인가' (바이탈 + 기분 + 관계).
    """

    async def read(self) -> CreatureStateSnapshot: ...
    async def apply(self, delta: CreatureStateDelta) -> None: ...
    async def snapshot_for(self, layer: str) -> Dict[str, Any]: ...

@dataclass
class CreatureStateSnapshot:
    vitals: Dict[str, float]        # e.g. {"hunger": 40.0, "fatigue": 20.0}
    mood:   Dict[str, float]        # e.g. {"happy": 0.6, "lonely": 0.1}
    relationships: Dict[str, Dict[str, float]]  # user_id → relation vector
    progression: Dict[str, Any]     # age, phase, milestones
    updated_at: datetime

@dataclass
class CreatureStateDelta:
    vitals: Dict[str, float] = field(default_factory=dict)   # additive
    mood:   Dict[str, float] = field(default_factory=dict)
    relationship: Optional[Tuple[str, Dict[str, float]]] = None
    progression: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""                # 감사 로그용
```

### 통합 방식 — `attach_runtime` 확장

executor `Pipeline.attach_runtime()` 시그니처에 **1개 선택 인자 추가**:

```python
def attach_runtime(
    self,
    *,
    memory_retriever=None,
    memory_strategy=None,
    memory_persistence=None,
    system_builder=None,
    tool_context=None,
    llm_client=None,
    creature_state=None,       # 신설
) -> None:
    ...
    if creature_state is not None:
        # 공개 접근: state.creature_state = provider
        # 각 stage 에서 state.creature_state.read() / apply() 로 사용
        self._creature_state = creature_state
```

- **일회성 수정** — 이후 다른 "런타임 플러그인" 이 필요하다면 **같은 패턴** 을 따르면 됨.
- Geny 는 세션 단위로 자체 `SessionCreatureState` 구현 후 주입.

### 대안 — 확장하지 않고 ToolContext 에 얹기

- `ToolContext.metadata: Dict[str, Any]` 가 이미 임의 데이터를 들고 들어갈 수 있음.
- 단점: Tool 에만 접근 가능. s03 의 PromptBlock / s15 의 MemoryStrategy 에선 직접 접근 불가
  (state 로 공유해야 함).
- **권고.** ToolContext.metadata 로 시작 (MVP), 공식 인터페이스가 필요해지면 attach_runtime
  확장 (v1 이후).

---

## 2. 신설 제안 B — **PersonaProvider** (s03_system 확장)

### 문제 — I3 (분석 03)

- `PersonaBlock(persona_text)` 은 문자열 단발.
- 관계/기분에 따라 페르소나를 동적으로 바꾸려면 Geny 가 `_system_prompt` 를 외부에서 수정
  (사이드도어 3곳 — 분석 02 §5).
- 이는 약한 합성 방식, 재빌드 정합성 문제 있음.

### 제안 — PromptBlock 의 late-binding 확장

`PromptBlock` ABC (현 `stages/s03_system/interface.py:20-35`) 는 이미 `render(state)` 메서드
에서 state 을 받는다. 즉 **late-binding 을 위한 훅이 이미 있다.**

**필요한 것은 새 ABC 가 아니라 _공식 PersonaProvider 관례의 합의_.** 즉:

```python
# 이미 가능한 형태 — executor 수정 불필요
class DynamicPersonaBlock(PromptBlock):
    def __init__(self, persona_provider: PersonaProvider):
        self._provider = persona_provider

    @property
    def name(self) -> str:
        return "persona"

    def render(self, state: PipelineState) -> str:
        snapshot = state.creature_state.read_sync()   # or cached
        tone = self._provider.pick_tone(snapshot)
        return self._provider.render(tone, state)

@runtime_checkable
class PersonaProvider(Protocol):
    """페르소나 토널리티를 상태 스냅샷에서 선택."""
    def pick_tone(self, snap: CreatureStateSnapshot) -> str: ...
    def render(self, tone: str, state: PipelineState) -> str: ...
```

- executor 는 이미 render(state) 의 훅이 있으므로 **신규 ABC 없이** PersonaProvider 관례를
  선언만 하면 됨.
- Geny 쪽에 `SessionPersonaProvider` 구현체를 두고 `DynamicPersonaBlock` 에 주입.
- 사이드도어 3곳을 이것으로 수렴하면 `_system_prompt` 직접 수정이 사라진다.

### 이행 경로

1. Geny 에 `DynamicPersonaBlock + PersonaProvider` 도입.
2. `vtuber_controller` / `agent_controller` / `agent_session_manager` 의 3 사이드도어를
   `persona_provider.append_character(...)` / `.replace(...)` 형태로 rewire.
3. `_system_prompt` attribute 는 최종 fallback 으로만 유지 (혹은 완전 제거).

---

## 3. 신설 제안 C — **AffectAwareRetrieverMixin** (s02_context 확장)

### 문제 — I9 (분석 03)

- 현 `MemoryProvider.retrieve(query)` 는 keyword/vector.
- 다마고치의 "좋았던 기억이 더 자주 떠오름" 을 위해 현재 기분과 기억의 감정 가중 매칭이
  필요.

### 제안 — Retriever 쪽 Wrapper

신규 executor 수정 없음. Geny 의 `GenyMemoryRetriever` 내부에서:

```python
class AffectAwareRetriever(MemoryRetriever):
    def __init__(self, inner: MemoryRetriever, creature_state: CreatureStateProvider):
        self._inner = inner
        self._state = creature_state

    async def retrieve(self, state: PipelineState) -> List[Dict[str, Any]]:
        snap = await self._state.read()
        # 기분과 정합하는 감정 태그를 가진 기억에 가중
        refs = await self._inner.retrieve(state)
        return self._rerank_by_mood(refs, snap.mood)
```

- 완전히 *데코레이터* 패턴 — executor 는 전혀 모름.
- `attach_runtime(memory_retriever=AffectAwareRetriever(base, state))` 으로 주입.
- 이 접근이 통하면 동일 패턴으로 `AffectAwareMemoryStrategy` 도 가능 (s15 쪽).

**이 단순함이 16-STAGE 테제의 힘이다** — executor 본체 수정 없이 Geny 쪽에서 데코레이션 만으로
기능 추가.

---

## 4. 신설 제안 D — **EmitToState 훅** (s14_emit → 피드백)

### 문제 — I2 (분석 03)

- 감정 추출 결과가 `state.shared["mood"]` 로 돌아와 다음 iteration 에 반영돼야 함.
- 현재 VTuberEmitter / CallbackEmitter 는 부작용 채널로만 사용 — state 를 쓰지 않음.

### 제안 — 공식 피드백 Emitter

**executor 수정 불필요, 단지 Geny 측 Emitter 구현.**

```python
class EmitToStateEmitter(Emitter):
    """Emitter 결과를 state.shared 및 creature_state 로 피드백."""

    def __init__(self, extractor, state_attr="shared", key="mood"):
        self._extractor = extractor
        self._state_attr = state_attr
        self._key = key

    @property
    def name(self) -> str:
        return "emit_to_state"

    async def emit(self, state: PipelineState) -> EmitResult:
        result = self._extractor.extract(state.final_text)

        # 즉시 shared dict 로
        getattr(state, self._state_attr)[self._key] = result.primary_emotion

        # 영속 상태 업데이트 (세션 간 보존)
        if state.creature_state is not None:
            await state.creature_state.apply(
                CreatureStateDelta(mood={result.primary_emotion: 0.1}, reason="emit_tag")
            )
        return EmitResult(emitted=True, channels=["state"], metadata={...})
```

- s14_emit 의 emitters chain 끝에 추가.
- 이후 iteration 의 s02 retriever / s03 AffectBlock 이 `state.shared["mood"]` 를 읽음.
- **Chain 의 순서가 핵심** — Text → Callback (UI broadcast) → VTuberEmitter (Live2D) →
  EmitToStateEmitter (피드백) → TTS. 피드백은 UI emit 후에 놓아 UI 지연 없이 다음 턴에
  반영.

---

## 5. 신설 제안 E — **SessionLifecycleBus** (세션 경계 이벤트)

### 문제 — I4 (분석 03)

- 세션 `.start / .end / .resumed / .abandoned` 의 공식 이벤트 채널 없음.
- `agent_session_manager` 에 개별 hook 이 흩어져 있음.

### 제안 — executor 의 EventBus 와 쌍을 이루는 **Geny 측 SessionEventBus**

- executor 의 EventBus 는 *파이프라인 단일 run 수명* 이벤트.
- 다마고치는 **세션 수명 / 캐릭터 수명** 이벤트가 필요 — 이 레이어는 executor 의 관할이 아님.
- Geny 가 `agent_session_manager.py` 상위에 `SessionEventBus` 를 신설하고 다음 이벤트를 emit:

```
session.created           (character_id, user_id, manifest_id)
session.started           (첫 invoke 직전)
session.turn_ended        (iteration 하나 끝)
session.idle_detected     (thinking_trigger 의 기존 이벤트와 통일)
session.abandoned         (TTL 초과)
session.resumed           (다시 invoke 도착)
session.phase_changed     (Progression 전환)
session.closed            (명시적 종료)
```

- `DecayTicker`, `WelcomeBackInjector`, `PhaseChangeTransitioner` 등 모든 tick 서비스가 이
  단일 bus 를 구독.
- executor EventBus 와 *연결* 은 optional — 파이프라인 `pipeline.start / complete` 를
  `session.turn_ended` 로 수렴시키는 브리지가 있으면 충분.

### 왜 executor 에 안 넣고 Geny 에 넣는가

- 세션 / 캐릭터 / 유저 / manifest 는 **Geny 의 비즈니스 도메인**.
- executor 는 "파이프라인 한 번 돌려줘" 까지의 책임만 진다 — 도메인 침투를 피하는 건 설계 원칙.
- "**executor 는 인지 엔진, Geny 는 관계 관리자**" 라는 분업이 분명해진다.

---

## 6. 신설 제안 F — **TickEngine** (thinking_trigger 의 일반화)

### 문제 — I5 (분석 03)

- 현재 Geny 에는 `thinking_trigger.py` 만 존재 (886 줄).
- 다마고치에는 **최소 3종** 의 주기 작업이 필요:
  1. DecayTicker — 상태값 감소.
  2. ThinkingTrigger — 유휴 자가 발화 (기존).
  3. EventSampler — 랜덤/조건부 이벤트 풀 샘플링.
- 세 가지를 제각각 구현하면 scheduling / concurrency / 세션 수명 관리가 중복.

### 제안 — 단일 TickEngine 추상

```python
class TickEngine:
    """세션 별 주기 작업 오케스트레이터.

    각 Ticker 는 session 에 관심사를 선언하고, TickEngine 이 스케줄 + 우선순위 + cooldown 관리.
    """
    def register(self, ticker: Ticker) -> None: ...
    async def start(self, session_id: str) -> None: ...
    async def stop(self, session_id: str) -> None: ...

class Ticker(Protocol):
    name: str
    interval_sec: float
    async def tick(self, session: SessionHandle) -> Optional[TickAction]: ...

@dataclass
class TickAction:
    kind: str                       # "inject_input" | "apply_state" | "emit_event" | "noop"
    payload: Any
    dedup_key: Optional[str] = None
```

- `ThinkingTrigger` → `inject_input` 액션 생성.
- `DecayTicker` → `apply_state` (creature_state.apply) 액션 생성.
- `EventSampler` → `emit_event` (SessionEventBus) 액션 생성.
- 기존 886 줄짜리 thinking_trigger 는 이 엔진의 Ticker 구현체 하나로 축소.

### 이점

- 세션 ↔ 캐릭터 생명주기와 통합 — `session.abandoned` 시 전부 stop, `session.resumed` 시
  전부 start.
- 백프레셔 / cooldown 을 한 곳에서.
- 테스트 가능성 향상 — Ticker 를 고립 테스트.

---

## 7. 신설 제안 G — **ManifestSelector** (Progression → 파이프라인 재빌드)

### 문제 — I7 (분석 03)

- "애기 → 성장기 → 성체" phase 전환 시 파이프라인 구조가 달라져야 하는데 공식 훅 없음.

### 제안 — AgentSessionManager 에 phase hook

기존:
```python
env_id = request.env_id or resolve_default_env(role)
```

확장:
```python
env_id = request.env_id or resolve_default_env(role)
if character_id is not None:
    progression = await creature_state_store.read_progression(character_id)
    env_id = manifest_selector.pick(env_id, progression)
```

- `ManifestSelector` 는 "기본 env_id + progression 스냅샷" 을 받아 "실제 사용할 env_id" 반환.
- 세션 생성 시 1회 결정 — phase 변경은 세션 재시작 시 반영 (안전).
- In-session phase 전환이 필요하면 `session.phase_changed` 이벤트 → `AgentSessionManager.reload`
  → 새 manifest 로 파이프라인 재빌드.

**이는 executor 수정 없이 Geny 레이어에서 완전 수용.**

---

## 8. 이제 각 신설점이 어디에 사는가

| 신설점 | 최소 수정 범위 | executor 수정 필요? |
|---|---|---|
| A. CreatureStateProvider | Geny (`SessionCreatureState` 구현) + optional executor `attach_runtime` 1줄 | 선택적 (MVP 는 ToolContext.metadata 사용) |
| B. PersonaProvider | Geny (`DynamicPersonaBlock`) | ❌ 없음 |
| C. AffectAwareRetriever | Geny (`GenyMemoryRetriever` decorator) | ❌ 없음 |
| D. EmitToStateEmitter | Geny (`Emitter` 구현) | ❌ 없음 |
| E. SessionLifecycleBus | Geny (`agent_session_manager` 레벨) | ❌ 없음 |
| F. TickEngine | Geny (`thinking_trigger` 리팩터) | ❌ 없음 |
| G. ManifestSelector | Geny (`agent_session_manager` 레벨) | ❌ 없음 |

### 핵심 통찰

**7개 제안 중 *6개는 executor 수정 없이 Geny 레이어만으로* 완전 구현 가능.**
단 하나 A (CreatureStateProvider) 만이 *선택적으로* executor 의 `attach_runtime` 시그니처
1줄 확장을 원한다 (그것마저도 MVP 는 ToolContext.metadata 로 회피 가능).

**이것이 16-STAGE 아키텍처가 "올바르게 설계되었다" 의 결정적 증거다.** 다마고치의
야심적인 기획안을 받아든 상태에서, 확장을 위해 executor 본체를 뜯어고칠 필요가
거의 없다.

---

## 9. "PLUGIN STAGE" 라는 단어를 쓰고 싶다면 — 이름 계약

유저가 말하는 "PLUGIN STAGE" 의 의미를 살려 구현하려면 **새 stage 를 추가하지 말고, 기존
확장 표면에 공식 이름을 붙여 패키지화** 하는 편이 맞다. 제안:

### Plugin = "Slot 주입 + PromptBlock + Emitter + Ticker" 의 번들

```python
@runtime_checkable
class GenyPlugin(Protocol):
    """플러그인 — 아래 훅들 중 *이식하고 싶은 것만* 구현."""

    name: str
    version: str

    # 파이프라인 내부에 슬롯 주입 (optional)
    def contribute_attach_runtime(self, session_ctx) -> Dict[str, Any]: ...

    # s03 프롬프트 블록 (optional, list 반환)
    def contribute_prompt_blocks(self, session_ctx) -> List[PromptBlock]: ...

    # s14 emitter (optional, list 반환)
    def contribute_emitters(self, session_ctx) -> List[Emitter]: ...

    # Tick 작업 (optional)
    def contribute_tickers(self) -> List[Ticker]: ...

    # Tool 풀 (optional)
    def contribute_tools(self) -> List[Tool]: ...

    # 세션 수명 이벤트 리스너 (optional)
    def contribute_session_listeners(self) -> Dict[str, Callable]: ...
```

### 플러그인 로더

- entry-point 그룹 `"geny.plugins"` 를 정의.
- `PluginRegistry.discover()` 가 installed plugins 을 로드.
- `AgentSessionManager.create_agent_session()` 단계에서 각 `contribute_*` 호출 결과를
  `attach_runtime` / ComposablePromptBuilder / EmitterChain / TickEngine 으로 분배.

### 이점

- **사용자가 요청한 "플러그인 스테이지" 의 멘탈 모델** (외부 모듈 하나 설치하면 기능 추가) 을
  *새 stage 없이* 제공.
- 내부적으로는 기존 7겹 확장 표면에 분해 주입되므로 16-STAGE 테제 유지.
- 각 플러그인은 "파이프라인을 깨뜨릴 수" 없다 — 그들이 기여하는 것은 정해진 slot 뿐.
- 의존성 명시, 버전 관리, 테스트 가능성 모두 확보.

### 예시 플러그인 (가상)

```
geny-tamagotchi-core:        CreatureState + AffectBlock + Decay/EventSampler tickers
geny-live2d-emotion-mapper:  EmitToStateEmitter + avatar_state callbacks
geny-relationship-tracker:   RelationshipState + PersonaProvider
geny-welcomeback:            session.resumed listener + welcome seed retriever
```

이 4개 플러그인만 결합하면 기획안의 80% 가 달성된다.

---

## 10. 적용 우선순위 요약

**Phase α (executor 손대지 않음, Geny 만):**
1. `PersonaProvider` + `DynamicPersonaBlock` 도입 (B) → 사이드도어 3곳 폐쇄
2. `SessionLifecycleBus` 도입 (E) → 이벤트 채널 정리
3. `TickEngine` 도입 (F) → thinking_trigger 리팩터
4. `ManifestSelector` 도입 (G) → phase 전환 훅
5. MVP: `CreatureStateProvider` (A) 를 ToolContext.metadata 로 시작
6. `EmitToStateEmitter` 도입 (D) → 감정 피드백 루프

**Phase β (executor 에 1줄 확장):**
7. `attach_runtime(creature_state=...)` 추가

**Phase γ (플랫폼화):**
8. `GenyPlugin` Protocol + `PluginRegistry` + entry-point 규약
9. 기존 기능을 `geny-*` 플러그인으로 재조직

---

## 11. 한 장 요약

- **17번째 stage = 금지.** 데이터 계약 흔들림 + 순서 지옥 + 이미 대체재 존재.
- **플러그인 = 기존 7겹 확장 표면의 번들.** 새 stage 대신 `attach_runtime` + PromptBlock +
  Emitter + Ticker + SessionListener 의 조합.
- **executor 수정은 최소 1줄 (attach_runtime 인자 추가) 또는 0줄.** 나머지는 전부 Geny 에서.
- **사이드도어 (`_system_prompt` 3곳) 는 `PersonaProvider` 로 정리.**
- **Tick 작업 (decay / trigger / event) 은 `TickEngine` 으로 수렴.**
- **세션 수명 이벤트는 `SessionLifecycleBus` 로 통일.**
- **phase 전환은 `ManifestSelector` 로.**
- **이름이 필요하다면 `GenyPlugin` Protocol — 사용자의 '플러그인 스테이지' 멘탈 모델을
  스테이지 없이 제공.**
