# Geny Broadcast Logic — 심층 분석

## 1. 개요

Broadcast는 Geny Messenger에서 **채팅방(Room)의 모든 에이전트에게 동시에 메시지를 전달**하는 메커니즘이다.
핵심 설계 철학은 **"채팅방 = 멀티 커맨드"** — 각 에이전트가 커맨드 탭에서 명령을 받는 것과 동일한 경로(`execute_command`)로 메시지를 처리한다.

---

## 2. 전체 흐름 (End-to-End Sequence)

```
User (CEO)                    Frontend               Backend (chat_controller)        Agent Sessions (×N)
    │                            │                           │                              │
    ├─ "안녕하세요 다들" ────────→│                           │                              │
    │                            ├─ POST /broadcast ────────→│                              │
    │                            │                           │                              │
    │                            │                           ├─ ① store.add_message(user)   │
    │                            │                           ├─ ② _notify_room (SSE)        │
    │                            │                           ├─ ③ BroadcastState 생성        │
    │                            │                           ├─ ④ asyncio.create_task        │
    │                            │        200 OK ◄───────────┤    (_run_broadcast)           │
    │                            │                           │                              │
    │                            │                           │  ┌── _invoke_one(session_1) ──┤
    │                            │                           │  ├── _invoke_one(session_2) ──┤  (병렬 실행)
    │                            │                           │  ├── _invoke_one(session_3) ──┤
    │                            │                           │  └── _invoke_one(session_4) ──┤
    │                            │                           │                              │
    │                            │                           │     각 세션별:                │
    │                            │                           │     execute_command(          │
    │                            │                           │       session_id,             │
    │                            │                           │       prompt="안녕하세요 다들" │
    │                            │                           │     )                         │
    │                            │                           │                              │
    │                            │                           │     ┌─ agent.invoke() ────────┤
    │                            │                           │     │  geny-executor Pipeline │
    │                            │                           │     │  ├ InputStage            │
    │                            │                           │     │  ├ MemoryStage           │
    │                            │                           │     │  ├ PromptStage           │
    │                            │                           │     │  ├ APIStage (Claude)     │
    │                            │                           │     │  ├ ParseStage            │
    │                            │                           │     │  └ YieldStage            │
    │                            │                           │     │                          │
    │                            │                           │     │  Claude 가 도구 호출:     │
    │                            │                           │     │  ├ geny_session_list  ★★  │
    │                            │                           │     │  ├ geny_room_list     ★★  │
    │                            │                           │     │  └ geny_send_room_message │
    │                            │                           │     │        ↓                  │
    │                            │                           │     │    store.add_message() ★★★│
    │                            │                           │     │    (도구 통한 직접 저장)   │
    │                            │                           │     │                          │
    │                            │                           │     │  result = {output: "..."}│
    │                            │                           │     └────────────────────────→ │
    │                            │                           │                              │
    │                            │                           ├─ result.output을 또 저장 ★★★★ │
    │                            │                           │  store.add_message(agent, ...) │
    │                            │                           ├─ _notify_room (SSE)          │
    │                            │                           │                              │
    │                            │   ◄── SSE events ─────────┤                              │
    │    ◄────── UI 업데이트 ─────┤                           │                              │
```

---

## 3. 핵심 코드 경로 상세

### 3.1 Broadcast Endpoint (`chat_controller.py`)

```
POST /api/chat/rooms/{room_id}/broadcast
```

**처리 순서:**
1. 방(Room) 존재 확인
2. 유저 메시지 저장 (`store.add_message(type="user")`)
3. SSE 알림 (`_notify_room`)
4. 방에 속한 `session_ids` 목록 조회
5. `BroadcastState` 생성 (진행 상황 추적용)
6. **Fire-and-forget** 백그라운드 태스크 `_run_broadcast()` 시작
7. 즉시 200 OK 응답 반환

### 3.2 Background Dispatcher (`_run_broadcast`)

각 에이전트를 **병렬로** 실행한다:

```python
async def _invoke_one(session_id: str):
    result = await execute_command(
        session_id=session_id,
        prompt=message,       # ← 원본 메시지 그대로 전달
        # ❌ is_chat_message 전달 없음
        # ❌ room_id 전달 없음
        # ❌ broadcast 컨텍스트 없음
    )

    if result.success and result.output and result.output.strip():
        store.add_message(room_id, {       # ★ result.output을 방에 저장
            "type": "agent",
            "content": result.output.strip(),
            ...
        })
```

**핵심 문제점:** `execute_command`에 어떤 broadcast context도 전달되지 않는다.

### 3.3 Agent Invoke (`agent_session.py`)

```python
async def invoke(self, input_text: str, **kwargs):
    kwargs.setdefault("agent_name", self._session_name)
    kwargs.setdefault("agent_role", self._role.value)
    # ❌ is_chat_message는 kwargs에 포함되지 않음

    initial_state = make_initial_autonomous_state(
        input_text,
        max_iterations=effective_max_iterations,
        **kwargs,
    )
    # → is_chat_message = extra_metadata.pop("is_chat_message", False)
    # → 항상 False
```

