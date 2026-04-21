# Plan/02 — DM tool 송신 기록 in STM (PR-2)

**해결 대상.** Bug B — `send_direct_message_internal` /
`send_direct_message_external`로 보낸 DM의 내용(`content`)이 송신자
STM에 남지 않는다. cycle 8 분류기는 "execute_command 레벨 입력"에만
적용되는데, 도구 호출은 이 레벨을 우회한다. `analysis/01_dm_continuity_regression.md`
§ 3 참조.

**접근.** DM tool의 `run()` 말미에서, 송신자의 `memory_manager`를 끌어와
`record_message("assistant_dm", content)` 한 줄을 호출. 실패 시 silently
swallow (cycle 8 PR-4의 non-critical 패턴 그대로).

## 1. 변경 파일

- `backend/tools/built_in/geny_tools.py` — DM tool 2개에 STM 기록 호출
  추가
- `backend/tests/service/langgraph/test_direct_message_stm.py` (신규) —
  DM 송신 시 STM 기록이 발생하는지 pin

## 2. 설계 선택

### 2.1. 왜 tool 내부에서?

- **session_logger vs memory_manager.** 기존 tool 이벤트는
  `session_logger.log_event("tool.call_complete", ...)`로 흘러가고,
  memory_manager와는 구조적으로 분리되어 있다. 이 둘을 묶는 구조 변경은
  범위 밖.
- **Pipeline 래퍼 vs tool 내부.** pipeline 종료 시 "이번 턴 동안 호출된
  DM의 content를 STM에 기록"하려면 이벤트 스트림 수집 로직을 추가해야
  하고, 실패 경로(예외, cancel)에서의 일관성이 복잡해진다. tool 내부
  기록은 **side-effect가 발생한 시점과 기록 시점이 같다** — 어떤 예외가
  나도 기록이 먼저 끝난 뒤에 뜬다.

### 2.2. 순환 import 방지

`geny_tools.py`에서 `AgentSessionManager`를 함수 레벨 lazy import. 기존
`_get_agent_manager()` 헬퍼가 이미 같은 패턴을 쓴다 (line 47-49). 새
기록 로직도 동일 패턴.

### 2.3. Send 실패 시

`inbox.deliver`가 예외를 내면 기존 로직은 그 예외를 그대로 올린다. 그
경우엔 STM 기록이 없어야 함 — 실제로 "보낸 적 없는 말"이 STM에 남는 건
더 큰 문제다. 따라서 **기록은 성공 경로에만 실행** (기존
`return json.dumps({"success": True, ...})` 직전).

## 3. 코드 변경 — 내부 DM 예시

`backend/tools/built_in/geny_tools.py` `SendDirectMessageInternalTool.run`
기존 (line 809-823):

```python
inbox = _get_inbox_manager()
msg = inbox.deliver(
    target_session_id=resolved_id,
    content=content.strip(),
    sender_session_id=session_id,
    sender_name=sender_name,
)

_trigger_dm_response(
    target_session_id=resolved_id,
    sender_session_id=session_id,
    sender_name=sender_name,
    content=content.strip(),
    message_id=msg["id"],
)
```

추가:

```python
# Record the outgoing DM on the sender's STM so it survives past the
# current turn. Without this, the DM body is visible only inside the
# tool call event log — next turn's retrieval (L0 recent-turns /
# session_summary / keyword / vector) has no record of what we asked.
# See dev_docs/20260421_1/analysis/01 § 3 for the regression pattern.
_record_dm_on_sender_stm(
    session_id=session_id,
    content=content.strip(),
    target_name=target.session_name,
    channel="internal",
)
```

그리고 파일 상단 헬퍼 영역(약 line 75 `_trigger_dm_response` 근처):

