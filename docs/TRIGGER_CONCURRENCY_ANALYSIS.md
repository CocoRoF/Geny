# 트리거 동시성 및 사용자 채팅 우선순위 분석

> 날짜: 2026-04-04
> 범위: VTuber Thinking/Activity 트리거 vs 사용자 채팅 상호작용

## 1. 요약

`[THINKING_TRIGGER]` 또는 `[ACTIVITY_TRIGGER]`가 VTuber 세션에서 실행 중일 때 사용자가 채팅 메시지를 보내면, **"Currently busy" 메시지와 함께 사용자 메시지가 거부된다.** 큐잉, 재시도, 중단 메커니즘이 전혀 없다.

본 리포트는 **5가지 핵심 문제**를 식별하고 구체적인 해결책을 제안한다.

---

## 2. 현재 아키텍처

### 2.1 실행 모델

```
execute_command(session_id, prompt)
├─ 확인: is_executing(session_id)?
│   ├─ YES → AlreadyExecutingError 발생
│   └─ NO  → _active_executions에 등록
├─ _execute_core(agent, prompt, holder)
│   └─ agent.invoke(prompt) → Claude 서브프로세스 (블로킹)
├─ 후처리 훅:
│   ├─ _emit_avatar_state()
│   └─ _notify_linked_vtuber() (CLI만 해당)
└─ cleanup_execution()
```

- `_active_executions: Dict[str, dict]` — 인메모리 실행 레지스트리
- `is_executing()` — holder 존재 여부 및 `done == False` 확인
- `ClaudeProcess._execution_lock` — asyncio.Lock() 서브프로세스 레벨 뮤텍스 (2차 잠금)
- **큐잉 없음, 중단 없음, 우선순위 시스템 없음**

### 2.2 트리거 발화

```
ThinkingTriggerService._loop() — 30초마다 폴링
├─ 각 VTuber 세션에 대해:
│   ├─ 유휴 시간 >= 적응형 임계값 확인
│   ├─ 트리거 프롬프트 생성 ([THINKING_TRIGGER] 또는 [ACTIVITY_TRIGGER])
│   └─ execute_command(session_id, prompt)
│       ├─ AlreadyExecutingError → 조용히 건너뜀 (debug 로그만)
│       ├─ AgentNotAliveError → 백오프 + 다음 사이클 재시도
│       └─ 성공 → 채팅방에 저장 + SSE 전송
```

### 2.3 사용자 채팅 메시지

```
POST /api/chat/rooms/{room_id}/broadcast
├─ 사용자 메시지 DB 저장
├─ 방 내 각 에이전트에 대해 (동시 실행):
│   └─ _invoke_one(session_id):
│       └─ execute_command(session_id, message)
│           ├─ AlreadyExecutingError →
│           │   └─ 시스템 메시지 저장: "{name}: Currently busy"
│           │   └─ 재시도 없음, 큐 없음, inbox 없음
│           └─ 성공 → 에이전트 응답 DB 저장 + SSE 전송
```

---

## 3. 충돌 시나리오

### 시나리오 A: 트리거 실행 중 → 사용자가 메시지 전송

```
T=0s:   [THINKING_TRIGGER] VTuber에서 발화
        → execute_command() 시작, _active_executions[vtuber] 등록
        → VTuber 반성 중 (LLM 실행, ~3-10초)

T=5s:   사용자가 채팅 메시지 전송
        → broadcastToRoom() → _invoke_one(vtuber)
        → execute_command() → is_executing(vtuber) = TRUE
        → AlreadyExecutingError 발생
        → 시스템 메시지: "VTuber: Currently busy with another execution"

T=8s:   트리거 완료, VTuber 반성 결과가 채팅에 저장됨
        → 사용자 메시지는 사라짐 — 처리되지 않음
```

**영향**: 사용자가 "busy" 메시지를 받음. 실제 메시지는 재시도되지 않음. 트리거 완료 후 수동으로 재전송해야 함.

**심각도**: 🔴 **CRITICAL** — 사용자 경험 심각하게 저하. 응답 없는 것처럼 느껴짐.

### 시나리오 B: Activity 트리거 실행 중 → 사용자가 메시지 전송

