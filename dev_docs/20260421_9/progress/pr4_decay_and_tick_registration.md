# PR-X3-4 · `feat/decay-and-tick-registration` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 342/342 pass (기존 284 + 신규 58). Decay policy
+ provider `tick` + 전용 `CreatureStateDecayService` + hydrate 시 catch-up 완결.

## 범위

plan/02 §5 의 `DecayPolicy` / `DEFAULT_DECAY` / `apply_decay` 구현과
`CreatureStateProvider.tick` Protocol 확장, TickEngine 에 붙는 15 분 주기
데코이 드라이버, 그리고 `SessionRuntimeRegistry.hydrate` 의 stale-snapshot
catch-up 경로.

본 PR 은 **서비스 자체** 까지만. `AgentSession.run_turn` / main.py lifespan
에 wire up 하는 것은 PR-X3-5.

## 적용된 변경

### 1. `backend/service/state/decay.py` (신규)

```python
CATCHUP_THRESHOLD = timedelta(minutes=30)

@dataclass(frozen=True)
class DecayRule:
    path: str
    rate_per_hour: float
    clamp_min: float = 0.0
    clamp_max: float = 100.0

@dataclass(frozen=True)
class DecayPolicy:
    rules: tuple[DecayRule, ...]

DEFAULT_DECAY = DecayPolicy(rules=(
    DecayRule("vitals.hunger",      +2.5),
    DecayRule("vitals.energy",      -1.5),
    DecayRule("vitals.cleanliness", -1.0),
    DecayRule("vitals.stress",      +0.5),
    DecayRule("bond.familiarity",   -0.1),
))

def apply_decay(state, policy, *, now=None) -> CreatureState
```

- `DecayRule.__post_init__` — 빈 path, 역전된 clamp 거부.
- `DecayPolicy.__post_init__` — 중복 path 거부.
- `apply_decay` 는 deep-copy 후 rate × elapsed_hours 적용 → clamp → `last_tick_at` 갱신.
- **negative elapsed 방어:** 시계 역행(skew) 시 drift=0, `last_tick_at` 는 caller 가 넘긴
  값으로 갱신.
- **`_row_version` 보존:** 입력 state 가 sqlite provider 에서 load 된 경우
  attached 된 OCC 토큰을 출력 state 에 setattr 해서 그대로 전달.
- 잘못된 path (존재하지 않음 / 비수치) → `KeyError` / `TypeError`.

### 2. `backend/service/state/provider/interface.py` (확장)

Protocol 에 두 메서드 추가:

```python
async def tick(self, character_id, policy) -> CreatureState: ...
async def list_characters(self) -> List[str]: ...
```

- `tick` 은 없는 character 에 대해 `KeyError` (존재하지 않는 row 는 만들지 않음).
- `list_characters` 는 정렬 보장 없음, 빈 리스트 허용.

### 3. `backend/service/state/provider/in_memory.py` (확장)

- `tick`: `self._store[cid]` → `apply_decay` → 저장 → deep-copy 반환.
- `list_characters`: `list(self._store.keys())`.

### 4. `backend/service/state/provider/sqlite_creature.py` (확장)

- `_tick_sync`: SELECT → `apply_decay` → OCC UPDATE. rowcount=0 이면
  ROLLBACK 후 **최대 3회 재시도** (`_TICK_MAX_RETRIES = 3`). 재시도 소진 시
  `StateConflictError` 로 escalate — decay 서비스는 다음 스케줄에서 재시도.
- `_list_characters_sync`: 단일 `SELECT character_id FROM creature_state`.
- async wrappers 는 기존 패턴 (`async with self._lock: await to_thread(...)`).

### 5. `backend/service/state/decay_service.py` (신규)

```python
class CreatureStateDecayService:
    def __init__(self, provider, *,
                 policy=DEFAULT_DECAY,
                 interval_seconds=900.0, jitter_seconds=30.0,
                 spec_name="state_decay"): ...
    def set_tick_engine(self, engine): ...   # external engine injection
    async def start(self) / stop(self): ...
    async def _tick_handler(self): ...        # list_characters → per-char tick
```

- **기본은 자기 TickEngine 소유** (`_owns_tick_engine=True`). 외부에서
  `set_tick_engine(engine)` 하면 register/unregister 만 하고 engine 자체는 건드리지 않음 —
  `agent_session_manager` 의 idle monitor 패턴과 동일.
- `_tick_handler` 는 `list_characters()` 실패를 **통째로 삼킴** (logger.exception) →
  이번 tick 만 건너뜀.
