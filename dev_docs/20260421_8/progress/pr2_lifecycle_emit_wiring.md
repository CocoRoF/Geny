# PR-X2-2 · `refactor/lifecycle-emit-from-session-manager` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 148/148 pass (persona 36 + lifecycle 17 + langgraph 95).

## 범위

PR-X2-1 의 `SessionLifecycleBus` 레일을 실제 호출지에 연결한다. 6 이벤트를 현재 코드의 해당 지점에서 emit 하도록 배선 (WS 기반 `SESSION_ABANDONED` 는 PR-X2-6 의 신규 탐지기 차지).

본 PR 이 다루는 5 종 emit (모두 manager 혹은 controller 스코프):

| 이벤트 | 호출 위치 | 비고 |
|---|---|---|
| `SESSION_CREATED` | `agent_session_manager.create_agent_session` 말미 | worker/vtuber 각각 1회. 워커의 `paired_parent = vtuber_id` 는 request.linked_session_id 에서 유도 |
| `SESSION_PAIRED` | 동 파일, 서브워커 append_context 직후 | payload: `{vtuber_id, worker_id}` — pair 당 1회 |
| `SESSION_DELETED` | 동 파일, `delete_session` soft-delete 완료 직후 | meta: `{hard: bool}` (`cleanup_storage` 여부) |
| `SESSION_IDLE` | 동 파일, `_scan_for_idle_sessions` 내 `mark_idle==True` 직후 | meta: `{reason: 'timeout'}` |
| `SESSION_REVIVED` | `AgentSession.revive()` + `_auto_revive()` | kind 구분: `pipeline_rebuild` vs `auto_revive` |
| `SESSION_RESTORED` | `agent_controller.restore_session` 말미 (linked 먼저 → main 나중) | meta: `{cascade, linked_id?}` |

## 적용된 변경

### 1. `backend/service/langgraph/agent_session_manager.py`

- `SessionLifecycleBus` import + `self._lifecycle_bus = SessionLifecycleBus()` 생성.
- `lifecycle_bus` property 노출 (persona_provider 와 동일한 패턴).
- `AgentSession.create(..., lifecycle_bus=self._lifecycle_bus)` 로 주입.
- `create_agent_session` 말미: SESSION_CREATED emit. `paired_parent` 는 request.linked_session_id 로부터 유도.
- 서브워커 pairing block 내 `append_context` 직후: SESSION_PAIRED emit.
- `delete_session` soft-delete 완료 직후: SESSION_DELETED emit.
- `_scan_for_idle_sessions` 를 **async 로 전환**, mark_idle 성공 후 emit. 호출지 `_idle_monitor_loop` 는 이미 async 라 await 만 붙임. `list(self._local_agents.items())` 로 스냅샷 — 스캔 중 dict mutate 에 대응.

### 2. `backend/service/langgraph/agent_session.py`

- `__init__` 에 `lifecycle_bus: Optional[Any] = None` kwarg 추가, `self._lifecycle_bus` 로 보관.
- `revive()` 성공 직후 `await self._emit_revived(kind="pipeline_rebuild")`.
- `_auto_revive()` (sync) 말미: `self._schedule_revived_emit(kind="auto_revive")`.
- 신규 메서드 2 개:
  - `_emit_revived(kind)` — async, bus 있으면 emit.
  - `_schedule_revived_emit(kind)` — sync, 실행 중 loop 있으면 `create_task`, 없으면 silent skip.
- **import 선택** — `LifecycleEvent` 는 메서드 안에서 지연 import. 이유: AgentSession 은 tests/ 에서도 bus 없이 구성 가능해야 하는데, 모듈-레벨 import 는 circular / missing module 위험이 있었음 (실제로는 없지만 방어적으로).

### 3. `backend/controller/agent_controller.py`

- `from backend.service.lifecycle import LifecycleEvent`.
- `restore_session`: linked (cascade) 복원 성공 직후 SESSION_RESTORED emit, 그 뒤 main SESSION_RESTORED emit. plan/01 §3.3 의 "linked 먼저 → main 나중" 준수.

### 4. `backend/tests/service/lifecycle/test_emissions.py` (신규)

5 case:

1. `test_manager_lifecycle_bus_is_wired` — `AgentSessionManager.lifecycle_bus` property 가 살아있는 bus 를 반환하고 subscribe/emit 정상 동작. manager `__init__` 의존성을 피하려 `object.__new__` + 최소 속성 세팅.
2. `test_agent_session_emit_revived_fires_with_bus` — `_emit_revived` 가 bus 에 SESSION_REVIVED 를 정확한 meta (revive_count, kind) 로 실어서 emit.
3. `test_agent_session_emit_revived_without_bus_is_noop` — bus=None 일 때 short-circuit.
4. `test_schedule_revived_emit_runs_in_background` — sync→async 변환이 loop 에 task 를 태우고 1~2 틱 안에 실행.
5. `test_schedule_revived_emit_outside_loop_is_noop` — running loop 없이 호출해도 raise 없음.

## 테스트 결과

- `backend/tests/service/lifecycle/` — **17/17 pass** (12 bus + 5 emission).
- `backend/tests/service/persona/` — **36/36 pass** 회귀 없음.
- `backend/tests/service/langgraph/` — **95/95 pass** 회귀 없음.
- 총계 **148/148 pass** in 0.56s.

## 의도적 비움

- **WS abandoned** — PR-X2-6 차지. 본 PR 에서는 bus 에 SESSION_ABANDONED emit 지점이 없음.
- **metric subscribe_all handler** — plan/01 §6 에서 언급한 `lifecycle_event_total{event=...}` 메트릭은 본 PR 에 없음. 별도 관측 PR 또는 X3 의 metric sink cycle 에서 추가.
- **Manager 의 CREATED / PAIRED 메타 스키마 불변화** — `meta` 는 dict 로 열려있고, 향후 subscriber 가 필드 추가 요청할 수 있음. 지금은 plan/01 §1 의 권장 키만 싣고, Frozen Schema 는 X3 에서 필요해지면 dataclass 로 승격.

## 다음 PR

**PR-X2-3 · `feat/tick-engine`** — plan/02 의 TickEngine 계약 구현 + fake-clock 테스트.
