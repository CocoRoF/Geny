# Chat & Messenger 심층 검토 및 구현 보고서

> **참고**: 이 문서는 구현 과정의 기록입니다. 현재 로직의 최종 문서는 아래를 참조하세요:
> - [docs/EXECUTION.md](docs/EXECUTION.md) / [docs/EXECUTION_KO.md](docs/EXECUTION_KO.md) — 실행 & 실시간 통신
> - [docs/CHAT.md](docs/CHAT.md) / [docs/CHAT_KO.md](docs/CHAT_KO.md) — 데이터 & 저장소

## 1. 개요

Geny 애플리케이션에는 두 가지 채팅/명령 실행 경로가 존재한다:

| 구분 | Command (명령 탭) | Messenger (메신저) |
|------|-------------------|---------------------|
| 위치 | Main 페이지 → 세션 클릭 → 명령 탭 | Messenger 페이지 → Room |
| 대상 | 단일 Agent 1:1 | Room 내 모든 Agent 1:N |
| 상태 | ✅ 정상 작동 | ✅ **통합 완료** |

### 핵심 설계 원칙

> **"채팅방은 그냥 multi-command일 뿐이다"**
>
> Messenger broadcast = N개의 Command 동시 실행. 단일 `agent_executor` 모듈이
> 모든 실행을 소유하며, 양쪽 컨트롤러는 이 모듈에 위임만 한다.

---

## 2. Command 흐름 (정상 작동 기준)

### 2.1 아키텍처: Two-Step SSE Streaming

```
[Frontend]                       [Backend]
    │                                │
    ├─ POST /execute/start ─────────►│  agent.invoke() 백그라운드 시작
    │◄──── { status: "started" } ────┤  _active_executions[sid] = holder
    │                                │
    ├─ GET /execute/events ─────────►│  SSE StreamingResponse
    │◄──── event: status (running) ──┤
    │◄──── event: log (entry 1) ─────┤  150ms 간격 폴링
    │◄──── event: log (entry 2) ─────┤  session_logger.get_cache_entries_since()
    │◄──── event: log (entry N) ─────┤
    │◄──── event: status (completed) ┤
    │◄──── event: result ────────────┤  { success, output, duration_ms, cost_usd }
    │◄──── event: done ──────────────┤
    │  EventSource.close()           │  _active_executions 정리
```

### 2.2 핵심 구성 요소

| 파일 | 역할 |
|------|------|
| `controller/agent_controller.py` | `/execute/start`, `/execute/events` 엔드포인트 |
| `service/executor/agent_session.py` | `AgentSession.invoke()` - 워크플로 실행 |
| `service/logging/session_logger.py` | 실시간 로그 캐시 (메모리 + 파일 + DB) |
| `frontend/src/lib/api.ts` | `agentApi.executeStream()` |
| `frontend/src/components/tabs/CommandTab.tsx` | UI, 이벤트 핸들러 |
| `frontend/src/store/useAppStore.ts` | `sessionDataCache` 상태 관리 |

### 2.3 SSE 이벤트 타입

| 이벤트 | 데이터 | 용도 |
|--------|---------|------|
| `status` | `{ status, message }` | 실행 상태 업데이트 |
| `log` | `LogEntry` (timestamp, level, message, metadata) | **실시간 로그 스트리밍** |
| `result` | `{ success, output, duration_ms, cost_usd }` | 최종 결과 |
| `error` | `{ error }` | 에러 |
| `done` | `{}` | 스트림 종료 |

### 2.4 핵심 특징

1. **실시간 로그 스트리밍**: `session_logger`의 메모리 캐시에서 150ms 간격으로 새 로그를 폴링하여 SSE로 전송
2. **실행 중 진행 상황 표시**: 각 노드 실행, 도구 호출, 사고 과정이 `log` 이벤트로 실시간 전달
3. **비용 추적**: 실행 완료 시 `cost_usd` 반환 및 DB 저장
4. **이중 실행 방지**: `_active_executions`에서 진행 중 실행 존재 시 409 반환
5. **자동 부활**: 프로세스가 죽은 세션은 `agent.revive()`로 자동 부활

