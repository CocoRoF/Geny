# Analysis/02 — Sub-Worker 결과가 VTuber 채팅에 안 뜨고, 기억에도 안 남는다

**관측일.** 2026-04-21 01:15~01:17 UTC 라이브 로그
**연관 이슈.** cycle 20260420_7 PR-B가 Sub-Worker의 `Write` 능력은
확보했으나, *Sub-Worker가 VTuber에게 결과를 돌려준 뒤 그 결과를
유저에게 노출/기억하는 경로*는 손대지 않았다.

---

## 증상

Sub-Worker가 test.txt 생성에 성공한 후 VTuber에게 `[SUB_WORKER_RESULT]`
태그 메시지를 보냈다. 이 경로는 두 층에서 모두 실패했다:

### (a) 유저에게 전달되지 않음

```
01:15:43  Sub-Worker(6e224bb4) Write(test.txt) 성공
01:15:44  _notify_linked_vtuber: execute_command(b14d61f2,
             "[SUB_WORKER_RESULT] Task completed successfully. ...")
01:15:47  VTuber pipeline.complete: output_len=164
             "와! Sub-Worker가 작업을 완료했네요!..."
01:15:47  (여기서 끝. chat room b14d61f2-chat 에는 아무 메시지도
          add 되지 않음. SSE notify도 안 감.)
```

VTuber는 LLM 응답까지 멀쩡히 생성했지만, **그 응답이 유저가 보는
VTuber chat panel에는 나타나지 않는다**. 유저 관점: "Sub-Worker에게
시킨 일이 어떻게 됐는지 답이 없네."

### (b) VTuber 자신도 응답을 기억하지 못함

2분 뒤 `THINKING_TRIGGER` (continued_idle) 가 자동 발동:

```
01:17:37  thinking_trigger → VTuber:
             "[THINKING_TRIGGER:continued_idle] ...
              여전히 조용하다. 내 인식이 아까 눈에 띄었던 것으로..."
01:17:41  VTuber 응답:
             "Sub-Worker에게 메시지를 보냈지만 아직 답장이
              없어요. 혹시 잘못 전달됐을까요?..."
```

유저가 "방금 Sub-Worker가 완료했다고 답했잖아"라고 치면 VTuber는
당황하며 "그런 적 없는데요?"를 반복한다. **VTuber 자체가 SUB_WORKER_
RESULT 턴을 경험한 기억이 없는 것처럼 행동한다.**

## 두 결함은 근원이 다르다

흔히 "같은 버그로 보일" 수 있지만, (a)와 (b)는 **별개의 독립적인
구조 결함**이며 각각의 고치는 층이 다르다.

---

## Bug 2a — `_notify_linked_vtuber`가 chat room broadcast를 안 한다

### 코드 위치

`backend/service/execution/agent_executor.py:202-246` `_trigger_vtuber`
내부:

```python
async def _trigger_vtuber() -> None:
    try:
        await execute_command(linked_id, content)
        # ↑ VTuber가 LLM 응답을 만들어 return 하지만,
        #   그 반환값(result.output)은 바닥에 버려진다.
    except AlreadyExecutingError:
        ...  # inbox 폴백
```

`execute_command(linked_id, content)`는 VTuber pipeline을 돌려
`ExecutionResult`를 반환하지만, 이 반환값을 **채팅방에 쓰는 코드가
어디에도 없다**.

### 레퍼런스 구현은 이미 존재한다

`backend/service/vtuber/thinking_trigger.py:717-764` 에 동일한 상황
(내부 자동 트리거의 결과를 유저에게 보여주기)을 처리하는
`_save_to_chat_room`이 멀쩡히 구현되어 있다:

```python
def _save_to_chat_room(self, session_id, result):
    agent = get_agent_session_manager().get_agent(session_id)
    chat_room_id = getattr(agent, '_chat_room_id', None)
    ...
    msg = store.add_message(chat_room_id, {
        "type": "agent",
        "content": result.output.strip(),
        "session_id": session_id,
        ...
    })
    _notify_room(chat_room_id)
```

