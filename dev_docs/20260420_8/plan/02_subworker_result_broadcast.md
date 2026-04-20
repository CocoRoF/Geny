# Plan/02 — Sub-Worker 결과의 VTuber 채팅방 브로드캐스트

**목적.** `analysis/02_subworker_result_broadcast_gap.md` § Bug 2a
해결. Sub-Worker가 보낸 `[SUB_WORKER_RESULT]`를 처리한 VTuber의
응답이 유저 채팅창에 실제로 뜨도록 한다.

**전제.** plan/01과 독립. 툴 이름 rename과 무관. plan/01 머지 전/후
어느 쪽에서도 적용 가능 (의존 없음).

**PR 구성.** 단일 PR.

---

## PR-3 — `_notify_linked_vtuber`에 chat-room broadcast 추가

### 범위 (Geny)

#### 3-1. `backend/service/execution/agent_executor.py`

`_trigger_vtuber` 내부 업데이트 (line 202-246):

```python
async def _trigger_vtuber() -> None:
    try:
        result = await execute_command(linked_id, content)
    except AlreadyExecutingError:
        # 기존 inbox 폴백 로직 유지
        ...
        return
    except (AgentNotFoundError, AgentNotAliveError) as exc:
        logger.debug("VTuber notification to %s skipped: %s", linked_id, exc)
        return

    # 2a 수정: VTuber가 SUB_WORKER_RESULT에 대해 생성한 응답을
    # 자기 chat room에 올리고 SSE notify 를 쏜다. 이 경로를 통해서만
    # 유저가 VTuber의 응답을 볼 수 있다 — thinking_trigger와 같은 구조.
    if result is not None:
        _save_subworker_reply_to_chat_room(linked_id, result)
```

#### 3-2. `_save_subworker_reply_to_chat_room` 신설

동일 파일 `agent_executor.py` 또는 `service/execution/_chat_bridge.py`
(신규 모듈). `thinking_trigger._save_to_chat_room` 와 대부분 동일
하지만 메시지 메타데이터가 살짝 다름:

```python
def _save_subworker_reply_to_chat_room(
    vtuber_session_id: str,
    result: "ExecutionResult",
) -> None:
    """Post the VTuber's reply to the user's chat room.

    Mirrors `thinking_trigger._save_to_chat_room` for the Sub-Worker
    → VTuber auto-report pathway. Without this, the VTuber's response
    to `[SUB_WORKER_RESULT]` is generated but never surfaces in the
    chat panel the user is watching.
    """
    try:
        if not result.success or not result.output or not result.output.strip():
            return

        from service.langgraph import get_agent_session_manager
        agent = get_agent_session_manager().get_agent(vtuber_session_id)
        if agent is None:
            return

        chat_room_id = getattr(agent, "_chat_room_id", None)
        if not chat_room_id:
            logger.debug(
                "VTuber %s has no _chat_room_id; skipping sub-worker reply broadcast",
                vtuber_session_id,
            )
            return

        from service.chat.conversation_store import get_chat_store
        store = get_chat_store()

        session_name = getattr(agent, "_session_name", None) or vtuber_session_id
        role_val = getattr(agent, "_role", None)
        role = role_val.value if hasattr(role_val, "value") else str(role_val or "vtuber")

        msg = store.add_message(chat_room_id, {
            "type": "agent",
            "content": result.output.strip(),
            "session_id": vtuber_session_id,
            "session_name": session_name,
            "role": role,
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
            "source": "sub_worker_reply",  # thinking_trigger와 구분
        })

        logger.info(
            "[SubWorkerReply] Posted VTuber response to chat room %s "
            "(msg_id=%s, len=%d)",
            chat_room_id, msg.get("id", "?"), len(result.output),
        )

        try:
            from controller.chat_controller import _notify_room
            _notify_room(chat_room_id)
        except Exception:
            logger.warning(
                "[SubWorkerReply] _notify_room failed for %s",
                chat_room_id, exc_info=True,
            )
    except Exception:
        logger.warning(
            "[SubWorkerReply] Failed to post VTuber reply to chat room",
            exc_info=True,
        )
```