---

## 3. Messenger 흐름 (현재 상태)

### 3.1 아키텍처: Fire-and-Forget Broadcast

```
[Frontend]                              [Backend]
    │                                       │
    ├─ POST /rooms/{id}/broadcast ─────────►│  user_msg 저장
    │◄──── { user_message, broadcast_id } ──┤  asyncio.create_task(_run_broadcast)
    │                                       │
    │  EventSource 구독 (이미 연결됨)        │
    │◄──── event: message (agent1 응답) ────┤  agent1.invoke() 완료 → store.add_message
    │◄──── event: broadcast_status ─────────┤  { completed: 1/3 }
    │◄──── event: message (agent2 응답) ────┤  agent2.invoke() 완료
    │◄──── event: broadcast_status ─────────┤  { completed: 2/3 }
    │◄──── event: message (agent3 타임아웃) ─┤  system msg
    │◄──── event: broadcast_done ───────────┤
    │                                       │
    │  + 2초 간격 폴링 (백업) ──────────────►│  GET /rooms/{id}/messages
```

### 3.2 핵심 구성 요소

| 파일 | 역할 |
|------|------|
| `controller/chat_controller.py` | `/broadcast`, `/events` 엔드포인트 |
| `service/chat/conversation_store.py` | Room/Message CRUD (PostgreSQL + JSON 이중 저장) |
| `frontend/src/lib/api.ts` | `chatApi.broadcastToRoom()`, `subscribeToRoom()` |
| `frontend/src/store/useMessengerStore.ts` | Zustand 상태 관리 |
| `frontend/src/components/messenger/*` | UI 컴포넌트들 |

### 3.3 SSE 이벤트 타입

| 이벤트 | 데이터 | 용도 |
|--------|---------|------|
| `message` | ChatRoomMessage (type, content, session_id 등) | 새 메시지 도착 |
| `broadcast_status` | `{ broadcast_id, total, completed, responded, finished }` | 진행률 |
| `broadcast_done` | `{ broadcast_id, total, responded }` | 브로드캐스트 완료 |
| `heartbeat` | `{ ts }` | 연결 유지 |

### 3.4 현재 동작 방식의 특징

1. **최종 결과만 표시**: `agent.invoke()` → 완료 후 최종 output만 메시지로 저장
2. **실시간 로그 없음**: Command와 달리 중간 로그(사고 과정, 도구 호출 등)가 전혀 전달되지 않음
3. **병렬 실행**: 모든 Agent가 동시에 `invoke()` 실행
4. **비용 미추적**: `cost_usd`를 반환받지만 저장/전달하지 않음
5. **폴링 이중화**: SSE + 2초 폴링으로 메시지 누락 방지
6. **영속 저장**: 모든 메시지가 DB + JSON에 저장 (Command는 로그 파일)

---

## 4. ✅ 구현 완료: 통합 실행 아키텍처

### 4.1 변경 전 문제점 (해결됨)

| 문제 | 심각도 | 상태 |
|------|--------|------|
| 세션 로깅 누락 (Messenger에서 log_command/log_response 미호출) | 🔴 Critical | ✅ 해결 |
| 비용 미추적 (invoke 결과의 cost를 저장하지 않음) | 🔴 Critical | ✅ 해결 |
| 실행 로직 중복 (양쪽이 각각 invoke 호출) | ⚠️ Medium | ✅ 해결 |
| 이중 실행 미방지 (Command↔Messenger 간) | ⚠️ Medium | ✅ 해결 |
| DB에 cost_usd 컬럼 없음 | 🔴 Critical | ✅ 해결 |
| MessageResponse에 cost_usd 필드 없음 | ⚠️ Medium | ✅ 해결 |

### 4.2 아키텍처 변경

