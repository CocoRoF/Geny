# 실행 & 실시간 통신

> 커맨드(1:1)와 채팅방 브로드캐스트(1:N)를 위한 통합 실행 아키텍처, SSE 기반 실시간 전달

## 핵심 원칙

**채팅방은 그냥 멀티 커맨드일 뿐이다.**

모든 에이전트 실행은 하나의 경로를 거친다. 사용자가 단일 에이전트에 커맨드를 보내든(Command 탭), N개 에이전트가 있는 방에 메시지를 브로드캐스트하든(Messenger), 모든 실행은 동일한 `agent_executor.py` 모듈을 통과한다. 이를 통해 다음이 보장된다:

- 세션 로깅 (log_command / log_response)
- 비용 추적 (increment_cost)
- 자동 복구 (죽은 에이전트 프로세스 부활)
- 이중 실행 방지
- 타임아웃 처리

```
                    ┌─────────────────────────┐
                    │    agent_executor.py     │
                    │                         │
                    │  execute_command()       │  ← 동기 (결과 대기)
                    │  start_command_background│  ← 비동기 (백그라운드)
                    │  _execute_core()         │  ← 공유 라이프사이클
                    └────────┬────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         Command 탭    Chat 브로드캐스트   (향후 확장)
         (1:1 에이전트)  (N개 에이전트)
```

---

## agent_executor.py

모든 에이전트 실행을 소유하는 중앙 모듈. `agent_controller`와 `chat_controller` 모두 여기에 위임한다.

### ExecutionResult

모든 실행은 `ExecutionResult`를 반환한다:

```python
@dataclass
class ExecutionResult:
    success: bool
    session_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0
    cost_usd: Optional[float] = None
```

### 실행 라이프사이클 (`_execute_core`)

내부 `_execute_core()`가 단일 에이전트 호출의 전체 라이프사이클을 수행한다:

```
1. 커맨드 기록   →  session_logger.log_command(prompt, timeout, ...)
2. 에이전트 호출 →  asyncio.wait_for(agent.invoke(input_text=prompt), timeout)
3. 응답 기록     →  session_logger.log_response(success, output, duration_ms, cost)
4. 비용 저장     →  session_store.increment_cost(session_id, cost)
```

에러 처리: `TimeoutError`, `CancelledError`, 일반 예외를 모두 처리한다. 모든 경로에서 결과를 기록하고 holder를 `done`으로 표시한다.

### 이중 실행 방지

세션별 가드가 동시 실행을 방지한다:

```python
_active_executions: Dict[str, dict]  # session_id → holder

def is_executing(session_id) -> bool
```

`execute_command()`과 `start_command_background()` 모두 시작 전에 이 레지스트리를 확인한다. 이미 실행 중이면 `AlreadyExecutingError`가 발생한다 (HTTP 409).

### 자동 복구

모든 실행 전에 `_resolve_agent()`가 호출된다:

1. session_id로 `AgentSession` 조회
2. `agent.is_alive()`가 False이면 → `agent.revive()` 시도
3. 복구 실패 시 → `AgentNotAliveError` 발생

이를 통해 프로세스 크래시에 대한 복원력을 제공한다. 호출자는 수동으로 에이전트를 복구할 필요가 없다.

### 공개 API

| 함수 | 동작 | 사용처 |
|------|------|--------|
| `execute_command(session_id, prompt, ...)` | 완료까지 대기, `ExecutionResult` 반환, holder 자동 정리 | Command 탭 동기 실행, Chat 브로드캐스트 에이전트별 |
| `start_command_background(session_id, prompt, ...)` | 백그라운드 태스크 실행, holder dict 즉시 반환 | Command 탭 SSE 스트리밍 |

---

## Command 탭 (1:1 실행)

Command 탭은 `agent_controller.py`를 통해 세 가지 실행 모드를 제공한다:

### 모드 1: 동기 실행

```
클라이언트                       백엔드
  │                               │
  ├── POST /execute ─────────────►│  execute_command()
  │                               │  (완료까지 블로킹)
  │◄───── JSON {output, cost} ────┤
```

- 엔드포인트: `POST /api/agents/{session_id}/execute`
- 에이전트가 완료될 때까지 블로킹
- `ExecuteResponse` 반환 (output, cost, duration)

### 모드 2: 2단계 SSE (Start + Events)

