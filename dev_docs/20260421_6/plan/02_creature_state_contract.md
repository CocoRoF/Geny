# Plan 02 — CreatureState 계약 (전략 D 의 세부 설계)

**작성일.** 2026-04-21
**선행.** `plan/01_long_term_state_deep_analysis.md` 가 채택한 **전략 D (External Wrapper)** 의
구체 계약을 정의한다. 데이터 모델, hydrate/persist 타이밍, mutation 프로토콜, 스토리지, 버전,
동시성, 테스트 전략까지.

이 문서가 확정되면 X3 (CreatureState 본체 사이클) 의 구현은 거의 기계적으로 진행된다.

---

## 0. 모듈 배치

`plan/01` 의 그림을 파일/클래스 단위로 구체화:

```
backend/service/state/
├─ __init__.py
├─ schema/
│  ├─ __init__.py
│  ├─ creature_state.py         # @dataclass CreatureState, MoodVector, Importance, ...
│  └─ mutation.py               # @dataclass Mutation, class MutationBuffer
├─ provider/
│  ├─ __init__.py
│  ├─ interface.py              # class StateProvider(Protocol)
│  └─ sqlite_creature.py        # SqliteCreatureStateProvider (MVP 구현체)
├─ registry.py                  # class SessionRuntimeRegistry
├─ decay.py                     # class DecayPolicy, default_decay()
├─ hydrator.py                  # hydrate_state(state, registry), persist_state(state, registry)
└─ migration/
   ├─ __init__.py
   └─ v1_to_v2.py               # schema migration hooks
```

Geny 쪽 파일 배치. executor 는 *아무 변화 없음* (X5 까지).

---

## 1. 데이터 모델 — `CreatureState`

### 1.1. 본체

```python
# backend/service/state/schema/creature_state.py

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .mood import MoodVector

SCHEMA_VERSION = 1

@dataclass
class Vitals:
    """Physical upkeep stats — decay over time, restored by interactions."""
    hunger: float = 50.0       # 0=포만, 100=굶주림
    energy: float = 80.0       # 0=완전 소진, 100=최상
    stress: float = 20.0       # 0=평온, 100=극도의 스트레스
    cleanliness: float = 80.0  # 0=지저분, 100=청결

@dataclass
class Bond:
    """Relationship stats — accumulate over long term."""
    affection: float = 0.0     # 애정도 (0..100+)
    trust: float = 0.0         # 신뢰 (0..100+)
    familiarity: float = 0.0   # 친숙도 (0..100+)
    dependency: float = 0.0    # 의존성 (양날. 높을수록 방치 페널티↑)

@dataclass
class Progression:
    """Long-term growth state."""
    age_days: int = 0
    life_stage: str = "infant"    # infant / child / teen / adult
    xp: int = 0                    # 경험치 누적
    milestones: List[str] = field(default_factory=list)
    manifest_id: str = "base"      # 현재 적용된 manifest

@dataclass
class CreatureState:
    # Identity
    character_id: str                          # PK
    owner_user_id: str                         # 소유자

    # 가변 상태
    vitals: Vitals = field(default_factory=Vitals)
    bond: Bond = field(default_factory=Bond)
    mood: MoodVector = field(default_factory=MoodVector)
    progression: Progression = field(default_factory=Progression)

    # 메타 / 시계 / 이벤트
    last_tick_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    last_interaction_at: Optional[datetime] = None
    recent_events: List[str] = field(default_factory=list)   # ring buffer (최근 20)

    # 스키마 버전 (마이그레이션용)
    schema_version: int = SCHEMA_VERSION
```

### 1.2. `MoodVector` 는 왜 별도 파일인가

`mood.py` 는 독립된 모듈로 둔다. 이유:
- 감정 추출 (`emotion_extractor.py`) 이 이미 존재하며, 동일한 벡터 표현을 공유해야 함.
- 다른 도메인 (예: Persona 의 "오늘 기분") 에서 재사용.
- 벡터 정규화, 이동평균, 감정 → 키워드 매핑 등 유틸이 붙음.

```python
@dataclass
class MoodVector:
    joy: float = 0.0
    sadness: float = 0.0
    anger: float = 0.0
    fear: float = 0.0
    calm: float = 0.5
    excitement: float = 0.0

    def ema(self, other: "MoodVector", alpha: float) -> "MoodVector": ...
    def dominant(self) -> str: ...
```

### 1.3. 왜 vitals / bond / progression 을 분리했는가