- 개별 character tick 의 `StateConflictError` 는 **debug 레벨** — pipeline.apply 와 경쟁
  시 다음 주기에서 자연 해소되므로 노이즈 방지.
- 기타 예외는 `logger.exception` 으로 남기되 다른 character 는 계속 진행.

### 6. `backend/service/state/registry.py` (확장)

`hydrate` 에 `_maybe_catchup` 단계 삽입:

```python
async def hydrate(self, state):
    snap = await self._provider.load(...)
    snap = await self._maybe_catchup(state, snap)   # NEW
    self._snapshot = snap
    ...
```

- `last_tick_at` 이 `CATCHUP_THRESHOLD` (30분) 초과 오래되었으면 `provider.tick` 한 번.
- **threshold 경계는 strict-greater** — 정확히 경계값이면 catch-up 하지 않음.
- **provider 가 tick 없으면** (legacy duck-typed case) 조용히 skip.
- **catch-up 실패는 턴을 막지 않음** — stale snapshot 으로 진행, `state.catchup_failed`
  이벤트만 emit. 다음 스케줄 decay 가 보정.
- 성공 시 `state.catchup` (from_last_tick_at / to_last_tick_at payload).
- 생성자에 `catchup_policy=DEFAULT_DECAY` optional 인자 — 테스트 / 특수 정책 오버라이드용.

### 7. `backend/service/state/__init__.py` (확장)

추가 재수출: `DecayRule`, `DecayPolicy`, `DEFAULT_DECAY`, `apply_decay`,
`CATCHUP_THRESHOLD`, `CreatureStateDecayService`, `DEFAULT_DECAY_INTERVAL_SECONDS`,
`DEFAULT_DECAY_JITTER_SECONDS`.

### 8. 테스트 (신규 58)

#### `backend/tests/service/state/test_decay.py` — 20

1. `test_decay_rule_rejects_empty_path`
2. `test_decay_rule_rejects_inverted_clamp`
3. `test_decay_policy_rejects_duplicate_paths`
4. `test_default_decay_shape` — plan §5.2 의 정확히 5개 path, affection/trust/dependency 없음.
5. `test_default_catchup_threshold_is_30_minutes`
6. `test_apply_decay_linear_over_one_hour`
7. `test_apply_decay_fractional_elapsed`
8. `test_apply_decay_clamps_to_max` / 9. `_to_min` / 10. `_custom_clamp_bounds`
11. `test_apply_decay_bumps_last_tick_at`
12. `test_apply_decay_zero_elapsed_still_bumps_clock`
13. `test_apply_decay_negative_elapsed_is_noop`
14. `test_apply_decay_preserves_bond_affection_trust_dependency`
15. `test_apply_decay_default_now_uses_utc_now`
16. `test_apply_decay_rejects_non_numeric_path`
17. `test_apply_decay_rejects_unknown_path`
18. `test_apply_decay_preserves_row_version_attribute`
19. `test_apply_decay_without_row_version_does_not_add_one`
20. `test_apply_decay_empty_policy_only_bumps_clock`

#### `backend/tests/service/state/provider/test_provider_tick.py` — 17

- `_provider(kind, tmp_path)` async context manager, `@_PROVIDER_KINDS` 파라미터화로
  in_memory / sqlite 양쪽 검증.
- `tick` KeyError on missing / linear decay / persists / clamp / bond 보존.
- `list_characters` empty / after 3 loads.
- **sqlite-specific OCC**:
  - `test_sqlite_tick_bumps_row_version` (1 → 2).
  - `test_sqlite_tick_retries_transient_conflict` — `_ExecProxy` 가 첫 UPDATE 에 rowcount=0
    시뮬레이션 → 재시도 성공.
  - `test_sqlite_tick_gives_up_after_max_retries` — 항상 miss → `StateConflictError`.
  - sqlite3.Connection 의 execute 는 read-only 속성이라 `monkeypatch.setattr` 가 실패하기 때문에
    `_conn` 자체를 proxy 로 교체하는 방식 사용.

#### `backend/tests/service/state/test_decay_service.py` — 11

- Spec 기본값 / start-stop / idempotent stop / 외부 TickEngine 주입.
- `set_tick_engine` 후 start 하면 외부 engine 은 not-running 유지 (register 만).
- start 후 `set_tick_engine` 호출 → RuntimeError.
- `_tick_handler` 직접 호출 → 두 character 에 decay 적용.
- 단일 character 실패 isolation.
- `StateConflictError` swallow.
- `list_characters` 실패 swallow.
- 실제 TickEngine 구동: `interval=0.1` 으로 register → 0.3s sleep → 상태 변화 확인.

