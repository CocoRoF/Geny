# PR-X2-3 · `feat/tick-engine` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 167/167 pass (tick 19 + lifecycle 17 + persona 36 + langgraph 95).

## 범위

plan/02 의 TickEngine 계약 구현. 본 PR 은 **컨테이너만** — spec 이식은 PR-X2-4 / X2-5 / X2-6 에서.

## 적용된 변경

### 1. `backend/service/tick/__init__.py` (신규)

재수출 (`TickEngine`, `TickSpec`, `TickHandler`).

### 2. `backend/service/tick/engine.py` (신규)

- `TickHandler = Callable[[], Awaitable[None]]` alias.
- `TickSpec` frozen dataclass, `__post_init__` 검증:
  - `name` 비어있지 않음
  - `interval >= 0.1` (plan/02 §1 의 minimum 0.1)
  - `jitter >= 0` 및 `jitter < interval` (음수 sleep 방지)
  - `handler` 가 `asyncio.iscoroutinefunction` 통과해야 함
- `TickEngine`:
  - `register(spec)` — 중복 이름 `ValueError`. 실행 중이면 즉시 task 생성.
  - `unregister(name)` — 실행 중 task 에 cancel. 이름 없으면 no-op.
  - `start()` / `stop(timeout=5.0)` — idempotent. stop 은 cancel 후 `asyncio.wait`.
  - `is_running()` / `specs()` — specs 는 snapshot copy 반환 (외부 mutation 격리).
  - `_run_spec(spec)` — `run_on_start` 면 즉시 1회 → `await sleep(interval ± jitter)` → handler 루프.
  - `_tick_once(spec)` — handler 예외 `logger.exception` + 삼킴, 루프 유지. `finally` 에서 duration 측정 후 `_on_tick_complete` 호출.
  - `_on_tick_complete(name, duration_ms)` — no-op 훅. 실제 메트릭 훅은 X2-4/5.
- **오버런 정책.** handler 끝난 후 `sleep(interval)` → 다음 tick. drift 보정 없음. per-spec 단일 in-flight 보장 (같은 task 안에서 순차 await 이므로 자동).
- **Jitter.** `random.uniform(-jitter, +jitter)` 를 매 sleep 에 더함. 음수면 0 으로 clamp.

### 3. `backend/tests/service/tick/test_engine.py` (신규, 19 case)

**TickSpec 검증 (5)**:
1. `test_tickspec_rejects_empty_name`
2. `test_tickspec_rejects_interval_below_floor` (0.05 → reject)
3. `test_tickspec_rejects_negative_jitter`
4. `test_tickspec_rejects_jitter_ge_interval`
5. `test_tickspec_rejects_sync_handler`

**Engine 동작 (14)**:
6. `test_spec_fires_at_interval` — interval=0.1s over 0.55s → 3~6 ticks.
7. `test_run_on_start_fires_immediately` — interval=1.0s 이지만 start 직후 1회.
8. `test_handler_exception_does_not_kill_loop` — 매 tick raise 해도 계속 스케줄.
9. `test_overrun_does_not_overlap_handler` — handler=0.3s, interval=0.1s, max_concurrent=1.
10. `test_independent_specs_run_concurrently` — b 가 sleep(10) 으로 묶여도 a 는 계속.
11. `test_register_after_start_schedules_immediately` — 사후 register 도 즉시 task.
12. `test_unregister_cancels_running_task` — count stops growing after unregister.
13. `test_unregister_unknown_is_noop`.
14. `test_register_duplicate_name_raises`.
15. `test_stop_is_idempotent`.
16. `test_start_is_idempotent` — 두 번째 start 가 중복 task 를 만들지 않는지.
17. `test_specs_returns_snapshot` — snapshot mutate 해도 engine 불변.
18. `test_metric_hook_called_with_duration` — handler=20ms, 적어도 1 tick 은 `>= 15ms` 로 관측 (마지막 tick 은 stop cancel 로 중단될 수 있음).
19. `test_jitter_produces_variance_in_sleep` — gaps stdev > 5ms.

**테스트 스타일**: fake clock 대신 real ms-level interval. 모든 테스트 총 4 초.

## 테스트 결과

- `backend/tests/service/tick/` — **19/19 pass** in 4.1s.
- `backend/tests/service/lifecycle/` — **17/17 pass** 회귀 없음.
- `backend/tests/service/persona/` — **36/36 pass** 회귀 없음.
- `backend/tests/service/langgraph/` — **95/95 pass** 회귀 없음.
- 총 **167/167 pass**.

## 의도적 비움

- **메트릭 싱크** — `_on_tick_complete` 는 no-op. 실제 `tick_handler_duration_ms{name=}` / `errors_total` export 는 X2-4 (thinking_trigger 이식) 에서 훅 교체.
- **spec 등록** — 본 PR 은 TickEngine 인스턴스를 만들지도, DI 로 주입하지도 않는다. plan/02 §5 의 3 spec (thinking_trigger, idle_monitor, ws_abandoned_detector) 는 순서대로 X2-4 / X2-5 / X2-6.

## 다음 PR

**PR-X2-4 · `feat/thinking-trigger-onto-tick-engine`** — `thinking_trigger` 의 `while True: sleep` 루프를 `TickEngine` spec 으로 전환. 세션별 적응형 backoff 는 handler 내부에서 skip 판정.