| 그룹 | 수명 | 변화 속도 | 변화 방향 |
|---|---|---|---|
| `vitals` | 짧음 (수 시간 ~ 수 일) | 빠름 | 양방향 (decay ↓, 회복 ↑) |
| `bond` | 매우 김 (수 주 ~ 수 개월) | 느림 | 대체로 단방향 누적 |
| `progression` | 영구 | 매우 느림 | 단조 증가 / stage 전이 |
| `mood` | 턴 단위 | 매우 빠름 | EMA 기반 |
| `recent_events` | 슬라이딩 | 턴마다 push/pop | 큐 |

수명 / 변화 특성이 다른 것을 섞으면 밸런스 조정이 난잡해짐.

### 1.4. 외래 식별

- `character_id` 는 PK. 같은 유저가 여러 캐릭터를 키울 수 있으므로 `user_id + character_name`
  조합 아님.
- `owner_user_id` 는 FK 로 유저 테이블 참조.
- Geny 의 기존 `character` 테이블이 있다면 1:1 관계.

---

## 2. Mutation 프로토콜

Stage 는 provider 를 직접 부르지 않는다. 대신 `MutationBuffer` 에 diff 를 append 한다.

### 2.1. `Mutation` 타입

```python
# backend/service/state/schema/mutation.py

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Literal, Optional

MutationOp = Literal["add", "set", "append", "event"]

@dataclass(frozen=True)
class Mutation:
    op: MutationOp                  # "add" | "set" | "append" | "event"
    path: str                       # "vitals.hunger" / "bond.affection" / "recent_events"
    value: Any                      # add: float delta, set: new value, append: item, event: str
    source: str                     # 누가 생성했는가 (e.g., "s14_emit/joy_tag")
    at: datetime                    # 기록 시각
    note: Optional[str] = None

class MutationBuffer:
    def __init__(self) -> None:
        self._items: List[Mutation] = []

    def append(self, *, op, path, value, source, note=None) -> None:
        self._items.append(Mutation(op=op, path=path, value=value, source=source,
                                    at=datetime.now(timezone.utc), note=note))

    @property
    def items(self) -> tuple[Mutation, ...]:
        return tuple(self._items)

    def __len__(self) -> int: return len(self._items)
```

### 2.2. 4가지 op 만 허용

- **add** — 숫자 path 에 delta. `add vitals.hunger +3.0`
- **set** — 임의 path 에 절대값. `set progression.life_stage "teen"`
- **append** — list path 에 push. `append recent_events "played_with_owner"`
- **event** — 의미 태그만 기록 (집계용). `event "first_meet"`

이 4개로 다마고치에 필요한 모든 상태 변화를 표현 가능.
`remove` / `delete` 는 의도적으로 뺀다 (롤백을 mutation 으로 표현하지 않음, provider.apply 가
transaction 내에서 처리).

### 2.3. Mutation 예시

```python
# Stage 14 (Emitter) 가 "[joy]" 태그를 감지했을 때
buf.append(op="add", path="bond.affection", value=+1.5,
           source="s14_emit/joy_tag",
           note="LLM emitted [joy] after user's gift")

# Stage 10 (Tool) 이 "feed" 도구를 실행했을 때
buf.append(op="add", path="vitals.hunger", value=-20.0, source="s10_tool/feed")
buf.append(op="append", path="recent_events", value="fed", source="s10_tool/feed")

# Stage 12 (Evaluate) 가 세션을 "긍정 종료" 로 판정
buf.append(op="event", path="", value="positive_close", source="s12_evaluate")
```

### 2.4. 멱등성과 순서

Mutation 은 **순서가 있다**. `apply` 는 append 순으로 적용.
같은 path 에 `add +2` 와 `set 50` 이 들어오면 최종 결과는 *append 순서에 의존*.
- 이로 인해 **두 stage 가 같은 turn 에 같은 path 를 set** 하는 것은 위험.
- 규약: set 은 **pipeline 외부의 progression 전이** 나 **관리자 명령** 에서만 사용.
  stage 는 원칙적으로 add / append / event 만 사용.

### 2.5. 이벤트로의 투영

`MutationBuffer` 는 디버그를 위해 `state.add_event('state.mutation', {...})` 를 동시에 발행
할 수 있다 (옵션). 기본은 off (이벤트 스팸 방지), dev 모드에서만 on.

---

## 3. StateProvider 인터페이스

### 3.1. Protocol 정의