```python
def _record_dm_on_sender_stm(
    session_id: str,
    content: str,
    target_name: str,
    channel: str,  # "internal" | "external"
) -> None:
    """Write the outgoing DM body to the sender's short-term memory.

    Classified as ``assistant_dm`` so it mirrors how incoming DMs are
    recorded on the recipient side (via ``_trigger_dm_response``'s
    ``[SYSTEM] You received a direct message ...`` prompt, which the
    classifier already routes to ``assistant_dm``). Non-critical: any
    failure is swallowed — STM write must never break tool execution.
    """
    try:
        agent = _get_agent_manager().get_agent(session_id)
        if agent is None:
            return
        memory = getattr(agent, "_memory_manager", None)
        if memory is None:
            return
        # Prefix makes the record self-describing in STM transcripts.
        body = f"[DM to {target_name} ({channel})]: {content}"
        memory.record_message("assistant_dm", body[:10000])
    except Exception:
        logger.debug(
            "Failed to record outgoing DM on sender STM — non-critical",
            exc_info=True,
        )
```

`SendDirectMessageExternalTool.run`도 동일한 `_record_dm_on_sender_stm`
호출을 추가 (channel="external"). external 쪽은 target agent name이 없을
수 있어 `target_session_id` fallback.

## 4. 분류

기록하는 role은 `assistant_dm`. 근거:

- 수신자 쪽은 `_trigger_dm_response`가 주입한 `[SYSTEM] You received a
  direct message ...` 프롬프트가 classifier에서 `assistant_dm`으로
  분류됨 (cycle 8 PR-4).
- 송신자 쪽도 같은 role로 통일하면 "agent↔agent 대화는 assistant_dm 선"
  이라는 일관된 해석이 된다. user 라벨을 건드리지 않으므로 L0 recent-turns
  에서 사용자 입력과 구분 가능.

## 5. 테스트

### 5.1. 신규 — `test_direct_message_stm.py`

```python
def test_send_internal_records_to_sender_stm():
    # Arrange: fake agent with in-memory manager + linked counterpart
    # Act: tool.run(session_id=sender, content="hello sub")
    # Assert: sender._memory_manager.messages ends with
    #   ("assistant_dm", "[DM to Sub-Worker (internal)]: hello sub")

def test_send_external_records_to_sender_stm():
    # 같은 pattern, channel="external"

def test_record_failure_does_not_break_tool_return():
    # memory.record_message가 예외 터져도 tool은 성공 JSON 반환

def test_no_record_when_send_fails():
    # inbox.deliver 예외 상황에서는 STM에 쓰지 않음
```

### 5.2. 기존 STM 테스트 회귀 확인

`tests/service/langgraph/test_agent_session_memory.py`는 pipeline 레벨만
보므로 이번 변경으로 영향 없음. 실행해서 27개 green 유지만 확인.

## 6. 롤아웃 리스크

- **STM 창 팽창.** 한 턴에 DM을 여러 번 보내면 각각이 별도 turn으로
  기록된다. 현실적으로 VTuber/SW 대화는 한 턴당 1회 정도이므로 문제 없음.
  10000자 cap이 안전판.
- **비-DM tool 도입 압박.** 다른 tool(`web_search`, `Read`)도 기록해달라는
  요구가 생길 수 있으나, 본 PR은 DM류 한정. 별도 cycle에서 판단.
- **이중 기록 우려.** Bug A가 고쳐지면 수신자 쪽은 drain 때
  `assistant_dm`으로 이미 기록된다. 송신자 쪽 기록은 **"본인이 보낸
  말"**이고, 수신자 쪽은 **"본인이 받은 말"**이므로 같은 session 안에서
  중복되지 않는다 (send/receive는 서로 다른 두 session의 STM).

## 7. 검증

- `pytest backend/tests -q` → all green
- 수동 smoke (analysis/01 § 7과 동일).

## 8. 커밋 + PR

- 브랜치: `feat/dm-sender-stm-record`
- 커밋 제목: `feat(memory): record outgoing DM body on sender STM`
- PR 제목: 동일
