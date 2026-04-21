# Plan 02 — Wire sanitizer into 5 display sinks (PR-2)

**해결 대상.** PR-1에서 만든 `sanitize_for_display`를 chat-room 쓰기
경로 4곳 + live streaming 경로 1곳에 적용. PR-1 merged 후 진행.

## 1. 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `backend/controller/chat_controller.py` | Sink #1 (line 671, broadcast reply) + Sink #5 (line 607-609, streaming accumulation) |
| `backend/service/execution/agent_executor.py` | Sink #2 (line 928, sub-worker reply) + Sink #3 (line 983, drain) |
| `backend/service/vtuber/thinking_trigger.py` | Sink #4 (line 743, thinking trigger) |
| `backend/tests/controller/test_chat_broadcast_sanitize.py` | 신규 |
| `backend/tests/service/execution/test_agent_executor_sanitize.py` | 신규 |
| `backend/tests/service/vtuber/test_thinking_trigger_sanitize.py` | 신규 |

## 2. Sink-by-sink 변경

### 2.1. Sink #1 — chat_controller.py broadcast reply

`backend/controller/chat_controller.py:671` (안에서):

```python
# Before
"content": result.output.strip(),

# After
from service.utils.text_sanitizer import sanitize_for_display
...
"content": sanitize_for_display(result.output),
```

조기 return 조건도 sanitize 후 길이로 판단:

```python
# Before
if result.success and result.output and result.output.strip():

# After
cleaned = sanitize_for_display(result.output) if result.success else ""
if cleaned:
    msg_data = {"type": "agent", "content": cleaned, ...}
    ...
```

Rationale: 태그만으로 가득한 output (예: `[joy][surprise]`)은
sanitize 후 빈 문자열 → chat-room에 empty-content turn을 남기는 건
무의미하므로 skip. failure path는 기존대로.

### 2.2. Sink #2 — `_save_subworker_reply_to_chat_room`

`backend/service/execution/agent_executor.py:904-928`:

```python
# Before
if not result.success or not result.output or not result.output.strip():
    return
...
"content": result.output.strip(),

# After
from service.utils.text_sanitizer import sanitize_for_display
...
cleaned = sanitize_for_display(result.output) if result.success else ""
if not cleaned:
    return
...
"content": cleaned,
```

### 2.3. Sink #3 — `_save_drain_to_chat_room`

`backend/service/execution/agent_executor.py:983`: 동일 패턴. drain
결과에는 `[INBOX from X]` 프리픽스가 살아 있을 수 있으나, 이건
**input** 쪽에서 온 routing tag고 agent output에는 남지 않음. 그래도
방어적으로 sanitize.

### 2.4. Sink #4 — `ThinkingTriggerService._save_to_chat_room`

`backend/service/vtuber/thinking_trigger.py:743`: 동일 패턴.

### 2.5. Sink #5 — live streaming accumulation

`backend/controller/chat_controller.py:606-612`:

```python
# Before
if level == "STREAM":
    agent_state.streaming_text = (
        (agent_state.streaming_text or "") + (entry.message or "")
    )

# After
if level == "STREAM":
    raw = (agent_state.streaming_raw or "") + (entry.message or "")
    agent_state.streaming_raw = raw
    agent_state.streaming_text = sanitize_for_display(raw)
```

주의:
- **원본 보관 (`streaming_raw`)** — 다음 토큰이 partial tag를 완성할 수
  있으므로 누적은 raw 문자열에 대해 이뤄져야 함. 예: `[j` (raw) + `oy]`
  (new) → raw accumulates `[joy]` → sanitize → `""`.
- **sanitize 반복 비용** — broadcast 주기가 수십 ms 단위. 전형적
  응답 길이(수백~수천 자)에서 regex 네 번 sub은 sub-ms. 무시 가능.
- `AgentState`에 `streaming_raw` 필드 추가. 기존 `streaming_text`는
  sanitized view — 프론트엔드가 읽는 필드는 그대로라 프론트 변경 불요.

