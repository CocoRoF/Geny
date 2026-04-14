# Chat Streaming 심층 분석 — 토큰 스트리밍 + 초기 연결 문제

> Date: 2026-04-15

---

## 1. 문제 정의

### 1.1 토큰 단위 스트리밍 안 됨

현재 채팅 broadcast의 실행 경로:

```
_invoke_one() → execute_command() → agent.invoke() → _invoke_pipeline()
  │
  └── async for event in pipeline.run_stream(input, state):
        accumulated_output += text   ← 토큰별로 누적만 함
  │
  └── return {"output": accumulated_output}   ← 전체를 한번에 반환
        │
        ← execute_command() → ExecutionResult(output=full_text)
          │
          ← _invoke_one() → store.add_message(content=full_text)
            │
            ← _notify_room() → WebSocket/SSE에 완성된 메시지 한 개 전달
```

**결과**: 에이전트가 30초 걸려서 응답을 생성해도, 프론트엔드에는 30초 후에 **전체 텍스트가 한번에** 나타남.

### 1.2 초기 WebSocket 연결 지연

첫 페이지 로드 시 WebSocket이 실패하고 SSE로 폴백 → 3초 reconnect delay.
새로고침 후에는 정상 동작 (WebSocket 연결 성공).

---

## 2. 토큰 스트리밍 — 구조적 한계

### 2.1 현재 아키텍처의 문제

채팅 시스템은 **메시지 단위** 설계:
- `store.add_message()` → 완성된 메시지 1개 저장
- `_notify_room()` → "새 메시지 있음" 시그널
- WebSocket → `_get_messages_after()` → 완성된 메시지 전달

**파이프라인은 토큰 단위로 이벤트를 생성**하지만, 채팅 시스템에 전달할 경로가 없음.

### 2.2 해결 방향 — broadcast_status로 중간 텍스트 전달

`_invoke_one()`의 `_poll_logs()` 태스크가 이미 `agent_state.thinking_preview`를 업데이트하고 `_notify_room()`을 호출합니다. 이것을 확장하여 **누적 텍스트를 `agent_progress` 이벤트로 전달**할 수 있습니다.

```python
# chat_controller.py _poll_logs()에서:
# 현재: thinking_preview만 업데이트
# 개선: accumulated_text도 업데이트

for entry in new_entries:
    level = entry.level.value if hasattr(entry.level, "value") else str(entry.level)
    # STREAM 레벨 이벤트에서 텍스트 누적
    if level == "STREAM":
        agent_state.accumulated_text += entry.message
        _notify_room(room_id)
```

**하지만** `_invoke_pipeline()`이 session_logger에 `text.delta` 이벤트를 **기록하지 않습니다**.

현재 기록하는 이벤트:
- `tool.execute_start` → TOOL 레벨
- `tool.execute_complete` → TOOL_RES 레벨
- `stage.enter/exit` → GRAPH 레벨

**`text.delta` 이벤트는 session_logger에 기록하지 않음** — 로그가 너무 많아질 수 있어서 의도적으로 생략.

### 2.3 구체적 수정 방안

#### Option A: text.delta를 session_logger에 기록 + _poll_logs에서 누적

`_invoke_pipeline()`에서:
```python
elif event_type == "text.delta":
    text = event_data.get("text", "")
    if text:
        accumulated_output += text
        if session_logger:
            session_logger.log(
                level="STREAM",
                message=text,
                metadata={"type": "text_delta"},
            )
```

`_poll_logs()`에서:
```python
if level == "STREAM":
    agent_state.streaming_text = (agent_state.streaming_text or "") + entry.message
    _notify_room(room_id)
```

WebSocket `agent_progress` 이벤트에 `streaming_text` 포함:
```python
data["streaming_text"] = astate.streaming_text
```

프론트엔드에서 `agent_progress` 이벤트의 `streaming_text`를 실시간 표시.

#### Option B: 별도 streaming channel (더 깔끔하지만 대규모 변경)

broadcast가 `execute_command()` 대신 `start_command_background()`를 사용하고,
별도의 스트리밍 채널로 text.delta를 전달.

**→ Option A가 더 실현 가능. 기존 인프라(session_logger + _poll_logs + agent_progress)를 활용.**

---

## 3. 초기 WebSocket 연결 문제

### 3.1 원인 분석

Docker dev-core 환경:
- 프론트엔드: `localhost:3000` (Next.js dev server)
- 백엔드: `localhost:8000` (uvicorn)
- WebSocket URL: `ws://localhost:8000/ws/chat/rooms/{roomId}`

**첫 로드 시 타이밍**:
1. 브라우저가 `localhost:3000` 접속
2. React 컴포넌트 마운트 → `useEffect` → `subscribeToRoom()` 호출
3. `getChatWsUrl()` → `ws://localhost:8000/ws/chat/rooms/{roomId}`
4. `new WebSocket(url)` — 연결 시도

**가능한 실패 원인**:
- 컴포넌트가 roomId 없이 마운트 → roomId가 늦게 설정 → 첫 연결 실패
- 브라우저의 WebSocket handshake timeout
- Next.js HMR이 WebSocket 포트를 선점

### 3.2 VTuberChatPanel의 구독 시점

```javascript
useEffect(() => {
  if (!roomId) return;  // roomId 없으면 무시
  
  const init = async () => {
    const historyResp = await chatApi.getRoomMessages(roomId);  // HTTP 요청
    // ... messages 설정 ...
    const sub = chatApi.subscribeToRoom(roomId, lastMsgIdRef.current, ...);
    sseRef.current = sub;
  };
  
  init();
  return () => { sseRef.current?.close(); };
}, [roomId, toDisplayMessage]);
```

`toDisplayMessage`가 의존성에 포함되어 있어, 이 함수의 참조가 변경될 때마다 **구독이 해제→재생성**됩니다. `useCallback`으로 감싸져 있으면 문제없지만, 아니면 불필요한 재구독 발생.

---

## 4. 개선 계획

### Phase 1: 토큰 스트리밍 (채팅)

| # | 작업 | 파일 |
|---|------|------|
| 1 | `_invoke_pipeline()`에서 `text.delta` → session_logger STREAM 레벨 기록 | agent_session.py |
| 2 | `AgentExecutionState`에 `streaming_text` 필드 추가 | chat_controller.py |
| 3 | `_poll_logs()`에서 STREAM 레벨 감지 → `streaming_text` 누적 | chat_controller.py |
| 4 | `_build_agent_progress_data()`에 `streaming_text` 포함 | chat_controller.py |
| 5 | ws/chat_stream.py에서 `agent_progress` 이벤트에 `streaming_text` 전달 | ws/chat_stream.py |
| 6 | 프론트엔드에서 `agent_progress`의 `streaming_text`를 실시간 표시 | VTuberChatPanel.tsx, ChatTab.tsx |
| 7 | 파이프라인 완료 시 최종 메시지로 교체 | 프론트엔드 |

### Phase 2: WebSocket 연결 안정성

| # | 작업 | 파일 |
|---|------|------|
| 1 | `useEffect` 의존성에서 `toDisplayMessage` 제거 (불필요한 재구독 방지) | VTuberChatPanel.tsx |
| 2 | WebSocket 연결 실패 시 즉시 SSE 폴백 (3초 대기 제거) | api.ts |
| 3 | SSE 폴백 후 WebSocket 재시도 메커니즘 | api.ts |
