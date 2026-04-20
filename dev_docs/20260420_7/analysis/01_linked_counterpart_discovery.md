# Analysis/01 — VTuber↔Sub-Worker 연결 발견 결함

## 증상 (2026-04-21 15:17 UTC 로그)

VTuber `b14d61f2-5da0-4107-9573-09f851df8cee`(ㅅㅁㅅㅁㅅㅇㄴㅇ)는 생성
직후 15:17:04에 자동으로 Sub-Worker `6e224bb4-0f79-4cb2-9d0b-
ec50ca8c8f55`(ㅅㅁㅅㅁㅅㅇㄴㅇ_worker)를 얻고 서로 링크되었다. 그러나
사용자 요청이 들어온 15:17:37 시점에 VTuber는:

1. `geny_session_create(session_name="Sub-Worker Agent",
   role="developer")`를 호출해 **새 세션** `5e2edaab-...` 생성
2. `geny_send_direct_message(target_session_id="5e2edaab...",
   content="test.txt 파일을 만들어주세요")` 호출
3. 진짜 Sub-Worker `6e224bb4`는 아무 일도 수행하지 않음

즉 VTuber는 이미 확보된 Sub-Worker를 **찾지 못했고**, 세션 이름이
"Sub-Worker Agent"인 것을 보고 "만들어야 할 것"으로 해석해 신규 생성했다.

## 현재 연결(linkage) 저장 구조

`backend/service/langgraph/agent_session_manager.py:580-665`

- VTuber 생성 시 `create_agent_session`은 내부에서 Sub-Worker도
  만들고 양쪽에 저장:
  - `agent._linked_session_id = worker_session_id` (VTuber 인스턴스)
  - `self._store.update(vtuber_id, {"linked_session_id": worker_id, ...})`
  - Worker 쪽도 `request.linked_session_id = vtuber_id`로 생성되어
    동일한 `_linked_session_id` 속성이 VTuber ID를 가리킴
- 프롬프트에 주입 (같은 파일 `275-287`, `653-664`):
  ```
  ## Sub-Worker Agent
  You have a Worker agent bound to you: session_id=`<worker_id>`.
  For complex tasks ... delegate to the Worker via the
  `geny_send_direct_message` tool with target_session_id=`<worker_id>`.
  ```

즉 **런타임 레벨**에선 양방향 링크가 이미 존재한다. 도구를 호출할 때
`_GenyToolAdapter.execute(input, context)`의 `context.session_id`를
통해 호출자(VTuber)의 세션 ID도 알 수 있고, 거기서
`AgentSession._linked_session_id`를 꺼내면 상대 ID는 **프롬프트를
거치지 않고** 얻어낼 수 있다.

## 왜 실패했는가 — 3가지 설계 결함이 겹친다

### (A) 진실의 원천이 두 곳으로 쪼개져 있다

- **코드 상의 진실**: `agent._linked_session_id`
- **LLM이 읽는 진실**: 시스템 프롬프트에 끼워 넣은 UUID 문자열

LLM은 두 번째만 본다. UUID를 토큰 단위로 분해해 `target_session_id`
인자에 정확히 복사해 넣어야 하는데, 36자 하이픈 문자열은 LLM이 약한
조합이다. 한 글자만 틀어져도 `_resolve_session`은 이름으로 해석을
재시도하고, 그 결과 *새 이름*으로 인식되거나 안 보이면
`geny_session_create`가 존재한다는 사실이 LLM에게 유혹이 된다.

### (B) VTuber 프리셋이 `geny_session_create`를 차단하지 않는다

`service/environment/templates.py:68` —

```python
_PLATFORM_TOOL_PREFIXES = ("geny_", "memory_", "knowledge_", "opsidian_")
```

접두사로만 걸러지기 때문에 `geny_session_create`도 VTuber 롤에
그대로 실려 나간다. 프롬프트는 "Sub-Worker는 이미 있다"고 말하지만
도구 목록은 "새 세션도 만들 수 있다"고 한다. 이 모순이 LLM에게
*만드는 쪽*을 선택할 구실을 준다 — 특히 프롬프트의 "## Sub-Worker
Agent" 헤더 문자열이 `geny_session_create(session_name="Sub-Worker
Agent")` 호출로 패턴 매칭되기 쉽다.

### (C) `geny_send_direct_message`의 입력 스키마가 실수를 허용한다

```python
def run(target_session_id: str, content: str,
        sender_session_id: str = "", sender_name: str = ""): ...
```

`target_session_id`가 LLM에게 **자유 입력 필드**로 노출된다. 이름도
받고 UUID도 받는 `_resolve_session`의 유연함이 오히려 독이 되어
"Sub-Worker Agent"라는 헤더 문자열까지 그럴듯한 입력으로 보이게
만든다. 스키마에서 선택지 자체를 제거하지 않는 한 이 경로는 계속
오분사(mis-delivery) 위험을 안는다.

## 바꿔야 할 것

단일 원칙: **연결된 상대(counterpart)에게 메시지를 보내는 일은 LLM의
추론 대상이 아니라 런타임이 결정해야 한다.**

구체적으로:

1. 새 내장 도구 `geny_message_counterpart(content: str)` — 입력에
   target을 받지 않는다. 어댑터가 `context.session_id`로 호출자를
   식별하고 `_linked_session_id`로 상대를 해석해 배달한다.
2. VTuber 롤의 기본 프롬프트는 이 도구 사용을 강제하는 문구로 교체.
   `geny_send_direct_message`는 *다른 팀원*(동료 에이전트) 커뮤니
   케이션 용도로 남겨두되, 링크된 상대에겐 새 도구만 쓰도록 명시한다.
3. `geny_session_create`는 VTuber 롤 기본에서 제외한다 — VTuber가
   새 세션을 만들 일은 운영상 존재하지 않는다. 필요하면 preset을
   커스터마이즈한 사용자가 opt-in 하도록.

(2)와 (3)은 플랜 `01`에서 구체화한다. 이 문서는 결함의 "형태"를
고정시키는 용도다.

## 비결함 확인 (건드리지 않는 범위)

- `AgentSession._linked_session_id` 저장/복구 로직 자체는 정상 — 로그
  상 양방향으로 저장·조회되고 있다. 건드릴 필요 없음.
- 채팅방 자동 생성, inbox 배달, `_trigger_dm_response`도 정상 —
  목적지 ID만 올바르면 현재 경로가 그대로 동작한다.
- `_GenyToolAdapter`의 `session_id` 주입(Cycle 6)도 그대로 유지 —
  새 도구가 이 메커니즘을 직접 활용한다.