```python
# backend/service/state/provider/interface.py

from typing import Protocol, Optional, Sequence
from ..schema.creature_state import CreatureState
from ..schema.mutation import Mutation

class CreatureStateProvider(Protocol):
    async def load(self, character_id: str) -> CreatureState:
        """Return CreatureState. If absent, creates from defaults and returns."""

    async def apply(
        self,
        snapshot: CreatureState,
        mutations: Sequence[Mutation],
    ) -> CreatureState:
        """Apply mutations to snapshot, persist to storage, return new state.
        Must be atomic: either all mutations apply or none do."""

    async def tick(self, character_id: str, decay: "DecayPolicy") -> CreatureState:
        """Apply time-based decay. Called by TickEngine, not by pipeline wrapper."""

    async def set_absolute(
        self, character_id: str, patch: dict,
    ) -> CreatureState:
        """Administrative override — for manual edits, progression transitions, migrations."""
```

### 3.2. MVP 구현 — `SqliteCreatureStateProvider`

Geny 백엔드는 이미 SQLite / PostgreSQL 에 세션 메타를 저장 중. 동일 DB 에 테이블 추가:

```sql
CREATE TABLE creature_state (
    character_id     TEXT PRIMARY KEY,
    owner_user_id    TEXT NOT NULL,
    schema_version   INTEGER NOT NULL,
    data_json        TEXT NOT NULL,       -- CreatureState 를 JSON 직렬화
    last_tick_at     TEXT NOT NULL,       -- ISO 8601
    last_interaction_at TEXT,
    updated_at       TEXT NOT NULL,
    row_version      INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_creature_state_owner ON creature_state(owner_user_id);
```

- `data_json` 을 쓰는 이유: 필드가 빠르게 추가/변경되는 초기엔 컬럼보다 JSON 이 관리 편함.
  안정화된 후 V2 에서 쿼리 성능이 필요한 필드만 컬럼 승격.
- `row_version` — optimistic concurrency. apply 시 `WHERE row_version = :v` 갱신 실패 시 retry.

### 3.3. Mock 구현 — `InMemoryCreatureStateProvider`

테스트용. dict 기반. 동시성 테스트 위해 asyncio.Lock 내장.

### 3.4. 의도적으로 빠진 것

- 분산 캐시 (Redis). 필요성 확인 후 추가.
- 이력 추적 (audit log). mutation 단위 append-only 로그 저장은 X6 이후 옵션.

---

## 4. Hydrate / Persist 타이밍 — `SessionRuntimeRegistry`

### 4.1. 클래스 골격

```python
# backend/service/state/registry.py

class SessionRuntimeRegistry:
    def __init__(self, session_id: str, character_id: str, owner_user_id: str,
                 creature_state_provider: CreatureStateProvider):
        self.session_id = session_id
        self.character_id = character_id
        self.owner_user_id = owner_user_id
        self._csp = creature_state_provider
        self._snapshot: Optional[CreatureState] = None

    async def hydrate(self, state: PipelineState) -> None:
        """Called BEFORE pipeline.run. Populates state.shared."""
        snap = await self._csp.load(self.character_id)

        # Catch-up: last_tick_at 부터 now 까지 TickEngine 이 안 돈 구간 보정
        now = datetime.now(timezone.utc)
        if now > snap.last_tick_at + CATCHUP_THRESHOLD:
            snap = await self._csp.tick(self.character_id, DEFAULT_DECAY)

        self._snapshot = snap
        state.shared['creature_state'] = snap
        state.shared['creature_state_mut'] = MutationBuffer()
        state.shared['session_meta'] = {
            'session_id': self.session_id,
            'character_id': self.character_id,
        }

    async def persist(self, state: PipelineState) -> CreatureState:
        """Called AFTER pipeline.run. Commits mutations."""
        if self._snapshot is None:
            raise RuntimeError("persist called without hydrate")
        buf: MutationBuffer = state.shared['creature_state_mut']
        new_state = await self._csp.apply(self._snapshot, buf.items)
        return new_state
```

### 4.2. AgentSession 통합 (pseudo-code)

```python
# backend/service/langgraph/agent_session.py (§_run_turn 주변)

async def run_turn(self, user_input):
    registry = SessionRuntimeRegistry(
        self.session_id, self.character_id, self.user_id, self._csp,
    )
    state = PipelineState(session_id=self.session_id)
    await registry.hydrate(state)

    try:
        result = await self.pipeline.run(user_input, state=state)
    finally:
        # persist even on exception (partial mutations may have meaning)
        try:
            await registry.persist(state)
        except Exception as e:
            log.exception("state persistence failed", exc_info=e)
            # continue — 다음 턴에서 다시 시도하도록 snapshot 은 유지.

    return result
```

### 4.3. 예외 처리 규칙

