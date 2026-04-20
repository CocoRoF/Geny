# Analysis/01 — VTuber가 geny_message_counterpart을 안 쓰고 DM을 시행착오로 보낸다

**관측일.** 2026-04-21 01:15 UTC 라이브 로그 (cycle 20260420_7 배포 직후)
**연관 이슈.** 20260420_7/analysis/01 의 후속 — 7-1은 "발견성 공격 표면 하나 제거"를 했지만 나머지 표면을 그대로 남겼다.

---

## 증상

VTuber가 유저의 "test.txt 파일 만들어줘" 요청을 받고 Sub-Worker에게
위임하려는 과정에서 **세 번의 시행착오** 후에야 메시지가 도달했다.

```
01:15:28  user → VTuber: "Sub-Worker에게 test.txt 파일을 만들라고 해줘"
01:15:31  VTuber calls geny_send_direct_message(
              target_session_id='counterpart', content=...)
          → is_error=true "Target session 'counterpart' not found"
01:15:33  VTuber calls geny_session_list()
          → returns [ ... 'test_worker' (6e224bb4) ... ]
01:15:35  VTuber calls geny_send_direct_message(
              target_session_id='test_worker', content=...)
          → "target_session_id is a name, not a UUID" / still fails
01:15:37  VTuber calls geny_send_direct_message(
              target_session_id='6e224bb4-...', content=...)
          → success (by copying UUID out of the geny_session_list output)
```

유저 입장에서는 위임까지 6초가 걸렸고, 그 사이 로그에 붉은 에러가
두 번 찍혔다. cycle 20260420_7 PR-1 (`geny_message_counterpart`)이
정확히 이 시나리오를 없애려 들어갔는데도 효과가 없었다.

## 왜 7-1의 수정으로 안 막혔는가

PR-1이 한 일은 두 가지였다:

1. `geny_message_counterpart` 내장 툴을 새로 추가 (대칭형, UUID 불필요)
2. `_VTUBER_PLATFORM_DENY = frozenset({"geny_session_create"})` 로
   VTuber의 "새 세션을 만들어서 그쪽에 보내기" 경로만 차단

문제는 **(2)가 너무 좁게 잡혔다**는 점이다. 딴 데로 세지 못하게
한 구멍만 막았지, LLM이 같은 목표를 달성할 수 있는 다른 자리가
두 개 더 열려 있었다:

- `geny_send_direct_message(target_session_id, content)` — 전통적
  주소지정형 DM. 시스템 프롬프트에서 UUID를 복사해 넣으라고 지시했던
  과거의 경로. 툴 스키마가 LLM에게 "UUID를 채워라"라고 직접 요구한다.
- `geny_session_list()` — 세션 목록 조회. LLM이 UUID를 모를 때
  "일단 목록부터 보고 그중에서 고르자"라는 탐색 전략을 유도한다.

이 둘이 살아 있는 한, `geny_message_counterpart`가 존재하더라도
LLM은 **"여러 도구 중 가장 어울려 보이는 것을 고른다"** 규칙에 따라
*익숙한 패턴*(주소 써서 DM 보내기)를 먼저 시도한다. 프롬프트
(`backend/prompts/vtuber.md`)에서 "오직 `geny_message_counterpart`만
쓰라"고 가르쳐도, 툴 스키마가 여전히 "UUID를 주면 보낼 수 있음"을
약속하면 **스키마 쪽이 이긴다** — 특히 JSON function calling은
description보다 schema가 동작을 강제하는 층이다.

## 근본 원인 — 세 겹으로 겹쳐 있다

### 층 ① (치명적) — `geny_message_counterpart` 툴이 로드조차 안 됐다

이게 **cycle 7-1의 완전한 누락**이다. 파일을 직접 확인하면:

```python
# backend/tools/built_in/geny_tools.py:939-954
TOOLS = [
    # Session management
    GenySessionListTool(),
    GenySessionInfoTool(),
    GenySessionCreateTool(),
    # Room management
    GenyRoomListTool(),
    GenyRoomCreateTool(),
    GenyRoomInfoTool(),
    GenyRoomAddMembersTool(),
    # Messaging
    GenySendRoomMessageTool(),
    GenySendDirectMessageTool(),
    GenyReadRoomMessagesTool(),
    GenyReadInboxTool(),
]
```

