# Plan 03 — 구조적 보완 (CreatureState 전에 완성되어야 할 것들)

**작성일.** 2026-04-21
**선행.** `plan/01`, `plan/02`, `analysis/02`, `analysis/04`, `analysis/05`.
**초점.** `plan/02` 의 CreatureState 가 탑재되기 **이전에** 반드시 정리되어야 할 구조적 격차.
즉 X1, X2 사이클의 범위. 이 세 구조가 없으면 CreatureState 는 분석 02 의 사이드도어를
재생산할 위험이 있다.

이 문서의 3개 축:
1. **PersonaProvider** — `_system_prompt` 3 사이드도어 제거, late-binding PromptBlock.
2. **SessionLifecycleBus** — 세션 경계 이벤트 체계화 (접속/이탈/재접속/만료).
3. **TickEngine** — `thinking_trigger` 의 일반화, decay / progression / heartbeat 공용 틱.

---

## 1. 문제 지도

### 1.1. 사이드도어 재진술

`analysis/02 §5` 의 3 곳:

| # | 파일 | 라인 | 무엇을 하는가 | 왜 사이드도어인가 |
|---|---|---|---|---|
| SD1 | `backend/service/vtuber/vtuber_controller.py` | 49–54 | 캐릭터 선택 시 `agent_session.pipeline._system_prompt = ...` 직접 덮어씀 | attach_runtime 이후 프롬프트를 *갱신* 하고 싶었음. 공식 재갱신 API 없음. |
| SD2 | `backend/service/langgraph/agent_controller.py` | 304 | `/system_prompt` 엔드포인트가 동일하게 덮어씀 | 유저가 실시간으로 persona 교체 시 즉시 반영 요구. |
| SD3 | `backend/service/langgraph/agent_session_manager.py` | 673 | 세션 재개 시 VTuber context 를 append | 재개 시 persona 가 새로 필요. |

**공통 원인.** `system_builder` (s03 의 strategy) 는 pipeline 수명 전체에 1개가 고정되고,
그 builder 가 만든 문자열이 첫 턴에 `state.system` 에 박혀 그대로 재사용됨.
**"매 턴 persona 를 다시 resolve" 할 인터페이스가 없다.**

### 1.2. 왜 X3 (CreatureState) 전에 해결해야 하는가

CreatureState 가 들어오면 "매 턴 persona 가 mood/bond 에 따라 변해야 한다" 는 요구가 즉시
생긴다. 예: affection > 80 이면 말투가 부드러워지고 호칭이 바뀜. 이것을 **`_system_prompt`
사이드도어로 구현하면** SD1/SD2/SD3 가 SD4/SD5... 로 증식한다. 따라서 **먼저 late-binding
PromptBlock 을 정비** 해야 한다.

같은 논리로:
- **SessionLifecycleBus** 없이 CreatureState 를 하면 "방치 페널티" (ghosting penalty) 가
  어디서 트리거되는지 규약 없음. 기존 단발 이벤트에 끼워 넣으면 혼란.
- **TickEngine** 없이 CreatureState 를 하면 decay 를 어디에 붙일지 혼란 (thinking_trigger 에
  태우거나 별도 cron 으로 분기).

그래서 X1 (PersonaProvider) → X2 (Lifecycle + Tick) → X3 (CreatureState) 순서.

---

## 2. PersonaProvider — `_system_prompt` 사이드도어 철거

### 2.1. 현재 구조 재확인

- `s03_system` stage 는 `system_builder: SystemBuilderStrategy` slot 을 가진다.
- `SystemBuilderStrategy` 는 `build(state) -> str` 을 구현. 기본 구현은
  `ComposablePromptBuilder` 로 PromptBlock 들을 합성.
- `state.system` 에 결과 문자열 저장. 다음 턴도 같은 pipeline._system_prompt 사용 (캐싱).

### 2.2. 새 인터페이스 — `PersonaProvider`