THINKING_TRIGGER은 이 함수로 VTuber의 내면 독백을 유저 채팅에
올려주는데, Sub-Worker → VTuber 자동 전달은 같은 패턴을 쓰지 않는다.
*`_trigger_vtuber`의 try 블록에서 `await execute_command(...)`의
반환값을 받아 그대로 `_save_to_chat_room` 동등 로직에 넘겨주면 끝*인데,
그 한 덩이가 비어 있다.

### 왜 이렇게 됐나 (추정)

`_notify_linked_vtuber`는 "VTuber한테 신호를 던져서 요약만 시키면
된다"는 관점으로 만들어졌다. 즉 *트리거 송신 쪽* 책임으로 설계된
함수이고, *응답을 어떻게 쓸지*는 VTuber 쪽이 알아서 하리라 가정했다.
그런데 `agent_session`의 파이프라인 실행 경로는 **유저가 직접 친
메시지에 대해서만** chat room에 반영한다
(`controller/chat_controller.py:660-700` — `_broadcast_user_message`
→ pipeline 실행 → 결과를 `store.add_message`로 올림). 자동 트리거로
실행된 턴은 이 경로를 거치지 않아서 chat room이 갱신되지 않는다.
THINKING_TRIGGER은 이 갭을 알고 `_save_to_chat_room`을 직접 붙여
메웠고, `_notify_linked_vtuber`는 같은 갭에 같은 수리를 안 했다.

### 관측된 2차 효과

Bug 2b가 이 결함의 파급이다: chat room에 메시지가 없으면 향후 턴의
*채팅 히스토리 기반 맥락*이 "SUB_WORKER_RESULT는 없었던 일"로 보인다.
(단, 뒤에서 설명하듯 VTuber가 턴 간 맥락을 chat room에서 가져오지도
않기 때문에 이건 2b의 원인이 되진 않는다. 하지만 **유저와 디버거
양쪽의 가시성**에는 치명적이다.)

### 수정 방향

`_trigger_vtuber` 을 다음처럼 확장:

```python
async def _trigger_vtuber() -> None:
    try:
        result = await execute_command(linked_id, content)
    except AlreadyExecutingError:
        ...  # 기존 inbox 폴백 유지
        return
    except (AgentNotFoundError, AgentNotAliveError) as exc:
        ...
        return

    # Thinking-trigger 패턴을 미러링: VTuber가 생성한 답을
    # 자기 chat room에 올리고 SSE notify 를 쏜다.
    _save_subworker_reply_to_chat_room(linked_id, result)
```

`_save_subworker_reply_to_chat_room`은 `thinking_trigger.
_save_to_chat_room`과 거의 동일 — 다만 type/source 라벨만
`"sub_worker_result"` 같은 것으로 살짝 다르게 달아 프런트에서
구분 가능하도록. 공유화가 자연스러워 보이지만 두 호출처의
스레딩 / 예외 처리 취향이 달라 **일단은 복붙형 헬퍼로 두고**
리팩터는 다음 사이클로 미루는 게 PR 범위상 깔끔하다.

---

## Bug 2b — VTuber가 이전 턴의 대화를 "기억"하지 못한다

### 기계적 원인

VTuber는 2분 후 THINKING_TRIGGER 턴에서 "아직 답이 안 왔다"라고
답한다. 이는 **LLM이 실제로 이전 턴의 입출력을 컨텍스트로 받지
못한 채 응답한 결과**다. 메모리 파이프라인을 순서대로 따라가면:

1. `agent_session._invoke_pipeline`은 턴마다 *fresh*
   `PipelineState(session_id=self._session_id)`을 생성한다
   (line 901). 즉, 파이프라인 레벨에서는 **각 invoke가 완전
   독립**이다. 턴 간 대화 상태는 메모리 리트리버가 주입하는
   `MemoryContextBlock`을 통해서만 들어온다.
2. `record_message("user", input_text)`은 매 invoke 시작 시
   STM transcript에 **user 메시지만** 기록한다
   (`memory/manager.py:200-220`). **assistant의 응답은 STM에
   전혀 기록되지 않는다** — grep 결과 `record_message("assistant", ...)`
   를 호출하는 프로덕션 경로가 backend 내에 존재하지 않는다
   (docs 파일에서만 예시로 언급됨: `backend/docs/AUTONOMOUS_GRAPH_
   DEEP_DIVE.md:598`, 실제 코드 미호출).
