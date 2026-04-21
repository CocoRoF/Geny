# Analysis/01 — VTuber↔Sub-Worker DM 연속성 재발 (cycle 20260420_8 사후)

**대상 로그.** 2026-04-21 10:20–10:23 UTC (cycle 20260420_8 배포 직후).

## 0. 요약

cycle 8 PR-4/5가 도입한 `_classify_input_role` + L0 recent-turns는
**non-busy 경로의 `_notify_linked_vtuber`**(즉, `[SUB_WORKER_RESULT]`가
VTuber의 `execute_command` 입력으로 직접 들어오는 경로)만을 보호한다.
그러나 실제 프로덕션에서 VTuber는 **자기 턴 안에서** Sub-Worker를
호출하므로, Sub-Worker가 결과를 낸 시점에 VTuber는 항상 busy 상태이고,
`_notify_linked_vtuber`의 `AlreadyExecutingError` 분기로 흘러 inbox에
적재된다. VTuber는 (a) 현재 턴 안에서 `read_inbox` 도구로 결과를 확인할
수 있고, (b) 턴 종료 후 `_drain_inbox`가 다시 execute_command를 트리거해
처리한다.

세 개의 독립 결함이 이 경로에 겹쳐 있고, 모두 **STM에 대화가 올바르게
남지 않게** 만든다.

| # | 결함 | 위치 | 증상 |
|---|---|---|---|
| A | drain 래퍼가 원 태그를 숨김 | `_drain_inbox` @ `agent_executor.py:856` | `[INBOX from Sub-Worker]\n[SUB_WORKER_RESULT] ...`가 `_classify_input_role`에서 `user`로 폴백됨 |
| B | DM tool 호출이 STM 바깥 | `send_direct_message_internal` @ `geny_tools.py:765-837` | VTuber가 요청을 보낸 흔적이 STM에 남지 않음 |
| C | `read_inbox` tool 결과가 STM 바깥 | `ReadInboxTool.run` @ `geny_tools.py:906-939` | 현재 턴에서만 관측 가능, 다음 턴이 되면 접근 불가 |

## 1. 관찰된 로그 재현

```
# Sub-Worker log (session 002b7d53 쌍의 Sub-Worker)
10:20:45  command   [SYSTEM] You received a direct message from testsa
10:20:50  tool      web_search(...)
10:20:54  response  "I'll help testsa find something interesting..." (9256ms)
10:20:54  info      [SUB_WORKER_RESULT] → 002b7d53    ← _notify_linked_vtuber 발화

# VTuber log (session 002b7d53, name=testsa)
10:20:58  tool      read_inbox(...)
10:21:05  response  "오! 서브워커가 뭔가 재미있는 걸 찾아주겠다고 하네!"  (11423ms)
                                                                            ↑ 같은 턴 안
10:23:24  command   [THINKING_TRIGGER:time_morning] 아침 시간이 왔다...
10:23:27  tool      read_inbox(...)                ← 두 번째 read — 이미 비어있음
10:23:36  response  "서브워커로부터는 아직 새로운 소식이 없네. 어제 부탁했던..."
```

10:21 응답을 낸 VTuber가 2분 뒤 "아직 소식이 없다"고 말한다는 사실은
**그 순간 VTuber의 context window에 10:21 턴이 없다**는 의미이고, 이는
곧 **STM retrieval이 10:21 턴을 복원하지 못한다**는 뜻이다. cycle 8
PR-5의 L0 recent-turns는 STM 가장 최근 6턴을 무조건 삽입하도록 설계되어
있으므로, L0가 10:21 턴을 못 찾는다는 건 STM 자체에 턴이 올바른 형태로
남지 않았다는 신호다.

## 2. Bug A — drain 래퍼의 태그 손실

### 2.1. 코드 경로

busy 상태의 VTuber에게 `_notify_linked_vtuber`가 결과를 전달하는
로직(`backend/service/execution/agent_executor.py:202-256`):