```python
# backend/service/persona/provider.py

from typing import Protocol, Optional
from geny_executor.core.state import PipelineState

class PersonaProvider(Protocol):
    """턴 시작 시점에 resolve 되어 PromptBlock 시퀀스를 반환."""
    async def resolve(
        self, state: PipelineState, *,
        session_meta: dict,
    ) -> "PersonaResolution": ...

@dataclass
class PersonaResolution:
    persona_blocks: list[PromptBlock]    # PersonaBlock, MoodBlock, RelationshipBlock, ...
    system_tail: Optional[str] = None    # 특수한 고정 tail (e.g., "절대 금칙")
    cache_key: str = ""                  # 동일 key → s03 가 재사용
```

### 2.3. 새 `SystemBuilderStrategy` 구현 — `DynamicPersonaSystemBuilder`

```python
# backend/service/persona/dynamic_system_builder.py

class DynamicPersonaSystemBuilder(SystemBuilderStrategy):
    def __init__(self, persona_provider: PersonaProvider, static_builder: SystemBuilderStrategy):
        self._provider = persona_provider
        self._static = static_builder

    async def build(self, state: PipelineState) -> str:
        # 1) provider 에서 매 턴 resolve
        session_meta = state.shared.get('session_meta', {})
        resolution = await self._provider.resolve(state, session_meta=session_meta)

        # 2) 정적 블록(Rules/ToolInstructions) + 동적 블록(Persona/Mood) 합성
        builder = ComposablePromptBuilder(blocks=[
            *self._static.base_blocks(),
            *resolution.persona_blocks,
        ], tail=resolution.system_tail)

        return builder.build(state)
```

이 builder 를 **attach_runtime(system_builder=DynamicPersonaSystemBuilder(...))** 로 주입.
기존 `system_builder` 교체 없이 **덮어쓰기** 로 해결.

### 2.4. 사이드도어 철거

- **SD1 / SD3.** `pipeline._system_prompt = ...` 완전 제거. 대신 `PersonaProvider` 의 상태
  (e.g., `current_character_id`) 를 변경.
- **SD2.** `/system_prompt` 엔드포인트는 `PersonaProvider.set_static_override(str)` 를 호출.
  다음 턴 resolve 시 반영.

### 2.5. 기본 `PersonaProvider` 구현 — `CharacterPersonaProvider`

```python
class CharacterPersonaProvider(PersonaProvider):
    def __init__(self, character_repo):
        self._repo = character_repo
        self._static_override: Optional[str] = None

    async def resolve(self, state, *, session_meta):
        cid = session_meta.get('character_id')
        char = await self._repo.get(cid)
        blocks = [
            PersonaBlock(char.persona_prompt),
            DateTimeBlock(),
        ]
        # X3 이후: CreatureState 를 읽어서 MoodBlock / RelationshipBlock 추가
        creature = state.shared.get('creature_state')
        if creature:
            blocks.append(MoodBlock.from_mood(creature.mood))
            blocks.append(RelationshipBlock.from_bond(creature.bond))

        return PersonaResolution(
            persona_blocks=blocks,
            system_tail=self._static_override,
            cache_key=f"{cid}:{creature.mood.dominant() if creature else 'n/a'}",
        )
```

### 2.6. X1 범위 — 실제 PR

**PR 단위.**
- PR-X1-1: `backend/service/persona/` 트리 신설 + `PersonaProvider` Protocol + `DynamicPersonaSystemBuilder`.
  기존 `system_builder` 경로는 건드리지 않음. Opt-in.
- PR-X1-2: `CharacterPersonaProvider` 구현. 현재 character_repo 를 어댑트. MoodBlock /
  RelationshipBlock 은 **자리만 잡고 no-op** (CreatureState 아직 없음).
- PR-X1-3: `AgentSession._build_pipeline` 에서 `attach_runtime(system_builder=DynamicPersonaSystemBuilder(...))`
  로 교체. SD1/SD3 제거. SD2 의 엔드포인트를 override API 로 재작성.
- PR-X1-4: 회귀 테스트. 기존 "캐릭터 바꾸면 다음 턴부터 persona 반영" 시나리오 유지.