- **hydrate 실패.** 전체 턴 중단. 유저에게 에러 반환.
- **pipeline.run 실패.** persist 는 *시도한다*. mutation 중 일부는 이미 buffer 에 있을 수 있고,
  그것들은 의미 있을 수 있음. commit 실패 시 로그 + 다음 턴에서 재시도.
- **persist 실패.** 유저 응답은 이미 생성됨 → 유저에겐 성공 반환. 운영 알림 (metrics).
  다음 hydrate 에서 load 시 snapshot 이 아직 이전 것이므로 *사실상 잃은 턴* — 이 트레이드오프는
  명시적으로 받아들임.

### 4.4. Streaming 턴

현재 Geny 는 `pipeline.run_stream` 을 사용. hydrate 는 스트림 시작 전, persist 는 스트림 종료
(혹은 취소) 시에 한 번만. EventBus 에 `stream.closed` 이벤트를 구독해 트리거.

---

## 5. Decay 정책

### 5.1. `DecayPolicy` 데이터 클래스

```python
# backend/service/state/decay.py

@dataclass(frozen=True)
class DecayRule:
    path: str                   # "vitals.hunger"
    rate_per_hour: float        # +3.0  (시간당 +3 증가)
    clamp_min: float = 0.0
    clamp_max: float = 100.0

@dataclass(frozen=True)
class DecayPolicy:
    rules: tuple[DecayRule, ...]
```

### 5.2. 기본 규칙 (MVP)

```python
DEFAULT_DECAY = DecayPolicy(rules=(
    DecayRule("vitals.hunger",      +2.5),   # 40시간 방치 ≈ 포만→굶주림
    DecayRule("vitals.energy",      -1.5),   # 피로 누적
    DecayRule("vitals.cleanliness", -1.0),
    DecayRule("vitals.stress",      +0.5),
    DecayRule("bond.familiarity",   -0.1),   # 아주 천천히 잊힘
))
```

애정/신뢰/의존성은 **decay 하지 않는다** (유저가 쌓은 것은 쉽게 지워지지 않는 것이 좋다).

### 5.3. 적용 함수

```python
def apply_decay(state: CreatureState, policy: DecayPolicy, now: datetime) -> CreatureState:
    elapsed = (now - state.last_tick_at).total_seconds() / 3600.0
    for rule in policy.rules:
        current = _read_path(state, rule.path)
        new = clamp(current + rule.rate_per_hour * elapsed,
                    rule.clamp_min, rule.clamp_max)
        _write_path(state, rule.path, new)
    state.last_tick_at = now
    return state
```

### 5.4. 누가 호출하는가

- **TickEngine** (plan/03 §4) 이 주기적으로 (e.g., 15분마다) 모든 살아있는 character 에 대해 호출.
- **Hydrate 시 catch-up** — `hydrate` 가 last_tick_at 이 `CATCHUP_THRESHOLD` (예: 30분) 이상
  오래되었으면 즉시 tick 한 번 호출. 유저가 오랜만에 접속한 순간 상태가 튜닝된 수치로 반영됨.

### 5.5. Decay 가 pipeline 안에서 돌지 않는 이유

plan/01 §6.5 재진술:
- 유저가 접속 안 해도 시간은 흐른다.
- 한 턴 안에서 여러 번 decay 되면 이상.
- wall-clock coupling.

---

## 6. Stage 별 접근 규약

**읽기.** 모든 stage 는 아래 한 줄로 읽는다.

```python
creature: CreatureState | None = state.shared.get('creature_state')
```

없으면 (게임 기능이 꺼진 세션) 해당 로직을 skip. 존재 여부가 feature flag.

**쓰기.** 원칙적으로 *두 stage 만* 쓴다:

- **s10_tool** — 도구 실행 결과로 직접 상태 변화 (e.g., feed 도구 → hunger 감소).
- **s14_emit** — LLM 출력의 감정 태그 파싱 → mood/bond 갱신.

기타 stage 의 쓰기는 anti-pattern. 필요하면 *왜 여기서 써야 하는지* 를 분석 문서에 먼저.

**Evaluate / Guard.** s04_guard, s12_evaluate 는 필요하면 **읽기** 할 수 있다 (e.g., stress
가 80 이상이면 "짧게 답하라" 가드). 쓰기는 하지 않음.

**System.** s03_system 은 **읽기만**. PromptBlock 구성에 mood / bond 반영.

---

## 7. 스키마 버전과 마이그레이션

### 7.1. 원칙

- `CreatureState.schema_version` 을 필드로.
- load 시 `data_json['schema_version'] != SCHEMA_VERSION` 이면 `migration/` 의 업그레이드 체인 적용.
- 다운그레이드는 지원하지 않음. 롤백이 필요하면 DB 백업.