### 3.4 Relevance Gate (`relevance_gate_node.py`)

```python
is_chat = state.get("is_chat_message", False)

if not is_chat:
    return {}  # ← Broadcast에서 항상 이 경로
               # → 관련성 필터링 없이 무조건 통과
```

**설계 의도:** `is_chat_message=True`일 때 LLM으로 "이 메시지가 나와 관련있는지" 판단하여 불필요한 응답을 필터링하는 게이트.
**현실:** broadcast에서 이 플래그가 전달되지 않아 **항상 pass-through** → 모든 에이전트가 무조건 응답한다.

### 3.5 System Prompt — Geny 도구 인지 (`sections.py`)

에이전트의 시스템 프롬프트에 다음이 포함된다:

```
## Geny Platform Tools

You have built-in tools to interact with the Geny platform:
- **Session management**: geny_session_list, geny_session_info, geny_session_create
- **Room management**: geny_room_list, geny_room_create, ...
- **Messaging**: geny_send_room_message, geny_send_direct_message
- **Reading**: geny_read_room_messages, geny_read_inbox

Your session ID: `{session_id}`
```

**문제:** 에이전트는 `geny_send_room_message` 도구가 사용 가능하다고 인지하고 있다. Broadcast 상황임을 모르므로, 스스로 채팅방에 메시지를 보내야 한다고 판단한다.

---

## 4. 문제의 근본 원인 분석

### 4.1 이중 메시지 저장 (Double-Save Problem)

사용자가 "안녕하세요 다들"을 broadcast하면:

| 단계 | 누가 | 무엇을 | 어디에 |
|------|------|--------|--------|
| ① | `_run_broadcast` | 유저 메시지 저장 | `store.add_message(type="user")` |
| ② | Agent (Claude) | `geny_send_room_message` 도구 호출로 직접 메시지 저장 | `store.add_message(type="agent")` |
| ③ | `_run_broadcast` | `result.output`을 방에 저장 | `store.add_message(type="agent")` |

**②와 ③이 동시에 발생한다.** 에이전트가 도구(`geny_send_room_message`)로 직접 메시지를 저장하고, broadcast 핸들러가 결과 출력을 또 저장한다.

### 4.2 불필요한 도구 호출 (Unnecessary Tool Calls)

로그 분석:

```
[b89ed477] (지영/planner):   Tool calls: 3
  [1] geny_session_list    ← 불필요: 팀원 목록 조회
  [2] geny_room_list       ← 불필요: 방 목록 조회
  [3] geny_send_room_message ← 문제: 직접 메시지 전송

[64eead52] (현우/developer): Tool calls: 5
  [1] geny_session_list    ← 불필요
  [2] geny_room_list       ← 불필요
  [3] geny_read_room_messages ← 불필요: 방 대화 읽기
  [4] geny_send_room_message  ← 문제: 직접 메시지 전송
  [5] geny_read_inbox         ← 불필요: 받은편지함 확인
```

에이전트는 "안녕하세요 다들"이라는 간단한 인사에 대해:
1. 팀 구성원을 조회하고
2. 방 목록을 확인하고
3. 채팅 기록을 읽고
4. **도구를 사용해 직접 응답을 보내고** (이게 문제)
5. 받은편지함까지 확인한다

→ 이 모든 것이 **"나는 커맨드 모드에 있다"** 는 전제 하에 발생한다.

### 4.3 메타 메시지 출력 (Meta-Message Problem)

에이전트가 `geny_send_room_message`로 실제 인사 메시지를 보낸 뒤, Claude의 `final_answer`(result.output)는 도구 사용 결과를 요약하는 **메타 메시지**가 된다:

```
"AI-LAB 채팅방에 인사 메시지를 전달했습니다!"
"인사메세지를 전달했습니다"
```

이것이 `_run_broadcast`에 의해 방에 **또 하나의 메시지로 저장**된다.

**실제 방에 나타나는 메시지 순서 (에이전트 1명당):**
1. 에이전트의 인사 메시지 (geny_send_room_message 도구로 저장) ← 이건 그럴듯함
2. "인사 메시지를 전달했습니다" (result.output으로 저장) ← **이것이 불필요한 메시지**

### 4.4 비용 낭비 (Cost Waste)

간단한 인사에 대해 각 에이전트가:
- `geny_session_list` 호출 (API 비용)
- `geny_room_list` 호출 (API 비용)
- `geny_read_room_messages` 호출 (API 비용)
- `geny_send_room_message` 호출 (API 비용 + 중복 저장)
- `geny_read_inbox` 호출 (API 비용)

4명의 에이전트 총 비용: **$0.015 + $0.134 + $0.153 + $0.143 = ~$0.445** (단순 인사 한 마디에)

---

## 5. 문제의 병목 지점 요약