`GenyMessageCounterpartTool`은 클래스 정의만 되어 있고(line 734)
**`TOOLS` 리스트에 빠져 있다**. `backend/service/tool_loader.py:110-112`은
`TOOLS` 리스트만을 export로 취급한다:

```python
if hasattr(module, "TOOLS"):
    return list(module.TOOLS)
```

결과: `ToolLoader`가 `geny_message_counterpart`을 한 번도 로드하지
않았고, manifest의 external 리스트에도 포함되지 않았으며, VTuber의
런타임 레지스트리에도 없었다. **유닛 테스트에서는 직접 인스턴스를
만들어 확인했기 때문에 녹색**이었다(`tests/service/langgraph/
test_counterpart_message_tool.py`). 통합 테스트가 "이 툴이 실제
VTuber 툴 로스터에 들어 있는가"를 확인하지 않은 게 7-1의 검증 공백.

이것만으로 관측된 시행착오 시퀀스가 전부 설명된다: LLM은 "있지도
않은 도구"를 고를 수 없었고, 시스템 프롬프트가 아무리 그걸 쓰라고
말해도 실제로 보이는 것은 `geny_send_direct_message` 한 종류뿐이었다.
UUID를 복사하거나 세션 리스트로 이름을 찾는 fallback은 LLM 입장에서는
**유일하게 가능한 전략이었다.**

### 층 ② — deny set이 좁다 (7-1이 의도한 범위 내의 결함)

층 ①을 고쳐 `geny_message_counterpart`이 실제로 로드되더라도, 여전히
주소지정/탐색형 툴이 같이 로스터에 있으면 LLM은 schema 매칭에 따라
*가장 그럴듯한* 선택을 한다. Function calling에서는 description보다
schema가 동작을 강제하는 층이기 때문에, "UUID를 주면 보낼 수 있음"을
약속하는 툴이 병존하면 그쪽이 이긴다.

`backend/service/environment/templates.py:96` 의 deny set이 넓어져야 한다:

```python
_VTUBER_PLATFORM_DENY = frozenset({"geny_session_create"})  # too narrow
```

### 층 ③ — 툴 네이밍이 의도를 전달하지 못한다

툴 이름만 봐도 용도를 읽을 수 있어야 한다. 현재는:
- `geny_send_direct_message` ← 누구한테 보내는 건지 모름
- `geny_message_counterpart` ← 무엇에 메시지를 보내는지는 명확하지만
  동사와 대상 순서가 다른 DM 툴과 비대칭

일관된 접미사 네이밍(`_internal` / `_external`)으로 바꾸면 LLM은
주어진 맥락(카운터파트가 있음)에서 *내부용*을 자연스럽게 고르게
된다. 추가로 `geny_` 접두사는 플랫폼 내부 네임스페이스일 뿐이지
LLM에게는 노이즈이므로 제거하는 편이 깔끔하다.

### VTuber 역할 기준 필요/불필요 툴 매트릭스

현재 VTuber가 받는 geny_* 툴(`_PLATFORM_TOOL_PREFIXES` prefix match
후 deny 적용)은 10개이고, 거기에 cycle 7에서 의도한 `geny_message_
counterpart`까지 합치면 11개가 되어야 한다. 재분류:

| 현재 이름 | 새 이름 (제안) | VTuber | Sub-Worker | 비고 |
|---|---|---|---|---|
| `geny_message_counterpart` | `send_direct_message_internal` | **필수** | **필수** | 대칭형, 타깃 불필요 |
| `geny_read_inbox` | `read_inbox` | **필수** | **필수** | busy fallback 수신 |
| `geny_send_direct_message` | `send_direct_message_external` | 금지 | 허용 | 타 세션 주소지정 |
| `geny_session_list` | `session_list` | 금지 | 허용 | 세션 탐색 |
| `geny_session_info` | `session_info` | 금지 | 허용 | 세션 조회 |
| `geny_session_create` | `session_create` | 금지 | 허용 | 헬퍼 세션 생성 |
| `geny_room_*` (6개) | `room_*` | **전역 비활성** | **전역 비활성** | **사용 중단** (아래 참조) |