```
[변경 전]
  agent_controller.py ──► agent.invoke() (인라인 실행 로직 ~350줄)
  chat_controller.py  ──► agent.invoke() (별도 실행 로직, 로깅/비용 누락)

[변경 후]
  agent_controller.py ──┐
                        ├──► service/execution/agent_executor.py ──► agent.invoke()
  chat_controller.py  ──┘     (단일 실행 모듈, 모든 전/후 처리 통합)
```

### 4.3 변경된 파일 목록

| 파일 | 변경 유형 | 주요 변경 |
|------|-----------|-----------|
| `service/execution/__init__.py` | **신규** | 패키지 초기화 |
| `service/execution/agent_executor.py` | **신규** (~300줄) | 통합 실행 모듈 |
| `controller/agent_controller.py` | **수정** | 4개 실행 엔드포인트가 executor 사용 |
| `controller/chat_controller.py` | **수정** | broadcast가 `execute_command()` 사용 |
| `service/database/models/chat_message.py` | **수정** | `cost_usd` 컬럼 추가 |
| `service/database/chat_db_helper.py` | **수정** | INSERT/SELECT에 `cost_usd` 포함 |

---

## 5. agent_executor.py 상세

### 5.1 핵심 구성

```python
# === 데이터 ===
@dataclass
class ExecutionResult:
    success: bool
    session_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0
    cost_usd: Optional[float] = None

# === 예외 ===
class AgentNotFoundError(Exception): ...
class AgentNotAliveError(Exception): ...
class AlreadyExecutingError(Exception): ...

# === 상태 관리 ===
_active_executions: Dict[str, dict] = {}  # 실행 중인 세션 레지스트리 (agent_controller에서 이관)

# === 핵심 함수 ===
async def _execute_core(agent, session_id, prompt, holder, **kwargs) -> ExecutionResult
    """실행 생명주기 전체:
       1. log_command → 2. agent.invoke() → 3. log_response → 4. increment_cost"""

async def execute_command(session_id, prompt, **kwargs) -> ExecutionResult
    """동기(blocking) 실행. Messenger broadcast + POST /execute 에서 사용"""

async def start_command_background(session_id, prompt, **kwargs) -> dict
    """비동기(background) 실행. SSE 스트리밍용. POST /execute/start, /stream 에서 사용"""
```

### 5.2 실행 흐름

```
execute_command() / start_command_background()
    │
    ├─ _resolve_agent(session_id)     # 세션 조회 + 자동 부활
    ├─ is_executing(session_id)       # 이중 실행 방지
    ├─ _active_executions 등록        # 실행 추적
    │
    └─ _execute_core()
        ├─ session_logger.log_command()     # 1. 명령 로깅
        ├─ agent.invoke(input_text=prompt)  # 2. 에이전트 호출
        ├─ session_logger.log_response()    # 3. 결과 로깅
        ├─ session_store.increment_cost()   # 4. 비용 영속화
        └─ return ExecutionResult           # 5. 결과 반환
```

---

## 6. 엔드포인트별 실행 경로

### 6.1 Command 엔드포인트 (agent_controller.py)

| 엔드포인트 | 방식 | executor 호출 |
|------------|------|---------------|
| `POST /execute` | 동기 블로킹 | `execute_command()` |
| `POST /execute/start` | 비동기 백그라운드 | `start_command_background()` |
| `GET /execute/events` | SSE 스트리밍 | `get_execution_holder()` |
| `POST /execute/stream` | 시작+스트림 합체 | `start_command_background()` |

### 6.2 Messenger 엔드포인트 (chat_controller.py)

| 엔드포인트 | 방식 | executor 호출 |
|------------|------|---------------|
| `POST /rooms/{id}/broadcast` | Fire-and-forget | `execute_command()` × N |

```python
# Messenger broadcast의 핵심 변경:
async def _invoke_one(session_id):
    # 변경 전: result = await agent.invoke(input_text=message)
    # 변경 후:
    result = await execute_command(session_id=session_id, prompt=message)
    #          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    #          로깅, 비용 추적, 자동 부활, 이중 실행 방지 모두 내장
```

---

## 7. 기능 비교 매트릭스 (변경 후)