```
T=0s:   [ACTIVITY_TRIGGER] VTuber에서 발화
        → VTuber가 CLI에 웹서핑 작업 위임
        → VTuber 실행 ~5-15초 소요 (LLM 재구성, DM, 확인 메시지)

T=3s:   사용자가 채팅 메시지 전송
        → execute_command(vtuber) → AlreadyExecutingError
        → "Currently busy with another execution"

T=10s:  VTuber 위임 완료, 확인 메시지 표시
T=10s:  CLI가 웹서핑 시작 (20-60초 소요)

T=60s:  서브 워커 완료 → _notify_linked_vtuber(vtuber, [SUB_WORKER_RESULT])
        → execute_command(vtuber, [SUB_WORKER_RESULT]) → 성공 (VTuber 유휴 상태)
        → VTuber가 웹 발견 내용 공유

결과: T=3s의 사용자 메시지는 유실됨
```

**심각도**: 🔴 **CRITICAL** — Activity 트리거는 Thinking보다 길어서 충돌 가능성이 더 높음.

### 시나리오 C: 사용자 실행 중 → 트리거 발화

```
T=0s:   사용자 메시지 전송 → VTuber 실행 시작
T=30s:  ThinkingTrigger 루프 발화
        → execute_command(vtuber) → AlreadyExecutingError
        → 조용히 건너뜀 (debug 로그만)
        → Thinking 트리거 사일런트 드롭 ✅ (올바른 동작)
```

**영향**: 없음 — 트리거가 사용자 상호작용에 올바르게 양보함. `record_activity()`를 통해 타이머 리셋.

**심각도**: ✅ **정상** — 올바른 동작.

### 시나리오 D: 서브 워커 작업 완료 → VTuber 바쁜 동안 SUB_WORKER_RESULT 도착

```
T=0s:   VTuber가 CLI에 작업 위임
T=30s:  사용자가 VTuber에 새 메시지 전송 → VTuber 실행 시작
T=35s:  서브 워커 작업 완료 → _notify_linked_vtuber() 발동
        → execute_command(vtuber, [SUB_WORKER_RESULT]) → AlreadyExecutingError
        → INBOX 폴백: inbox.deliver(vtuber, cli_result_content)
T=40s:  VTuber 사용자 응답 완료

결과: 서브 워커 결과가 inbox에 있지만 자동 처리되지 않음
      VTuber가 geny_read_inbox 도구를 호출해야 하지만 자율적으로 하지 않음
```

**영향**: 서브 워커 작업 결과가 inbox에 영구적으로 묻힘. 사용자가 위임한 작업 결과를 절대 볼 수 없음.

**심각도**: 🔴 **CRITICAL** — 동시성 하에서 핵심 기능 고장.

### 시나리오 E: Activity 트리거가 CLI를 점유 중 → 사용자가 CLI에 작업 요청

```
T=0s:   Activity 트리거 → VTuber가 CLI에 웹서핑 위임
T=0s:   CLI가 web_search 실행 시작

T=10s:  사용자가 "Python 뉴스 검색해줘" 전송 → broadcast
        → VTuber가 메시지 처리 → CLI에 위임
        → _send_dm → execute_command(Sub-Worker) → AlreadyExecutingError
        → DM이 inbox에 저장되지만, CLI가 inbox를 자동으로 읽지 않음

T=40s:  CLI가 Activity 트리거의 웹서핑 완료
        → VTuber에 결과 보고
        → 사용자의 "Python 뉴스 검색" 요청은 여전히 inbox에 묻혀 있음 — 유실
```

**심각도**: 🔴 **CRITICAL** — 자율 활동이 CLI를 점유하여 사용자의 명시적 요청이 유실됨.

---

## 4. 근본 원인 분석

| 근본 원인 | 설명 |
|-----------|------|
| **실행 우선순위 없음** | 트리거와 사용자 메시지가 동일한 `execute_command()` 경로를 사용하며 우선순위 구분 없음 |
| **취소 API 없음** | 실행 중인 트리거를 사용자 입력을 위해 중단할 수 없음 |
| **메시지 큐 없음** | 실패한 실행은 큐잉되지 않고 그냥 드롭됨 |
| **Pull 전용 inbox** | Inbox 메시지는 명시적 도구 호출이 필수이며 자동 처리 안 됨 |
| **실행 후 inbox 드레인 없음** | 실행 완료 후에도 inbox를 확인하지 않음 |