```
클라이언트                       백엔드
  │                               │
  ├── POST /execute/start ───────►│  start_command_background()
  │◄───── {status: "started"} ────┤
  │                               │
  ├── GET /execute/events ───────►│  SSE 스트림 (EventSource)
  │◄── event: log ────────────────┤  ← 실시간 로그 엔트리
  │◄── event: log ────────────────┤
  │◄── event: status {completed} ─┤
  │◄── event: result {output} ────┤
  │◄── event: done ───────────────┤  ← 스트림 종료
```

- 시작: `POST /api/agents/{session_id}/execute/start`
- 스트림: `GET /api/agents/{session_id}/execute/events`
- 클라이언트가 `EventSource`(GET 기반 SSE)로 연결
- 시작 액션과 스트리밍을 분리해야 할 때 유용

### 모드 3: 단일 SSE 스트림

```
클라이언트                       백엔드
  │                               │
  ├── POST /execute/stream ──────►│  start_command_background()
  │                               │  + 즉시 SSE 응답
  │◄── event: status {running} ───┤
  │◄── event: log ────────────────┤  ← 실시간 로그 엔트리
  │◄── event: log ────────────────┤
  │◄── event: status {completed} ─┤
  │◄── event: result {output} ────┤
  │◄── event: done ───────────────┤
```

- 엔드포인트: `POST /api/agents/{session_id}/execute/stream`
- 단일 요청: 실행 시작 + SSE 스트림 반환
- 대부분의 사용 사례에 권장

### Command SSE 이벤트 타입

| 이벤트 | 데이터 | 설명 |
|--------|--------|------|
| `status` | `{status, message}` | `"running"`, `"completed"`, 또는 `"error"` |
| `log` | LogEntry dict | 세션 로거 인메모리 캐시의 실시간 로그 엔트리 |
| `result` | ExecuteResponse dict | 최종 실행 결과 (output, cost, duration) |
| `error` | `{error}` | 최상위 실행 에러 |
| `done` | `{}` | 스트림 완료 시그널 |

### 로그 스트리밍 메커니즘

SSE 스트림은 세션 로거의 **인메모리 캐시**에서 읽는다 (로그 파일이 아님):

```python
while not holder["done"]:
    new_entries, cursor = session_logger.get_cache_entries_since(cursor)
    for entry in new_entries:
        yield sse_event("log", entry)
    await asyncio.sleep(0.15)  # 150ms 폴링 간격
```

에이전트가 실행되는 동안 거의 실시간(~150ms 지연) 로그 전달을 제공한다.

---

## 채팅방 (1:N 브로드캐스트)

Messenger는 `chat_controller.py`를 통해 다중 에이전트 통신을 제공한다.

### 브로드캐스트 흐름

```
클라이언트                            백엔드
  │                                    │
  ├── POST /rooms/{id}/broadcast ─────►│
  │                                    ├── 1. 사용자 메시지 저장
  │                                    ├── 2. BroadcastState 생성
  │                                    ├── 3. asyncio.create_task(_run_broadcast)
  │◄── {broadcast_id, target_count} ───┤  ← 즉시 응답
  │                                    │
  │  (SSE 스트림 — 이미 연결됨)         │
  │◄── event: message (사용자 메시지) ──┤  ← SSE로 사용자 메시지 수신
  │◄── event: broadcast_status ────────┤  ← 진행: 0/3 완료
  │◄── event: message (에이전트 응답) ──┤  ← 에이전트 1 응답
  │◄── event: broadcast_status ────────┤  ← 진행: 1/3 완료
  │◄── event: message (에이전트 응답) ──┤  ← 에이전트 2 응답
  │◄── event: message (에이전트 응답) ──┤  ← 에이전트 3 응답
  │◄── event: broadcast_status ────────┤  ← 진행: 3/3 완료
  │◄── event: message (시스템) ────────┤  ← "3/3 sessions responded (5.2s)"
  │◄── event: broadcast_done ──────────┤  ← 브로드캐스트 완료
```

### _run_broadcast

각 에이전트에 대해 동일한 `execute_command()`를 실행하는 백그라운드 태스크:

```python
async def _invoke_one(session_id):
    result = await execute_command(session_id=session_id, prompt=message)
    store.add_message(room_id, {type: "agent", content: result.output, ...})
    _notify_room(room_id)   # SSE 리스너 깨우기

tasks = [asyncio.create_task(_invoke_one(sid)) for sid in session_ids]
await asyncio.gather(*tasks, return_exceptions=True)
```