```python
async def _trigger_vtuber() -> None:
    try:
        vtuber_result = await execute_command(linked_id, content)
                                                    # ↑ content = "[SUB_WORKER_RESULT] ..."
    except AlreadyExecutingError:
        inbox = get_inbox_manager()
        inbox.deliver(
            target_session_id=linked_id,
            content=content,                        # ← 원 태그 보존하여 inbox 저장
            sender_session_id=session_id,
            sender_name="Sub-Worker",
        )
        ...
```

턴 종료 후 `_drain_inbox`(line 818-883)가 다시 꺼낸다:

```python
pulled = inbox.pull_unread(session_id, limit=1)
msg = pulled[0]
sender = msg.get("sender_name") or "Unknown"
prompt = f"[INBOX from {sender}]\n{msg['content']}"    # ← line 856
...
result = await execute_command(session_id, prompt)
```

`execute_command`는 결국 `AgentSession._invoke_pipeline` 또는
`_astream_pipeline`으로 진입하고, 그 시작부에서 `_classify_input_role`이
동작한다(`backend/service/langgraph/agent_session.py:933 / 1123`).

### 2.2. 분류 결과

`_classify_input_role`의 prefix 리스트(line 82-94):

```python
head = input_text.lstrip()[:128]
if head.startswith("[THINKING_TRIGGER") or head.startswith("[ACTIVITY_TRIGGER"):
    return "internal_trigger"
if (
    head.startswith("[SUB_WORKER_RESULT")
    ... (그 외 6개)
    or head.startswith("[SYSTEM] You received a direct message")
):
    return "assistant_dm"
return "user"
```

실제 입력: `"[INBOX from Sub-Worker]\n[SUB_WORKER_RESULT] Task completed successfully.\n\n..."`

- `head[0:10] == "[INBOX fro"` — 어떤 prefix에도 매칭되지 않음
- `return "user"` — **역할 폴백**

결과적으로 Sub-Worker의 답변이 VTuber STM에 `role=user`로 저장된다.
이는 cycle 8이 없애려고 했던 "trigger/DM을 user로 기록하는" 회귀를 **다른 경로를 통해 정확히 재현**한다.

### 2.3. 2차 피해 — retrieval

L0 recent-turns는 STM 말미 6턴을 `[<role>] <content>` 형식으로 주입한다
(geny-executor v0.28.0, `GenyMemoryRetriever.retrieve`). 실제 10:21 턴
이후 VTuber의 STM은 대충 이렇게 쌓였을 것이다:

```
[user]       create interesting stuff about testsa   ← 사용자 원 입력
[assistant]  네, 서브워커에게 부탁해볼게요!           ← 10:20:58 이전 턴
[user]       [INBOX from Sub-Worker]\n[SUB_WORKER_RESULT] ... ← Bug A로 user 저장
[assistant]  오! 서브워커가 뭔가 재미있는 걸 ...       ← 10:21:05 본문
[internal_trigger] [THINKING_TRIGGER:time_morning] ...  ← 10:23:24
...
```

