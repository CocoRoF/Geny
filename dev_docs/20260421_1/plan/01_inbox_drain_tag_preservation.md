# Plan/01 — Inbox drain 태그 보존 + classifier 확장 (PR-1)

**해결 대상.** Bug A — `_drain_inbox`가 생성하는 `[INBOX from {sender}]`
래퍼 프롬프트가 `_classify_input_role`의 prefix 리스트에 없어, drain
경로로 흐른 Sub-Worker 응답이 VTuber STM에 `role=user`로 저장되는 문제.
`analysis/01_dm_continuity_regression.md` § 2 참조.

**접근.** `_classify_input_role`에 `[INBOX from` prefix를 추가해 모든
inbox drain 입력을 `assistant_dm`으로 분류. drain 래퍼는 그대로 유지하고
(사용자/에이전트가 "누가 보냈는지" 맥락을 잃지 않도록), 분류만 바로잡는다.

## 1. 변경 파일

- `backend/service/langgraph/agent_session.py` — `_classify_input_role`
  확장
- `backend/tests/service/langgraph/test_agent_session_memory.py` —
  parametrized 케이스 추가

## 2. 코드 변경

### 2.1. `_classify_input_role` prefix 추가

현재 (lines 82-95):

```python
head = input_text.lstrip()[:128]
if head.startswith("[THINKING_TRIGGER") or head.startswith("[ACTIVITY_TRIGGER"):
    return "internal_trigger"
if (
    head.startswith("[SUB_WORKER_RESULT")
    or head.startswith("[SUB_WORKER_PROGRESS")
    or head.startswith("[CLI_RESULT")
    or head.startswith("[DELEGATION_REQUEST")
    or head.startswith("[DELEGATION_RESULT")
    or head.startswith("[FROM_COUNTERPART")
    or head.startswith("[SYSTEM] You received a direct message")
):
    return "assistant_dm"
return "user"
```

변경: `[INBOX from` prefix를 `assistant_dm` 분기에 추가한다. 또한
docstring에 cycle 21_1 근거를 한 줄 추가.

```python
if (
    head.startswith("[SUB_WORKER_RESULT")
    or head.startswith("[SUB_WORKER_PROGRESS")
    or head.startswith("[CLI_RESULT")
    or head.startswith("[DELEGATION_REQUEST")
    or head.startswith("[DELEGATION_RESULT")
    or head.startswith("[FROM_COUNTERPART")
    or head.startswith("[SYSTEM] You received a direct message")
    or head.startswith("[INBOX from")
):
    return "assistant_dm"
```

### 2.2. 근거 주석

docstring에 다음 bullet 추가:

```
* ``[INBOX from {sender}]`` — wrapper 형식 emitted by
  ``_drain_inbox`` in ``service/execution/agent_executor.py`` when
  a queued DM is picked up after the busy window closes. Always an
  inter-agent message, never from the human user → ``assistant_dm``.
```

## 3. 테스트

### 3.1. 새 parametrized 케이스

`backend/tests/service/langgraph/test_agent_session_memory.py`의
`test_classify_input_role` 파라미터에 추가:

```python
# Inbox drain wrapper — emitted by _drain_inbox @ agent_executor.py
("[INBOX from Sub-Worker]\n[SUB_WORKER_RESULT] Task completed: file.txt created", "assistant_dm"),
("[INBOX from Sub-Worker]\n(plain body with no tag)", "assistant_dm"),
("[INBOX from alice]\nhi there", "assistant_dm"),  # from external DM
# Leading whitespace still matches
("   [INBOX from Bob]\nhello", "assistant_dm"),
# Embedded [INBOX from inside prose is NOT at start → stays user
("fake [INBOX from foo] mid-sentence", "user"),
```

### 3.2. 통합 플로우 테스트 (선택적)

현 cycle의 최소 PR은 classifier 순수 함수만 고치므로, 분류 확인으로
충분. drain → invoke → record 연결은 cycle 8 PR-4가 이미 pin했고
이번 확장으로 자동 커버된다.

## 4. 롤아웃 리스크

- **Non-regression.** 기존 케이스(`[SUB_WORKER_RESULT]`, `[THINKING_TRIGGER]`,
  plain `[SYSTEM]`)에 영향 없음. prefix가 하나 추가될 뿐이고, 다른
  prefix와 충돌 없음 (`[I` 단독으로 시작하는 prefix 없음).
- **외부 DM drain.** 외부(`send_direct_message_external`)로 받은 DM이
  drain되는 경우도 `[INBOX from <external_sender>]`로 감싸지므로 동일하게
  `assistant_dm`으로 분류된다. "사용자의 실시간 입력이 아님"을 STM에
  표시한다는 의미에서 이 라벨이 정확하다 — cycle 8 설계 의도와 일치.
- **Re-classification.** 과거 로그(이미 STM에 `user`로 저장된 drain 메시지)는
  재라벨되지 않지만, 새 turn부터는 올바르게 들어간다. STM은 append-only
  transcript로 동작하므로 수동 migration 불필요.

## 5. 검증

- `pytest backend/tests/service/langgraph/test_agent_session_memory.py -q`
  → 전 케이스 green
- 수동: 스테이징에서 § 7 smoke 재현 — VTuber가 2분 전 응답을 사실로 인용.

## 6. 커밋 + PR

- 브랜치: `fix/classifier-inbox-drain-wrapper`
- 커밋 제목: `fix(memory): classify [INBOX from drain wrappers as assistant_dm`
- PR 제목: `fix(memory): classify [INBOX from drain wrappers as assistant_dm`