### 7.2. 예시 — v1 → v2

```python
# backend/service/state/migration/v1_to_v2.py

def migrate(data: dict) -> dict:
    # v2 에서 bond.familiarity 추가, 기본 0.0
    data['bond']['familiarity'] = 0.0
    data['schema_version'] = 2
    return data
```

---

## 8. 동시성

### 8.1. 단일 character 에 동시 턴 — 금지

같은 character_id 에 동시에 두 턴이 돌면 mutation 이 섞임. Geny 의 `AgentSession` 은 이미
세션 단위 Lock 을 가짐 — character_id 단위로 확장 (같은 character 에 여러 세션 동시 개설 금지
혹은 mutex).

### 8.2. Optimistic concurrency (DB 레벨)

`apply` 는 `row_version` 을 이용한 OCC:

```sql
UPDATE creature_state
   SET data_json = :new, row_version = :v + 1, updated_at = :now
 WHERE character_id = :cid AND row_version = :v;
```

0행 영향 시 `StateConflictError` → retry (최대 3회) → 실패 시 load + replay.

### 8.3. TickEngine 과의 경합

TickEngine 이 tick 중인 character 에 pipeline.run 이 hydrate 시도 → OCC 로 잡힘 → tick 이
먼저 끝나면 pipeline 이 새로 load 후 진행. 역의 경우 pipeline 이 먼저, tick 이 retry.

---

## 9. 관찰성 (Observability)

### 9.1. 이벤트

```python
state.add_event('state.hydrated',  {'character_id': cid, 'last_tick_at': ...})
state.add_event('state.mutated',   {'op': 'add', 'path': 'bond.affection', 'value': +1.5, 'source': '...'})  # opt-in
state.add_event('state.persisted', {'character_id': cid, 'mutations': N})
state.add_event('state.conflict',  {'character_id': cid, 'attempts': 3})
```

### 9.2. 메트릭

- `state_hydrate_duration_ms` (histogram)
- `state_persist_duration_ms`
- `state_mutations_per_turn` (gauge / histogram)
- `state_conflict_total` (counter)

Prometheus / OTEL 이미 있으면 거기로.

---

## 10. 테스트 전략

### 10.1. 단위 테스트

- `test_mutation_buffer.py` — append / items 튜플 / snapshot 독립성.
- `test_apply_mutations.py` — 각 op × 각 path (nested dataclass path) 쌍 전수.
- `test_decay.py` — 시간 경과 → vitals 변화. clamp. last_tick_at 갱신.
- `test_creature_state_roundtrip.py` — serialize → json → deserialize equality.

### 10.2. 통합 테스트

- `test_registry_hydrate_persist.py` — fake CSP 사용. mutation buffer 에 N 개 넣고 persist
  → DB 갱신 확인.
- `test_pipeline_with_state.py` — s01~s16 를 모두 no-op 으로 두고, s10 대체 stage 가 mutation
  넣는 시나리오 → wrapper 가 제대로 commit.

### 10.3. Property 테스트

- Hypothesis: 임의 mutation 시퀀스 → apply → 다시 load → 동일한 최종값.

### 10.4. 회귀

- 기존 메시지 persistence / memory path 에 영향 없는지 snapshot 테스트.

---

## 11. 명시적 범위 외

- UI 에서의 CreatureState 표시 (대시보드) — frontend 작업, 본 PLAN 밖.
- 다중 character 소유자 간 "방문" / "맡기기" — future.
- 캐릭터 간 관계 그래프 — future. 현재는 owner↔creature 1:N.
- 서버 간 migration (distributed). 현재는 단일 서버 가정.

---

## 12. 합격 조건 (Definition of Done for X3)

1. `backend/service/state/` 트리 전부 존재. 타입 힌트 통과.
2. `SqliteCreatureStateProvider` 구현, 테이블 마이그레이션 스크립트 있음.
3. `SessionRuntimeRegistry.hydrate / persist` 호출부가 `AgentSession.run_turn` 에 주입됨.
4. `s10_tool` 의 `feed` / `play` / `gift` 세 도구가 mutation 을 발행함.
5. `s14_emit` 의 Emitter 하나가 LLM 태그를 mutation 으로 변환함.
6. 단위 + 통합 테스트 모두 통과.
7. 기존 회귀 (비-게임 세션) 없음.
8. 이벤트 `state.hydrated` / `state.persisted` 가 EventBus 에 emit 됨.

Plan 03 에서 X1~X2 (전제 사이클) 의 구조적 보완을 확정한다.