**헬퍼 공유 vs 복붙 선택**: `thinking_trigger._save_to_chat_room`과
90% 동일하다. 유혹이 있지만:

- 두 호출처의 실행 컨텍스트가 다름 (인스턴스 메서드 vs 자유 함수)
- `source` 필드가 다름 (`thinking` vs `sub_worker_reply`) — 프런트
  구분용
- 예외 스레딩이 다름 (trigger는 trigger 내부 catchall, 여기는 FnF task)

리팩터는 cycle 9 이후로 미루고, 지금은 **거의 복붙**으로 유지해
호출처별 미묘한 차이를 명시적으로 남긴다. 공유 모듈화는 핵심 결함
해결과 관계없는 리팩터 noise.

#### 3-3. 회귀 테스트

파일: `tests/service/execution/test_notify_linked_vtuber.py` (신규
또는 `tests/service/execution/test_agent_executor.py`에 확장)

- `test_successful_vtuber_reply_posts_to_chat_room`:
  - Sub-Worker 세션 + 바인딩된 VTuber 세션 mock
  - `execute_command` mock → `ExecutionResult(success=True, output="...")`
  - `_notify_linked_vtuber` 호출
  - `asyncio` task 완료 대기
  - `store.add_message(chat_room_id, ...)` 가 한 번 호출됨 검증
  - `_notify_room(chat_room_id)` 한 번 호출됨 검증
- `test_empty_output_skips_chat_room_post`:
  - 결과 output이 빈 문자열 → `store.add_message` 호출 0회
- `test_already_executing_falls_back_to_inbox`:
  - `AlreadyExecutingError` 발생 → inbox 로직만 동작, chat room 포스트
    0회 (기존 동작 유지 확인)
- `test_vtuber_without_chat_room_does_not_crash`:
  - `_chat_room_id` 없음 → 경고 로그 + 조용히 리턴

### 검증

```bash
cd backend && pytest tests/service/execution -x -q
```

`asyncio.create_task` FnF 패턴이라 테스트는 `asyncio.gather` /
`await task` 로 명시적 대기 필요. 기존 `_notify_linked_vtuber` 테스트가
있다면 패턴 참조.

### 배포 관점

- 기존 경로(유저 → VTuber 직접 메시지)는 아예 건드리지 않으므로 회귀 없음
- 유저는 VTuber 응답을 두 번 보게 되지 않음 — SUB_WORKER_RESULT 경로는
  *원래 브로드캐스트되지 않던 것*이므로 새로 생기는 것이지 중복이 아님
- SSE 구독자 수가 0인 경우 `_notify_room`은 조용히 no-op

### 비범위

- Bug 2b (메모리 연속성) — plan/03
- `_save_to_chat_room` 리팩터 공유화 — cycle 9 이후
- DLQ 경로 개선 — 기존 동작 유지

---

## 라이브 스모크 체크리스트 (PR-3 머지 후)

1. 서비스 재시작
2. VTuber 세션 생성 → Sub-Worker 자동 링크
3. 유저: "Sub-Worker에게 test.txt 파일을 만들라고 해줘"
4. Sub-Worker Write 성공
5. **새 체크**: VTuber 채팅창에 Sub-Worker 완료에 대한 VTuber 응답
   메시지가 *자동으로 나타나야 함* (유저 추가 입력 없이)
6. SSE 스트림에서 `chat.message` 이벤트가 한 번 발생함을 확인
   (DevTools Network 탭)

## 완료 기준 (plan/02 단독)

- 위 스모크 5번이 일관되게 동작 (관측된 `output_len=164` 메시지가
  유저 화면에 뜸)
- 회귀 테스트 4개 모두 통과
- 기존 VTuber ↔ 유저 직접 대화 경로는 변화 없음 (`responded` 카운터,
  chat_controller flow 회귀 없음)