### 2.7. X1 의 위험

- 기존 prompt 캐싱이 매 턴 재계산으로 바뀌면서 비용 조금 상승. 캐시 키 기반 캐싱 (Anthropic
  prompt cache marker) 로 상쇄.
- SD2 엔드포인트의 기존 호출자 (admin 도구) 의 응답 의미 변경. 문서 업데이트 필요.

### 2.8. 합격 조건

1. `grep '_system_prompt' backend/` 결과 0건 (테스트 제외).
2. 동일 세션에서 persona 교체 후 다음 턴에 새 persona 가 state.system 에 반영됨 (e2e).
3. MoodBlock / RelationshipBlock 이 no-op 이어도 DynamicPersonaSystemBuilder 가 안정 동작.
4. prompt cache hit rate 가 회귀 이전 대비 ±5% 이내.

---

## 3. SessionLifecycleBus

### 3.1. 현재의 얄팍함

`EventBus` 는 있지만, 이벤트 *이름 공간이 stage-internal 위주*. 세션 경계 이벤트가 정의되어
있지 않음:

- `session.start` — 어디서 emit? (agent_session_manager? agent_controller?)
- `session.resumed` — WebSocket 재연결 vs "DB 상 오랜만에 돌아옴" 구분 없음.
- `session.idle` — 몇 분 무응답 시 상태? 현재 없음.
- `session.abandoned` — 유저가 창을 닫았는지 여부 파악 없음.
- `session.closed` — 정상 종료.

### 3.2. 인터페이스

```python
# backend/service/lifecycle/bus.py

class SessionLifecycleBus:
    EVENTS = [
        "session.started",      # 첫 접속
        "session.resumed",      # ≥ 10 min 후 재접속
        "session.tick",         # 매 N 초 주기 (heartbeat)
        "session.idle",         # 유저 입력 없이 N 분 경과
        "session.abandoned",    # idle 후 websocket 종료
        "session.closed",       # 명시적 로그아웃
    ]

    def subscribe(self, event: str, handler: Callable) -> Unsubscribe: ...
    async def emit(self, event: str, data: dict) -> None: ...
```

### 3.3. Geny 의 기존 EventBus 와의 관계

- `EventBus` 는 pipeline *턴 내* 이벤트 (stage.*) 용.
- `SessionLifecycleBus` 는 pipeline 밖 *세션 수명* 이벤트 용.
- 둘을 합치면 네임스페이스가 더러워짐. 별도 유지 + 필요시 bridge.

### 3.4. 누가 emit 하는가

- `session.started` / `session.resumed` — `AgentSessionManager` 의 세션 생성부.
- `session.tick` — 내부 asyncio task (아래 TickEngine 의 heartbeat 적용).
- `session.idle` / `session.abandoned` — WebSocket 이 idle 감지 (inactivity timer).
- `session.closed` — AgentSessionManager 의 close 경로.

### 3.5. 소비자 (구독자)

- `TickEngine` — session.tick 으로 주기 작업 트리거.
- `CreatureStateProvider` (X3 이후) — session.abandoned 에서 "방치 페널티" 기록
  (event 로그에만, 즉시 penalty 적용은 decay 에 맡김).
- `CurationEngine` — session.closed 에서 curation 큐에 push.
- `avatar_state_manager` — session.tick 에서 표정 갱신.

### 3.6. X2 범위 (Bus 부분) — 실제 PR

- PR-X2-1: `backend/service/lifecycle/bus.py` + 기본 테스트.
- PR-X2-2: `AgentSessionManager` 가 bus 에 emit. 기존 임시 플래그 정리.
- PR-X2-3: WebSocket 레이어에 idle / abandoned 감지 추가. 기존 heartbeat 제거 후 bus 기반으로 통합.
- PR-X2-4: 기존 `thinking_trigger`, `avatar_state_manager` 를 Bus 구독자로 리팩토링.

### 3.7. 합격 조건

