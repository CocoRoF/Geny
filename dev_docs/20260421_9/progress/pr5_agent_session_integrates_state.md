# PR-X3-5 · `feat/agent-session-integrates-state` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 359/359 cycle-relevant pass (기존 342 + 신규 17).
`AgentSession` 의 매 턴 hydrate/persist 배선 완결, main.py lifespan 에서
sqlite provider + `CreatureStateDecayService` 를 `GENY_GAME_FEATURES` 플래그로
토글.

## 범위

plan/02 §4 의 "AgentSession 이 턴 전후로 `SessionRuntimeRegistry.hydrate` /
`persist` 를 호출" 계약 구현. 본 PR 은 **pipeline 의 외곽 래핑** 까지만 —
stage 가 실제로 `state.shared[CREATURE_STATE_KEY]` 를 읽고 mutation 을
append 하는 것은 PR-X3-6..X3-9 에서 도구/emitter/블록 구현 시 연결.

쉐도우 모드(shadow mode) 가 기본. `GENY_GAME_FEATURES=1` 일 때만 provider 가
wire up 되고, 그 외 경로는 classic mode 로 동작 (hydrate/persist 완전 skip).

## 적용된 변경

### 1. `backend/service/langgraph/agent_session.py` (수정)

**생성자 확장:**

- `state_provider: Optional[Any] = None`
- `character_id: Optional[str] = None`
- `catchup_policy: Optional[Any] = None`

**턴 단위 registry 빌더** (`_build_state_registry`):

- `state_provider is None` → `None` 반환 (classic mode 게이트).
- `character_id` 누락 시 `session_id` 기본값 — MVP 는 세션당 하나의 크리처.
  PR-X4 에서 owner-driven 다중 character lookup 으로 치환.
- 매 호출마다 **fresh** `SessionRuntimeRegistry` — 턴 간 스냅샷/버퍼 유출 방지
  (plan/02 §4).
- `owner_user_id` 는 `self._owner_username or ""` — AgentSession 의 기존 필드.

**예외 격리 헬퍼:**

- `_hydrate_state_safely(registry, state) -> bool` — 어떤 예외도 턴을 막지
  않음. 실패 시 `exception` 로그 남기고 `False` 반환 → stages 는 `state.shared`
  에 `creature_state` 없이 실행.
- `_persist_state_safely(registry, state) -> None` — `StateConflictError` 는
  `debug` (pipeline.apply vs decay 경쟁은 정상). 그 외 예외는 `exception`.

**Pipeline 경로 배선:**

- `_invoke_pipeline` — `run_stream` 직전 hydrate, 응답 record/LTM 직후 persist.
- `_astream_pipeline` — 동일한 배치, stream 완료 후 persist.
- **persist-on-error**: pipeline 이 `pipeline.error` 로 끝나도 buffer 에 쌓인
  mutation 은 커밋. plan/02 §4.3 — "턴 중간에 발생한 상태 변경은 유저 응답과
  무관하게 반영" 원칙.

### 2. `backend/service/langgraph/agent_session_manager.py` (수정)

- `__init__`: `_state_provider = None`, `_state_decay_service = None`.
- `set_state_provider(provider, *, decay_service=None)` — 매니저-와이드 셋업.
  decay service 는 선택 (main.py 에서 start/stop 소유권 유지 용도).
- `state_provider` / `state_decay_service` 프로퍼티.
- `create_agent_session` — `AgentSession.create` 에 `state_provider` +
  `character_id` (provider wired 이면 `session_id`, 아니면 None) 전달.

### 3. `backend/main.py` (수정)

**lifespan 시작부** (ArtifactService 직전):

```python
geny_game_features = os.environ.get("GENY_GAME_FEATURES", "0") in {"1", ...}
if geny_game_features:
    state_provider = SqliteCreatureStateProvider(db_path=GENY_STATE_DB)
    decay_service = CreatureStateDecayService(provider=state_provider)
    await decay_service.start()
    agent_manager.set_state_provider(state_provider, decay_service=decay_service)
    app.state.state_provider = state_provider
    app.state.state_decay_service = decay_service
```

- 기본 DB 경로: `backend/data/geny_state.sqlite3`. `GENY_STATE_DB` 환경변수로
  재지정.
- 디렉토리 자동 생성 (첫 부팅 시).

**shutdown:** decay service stop → provider close (in order).

### 4. 테스트 (신규 17)

#### `backend/tests/service/langgraph/test_agent_session_state.py` — 13

`_RecordingPipeline` — `state.shared` 를 기록하고 사전 주입된 mutation 을
buffer 에 append. 기존 `_FakePipeline` 패턴을 살짝 확장해서 PR-X3-5 가 필요한
상호작용만 커버.

1. `test_classic_mode_leaves_state_shared_untouched` — no provider → no
   `creature_state` keys.