---

## 5. 제안 해결책

### 5.1 [P0] 사용자 채팅 시 트리거 자동 취소 (우선순위 프리엠션)

**문제**: 트리거 실행 중에 사용자 메시지가 거부됨.

**해결**: `abort_execution()` 함수를 추가하고, 트리거 실행 중 사용자 메시지가 도착하면 트리거를 취소 후 사용자 메시지를 처리.

```
execute_command() 흐름:
  1. is_executing(session_id)?
  2. YES인 경우, 현재 실행이 TRIGGER인지 확인 (사용자 메시지가 아닌지):
     a. 트리거 → abort_execution(session_id) → 대기 → 사용자 메시지 처리
     b. 사용자 메시지 → AlreadyExecutingError 발생 (기존 동작 유지)
```

**구현 포인트**:
- `agent_executor.py`: 취소 플래그를 설정하는 `abort_execution(session_id)` 추가
- `_execute_core`: 실행 중 취소 플래그 확인
- `execute_command`: 트리거 실행 태깅을 위한 `is_trigger: bool` 파라미터 추가
- `_active_executions` holder: `"is_trigger": True/False` 필드 추가
- Broadcast `_invoke_one`: AlreadyExecutingError 발생 전, 현재 실행이 트리거이면 중단 시도

**예상 난이도**: 중간 — asyncio.Task 취소 처리에 주의 필요.

### 5.2 [P0] 실행 후 Inbox 자동 드레인

**문제**: SUB_WORKER_RESULT 또는 DM이 inbox에 폴백 저장되지만 읽히지 않음.

**해결**: 모든 VTuber/Worker 실행 완료 후 자동으로 미읽은 inbox 메시지를 확인하고 처리.

```
execute_command() finally 블록:
  cleanup_execution(session_id)
  → role == 'vtuber' 또는 role == 'worker'인 경우:
       await _drain_inbox(session_id)  # fire-and-forget

async def _drain_inbox(session_id):
    inbox = get_inbox_manager()
    unread = inbox.read(session_id, unread_only=True)
    if unread:
        combined = format_inbox_summary(unread)
        inbox.mark_all_read(session_id)
        await execute_command(session_id, combined)
```

**구현 포인트**:
- `agent_executor.py`: `finally` 블록에서 호출하는 `_drain_inbox()` 헬퍼 추가
- 무한 재귀 방지 필수 (inbox 드레인 → 새 실행 → 새 inbox 드레인)
- `_skip_inbox_drain` 플래그 또는 최대 깊이 카운터 추가

**예상 난이도**: 낮음 — 단순한 후처리 훅.

### 5.3 [P1] 사용자 메시지 큐 + 재시도

**문제**: Broadcast 중 AlreadyExecutingError가 발생하면 사용자 메시지가 완전히 유실됨.

**해결**: Broadcast에서 AlreadyExecutingError가 발생하면 메시지를 큐에 저장하고 현재 실행 완료 후 재시도.

```
_invoke_one():
  except AlreadyExecutingError:
    # 로깅만 하는 대신 재시도 큐잉
    _pending_user_messages[session_id] = (room_id, message, broadcast_state)
    store.add_message(room_id, {
        type: "system",
        content: f"{name}: 현재 작업 완료 후 처리합니다..."
    })
```

**5.2와 결합**: Inbox 드레인 메커니즘이 큐잉된 사용자 메시지도 처리 가능.

**단순 대안**: 사용자 메시지를 inbox에 저장 + 5초 후 재시도 스케줄링.

**예상 난이도**: 중간.

### 5.4 [P1] 트리거 전용 짧은 타임아웃

**문제**: 트리거 기본 타임아웃이 21600초(6시간) — 사용자 명령과 동일.

**해결**: 트리거 실행에 전용 짧은 타임아웃 설정.

```python
# _fire_trigger()에서:
result = await execute_command(
    session_id, prompt,
    timeout=30.0,     # Thinking: 최대 30초
    is_trigger=True,  # 우선순위 프리엠션용 태그
)
```

