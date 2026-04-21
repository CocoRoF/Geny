# PR-X2-6 · `feat/ws-abandoned-detector` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 197/197 pass (기존 187 + 신규 10). cycle 의 7번째 이벤트 `SESSION_ABANDONED` 를 끝으로 X2 사이클 emit 레일 완료.

## 범위

WS connect/disconnect 를 lifecycle bus 에 올리는 전용 브릿지. transport-level WS 이벤트를 **세션 수준 "abandoned"** 상태로 집계 — 한 세션에 다중 WS 가 달릴 수 있고, 일시 drop 은 abandoned 가 아니다.

## 적용된 변경

### 1. `backend/service/lifecycle/ws_abandoned_detector.py` (신규)

```python
class WSAbandonedDetector:
    def __init__(self, bus, *, threshold_seconds=120.0): ...
    def connect(self, session_id): ...      # 카운트 ++ , pending ts 제거
    def disconnect(self, session_id): ...   # 카운트 -- , 0 되면 pending ts=now
    def is_connected(self, session_id) -> bool
    def pending_count(self) -> int
    async def scan(self):                   # TickEngine 핸들러
        # pending 중 gap >= threshold 이면 SESSION_ABANDONED emit, ts 삭제
```

- **per-episode 1 회 emit.** scan 이 emit 하기 *전에* ts 삭제 — re-entrant 방지.
- **재연결 = episode 취소.** pending 중 connect 가 들어오면 ts 즉시 제거.
- **emit 후 재연결/재단절** 은 **새 episode** 로 처리. 따라서 같은 세션이 두 번째 SESSION_ABANDONED 받을 수 있음.
- meta: `{disconnect_gap_seconds: float, threshold_seconds: float}`.

### 2. `backend/service/lifecycle/__init__.py`

`WSAbandonedDetector` 재수출.

### 3. `backend/ws/execute_stream.py`

- `ws_execute_stream(...)` 안:
  - `await websocket.accept()` 직후 `abandoned_detector.connect(session_id)` 호출.
  - **finally** 블록 추가 (기존에 없었음) 에서 `abandoned_detector.disconnect(session_id)`.
- `abandoned_detector` 는 `app.state.ws_abandoned_detector` 에서 getattr (없으면 no-op). 테스트/부팅 중 lifecycle 을 단순하게 유지.

### 4. `backend/main.py`

- lifespan startup:
  ```python
  ws_abandoned_detector = WSAbandonedDetector(bus=agent_manager.lifecycle_bus,
                                              threshold_seconds=120.0)
  _ws_detector_engine = TickEngine()
  _ws_detector_engine.register(TickSpec(name="ws_abandoned_detector",
                                        interval=60.0,
                                        handler=ws_abandoned_detector.scan,
                                        jitter=5.0))
  await _ws_detector_engine.start()
  app.state.ws_abandoned_detector = ws_abandoned_detector
  app.state.ws_detector_engine = _ws_detector_engine
  ```
- lifespan shutdown: idle monitor stop 직후 `await app.state.ws_detector_engine.stop()`.

- **WS 대상** — `/ws/execute/{session_id}` 만 연결. `/ws/vtuber/agents/{id}/state` (avatar_stream) 는 SSE 성격 + 세션 활성도 신호로 취급하지 않음. `/ws/chat/rooms/{room_id}` 는 room scope 라 세션 scope 아님.

- **자체 TickEngine 소유.** PR-X2-4/5 와 동일 패턴 (각 서비스가 engine 하나씩 소유). shared engine 으로의 통합은 metric 도입 PR 또는 X3 에서 자연스럽게 수행.

### 5. `backend/tests/service/lifecycle/test_ws_abandoned_detector.py` (신규, 10 case)

`time.time` monkey-patch 로 실제 sleep 없이 gap 을 조작.

1. `test_is_connected_reflects_connect_disconnect`
2. `test_multiple_ws_keeps_session_connected` — 2 연결 후 1 disconnect → 여전히 connected.
3. `test_reconnect_cancels_pending_abandoned` — disconnect 후 pending 중 connect → pending 취소.
4. `test_threshold_must_be_positive`
5. `test_scan_no_pending_is_noop`
6. `test_scan_skips_sessions_within_threshold` — 30s gap → emit 안 함.
7. `test_scan_emits_after_threshold` — 61s gap → emit 1, payload meta 검증, 다시 scan 해도 re-emit 안 함.
8. `test_reconnect_after_emit_starts_fresh_episode` — emit 뒤 재연결→단절→scan → 두 번째 emit.
9. `test_scan_multiple_sessions` — 서로 다른 disconnect 시각의 3 세션, gap 에 따라 선별 emit.
10. `test_unbalanced_disconnect_is_tolerated` — connect 없이 disconnect 만 와도 raise 하지 않음.

## 테스트 결과

- `backend/tests/service/lifecycle/test_ws_abandoned_detector.py` — **10/10 pass**.
- `backend/tests/service/tick/` — **19/19**.
- `backend/tests/service/lifecycle/` 전체 — **27/27** (12 bus + 5 emissions + 10 detector).
- `backend/tests/service/persona/` — **36/36**.
- `backend/tests/service/langgraph/` — **104/104**.
- `backend/tests/service/vtuber/test_thinking_trigger_tick.py` — **11/11**.
- 총 **197/197 pass**. (venv 에서 실행 불가한 fastapi/numpy 의존 테스트는 PR 변경과 무관 — pre-existing)

## 의도적 비움

- **Shared TickEngine 통합** — 현재 3 개 engine (thinking_trigger, idle_monitor, ws_abandoned_detector) 가 각자 소유. 하나로 합치면 코드가 간결해지지만 lifespan 재편이 필요 (`main.py` 에 engine 생성 → 주입). 본 PR 은 lifecycle emit 레일 완결에 집중.
- **메트릭** — `tick_handler_duration_ms{name="ws_abandoned_detector"}` 등은 별도 관측 PR.
- **다른 WS 연결 감지** — chat_stream/avatar_stream 은 session-scope 아니므로 본 PR 에서 제외. 향후 필요해지면 별도 scope 의 detector 추가.

## X2 사이클 종료

PR-X2-1 ~ PR-X2-6 로 **SessionLifecycleBus + 7 이벤트 emit + TickEngine + 3 spec** 완결.

| PR | 결과 |
|---|---|
| X2-1 | `SessionLifecycleBus` skeleton + 12 bus 테스트 (PR #214) |
| X2-2 | 5 이벤트 emit 배선 + 5 emission 테스트 (PR #215) |
| X2-3 | `TickEngine` skeleton + 19 테스트 (PR #216) |
| X2-4 | thinking_trigger → TickEngine + 11 테스트 (PR #217) |
| X2-5 | idle monitor → TickEngine + 9 테스트 (PR #218) |
| X2-6 | WS abandoned detector + 10 테스트 (본 PR) |

**총 66 신규 테스트, 197/197 pass.** 다음 사이클 **X3 — CreatureState MVP + Tools + Emitter + Blocks** 로 진입.