3. `record_execution`은 실행 완료 후 `memory/YYYY-MM-DD.md` 에
   구조화된 실행 요약(입력 + 출력 + duration)을 쓴다. 이건 제대로
   동작하고 로그에도 `record_execution: #2` 로 확인됐다.
4. 다음 턴에서 `GenyMemoryRetriever.retrieve(query, state)` 가
   5층으로 메모리를 주입한다 (`geny-executor/src/geny_executor/memory/
   retriever.py`):
   - **L1 session_summary** — `stm.get_summary()`. 이 summary는
     *주기적 reflection*에 의해서만 갱신되는 파일/DB 필드이지
     턴마다 자동으로 업데이트되지 않는다. 이 세션은 방금 생성된
     세션이므로 summary가 **비어 있다.**
   - **L2 MEMORY.md** — 영구성 노트. 이번 대화와 관련 없음.
   - **L3 FAISS vector search** — 쿼리가 `[THINKING_TRIGGER:
     continued_idle] ... 여전히 조용하다 ...` 이다. 이전 턴의
     input이었던 `[SUB_WORKER_RESULT] Task completed successfully.
     {실제 결과 텍스트}` 와의 의미 유사도는 **매우 낮다** —
     자동 트리거 문구는 "idle/silent" 의미장에 있고 SUB_WORKER_
     RESULT는 "completion/success" 의미장에 있다. Top-k 검색에서
     밀려난다.
   - **L4 keyword search** — `_mgr.search(query, ...)` — 쿼리 단어
     ("여전히", "조용", "인식", "아까") 중 어느 것도 이전 턴의
     기록에 매치되지 않는다. 태그 기반 boost도 시트리거 쪽 태그
     (`["execution", "success", ...]`)와 교집합이 없다.
   - **L5 backlink / L6 curated** — 연결 고리 없음.
5. 결과적으로 메모리 리트리버는 **이전 턴에 대한 어떤 조각도
   주입하지 않는다**. VTuber의 LLM은 시스템 프롬프트 + 오늘 날짜
   + (빈) 메모리 + 현재 트리거 프롬프트만 보고 응답한다.
6. 시스템 프롬프트는 "너에게는 연결된 Sub-Worker가 있다"까지는
   알려주지만, *지금 방금 무슨 일이 있었는지*는 알려주지 않는다.
   LLM은 주어진 맥락 안에서 *가장 그럴듯한* 이야기를 만든다 →
   "Sub-Worker에게 보냈는데 답이 아직 안 와서 걱정되네요" 서사가
   자연스럽게 뽑혀 나온다. **LLM이 틀린 게 아니라, 컨텍스트가
   진실을 담지 않은 것이다.**

### 즉, 결함은 두 겹

**결함 2b-α — assistant 응답이 STM에 기록되지 않는다.**
`_invoke_pipeline` / `_astream_pipeline` 두 경로 모두
`record_message("user", ...)` 만 호출하고, 종료 후 `record_execution`
만 호출한다. STM transcript에는 user side만 쌓인다. 레퍼런스 문서
(`backend/docs/AUTONOMOUS_GRAPH_DEEP_DIVE.md:598`)는 "assistant도
기록해야 한다"고 되어 있지만 실제 코드는 그러지 않는다.

이 결함의 영향은 메모리 리트리버가 어떤 층을 쓰든 동일하다: transcript
기반 리콜은 영원히 *절반짜리 대화*만 본다. assistant가 뭐라고
답했는지 모르면 "나는 방금 사용자에게 X를 약속했다" 같은 사실을
보존할 수 없다.

**결함 2b-β — 자동 트리거 턴은 의미/키워드 검색 양쪽 모두에서
이전 턴을 놓친다.**
LTM `record_execution` 엔트리는 존재하지만, THINKING_TRIGGER의
쿼리 문구는 실행 요약의 어휘/태그와 맞닿는 지점이 없다. 즉 *턴간
스토리 연속성은 의미적/키워드적 유사도로는 확보되지 않는 구조*다.