```
                         ┌─────────────────────────────────────────┐
                         │          _run_broadcast()               │
                         │                                         │
                         │  execute_command(prompt="안녕하세요")    │
                         │    ❌ is_chat_message 전달 안됨          │
                         │    ❌ room_id 전달 안됨                  │
                         │    ❌ 브로드캐스트 컨텍스트 없음           │
                         └─────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                   │
                    ▼                  ▼                   ▼
        ┌───── 문제 1 ─────┐  ┌── 문제 2 ──┐  ┌──── 문제 3 ────┐
        │ Relevance Gate   │  │ Agent가     │  │ 이중 저장       │
        │ 비활성화됨       │  │ 도구를 남용  │  │                 │
        │                  │  │             │  │ 도구 호출 저장 + │
        │ is_chat=False    │  │ session_list│  │ result.output   │
        │ → 모든 에이전트  │  │ room_list   │  │ 저장             │
        │   무조건 응답    │  │ send_msg ★  │  │                 │
        │ (필터링 없음)    │  │ read_inbox  │  │ → 중복 메시지    │
        └──────────────────┘  └─────────────┘  └─────────────────┘
```

### 근본 원인 (Root Cause):

**`_run_broadcast`가 `execute_command`를 호출할 때 broadcast context를 전달하지 않는다.**

구체적으로:
1. **`is_chat_message=True`가 전달되지 않음** → Relevance Gate 비활성화 → 불필요한 에이전트도 응답
2. **에이전트가 broadcast 상황임을 모름** → `geny_send_room_message` 도구를 직접 호출하여 응답 (broadcast 핸들러가 이미 output을 저장하는데도)
3. **output 이중 저장** → 도구 호출로 인한 저장 + `_run_broadcast`의 `result.output` 저장 = 중복 메시지

---

## 6. 영향받는 코드 파일

| 파일 | 역할 | 문제 |
|------|------|------|
| `controller/chat_controller.py` | broadcast 핸들러 | `execute_command`에 context 미전달, output 이중 저장 |
| `service/execution/agent_executor.py` | 명령 실행기 | `is_chat_message` 파라미터 미지원 |
| `service/executor/agent_session.py` | 에이전트 세션 | `invoke()`에 `is_chat_message` 전달 누락 |
| `service/executor/state.py` | 상태 정의 | `is_chat_message` 필드 존재하나 사용 안됨 |
| `service/workflow/nodes/logic/relevance_gate_node.py` | 관련성 필터 | `is_chat_message=False`로 인해 비활성화 |
| `service/prompt/sections.py` | 시스템 프롬프트 | broadcast 시 도구 사용 지침 없음 |
| `tools/built_in/geny_tools.py` | 플랫폼 도구 | broadcast 중 도구 호출 방지 메커니즘 없음 |

---

## 7. 이상적인 동작 (Expected Behavior)

CEO가 "안녕하세요 다들"을 broadcast하면:

1. 각 에이전트가 메시지를 받는다
2. **Relevance Gate가 활성화**되어 관련 없는 에이전트는 자동으로 스킵
3. 관련 에이전트는 **직접 텍스트로만 응답** (도구 호출 없이)
4. `_run_broadcast`가 `result.output`을 방에 **한 번만** 저장
5. 불필요한 메타 메시지("인사 전달했습니다") 없음
6. 불필요한 도구 호출 없음 → 비용 절감

---

## 8. 적용된 수정 사항

### 수정 1: `is_chat_message=True` 전달 체인 구축

**변경 파일:** `service/execution/agent_executor.py`

`execute_command()`와 `_execute_core()`에 `**invoke_kwargs`를 추가하여 broadcast context가 agent까지 전달되도록 수정:

```
_run_broadcast(is_chat_message=True)
  → execute_command(**invoke_kwargs)
    → _execute_core(**invoke_kwargs)
      → agent.invoke(**invoke_kwargs)
        → make_initial_autonomous_state(is_chat_message=True)
          → state["is_chat_message"] = True
            → relevance_gate 활성화 ✅
```

**변경 파일:** `controller/chat_controller.py`

`_invoke_one()`에서 `execute_command` 호출 시 `is_chat_message=True` 전달:

```python
result = await execute_command(
    session_id=session_id,
    prompt=message,
    is_chat_message=True,  # ← 추가
)
```

### 수정 2: 이중 저장(Double-Save) 방지

**변경 파일:** `controller/chat_controller.py`

실행 전 메시지 ID를 스냅샷하고, 실행 후 에이전트가 도구로 이미 메시지를
보냈으면 `result.output` 저장을 건너뛴다:

```python
# 실행 전 스냅샷
pre_msg_ids = {m.get("id") for m in store.get_messages(room_id)}

# 실행
result = await execute_command(...)

# 에이전트가 도구로 이미 보냈는지 확인
post_msgs = store.get_messages(room_id)
agent_already_posted = any(
    m.get("id") not in pre_msg_ids
    and m.get("session_id") == session_id
    and m.get("type") == "agent"
    for m in post_msgs
)

if agent_already_posted:
    # 도구로 이미 저장됨 → result.output 저장 건너뜀
    state.responded += 1
else:
    # 도구 미사용 → result.output 저장
    store.add_message(...)
```