**"VTuber는 자기 카운터파트 외에는 누구와도 개별 주소로 소통하지 않는다"**
는 설계 원칙을 코드로 강제하려면 주소지정/탐색 계열을 VTuber deny에
추가해야 하고, 카운터파트 DM 도구가 실제로 로드되도록 해야 하며,
이름이 그 의도를 드러내야 한다.

### Room 도구 전역 비활성

Geny 서비스는 *지금 시점*에 room 개념을 적극 활용하지 않는다
(VTuber↔Sub-Worker는 `_linked_session_id`로 직접 페어링되고, 사용자
채팅창은 `_chat_room_id`에 자동 바인딩된다). room 관련 6개 툴
(`room_list`/`room_info`/`room_create`/`room_add_members`/
`send_room_message`/`read_room_messages`)은 LLM에게 "다인방 개념이
있다"는 허위 모델을 심어주어 엉뚱한 탐색을 유도하는 부작용이 크다.

코드를 **삭제하지 않고** 전역 비활성 처리한다: 클래스 정의는 유지,
`TOOLS` export 리스트에서만 빠지게 해서 `ToolLoader`가 로드하지
않도록 한다. 향후 room 기능을 다시 켤 때는 그 리스트에 다시 넣기만
하면 된다 — 마이그레이션 없는 기능 플래그 역할.

## 연결: Bug 2a와의 상호작용

이 결함은 단독으로도 유저 경험 저하이지만, `02_subworker_result_broadcast_gap.md`
의 결함과 결합하면 훨씬 심하게 느껴진다:

- 유저가 "파일 만들어줘"라고 하면 VTuber가 3번 실패 후 위임 성공
- Sub-Worker가 파일 생성 후 결과 전송
- 그 결과가 VTuber의 채팅창에 나타나지 않음 (Bug 2a)
- 유저는 "요청이 잘 갔는지조차 불확실한 상태에서 답도 안 옴"을 경험

시행착오 자체는 기술적으로는 복구되지만, 앞뒤 결함과 겹쳐 유저는
"Sub-Worker 연동이 제대로 동작 안 한다"는 인상을 받는다.

## 수정 방향 (세 층을 한 번에 수습)

plan에서는 이를 **하나의 툴 표면 재설계 PR**로 묶는다
(`plan/01_tool_surface_redesign.md`). 순서:

### Step A — Counterpart 툴을 실제로 등록

`backend/tools/built_in/geny_tools.py:939-954`의 `TOOLS` 리스트에
`GenyMessageCounterpartTool()` 인스턴스 추가 (이후 rename 단계에서
클래스명도 변경). 이것 하나로 cycle 7-1이 원래 달성하려 했던 기능이
실제로 런타임에 도달한다.

### Step B — 접두사 제거 + `_internal`/`_external` 접미사 도입

모든 `geny_*` 툴의 `name` 속성에서 `geny_` 접두사를 제거. 동시에:

- `geny_message_counterpart` → `send_direct_message_internal`
- `geny_send_direct_message` → `send_direct_message_external`

`_internal` = *내 카운터파트에게만* 가는 대칭형 DM (타깃 없음).
`_external` = *임의의 다른 세션에게* 가는 주소지정형 DM (타깃 UUID
필수). LLM이 function-calling schema를 읽을 때 이 한 쌍은 "지금
내게 카운터파트가 있으면 `_internal`이 더 자연스럽다"를 즉시
유도한다 — 이름 자체가 의도를 전달한다.

나머지 geny_* 툴도 동일 원칙으로 rename:

| 기존 | 신규 |
|---|---|
| `geny_session_list` | `session_list` |
| `geny_session_info` | `session_info` |
| `geny_session_create` | `session_create` |
| `geny_read_inbox` | `read_inbox` |