Activity 트리거의 서브 워커 위임 시:
```python
# Activity 트리거 VTuber 측: 30초 (위임만)
# Sub-Worker 측 실행: 120초 (실제 웹 검색)
```

**예상 난이도**: 낮음 — 파라미터 변경만.

### 5.5 [P2] 프론트엔드 "바쁨" UX 개선

**문제**: 사용자가 일반적인 "Currently busy"를 보지만 왜 바쁜지, 언제 재시도해야 하는지 모름.

**해결**:
1. 백엔드: 구조화된 오류 반환: `{"busy_reason": "thinking_trigger", "estimated_wait_s": 10}`
2. 프론트엔드: 상황별 메시지 표시: "VTuber가 생각 중이에요... 잠시 후 자동으로 전송됩니다"
3. 프론트엔드: 몇 초 후 자동 재시도

**예상 난이도**: 낮음 (백엔드) + 중간 (프론트엔드 자동 재시도).

---

## 6. 구현 우선순위

| 우선순위 | 해결책 | 영향 | 노력 |
|---------|--------|------|------|
| **P0** | 5.1 사용자 채팅 시 트리거 취소 | 사용자가 트리거에 의해 차단되지 않음 | 중간 |
| **P0** | 5.2 실행 후 inbox 드레인 | 서브 워커 결과가 유실되지 않음 | 낮음 |
| **P1** | 5.3 사용자 메시지 큐 + 재시도 | 우아한 성능 저하 | 중간 |
| **P1** | 5.4 짧은 트리거 타임아웃 | 차단 시간 단축 | 낮음 |
| **P2** | 5.5 프론트엔드 바쁨 UX | 더 나은 사용자 경험 | 중간 |

### 권장 구현 순서

1. **Phase 1** (Quick Win): 5.4 짧은 트리거 타임아웃 + 5.2 Inbox 드레인
   - 충돌 시간 창을 ~10초에서 최소화
   - Inbox 메시지가 항상 최종적으로 처리됨을 보장

2. **Phase 2** (핵심 수정): 5.1 트리거 취소
   - 사용자 메시지가 항상 트리거보다 우선
   - executor에 중단 메커니즘 필요

3. **Phase 3** (마무리): 5.3 큐 + 5.5 프론트엔드 UX
   - 양쪽 모두 진짜 바쁜 경우에도 우아하게 처리
   - 사용자에게 시각적 피드백 제공

---

## 7. 부록: 코드 참조 맵

```
backend/service/execution/agent_executor.py
├─ execute_command()          L500-548  — 메인 진입점, 이중 실행 가드
├─ start_command_background() L551-600  — SSE 스트리밍 변형
├─ is_executing()             L304-308  — 바쁨 확인
├─ _execute_core()            L232-286  — Claude 서브프로세스 호출
├─ _notify_linked_vtuber()    L170-200  — Sub-Worker→VTuber 결과 전달
├─ cleanup_execution()        L316-320  — holder 제거
└─ _active_executions         L299      — 글로벌 실행 레지스트리

backend/service/vtuber/thinking_trigger.py
├─ _fire_trigger()            L388-457  — 트리거 실행 + 오류 처리
├─ _build_trigger_prompt()    L505-580+ — 확률 기반 카테고리 선택
├─ _loop()                    L359-386  — 30초 폴링 사이클
└─ record_activity()          L310-314  — consecutive 카운터 리셋

backend/controller/chat_controller.py
├─ _run_broadcast()           L437-560  — 멀티 에이전트 채팅 실행
├─ _invoke_one()              L440-520  — 에이전트별 오류 처리
└─ room_event_stream()        L700-850  — SSE 메시지 전달

backend/service/workflow/nodes/vtuber/
├─ vtuber_classify_node.py    — 트리거용 Fast-path 라우팅
├─ vtuber_respond_node.py     — 직접 채팅 응답 (도구 없음)
├─ vtuber_delegate_node.py    — 서브 워커 위임 + fire-and-forget
└─ vtuber_think_node.py       — 반성 + [SILENT] 옵션

backend/service/chat/inbox.py
├─ InboxManager.deliver()     — 디스크에 메시지 작성
├─ InboxManager.read()        — Pull 전용 읽기
└─ 저장소: /chat_conversations/inbox/{session_id}.json
```