10:23:27의 `read_inbox`는 Tool 반환일 뿐 STM 기록은 없다. 그 직후 VTuber는
L0에 실린 `[user] [INBOX from Sub-Worker]\n[SUB_WORKER_RESULT]...`를 본다.
하지만 prompt는 "사용자가 방금 inbox를 붙여넣었다"로 해석될 소지가 매우
크고 — 어제-오늘 구분이 불명확해진다. 실제 관찰된 VTuber 응답 ("**어제**
부탁했던 …이 **아직 진행 중**인 것 같아")은 이 해석 결함의 전형적 형태다.

## 3. Bug B — 도구로 보낸 DM이 STM에 없음

### 3.1. 호출 사이트 조사

`backend/service/langgraph/agent_session.py`에서 `record_message`는 정확히
네 곳에서 호출된다:

```
933    self._memory_manager.record_message(_classify_input_role(input_text), input_text)   # _invoke_pipeline input
1068   self._memory_manager.record_message("assistant", accumulated_output[:10000])         # _invoke_pipeline output
1123   self._memory_manager.record_message(_classify_input_role(input_text), input_text)   # _astream_pipeline input
1249   self._memory_manager.record_message("assistant", ...)                                # _astream_pipeline output
```

즉 **"execute_command 레벨의 입력/출력"** 만 STM에 남는다. Tool 호출과 그
반환값은 `session_logger`의 `tool.call_start` / `tool.call_complete`
이벤트로만 남고 STM에는 들어가지 않는다.

### 3.2. `send_direct_message_internal`의 실제 반환

```python
# backend/tools/built_in/geny_tools.py:825-837
return json.dumps(
    {
        "success": True,
        "message_id": msg["id"],
        "delivered_to": resolved_id,
        "delivered_to_name": target.session_name,
        "timestamp": msg["timestamp"],
        "auto_triggered": True,
    }, ...
)
```

VTuber는 이 JSON을 받아 assistant 메시지에 자연어로 녹여낸다 ("좋아,
서브워커에게 물어봤어!"). 그러나 **"뭐를 물어봤는지"** 자체는 STM 어디에도
없다. 즉, VTuber가 다음 턴에 STM만으로 자신의 액션을 재구성하려 하면
`content="..."` 원문이 사라져 있고, Sub-Worker의 답변 측(Bug A)에도 문제가
있으므로 전체 대화가 끊어진다.

### 3.3. Bug A와의 상호작용

- Bug A만 고치면: SW→VTuber의 답변은 `assistant_dm`으로 들어가지만
  VTuber→SW의 요청은 여전히 유실. "답변은 있는데 무엇에 대한 답변인지
  모르는" 상태가 된다.
- Bug B만 고치면: VTuber→SW 요청은 `assistant_dm`으로 저장되지만 답변은
  여전히 `user`로 잘못 라벨됨. "내가 물어본 건 맞는데 상대가 사용자였나?"
  식의 혼동이 그대로.

**두 버그는 같은 cycle에서 같이 해결해야 완결**된다.

## 4. Bug C — `read_inbox` tool 결과도 STM 바깥 (정책적 판단)

`read_inbox`는 tool 반환을 agent 모델에게 돌려주지만 STM으로는 넘기지
않는다(3.1과 동일). 10:20:58에 읽은 Sub-Worker 메시지 내용은 그 턴 안에서만
존재하고, 10:21:05 assistant 응답이 끝나면 tool 반환값은 휘발된다.

Bug C는 Bug A/B와 달리 **"모든 tool 결과를 STM에 넣어야 한다"고 일반화하기
곤란**하다:

- `web_search`, `Bash`, `Read` 등은 내용이 매우 길고 STM 창을 폭파시킬 수
  있음.
- `read_inbox`만은 "대화 의미를 갖는" tool이라는 점에서 다름.

그러나 구조적으로 보면 **Bug A 해결이 Bug C를 자연스럽게 무력화**한다.
Bug A가 고쳐지면 busy 경로의 결과가 `assistant_dm`으로 STM에 들어가므로,
드레인 턴에서 이미 내용이 기록된 상태다. 따라서 `read_inbox`가 같은 내용을
다시 STM에 기록할 필요가 사라진다. 본 cycle에서는 **Bug C를 직접 고치는
PR을 열지 않고, Bug A 해결의 부수 효과로 닫힌다고 본다** (아래 § 5 참조).

## 5. 권장 해결 방향

### 5.1. Bug A 해결 — `[INBOX from` 래퍼를 분류기에서 인식 + drain 태그 보존

두 가지 방향이 가능하다:

- **(A1) Classifier 확장만.** `_classify_input_role`에 `[INBOX from`
  prefix를 추가. 단순하지만 약점: 래퍼 내부 본문이 `[SUB_WORKER_RESULT]`
  인지 일반 DM인지 구분하지 못해 모든 inbox drain을 `assistant_dm`으로
  일괄 분류한다. 외부 사람(`send_direct_message_external`)에게서 온 DM이
  drain되는 경우도 같은 라벨로 들어가지만, 의미상 "사용자처럼 취급되면
  안 됨"이라는 점은 일관되므로 이 일괄 라벨이 용납 가능.
- **(A2) drain이 태그를 살려서 prompt로 전달.** 예를 들어
  `_drain_inbox`가 `msg['content']`를 감싸지 말고 그대로 execute_command에
  넘기거나, `[INBOX from {sender}]` 래퍼를 유지하되 classifier 안쪽
  "두 번째 줄"을 검사하도록 확장. 복잡도 증가, 그러나 정확도 상승.

첫 PR은 **(A1)과 (A2)의 조합**으로 간다:
- drain 래퍼는 유지(사용자 노이즈를 `assistant`에게 투명하게 보여주는 장점이 있음).
- classifier에 `[INBOX from` prefix 추가 → 모두 `assistant_dm`.
- 다만 래퍼 안쪽에 `[SUB_WORKER_RESULT]`가 있는 경우에 한해 내부 태그를
  그대로 보이게 유지(문자열 그대로 보존되므로 추가 작업 없음).

### 5.2. Bug B 해결 — 최소 침습 DM 기록 훅

세 안:

- **(B1) Tool 내부에서 `AgentSession`을 끌어와 `record_message` 직접 호출.**
  순환 import 위험 + tool은 session-free 원칙 위배.
- **(B2) `AgentSession`이 tool 호출 이벤트를 구독하고, DM류 tool만 필터링해
  STM에 기록.** `session_logger`가 이미 `tool.call_complete` 이벤트를
  받는다. `record_message`로 연결만 해주면 됨. 단, 현재 session_logger와
  memory_manager는 완전히 분리되어 있어 리팩터 필요.
- **(B3) Pipeline/invoke 래퍼 레벨에서 처리.**
  `_invoke_pipeline` 종료 시점에 "이번 턴에 호출된 DM tool의 content를
  assistant_dm 전 기록"을 한 줄로 수집. 가장 명시적.

가장 낮은 위험 + 가장 적은 파일 변경은 **(B2)의 작은 버전** — tool 내부에서
`_memory_manager`를 lazy import해 `record_message("assistant_dm", content)`
한 줄을 호출. 순환 import는 함수 레벨 import로 회피. VTuber가 SW에게 보낸
요청이 `assistant_dm`으로 STM에 남는다.

대칭성: Sub-Worker가 `send_direct_message_internal`로 답장하는 경우에도
같은 방식으로 기록된다. Sub-Worker 쪽 STM은 `_trigger_dm_response`가
주입한 `[SYSTEM] You received a direct message ...` 입력이 이미
`assistant_dm`으로 기록되므로(line 933/1123 → classifier § 2.2), 대화의
앞뒤가 모두 `assistant_dm` 라벨로 묶인다.

### 5.3. Bug C — 별도 PR 없음

§ 4 후반부 논거대로, Bug A 해결로 자연스럽게 닫힌다. 만약 후속 관측에서
"read_inbox로만 보고 응답한 턴의 기억이 휘발된다"는 현상이 재현되면 그때
별도 cycle로 연다.

## 6. 비-범위

- **LTM(record_execution) 변경 없음.** LTM은 이미 full turn을 저장하므로
  재방문 시 접근 가능. 본 cycle은 STM 층에만 집중한다.
- **도구 일반 STM 정책 개정 없음.** `web_search` 같은 tool을 STM에 기록
  할지 여부는 별도 설계 이슈. 본 cycle은 DM/inbox류만 다룸.
- **벡터/키워드 retrieval 개선 없음.** L0 recent-turns가 STM의 진실을
  그대로 반영한다는 전제 하에, STM만 올바르면 retrieval은 따라온다. L0
  자체에 추가 개선 여지는 있겠지만 이번 cycle의 범위는 아님.

## 7. 검증 기준 (smoke)

1. 새 VTuber 세션 + Sub-Worker 바인딩. VTuber에 "흥미로운 사실 하나
   찾아서 알려줘" 투입.
2. VTuber가 `send_direct_message_internal` 호출 후 응답("알아볼게") 반환.
3. 2분 뒤 `THINKING_TRIGGER:time_morning` 발화.
4. **기대:** VTuber가 "어제 부탁했던" / "아직 소식이 없다"라고 말하지
   않고, 2분 전 받은 Sub-Worker 답변을 **사실로 인용**한다.
5. STM transcript 파일 확인:
   - `role=assistant_dm` 턴 2개(VTuber→SW 요청, SW→VTuber 답변)
   - `role=assistant` 턴 2개 이상
   - `role=user` 턴에는 **사용자 원문만 들어 있음** (SUB_WORKER_RESULT 없음)