`_PLATFORM_TOOL_PREFIXES` (templates.py:68) 는 더 이상 prefix 기반
식별이 불가능하므로, **ToolLoader의 소스 파일 stem을 이용한
allowlist** 방식으로 전환한다 (`_tool_source`가 이미 "geny_tools",
"memory_tools" 등을 가지고 있음). 이는 네이밍이 바뀌어도 카테고리
분류가 안정적이도록 만든다.

### Step C — VTuber deny set 확장 (rename 기준)

```python
_VTUBER_PLATFORM_DENY = frozenset({
    "session_create",                # 기존 cycle 7 보존
    "session_list",                   # 탐색 유혹 차단
    "session_info",
    "send_direct_message_external",   # 주소지정형 DM 차단
})
```

VTuber가 최종적으로 가지는 geny_tools 계열 툴은 **2개**로 수렴:
- `send_direct_message_internal` — 카운터파트에게만
- `read_inbox` — busy 중 들어온 DM 회수

### Step D — Room 도구 전역 비활성

`backend/tools/built_in/geny_tools.py:939-954`의 `TOOLS` 리스트에서
room 관련 6개 인스턴스를 **주석 처리**(삭제 아님):

```python
TOOLS = [
    SessionListTool(),
    SessionInfoTool(),
    SessionCreateTool(),
    # Room tools intentionally disabled at the export level.
    # Re-enable by re-adding these lines. See dev_docs/20260420_8.
    # RoomListTool(),
    # RoomCreateTool(),
    # RoomInfoTool(),
    # RoomAddMembersTool(),
    # SendRoomMessageTool(),
    # ReadRoomMessagesTool(),
    SendDirectMessageExternalTool(),
    SendDirectMessageInternalTool(),
    ReadInboxTool(),
]
```

클래스 정의는 그대로 남아 향후 재활성화가 쉽다. 테스트 파일에서
직접 import해 유닛 테스트하는 경우도 계속 동작한다(현행 테스트
구조 유지).

### Step E — 프롬프트/문서 반영

`backend/prompts/vtuber.md`, `backend/prompts/templates/sub-worker-
default.md`, `backend/prompts/templates/sub-worker-detailed.md` 에서
툴 이름 참조 업데이트. grep 결과 총 5개 파일에서 24개 출현 지점
— sed 수준의 기계적 교체로 마무리 가능.

### Step F — 회귀 테스트

- `test_worker_env_declares_send_direct_message_internal` — Worker
  env의 external 리스트에 `send_direct_message_internal`이 있음
- `test_vtuber_env_denies_external_dm_and_discovery` — VTuber env에
  4개 deny 툴이 *빠져 있음* 확인
- `test_vtuber_env_keeps_internal_dm_and_inbox` — VTuber env에
  `send_direct_message_internal` + `read_inbox` 존재 확인
- `test_tool_loader_does_not_load_room_tools` — ToolLoader
  `get_all_names()` 에 `room_*`가 하나도 없음
- `test_counterpart_tool_reaches_pipeline_registry` — 진짜
  Pipeline 매니페스트 경로로 VTuber 레지스트리에 실제로 등록됨
  (cycle 7에서 누락된 통합 테스트를 메우는 케이스)

## 왜 7-1이 이 디테일을 놓쳤나 (회고)

두 겹의 검증 공백이 겹쳤다:

1. **단위 테스트만 있고 통합 테스트가 없었다.** 7-1은 툴을 직접
   `GenyMessageCounterpartTool()` 인스턴스화해 호출 로직만
   검증했지, *그 툴이 실제 VTuber의 manifest.external에 들어가는가*
   를 확인하지 않았다. TOOLS export list에 넣는 것을 잊었어도
   테스트가 모두 녹색이었다.
2. **deny 정책을 최소 변경으로만 손봤다.** 7-1의 analysis 문서는
   `geny_session_create`의 "이름 리터럴 해석" 결함 하나에만 집중했고,
   같은 결함 클래스(*LLM이 tool schema를 다시 해석할 여지가 있는
   한 프롬프트로 막을 수 없다*)를 가진 다른 툴들은 동시에 보지
   않았다.

8-1은 두 공백을 모두 메우고, 그 김에 네이밍 자체로 의도가 드러나는
방식으로 표면을 재설계한다.