2. `test_classic_mode_build_state_registry_returns_none` — 헬퍼 게이트.
3. `test_hydrate_installs_creature_state_into_shared` — 3 키 주입.
4. `test_character_id_defaults_to_session_id` — MVP 기본값.
5. `test_persist_applies_mutations_and_bumps_state` — hunger +5.0 시드에
   mutation append → provider 에 반영.
6. `test_astream_also_hydrates_and_persists` — streaming 경로 대칭.
7. `test_stale_snapshot_triggers_catchup_in_hydrate` — registry
   `_maybe_catchup` path 를 AgentSession 통해 end-to-end 검증.
8. `test_hydrate_failure_does_not_break_the_turn` — `_ExplodingHydrateProvider`
   → `result["output"]` 그대로.
9. `test_persist_failure_does_not_break_the_turn` — `RuntimeError` on apply.
10. `test_persist_conflict_is_downgraded_to_debug` — `StateConflictError`.
11. `test_persist_runs_even_when_pipeline_errors` — `pipeline.error` 이벤트
    에도 persist 실행 (plan §4.3).
12. `test_build_state_registry_returns_fresh_instance_per_call` — 턴 스코프.
13. `test_build_state_registry_uses_owner_username_when_present` — owner
    forwarding.

#### `backend/tests/service/langgraph/test_agent_session_manager_state.py` — 4

Manager 플러밍:

1. `test_state_provider_defaults_to_none` — 초기 상태.
2. `test_set_state_provider_stores_provider_and_decay_service` — happy path.
3. `test_set_state_provider_without_decay_service_is_allowed` — optional arg.
4. `test_set_state_provider_overrides_previous` — 재호출 교체.

## 테스트 결과

- `backend/tests/service/state/` — **145/145 pass** (PR-X3-4 와 동일).
- `backend/tests/service/langgraph/` — **121/121 pass** (104 기존 + 17 신규).
- `backend/tests/service/tick/` — **19/19**.
- `backend/tests/service/lifecycle/` — **27/27**.
- `backend/tests/service/persona/` — **36/36**.
- `backend/tests/service/vtuber/test_thinking_trigger_tick.py` — **11/11**.
- 사이클 관련 전체 **359/359 pass** (342 기존 + 17 신규).

(사이클 무관 에러 3 건: `memory/test_memory_llm.py`, `utils/test_text_sanitizer.py`,
`vtuber/test_thinking_trigger_sanitize.py` — 모두 numpy/fastapi 환경 문제로
PR-X3-5 와 무관.)

## 설계 결정

- **Shadow mode 를 기본으로.** `GENY_GAME_FEATURES` 가 off 인 상태에서
  state_provider 는 None → AgentSession 은 classic mode (no hydrate/persist).
  X3 가 끝나기 전까지 기존 VTuber / worker 플로우가 영향받지 않도록 격리.
- **턴마다 fresh registry.** snapshot + mutation buffer 가 session-lifetime
  에 걸쳐 누적되면 OCC 토큰 stale 문제 + mutation 유출. plan/02 §4 의
  "턴 수명" 약속 그대로.
- **에러 격리 2-티어.** hydrate 실패는 **턴 진행**, persist 실패는 **응답 유지**.
  plan/02 §4.3 의 "유저 응답 우선" 원칙.
- **Persist on pipeline.error.** stage 가 중간에 failure 로 끝나도 이미
  buffer 에 push 된 mutation 은 반영. "reason: 사용자에게는 error 응답이
  나가도, 내부 상태 전이는 일어나야 한다 (예: 실패한 play 시도로 stress +1)".
- **character_id = session_id (MVP).** 세션당 하나의 크리처. PR-X4 에서
  owner 기반 다중 character persistence 로 확장 시 setter 추가.
- **decay service 소유권은 main.py.** `set_state_provider(decay_service=...)`
  는 레퍼런스를 들고 있을 뿐, start/stop 은 main.py lifespan.

## 의도적 비움

- **Stage 의 state 실제 읽기/쓰기.** PR-X3-6..X3-9 가 도구/emitter/블록
  구현 시 연결. 본 PR 은 배선만 완성.
- **Provider 별 구분 (prod vs test).** main.py 에서 무조건 sqlite. PR-X4/X5
  에서 Postgres 미러링 필요해지면 factory 추가.
- **character_id ↔ session_id 매핑 테이블.** MVP 는 1:1. X4 에서 owner ↔
  character mapping 테이블이 생기면 AgentSessionManager 의 create 경로가
  owner_username 으로 character_id 를 resolve 하도록 수정.
- **Websocket hydrate 이벤트 전달.** `state.hydrated` / `state.persisted` 는
  현재 PipelineState 내부 이벤트. WS 클라이언트 노출은 관찰성 PR 에서.

## 다음 PR

PR-X3-6 `feat/game-tools-basic` — `feed` / `play` / `gift` / `talk` 4 개 도구
구현 + `GenyToolProvider` 등록. 각 도구는 `state.shared[MUTATION_BUFFER_KEY]`
에 mutation 을 push 하고, 본 PR 의 persist 가 자동으로 commit.