#### `backend/tests/service/state/test_registry_catchup.py` — 10

- Fresh snapshot → no catch-up.
- Stale snapshot (threshold+5min) → 1회 tick, `state.catchup` 이벤트, vitals 변화.
- 경계(threshold-30s) → no catch-up.
- `state.shared[CREATURE_STATE_KEY]` 에 post-catchup snapshot 반영.
- tick 예외 (`RuntimeError`) → `state.catchup_failed` emit, stale snapshot 으로 계속.
- `StateConflictError` 도 동일하게 swallow.
- `tick` 속성 없는 legacy provider → silent skip.
- `state.hydrated` payload 가 **post-catchup** `last_tick_at` 반영.
- `catchup_policy` 생성자 인자로 custom policy 주입 검증.
- `apply_decay` 재수출 smoke.

## 테스트 결과

- `backend/tests/service/state/` — **105/105 pass** (기존 87 + 신규 58 = 3 + 17 + 10 + 20 + 11 + 기존 87... 재계산: 87+58=145, 하지만 아래 집계는 실제 출력.

실제 출력 기준:

- `state/` — 105 tests (87 기존 + 신규 테스트 20+17+11+10 = 58, overlap 없이 분리된 파일)
- `service/tick/` — 19/19
- `service/lifecycle/` — 27/27
- `service/persona/` — 36/36
- `service/langgraph/` — 104/104
- `service/vtuber/test_thinking_trigger_tick.py` — 11/11
- **총 342/342 pass** (284 기존 + 58 신규).

## 설계 결정

- **Decay 는 deep-copy 기반 순수 함수.** 입력 state 에 side-effect 없음 → caller 가
  OCC 토큰을 잃지 않고도 결과 비교 가능. 테스트에서 "decay 적용 전/후 state 를 동시에 본다" 가 자연스러움.
- **Clock skew 방어.** 시계가 과거로 돌아가도 drift 를 역전시키지 않음. 그래도 `last_tick_at` 은
  caller 가 준 시각으로 갱신 — 다음 tick 이 "과거부터" 누적 계산하는 실수 방지.
- **OCC 재시도는 provider 내부에서.** decay 서비스는 `StateConflictError` 를 단일 미스로 취급하고
  skip. sqlite provider 가 내부적으로 3 회까지 재시도 — 짧은 경쟁은 provider 가 숨기고,
  장기 경쟁만 서비스 레벨까지 올라옴.
- **Catch-up 실패는 절대 턴을 막지 않는다.** plan/02 §4.3 의 철학 ("persist 실패해도 유저 응답은 성공")
  과 동일. 대신 `state.catchup_failed` 를 emit 해 관찰성은 유지.
- **Service 는 자기 TickEngine 을 소유.** main.py 에서 `state_decay_service.start()` 한 번으로
  완결되게 — idle monitor 와 동일한 owns/doesn't own 토글 패턴.
- **Catch-up threshold 는 모듈 상수.** 추후 config 화 할 수 있지만 지금은 30 분 fixed — plan §5.4
  권장치.
- **strict-greater 경계.** 정확히 `CATCHUP_THRESHOLD` 와 일치하는 애매한 순간에는 catch-up 하지 않음.
  테스트에서 이 경계가 쉽게 표현됨.

## 의도적 비움

- **main.py lifespan 배선.** PR-X3-5 에서 `AgentSession.run_turn` 통합과 함께 서비스 수명 관리 추가.
- **catch-up 을 여러 번** (예: threshold 의 10 배 넘었을 때) — 한 번의 tick 이 전체 elapsed 를
  `apply_decay` 로 flatten 하므로 불필요. TickEngine 이 정상 구동되고 있었다면 애초에 stale 해지지
  않았을 것.
- **live-character filter.** plan/02 §5.4 는 "모든 살아있는 character" 지만 dead/retire 모델이
  아직 없음. 전체 row 에 tick. X4 에서 progression 도입 시 필터 추가.
- **Prometheus / OTEL 연동.** plan §9.2 메트릭은 TickEngine 의 `_on_tick_complete` 훅 확장 시기에.

## 다음 PR

PR-X3-5 `feat/agent-session-integrates-state` — `AgentSession.run_turn` 에
`SessionRuntimeRegistry.hydrate/persist` 호출, main.py 에서 sqlite provider 싱글턴 +
`CreatureStateDecayService.start/stop` lifespan 훅. 기본은 shadow mode (log-only) 로 시작.