1. `SessionLifecycleBus.EVENTS` 전부 최소 1 구독자 존재.
2. 기존 thinking_trigger 동작 회귀 없음.
3. WebSocket 끊김 → 10초 후 `session.abandoned` emit 확인.

---

## 4. TickEngine — 주기적 일을 하나의 장소로

### 4.1. 현재의 분산

현재 Geny 에는 *주기 작업이 여기저기 박혀 있다*:

- `thinking_trigger` — 유저 무응답 시 LLM 자발 발화.
- `avatar_state_manager` — 표정 갱신.
- (장차) CreatureState decay tick.
- (장차) curation batch.

각자 `asyncio.create_task` 로 독자 루프를 돌림. 시작/종료 수명 관리 제각각. 테스트 어려움.

### 4.2. 인터페이스

```python
# backend/service/tick/engine.py

@dataclass(frozen=True)
class TickSpec:
    name: str
    interval_seconds: float
    handler: Callable[[TickContext], Awaitable[None]]
    jitter: float = 0.1        # ±10% 랜덤으로 thundering-herd 방지
    concurrent_per_character: bool = False   # True 면 캐릭터마다 동시 실행
    enabled_when: Callable[[], bool] = lambda: True

class TickEngine:
    def __init__(self, lifecycle_bus: SessionLifecycleBus, *, clock=None): ...
    def register(self, spec: TickSpec) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

### 4.3. 구현 개요

- 단일 `asyncio.Task` 가 모든 TickSpec 을 순회.
- 각 Spec 의 next_fire_at 을 heap 에 넣어 wall-clock scheduling.
- 실행은 `asyncio.create_task(handler(ctx))` 로 발사-후-망각. handler 내부에서 예외 잡아 로깅.
- `lifecycle_bus` 의 `session.tick` 은 TickEngine 이 emit.

### 4.4. 기존 서비스 이식

- **thinking_trigger.** `TickSpec("thinking_trigger", 30.0, handler=...)`.
  유저 idle 여부 판정을 handler 내부에서.
- **avatar_state_manager.** `TickSpec("avatar_tick", 2.0, ...)`. 짧은 주기.
- **decay_tick.** `TickSpec("decay", 900.0, ...)` — 15 분마다 살아있는 character 전부 tick.
  X3 에서 등록. X2 에서는 프레임만.

### 4.5. 분리의 이점

- **한 곳에서 시작/중지.** 앱 shutdown 시 engine.stop() 한 번이면 모든 주기 작업 정리.
- **관찰성 일원화.** 각 tick 의 p95 실행 시간, 실패율 메트릭.
- **테스트 가능.** fake clock 주입해 시간 건너뛰기.

### 4.6. X2 범위 (Tick 부분)

- PR-X2-5: `backend/service/tick/engine.py` + fake clock 테스트.
- PR-X2-6: `thinking_trigger`, `avatar_state_manager` 를 TickSpec 으로 이식. 기존 진입점
  제거.
- PR-X2-7: `app.py` (혹은 startup hook) 에서 TickEngine 을 lifecycle 에 바인딩.

### 4.7. 합격 조건

1. 모든 기존 주기 작업이 TickEngine 경로로 통일.
2. `engine.stop()` 시 N 초 내 모든 handler 종료.
3. fake clock 테스트에서 1 시간 시뮬레이션 시 thinking_trigger 가 예상 횟수 호출.

---

## 5. 세 축 간 의존 관계

```
                  ┌──────────────────────────┐
                  │   SessionLifecycleBus    │ ◄── X2-1..4
                  └────────────┬─────────────┘
                               │ subscribe / emit
             ┌─────────────────┼────────────────┐
             │                 │                │
             ▼                 ▼                ▼
    ┌────────────────┐ ┌───────────────┐ ┌─────────────────┐
    │ PersonaProvider│ │  TickEngine   │ │ AvatarManager   │
    │ (no direct)    │ │  X2-5..7      │ │ (리팩토링)      │
    └────────────────┘ └───────┬───────┘ └─────────────────┘
                               │ fires
                               ▼
                      ┌──────────────────┐
                      │  decay / thinking │
                      │  / curation tick │
                      └──────────────────┘

 (X3 CreatureState — plan/02 — depends on PersonaProvider + Bus + TickEngine)