`AgentState` dataclass 위치 (chat_controller.py 상단 ~line 60-90
근방 추정)에 `streaming_raw: str = ""` 추가.

## 3. 테스트 전략

### 3.1. Unit 단위는 PR-1에서 이미 커버

각 sink의 regression test는 **sanitizer가 호출되었는가**와 **tag를
포함한 output이 저장될 때 cleaned 값이 저장되는가**만 pin.

### 3.2. Sink #1 — `test_chat_broadcast_sanitize.py`

```python
@pytest.mark.asyncio
async def test_broadcast_reply_sanitizes_emotion_tags(monkeypatch):
    # Stub execute_command to return result with [joy] tag.
    # Stub store.add_message to capture payload.
    # Assert captured content has no [joy].

async def test_broadcast_reply_sanitizes_routing_prefix():
    # result.output = "[SUB_WORKER_RESULT] Done"
    # Captured content should be "Done"

async def test_broadcast_skips_when_only_tags():
    # result.output = "[joy][smirk]"
    # store.add_message should NOT be called
```

### 3.3. Sink #2, #3, #4 — sink별 1-3개 테스트

각 sink 함수에 직접 fake `ExecutionResult`를 넣고 `store.add_message`
호출이 cleaned 값을 받는지 확인. Fake store / fake agent manager 패턴은
cycle 20260421_1에서 썼던 것 재사용.

### 3.4. Sink #5 — streaming

```python
def test_streaming_accumulates_raw_and_exposes_cleaned():
    state = AgentState(...)
    # simulate two STREAM events that split a [joy] tag across tokens
    _append_stream(state, "hello [j")
    assert state.streaming_text == "hello [j"   # partial, kept
    _append_stream(state, "oy] world")
    assert state.streaming_text == "hello world"  # fully stripped
    assert state.streaming_raw == "hello [joy] world"
```

(전용 helper `_append_stream` 함수를 extract하거나 inline test.)

## 4. 비-목표

- **Avatar 감정 추출 미변경.** `_emit_avatar_state`는 raw output을
  받아 emotion tag를 찾는다 — sanitize된 문자열에는 더 이상 tag가
  없으므로 avatar가 emotion을 받지 못한다. 이 함수는 sanitize 이전
  raw output으로 계속 호출되어야 함. 현재 호출 순서(result 생성 → avatar
  emit → chat-room save)는 유지되고, chat-room save 단계에서만 sanitize가
  새로 끼어들 뿐이라 자동으로 안전.
- **STM 저장 미변경.** `record_message`는 pipeline input/output을
  그대로 받는다. role 분류는 prefix 기반이므로 tag가 남아있어야 함.
- **프론트엔드 변경 없음.** 백엔드에서 이미 cleaned 문자열을 보내므로
  프론트는 무조건적으로 표시하면 됨.

## 5. 롤아웃 리스크

- **빈 output turn.** 태그만 있는 output이 drop되면 UX상 "응답이
  없어 보이는" 경우가 생길 수 있음. 실질적으로 LLM이 순수 태그만
  반환하는 경우는 거의 없고, 있다면 로그에 남기 때문에 디버깅은 가능.
  필요 시 `"(empty)"` placeholder를 쓸 수 있으나, 과잉이라 본 cycle
  에서는 drop으로 간단히 처리.
- **Streaming flash.** 앞서 말한 partial-tag 사이에 brackets가 잠시
  보일 수 있음. 수십 ms 단위라 사용자 인지 불가능에 가깝고, 완전히
  없애려면 lexer가 필요한데 ROI 없음.

## 6. 검증

- `pytest backend/tests -q` — 신규 + 기존 테스트 green.
- 수동 smoke: analysis/01 § 6 5-step scenario.

## 7. 커밋 + PR

- 브랜치: `feat/wire-sanitizer-into-display-sinks`
- 커밋 제목: `feat(chat): sanitize special tags from all display sinks`
- PR 제목: 동일