| 기능 | Command | Messenger | 상태 |
|------|---------|-----------|------|
| 실시간 로그 스트리밍 | ✅ 150ms 간격 SSE | ❌ 설계상 미지원 | ✅ 의도적 차이 |
| 최종 결과 반환 | ✅ result 이벤트 | ✅ message 이벤트 | ✅ |
| **비용 추적** | ✅ DB 저장 | ✅ **DB 저장** | ✅ 통합됨 |
| **세션 로그 기록** | ✅ log_command/response | ✅ **log_command/response** | ✅ 통합됨 |
| **이중 실행 방지** | ✅ 409 Conflict | ✅ **AlreadyExecutingError** | ✅ 통합됨 |
| 자동 부활 | ✅ | ✅ | ✅ |
| 실행 시간 기록 | ✅ duration_ms | ✅ duration_ms | ✅ |
| 실행 중단 (Stop) | ✅ POST /stop | ❌ 미지원 | ℹ️ 향후 가능 |
| 메시지 영속 저장 | △ 로그 파일 | ✅ DB + JSON | ✅ |
| **메시지에 비용 표시** | ✅ result.cost_usd | ✅ **message.cost_usd** | ✅ 추가됨 |

---

## 8. DB 스키마 변경

### chat_messages 테이블

```sql
-- 추가된 컬럼 (자동 마이그레이션)
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION DEFAULT NULL;
```

### MessageResponse 모델 (Pydantic)

```python
class MessageResponse(BaseModel):
    ...
    duration_ms: Optional[int] = None
    cost_usd: Optional[float] = None  # ← 추가됨
```

---

## 9. 테스트 결과

### 실행 환경
- 서버: `localhost:8000` (FastAPI, reload=False)
- 테스트 스크립트: `test_workspace/test_execution.py`

### TEST 1: Command Tab Execution (SSE)
```
POST /execute/start → 200
GET /execute/events  → 16개 로그 스트리밍
RESULT: success=True, cost=0.0551, duration=11472ms
Output: "hello test"
✅ 성공
```

### TEST 2: Messenger Broadcast
```
POST /rooms/{id}/broadcast → 200
target_count: 1
[final-verify/worker] (9911ms, cost=0.033541): hello messenger
1/1 sessions responded (9.9s)
✅ 성공 — cost_usd 정상 표시
```

### 검증 항목

| 항목 | 결과 |
|------|------|
| Command SSE 스트리밍 | ✅ 16개 로그 + result + done |
| Broadcast 실행 | ✅ 모든 에이전트 응답 |
| 비용 추적 (Command) | ✅ cost=0.0551 |
| 비용 추적 (Broadcast) | ✅ cost=0.033541 |
| DB 비용 저장 | ✅ chat_messages.cost_usd 컬럼에 저장 |
| API 비용 반환 | ✅ MessageResponse.cost_usd에 포함 |
| 세션 로깅 | ✅ log_command + log_response 호출됨 |
| 자동 부활 | ✅ executor 내 _resolve_agent()로 처리 |
| 이중 실행 방지 | ✅ AlreadyExecutingError → "Currently busy" 메시지 |

---

## 10. 요약

### 변경 전 → 변경 후

- **실행 로직**: 350줄 인라인 코드 (agent_controller) + 별도 코드 (chat_controller) → **단일 executor 모듈** (~300줄)
- **세션 로깅**: Command만 지원 → **양쪽 모두 지원**
- **비용 추적**: Command만 지원 → **양쪽 모두 지원** (DB 테이블 컬럼 추가 포함)
- **이중 실행 방지**: Command 내부만 → **전역** (Command ↔ Messenger 교차 방지)
- **코드 중복**: 높음 → **제거** (DRY 원칙 달성)

### API 호환성

- ✅ 기존 API 인터페이스 변경 **없음** (하위 호환)
- ✅ 프론트엔드 변경 **불필요** (비용 표시를 원하면 선택적으로 추가)
- ✅ SSE 이벤트 형식 변경 **없음**