```

**주의.** X1 (PersonaProvider) 은 Bus/Tick 과 독립. X2 (Bus + Tick) 는 X1 에 의존 없음.
→ X1, X2 는 **병렬 가능**. 단 X3 는 X1+X2 모두 끝난 뒤.

---

## 6. 사이클 X1 / X2 의 릴리즈·롤아웃

### 6.1. 롤아웃 깃발 (feature flag)

- X1 — `GENY_PERSONA_PROVIDER_V2=true` 환경변수로 교체 점진. 기본 off. 2 주 후 기본 on.
- X2 — Bus / Tick 은 *기본 on.* 기존 서비스 이식은 feature flag 없이 직접 대체 (모놀리식
  서비스이므로 flag 이점 적음).

### 6.2. executor 릴리즈 영향

- X1, X2 모두 **executor 수정 없음.** geny-executor v0.29.0 유지.
- (참고) X5 에서 `session_runtime` kwarg 를 도입할 때 executor 0.30.0 bump 예정.

### 6.3. 마이그레이션 / 데이터 변경

- X1 — 없음.
- X2 — 없음. Bus 는 in-memory, Tick 은 서비스 재시작하면 초기화.

### 6.4. 백아웃 전략

- X1 — feature flag off.
- X2 — 문제 발생 시 이전 `thinking_trigger` / `avatar_state_manager` 태스크를 임시 부활 가능
  (코드를 바로 지우지 않고 deprecated 주석 + unused import 로 2 주 유지 후 삭제).

---

## 7. 관찰성

### 7.1. 로그 / 메트릭

- **Persona.**
  - `persona_resolve_duration_ms`
  - `persona_cache_hits_total` / `persona_cache_misses_total`
- **Lifecycle.**
  - `lifecycle_event_total{event="..."}` (counter)
  - `session_idle_duration_seconds` (histogram)
- **Tick.**
  - `tick_handler_duration_ms{name="..."}`
  - `tick_handler_failures_total{name="..."}`

### 7.2. 대시보드 항목

- 활성 세션 수 (lifecycle.started - closed).
- 평균 idle 지속 시간.
- Tick handler p50/p95/p99.

---

## 8. 테스트

### 8.1. Persona

- `test_dynamic_persona_system_builder.py` — mock provider 로 매 턴 다른 blocks 반환 확인.
- `test_persona_provider_resolution.py` — CharacterPersonaProvider 통합.
- `test_sidedoor_removed.py` — `grep _system_prompt` 기반 assert.

### 8.2. Lifecycle

- `test_bus_subscribe_emit.py` — 동기 / 비동기 구독자.
- `test_websocket_idle_detection.py` — fake socket + fake clock.

### 8.3. Tick

- `test_tick_engine.py` — fake clock 으로 시간 점프.
- `test_tick_jitter.py` — 실행 시각 분포.
- `test_tick_graceful_shutdown.py`.

### 8.4. E2E

- 실제 `AgentSessionManager` 를 띄우고, 캐릭터 교체 → 다음 턴에 persona 반영 → session.closed
  발생 → tick 전부 멈춤 확인.

---

## 9. 합격 조건 총괄 (X1 + X2 완료 판단)

1. `_system_prompt` 3 사이드도어 제거.
2. `DynamicPersonaSystemBuilder` 가 운영 경로.
3. `SessionLifecycleBus.EVENTS` 전부 구독자 있고, integration 테스트 통과.
4. 모든 주기 작업이 TickEngine 으로 통일.
5. 회귀: 기존 VTuber / thinking_trigger / avatar 기능 동일하게 동작.
6. executor 수정 0.
7. Plan 04 (다마고치 레이어링) 에 필요한 전제가 모두 충족.

Plan 04 에서 X3 이후 실제 다마고치 게임 요소를 얹는다.