핵심 특성:
- 모든 에이전트가 **동시에** 실행 (asyncio.gather)
- 각 에이전트는 `execute_command()` 사용 — Command 탭과 동일한 경로
- 결과는 도착 즉시 저장 (일괄 처리 아님)
- 메시지 저장 후 SSE 리스너에 즉시 알림

### BroadcastState

단일 브로드캐스트의 진행 상황을 추적:

```python
@dataclass
class BroadcastState:
    broadcast_id: str
    room_id: str
    total: int          # 대상 에이전트 수
    completed: int      # 완료 (성공 또는 실패)
    responded: int      # 출력을 생성한 수
    finished: bool
    started_at: float
```

- `_active_broadcasts: Dict[str, BroadcastState]` (room_id → state)에 저장
- 완료 후 30초 뒤 자동 정리

### 채팅방 SSE 이벤트 스트림

```
GET /api/chat/rooms/{room_id}/events?after={last_msg_id}
```

실시간 방 업데이트를 위한 장기(long-lived) SSE 연결. 새 메시지를 수신하는 **유일한 채널**이며 — 프론트엔드는 폴링하지 않는다.

#### 연결 & 재연결

```python
EventSource 연결 대상:
  {BACKEND_URL}/api/chat/rooms/{room_id}/events?after={last_msg_id}
```

- `after` 파라미터: 마지막으로 수신한 메시지 ID부터 재개
- 최초 연결 (after 없음): 기존 최신 메시지에 앵커링, 이후 새 메시지만 스트리밍
- 재연결 시: `after=<last_msg_id>`로 단절 중 놓친 메시지 재전송
- 프론트엔드는 연결 끊김 시 3초 후 자동 재연결

#### 알림 메커니즘

```python
_room_new_msg_events: Dict[str, asyncio.Event]   # room_id → Event

def _notify_room(room_id):
    event.set()   # 이 방의 모든 SSE 리스너를 깨운다
```

1. 메시지가 저장소에 저장 → `_notify_room(room_id)` 호출
2. `asyncio.Event.set()`이 SSE 제너레이터를 깨움
3. 제너레이터가 `_get_messages_after(last_seen_id)`로 새 메시지 조회
4. 새 메시지를 `message` SSE 이벤트로 전송

폴링 없음 — SSE 제너레이터는 `asyncio.Event.wait()`에서 대기하다가 알림 시 즉시 깨어난다.

#### 채팅 SSE 이벤트 타입

| 이벤트 | 데이터 | 발생 시점 |
|--------|--------|-----------|
| `message` | 전체 메시지 객체 | 새 메시지 저장 (user, agent, system) |
| `broadcast_status` | `{broadcast_id, total, completed, responded, finished}` | 브로드캐스트 진행 상태 업데이트 |
| `broadcast_done` | `{broadcast_id, total, responded}` | 모든 에이전트 작업 완료 |
| `heartbeat` | `{ts}` | 5초마다 (keep-alive, 유휴 시에만) |

#### 메시지 객체 (SSE 전달)

```json
{
  "id": "uuid",
  "type": "user | agent | system",
  "content": "메시지 텍스트",
  "timestamp": "ISO 8601",
  "session_id": "발신 세션",
  "session_name": "표시 이름",
  "role": "developer",
  "duration_ms": 3500,
  "cost_usd": 0.0557
}
```

---

## 비용 추적

비용은 전체 실행 파이프라인을 통해 흐른다:

```
Claude CLI 출력
  → StreamParser (stream-json에서 비용 파싱)
  → ProcessManager
  → ClaudeCLIChatModel (AIMessage.additional_kwargs.cost_usd)
  → AutonomousState.total_cost (_add_floats 리듀서)
  → agent.invoke() 반환값 {output, total_cost}
  → _execute_core()에서 total_cost 읽기
  → session_store.increment_cost(session_id, cost)    ← DB 원자적 UPDATE
  → ExecutionResult.cost_usd                          ← 호출자에 반환
```

**Command 탭**: `ExecuteResponse`와 `result` SSE 이벤트의 `cost_usd`
**채팅방**: 각 메시지 객체의 `cost_usd` (SSE `message` 이벤트로 전달)

DB 스키마:
- 세션 테이블: `total_cost DOUBLE PRECISION DEFAULT 0` (세션별 누적)
- 채팅 메시지 테이블: `cost_usd DOUBLE PRECISION DEFAULT NULL` (메시지별)

---

