# PR-X2-4 · `feat/thinking-trigger-onto-tick-engine` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 178/178 pass (기존 167 + 신규 11). sanitize 기존 3 error 는 venv fastapi 미설치 건으로 비회귀.

## 범위

`ThinkingTriggerService` 의 ad-hoc `while not self._stopped: await asyncio.sleep(30)` 루프를 PR-X2-3 의 `TickEngine` 위로 이식.

## 적용된 변경

### 1. `backend/service/vtuber/thinking_trigger.py`

- `from service.tick import TickEngine, TickSpec` 추가.
- spec 상수: `_TICK_INTERVAL_SECONDS = 30.0`, `_TICK_JITTER_SECONDS = 2.0`, `_TICK_SPEC_NAME = "thinking_trigger"`.
- `__init__` 에 `engine: Optional[TickEngine] = None` kwarg 추가. None 이면 `TickEngine()` 자체 생성 + 소유. 외부 주입 시 `_owns_engine = False` 로 start/stop 을 호출하지 않음 (X2-5/X2-6 공유 engine 대비).
- `_stopped` / `_task` 제거, `_running: bool` 플래그로 통일.
- `start()` → **async**. 중복 start no-op. `TickSpec(name=_TICK_SPEC_NAME, interval=30s, handler=self.scan_all, jitter=2s)` 등록 후 owned 인 경우에만 `await self._engine.start()`.
- `stop()` → **async**. spec unregister, owned 인 경우에만 engine.stop. activity/disabled/consecutive map 모두 clear.
- **tick body 를 public 메서드로 노출.** 기존 `_loop` 삭제, 내용을 **`async def scan_all(self)`** 로 이식:
  - 30s sleep 제거 (cadence 는 spec 책임).
  - try/except 최상위 제거 (TickEngine 이 예외 isolate).
  - 본질 로직 (disabled skip, adaptive threshold, fan-out fire, activity reset) 보존.
- **적응형 backoff 는 handler 내부에서 유지.** spec 은 고정 30s, 세션별 `_get_adaptive_threshold` 기반 skip 판정은 `scan_all` 안에 그대로.

### 2. `backend/main.py`

- lifespan startup: `thinking_trigger.start()` → `await thinking_trigger.start()`.
- lifespan shutdown: `app.state.thinking_trigger.stop()` → `await app.state.thinking_trigger.stop()`.

### 3. `backend/tests/service/vtuber/test_thinking_trigger_tick.py` (신규, 11 case)

1. `test_start_registers_tick_spec` — spec name/interval/jitter/handler identity 검증.
2. `test_stop_unregisters_spec_and_clears_state` — stop 후 spec 사라지고 dict 들 비워짐.
3. `test_start_is_idempotent` — 2회 호출해도 spec 1 개.
4. `test_stop_without_start_is_noop`.
5. `test_injected_engine_is_not_auto_started_by_service` — 외부 engine 은 서비스가 건드리지 않음.
6. `test_owned_engine_is_started_and_stopped` — 자체 소유 engine 은 서비스가 제어.
7. `test_scan_all_skips_sessions_within_threshold` — 방금 activity → skip.
8. `test_scan_all_fires_for_sessions_over_threshold` — 60s idle + 10s threshold → fire.
9. `test_scan_all_skips_disabled_sessions`.
10. `test_scan_all_respects_adaptive_backoff` — consecutive=20 이면 500s idle 도 fire 안 함.
11. `test_scan_all_resets_activity_after_fire` — 즉시 re-fire 방지용 activity bump.

## 테스트 결과

- `backend/tests/service/vtuber/test_thinking_trigger_tick.py` — **11/11 pass**.
- `backend/tests/service/tick/` — **19/19 pass**.
- `backend/tests/service/lifecycle/` — **17/17 pass**.
- `backend/tests/service/persona/` — **36/36 pass**.
- `backend/tests/service/langgraph/` — **95/95 pass**.
- 총 신규 포함 **178/178 pass**. 회귀 없음.
- `test_thinking_trigger_sanitize.py` 3 개는 venv 에 fastapi 없어서 ImportError — PR-X2-4 변경과 무관 (monkeypatch 타깃이 `controller.chat_controller`).

## 의도적 비움

- **주입 engine 공유** — X2-5/X2-6 에서 `main.py` lifespan 이 단일 `TickEngine` 을 만들어 여러 서비스에 주입하는 흐름으로 재편 예정. 본 PR 에서는 ThinkingTriggerService 가 기본값 `engine=None` 으로 자체 소유하도록 유지해 main.py 쪽 변경을 최소화.
- **메트릭 훅** — `_on_tick_complete` 은 여전히 no-op. 실제 `tick_handler_duration_ms{name="thinking_trigger"}` export 는 별도 metric PR.

## 다음 PR

**PR-X2-5 · `feat/idle-monitor-onto-tick-engine`** — `AgentSessionManager._idle_monitor_loop` 를 TickEngine spec 으로. avatar_state_manager 는 analysis/02 근거로 migration 대상 아님 (반응형).