둘 중 *2b-α를 고치는 것이 수익이 훨씬 크다*. α가 고쳐지면:
- STM session_summary 재생성 시 assistant 응답이 함께 요약된다
- 키워드/벡터 검색 대상이 실제로 두 배로 늘어난다
- 무엇보다 *가장 최근 몇 턴*을 tail-recall하는 간단한 정책
  (예: STM의 최근 N개 message를 무조건 주입)이 의미 있는 양의
  맥락을 공급할 수 있게 된다

β는 α의 근본적 부산물이므로, α를 고친 뒤 "최근 K턴은 의미 검색
무관하게 무조건 주입"하는 L0 계층을 L1 앞에 삽입하는 식의 보강
(이것도 `GenyMemoryRetriever`에 `tail_turns=K` 옵션을 추가하는
수준)으로 마무리할 수 있다.

### 수정 방향

**Step 1 (필수)**: `_invoke_pipeline` / `_astream_pipeline` 양쪽에
`record_message("assistant", accumulated_output)` 호출 추가
(`record_execution` 바로 앞). assistant 응답이 빈 문자열이면 스킵.
이 한 줄이 α를 닫는다.

**Step 2 (보강)**: `GenyMemoryRetriever`에 L0 계층 신설 —
`_load_recent_turns(chunks, state, budget, tail=6)` 같은 형태로
STM transcript의 마지막 N 메시지를 무조건 주입. 이 층이 트리거
기반 리콜이 어휘 매칭 없이도 직전 맥락을 확보하도록 보장한다.
`backend/service/memory/short_term.py`에는 이미 `get_recent(n)`
류의 메서드가 있음 (line 330 주변).

**Step 3 (옵션)**: Sub-Worker → VTuber 자동 메시지에 명시적 tag
(`[SUB_WORKER_RESULT]`)가 이미 있으므로, `GenyMemoryRetriever`의
키워드 검색에 "카운터파트 이벤트" 부스트를 추가해 idle 트리거
문구가 들어올 때 `[SUB_WORKER_RESULT]` / `[SUB_WORKER_PROGRESS]`
를 포함한 최근 턴을 우선 리콜하게 하기. 하지만 Step 1+2만으로도
관측된 증상은 충분히 해소된다 — Step 3은 cycle 9 이후 후속.

---

## 두 결함의 관계 요약

| | 층 | 고치는 파일 | 결과 |
|---|---|---|---|
| **2a** | UI 브로드캐스트 | `agent_executor.py` | 유저가 VTuber의 응답을 본다 |
| **2b-α** | 메모리 기록 | `agent_session.py` | 이후 턴에서 자기 응답을 기억한다 |
| **2b-β** | 메모리 리트리브 정책 | `retriever.py` (executor) | 트리거 턴에서도 최근 맥락이 주입된다 |

**2a와 2b는 독립적으로 고쳐진다**는 점이 핵심이다. 2a만 고치면
유저는 보지만 VTuber는 다음 턴에 여전히 잊는다. 2b만 고치면 VTuber는
기억하지만 유저 화면에는 안 뜬다. Cycle 8의 스쳐야 할 기준은
*둘 다* 붙는 것이다.

## 8-1과의 상호작용 (툴 재설계 후)

`send_direct_message_internal` (rename 후 이름)이 제대로 로드되면,
Sub-Worker → VTuber 경로의 송신 쪽은 훨씬 깔끔해진다. 하지만
**수신 쪽 후처리 (Bug 2a)**와 **메모리 연속성 (Bug 2b)**은 툴
네이밍과 무관한 별도 결함이므로 8-1과 독립적으로 고쳐야 한다.

메시지 내용에 담긴 `[SUB_WORKER_RESULT]` 태그는 rename과 관계없이
유지한다 — 이 태그는 VTuber가 자기 LLM 프롬프트 안에서 사용하는
semantic marker이지 툴 이름이 아니다.

## Cycle 20260420_7과의 관계

7-B는 "Sub-Worker가 파일을 만들 수 있게 한다"만 해결했다. **만든
뒤 그 사실이 유저와 VTuber 자신에게 전달되는 경로**는 테스트
체크리스트에 없었다. 파일이 실제로 생겼는지만 smoke로 확인했지,
유저 UI가 반영하는지는 보지 않았다. 이 누락이 8-2의 두 결함을
잠복시켰다.
