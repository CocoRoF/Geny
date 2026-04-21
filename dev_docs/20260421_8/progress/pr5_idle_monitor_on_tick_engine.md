# PR-X2-5 · `feat/idle-monitor-onto-tick-engine` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 187/187 pass (기존 178 + 신규 9).

## 범위

`AgentSessionManager._idle_monitor_loop` 의 ad-hoc `while ... await asyncio.sleep(60)` 루프를 PR-X2-3 의 `TickEngine` spec 으로 이식. analysis/02 §4 근거로 `avatar_state_manager` 는 이식 대상 **아님** (완전 반응형 — 주기 루프 없음).

## 적용된 변경

### 1. `backend/service/langgraph/agent_session_manager.py`

- `__init__` 교체:
  - `_idle_monitor_task` 제거
  - `_idle_tick_engine: TickEngine` 자체 생성 + `_owns_idle_tick_engine = True`
  - `_idle_monitor_interval = 60.0`, `_idle_monitor_jitter = 3.0`
  - `_idle_monitor_running` flag 유지 (idempotent start 판정용)
- `set_tick_engine(engine)` 신규 — 외부 주입 시 소유권 이전, start 이후 호출 시 `RuntimeError`.
- `start_idle_monitor()` 를 **async 로 변경**:
  - `TickSpec(name="idle_monitor", interval=60s, handler=self._scan_for_idle_sessions, jitter=3s)` 등록
  - `_owns_idle_tick_engine` 일 때만 `await engine.start()`
- `stop_idle_monitor()`:
  - `engine.unregister("idle_monitor")`
  - owned 일 때만 `engine.stop()`
- `_idle_monitor_loop` 삭제 — tick body 는 기존 `_scan_for_idle_sessions` 가 그대로 담당 (PR-X2-2 에서 이미 async 로 전환됨).

### 2. `backend/main.py`

- lifespan startup `agent_manager.start_idle_monitor()` → `await agent_manager.start_idle_monitor()`.

### 3. `backend/tests/service/langgraph/test_idle_monitor_tick.py` (신규, 9 case)

manager 의 무거운 `__init__` 을 회피하려 `object.__new__` + `_make_manager_skeleton()` 헬퍼로 최소 속성만 세팅.

1. `test_start_registers_tick_spec` — spec 등록 + 자체 소유 engine is_running.
2. `test_stop_unregisters_spec_and_stops_owned_engine`.
3. `test_start_is_idempotent` — 2회 start 해도 spec 1 개.
4. `test_stop_without_start_is_noop`.
5. `test_injected_engine_is_not_started_by_manager` — shared engine 경로 (X2-6 대비).
6. `test_set_tick_engine_after_start_raises`.
7. `test_scan_flips_running_agents_and_emits_bus` — 2 RUNNING 세션 → 2 IDLE emit + store register.
8. `test_scan_skips_non_running_agents`.
9. `test_scan_handles_mark_idle_returning_false` — VTuber exempt 등 mark_idle=False 케이스에서 emit 안 함.

헬퍼: `_FakeAgent` / `_FakeStatus` / `_FakeStore`. `SessionStatus.RUNNING` 은 `_FakeStatus.__eq__` 안에서 lazy import.

## 테스트 결과

- `backend/tests/service/langgraph/test_idle_monitor_tick.py` — **9/9 pass**.
- `backend/tests/service/tick/` — **19/19** 회귀 없음.
- `backend/tests/service/lifecycle/` — **17/17**.
- `backend/tests/service/persona/` — **36/36**.
- `backend/tests/service/langgraph/` — **104/104** (기존 95 + 신규 9).
- `backend/tests/service/vtuber/test_thinking_trigger_tick.py` — **11/11**.
- 총 **187/187 pass**.

## 의도적 비움

- **avatar_state_manager 는 touch 하지 않음.** analysis/02 §4 근거 — 해당 모듈에 `asyncio.sleep` / `create_task` / `while True` / `_loop` 패턴이 전무, 완전 반응형. plan §2.5 가 잘못 적혀 있던 부분을 cycle 문서로 이미 재확정.
- **main.py 의 shared engine.** 현재 ThinkingTrigger 와 AgentSessionManager 가 각자 `TickEngine` 을 소유. 단일 shared engine 으로의 재편은 X2-6 에서 (`ws_abandoned_detector` 가 세 번째 spec 이므로 그때 합리적).
- **메트릭 훅.** 아직 `_on_tick_complete` 는 no-op.

## 다음 PR

**PR-X2-6 · `feat/ws-abandoned-detector`** — WebSocket disconnect 기반 `SESSION_ABANDONED` 탐지기. TickEngine 세 번째 spec 으로 등록.