## 프론트엔드 아키텍처

### Command 탭

프론트엔드는 `EventSource`를 사용하여 `/execute/stream` 또는 2단계 `/execute/start` + `/execute/events`에 연결:

- 실시간 로그 엔트리가 도착 즉시 표시
- `done` 이벤트 수신 시 최종 결과 표시
- 커맨드 실행 컴포넌트가 연결 관리

### Messenger (채팅방)

프론트엔드는 Zustand 스토어 (`useMessengerStore`)로 순수 SSE 통신을 사용:

```
┌─────────────────────────────────────────────┐
│  useMessengerStore (Zustand)                │
│                                             │
│  selectRoom(roomId)                         │
│    ├── fetchMessages(roomId)   ← HTTP GET   │
│    └── _subscribeToEvents(roomId)           │
│         └── EventSource → 백엔드 SSE        │
│              ├── message → 스토어에 추가     │
│              ├── broadcast_status → 업데이트 │
│              └── broadcast_done → 초기화     │
│                                             │
│  sendMessage(content)                       │
│    └── POST /broadcast          ← HTTP POST │
│         (응답은 SSE로 수신, 폴링 아님)       │
└─────────────────────────────────────────────┘
```

핵심 설계 결정:
- **폴링 없음**: 모든 새 메시지는 SSE로 도착. HTTP 폴링 타이머가 존재하지 않는다.
- **백엔드 직접 SSE**: 프론트엔드가 `{BACKEND_URL}/api/chat/rooms/{roomId}/events`에 직접 연결 (SSE 스트림을 버퍼링하는 Next.js 프록시를 우회).
- **중복 제거**: `messages.some(m => m.id === msg.id)`로 재연결 시 중복 메시지 방지.
- **재연결**: SSE 에러 시 3초 후 `after=<lastMsgId>`로 자동 재연결.
- **방 목록**: 브로드캐스트 완료 시 + 30초 간격으로 갱신 (방 메시지 SSE와 별개).

---

## API 레퍼런스

### 커맨드 실행 (agent_controller)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/agents/{id}/execute` | 동기 실행 (완료까지 블로킹) |
| `POST` | `/api/agents/{id}/execute/start` | 백그라운드 실행 시작 |
| `GET` | `/api/agents/{id}/execute/events` | 실행 중 SSE 스트림 |
| `POST` | `/api/agents/{id}/execute/stream` | 시작 + SSE 스트림 단일 요청 |
| `POST` | `/api/agents/{id}/stop` | 실행 중 취소 |

### 채팅방 (chat_controller)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/chat/rooms` | 모든 방 목록 |
| `POST` | `/api/chat/rooms` | 방 생성 |
| `GET` | `/api/chat/rooms/{id}` | 방 상세 조회 |
| `PATCH` | `/api/chat/rooms/{id}` | 방 수정 (이름, 세션) |
| `DELETE` | `/api/chat/rooms/{id}` | 방 + 메시지 이력 삭제 |
| `GET` | `/api/chat/rooms/{id}/messages` | 메시지 이력 (초기 로드) |
| `POST` | `/api/chat/rooms/{id}/broadcast` | 메시지 브로드캐스트 (fire-and-forget) |
| `GET` | `/api/chat/rooms/{id}/events` | SSE 스트림 (재연결 지원) |

---

## 에러 처리

| 에러 | HTTP 상태 | 원인 |
|------|-----------|------|
| `AgentNotFoundError` | 404 | 세션 ID가 존재하지 않음 |
| `AgentNotAliveError` | 400 | 프로세스 사망, 자동 복구 실패 |
| `AlreadyExecutingError` | 409 | 해당 세션에서 이미 다른 커맨드가 실행 중 |
| Timeout | — | 실행이 타임아웃 초과 (기본값: 21600초 / 6시간) |

---

## 소스 파일

| 파일 | 역할 |
|------|------|
| `service/execution/agent_executor.py` | 통합 실행 모듈 |
| `controller/agent_controller.py` | Command 탭 엔드포인트 + SSE 스트리밍 |
| `controller/chat_controller.py` | 채팅방 CRUD + 브로드캐스트 + 방 SSE |
| `service/chat/conversation_store.py` | 메시지 저장 (PostgreSQL + JSON) |
| `service/logging/session_logger.py` | 세션 로그 기록 + 인메모리 캐시 |
| `service/sessions/store.py` | 세션 메타데이터 + 비용 저장 |
