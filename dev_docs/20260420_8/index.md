# Cycle 20260420_8 — VTuber↔Sub-Worker 후처리 3종 세트 (도구 수렴 + 결과 브로드캐스트 + 턴 기억)

**상태.** Planning — 분석 완료, plan 3편 작성 완료. PR 구현 대기.
**트리거.** 2026-04-21 01:15~01:17 UTC 라이브 로그 — cycle 20260420_7
(counterpart 툴 + 파일 쓰기) 배포 직후에도 3가지 결함이 살아 있음이
확인됨.

## 문제 요약

cycle 7이 "Sub-Worker가 파일을 만들 수 있게" 수리를 끝냈지만, 그
주변의 사용자 경험 회로 3곳에 독립적 결함이 남아 있었다:

```
01:15:28  user: "test.txt 만들어줘"
01:15:31  VTuber: geny_send_direct_message('counterpart', ...) → 실패  ← Bug 1
01:15:33  VTuber: geny_session_list() → 탐색
01:15:35  VTuber: geny_send_direct_message('test_worker', ...) → 실패
01:15:37  VTuber: geny_send_direct_message('6e224bb4-...', ...) → 성공
01:15:43  Sub-Worker: Write(test.txt) 성공
01:15:44  _notify_linked_vtuber → VTuber execute_command(...)
01:15:47  VTuber 응답 "와! Sub-Worker가..." 생성
          ← 채팅방에 안 올라감                                        ← Bug 2a
01:17:37  THINKING_TRIGGER: VTuber "아직 답이 없어요..."
          ← 방금 받은 응답을 기억하지 못함                            ← Bug 2b
```

세 결함 모두 cycle 7 PR들과 같은 층에 붙어 있지만 **고치는 파일도,
고치는 층도 서로 다르다.**

1. **Bug 1** — VTuber의 `_VTUBER_PLATFORM_DENY`가 너무 좁아서
   `geny_send_direct_message` / `geny_session_list` 등 주소지정·탐색
   계열이 그대로 남아 있다. LLM이 익숙한 schema를 먼저 시도해
   `geny_message_counterpart`을 건너뛴다. (→ analysis/01)
2. **Bug 2a** — `_notify_linked_vtuber._trigger_vtuber`가 VTuber
   응답을 chat room에 broadcast하지 않는다. `thinking_trigger.
   _save_to_chat_room` 패턴이 이미 있는데 여기만 그 패턴을
   미러링하지 못했다. (→ analysis/02 § Bug 2a)
3. **Bug 2b** — `_invoke_pipeline`이 assistant 응답을 STM에 전혀
   기록하지 않는다. 메모리 리트리버가 의미/키워드 매칭에만 의존하는
   구조라 idle 트리거 쿼리가 `[SUB_WORKER_RESULT]` 턴을 못 찾는다.
   결과: VTuber는 *방금 한 자기 응답*을 기억 못 하는 것처럼 행동.
   (→ analysis/02 § Bug 2b)

## 폴더 구조

```
20260420_8/
├── index.md                                   — 본 파일
├── analysis/
│   ├── 01_vtuber_counterpart_fallback.md      — Bug 1 분석 (3층)
│   └── 02_subworker_result_broadcast_gap.md   — Bug 2a + 2b 분석
├── plan/
│   ├── 01_tool_surface_redesign.md            — Bug 1: rename + export + deny + room 비활성
│   ├── 02_subworker_result_broadcast.md       — Bug 2a
│   └── 03_turn_memory_continuity.md           — Bug 2b-α + 2b-β
└── progress/
    └── (pending — PR 머지 후 작성)
```

## 분석 단계의 핵심 발견

1. **Cycle 7-1은 절반만 배포됐다.** `GenyMessageCounterpartTool`은
   클래스 정의/단위 테스트만 있고 `TOOLS` export 리스트에 빠져
   있어 `ToolLoader`가 로드하지 않았다 (`tools/built_in/
   geny_tools.py:939-954`). VTuber가 `geny_message_counterpart`을
   "선택하지 않은" 것이 아니라 **가지고 있지 않았다**. 이게 Bug 1의
   가장 근원적인 층.
2. 그 위에 deny set 부족(층 ②) + 네이밍이 의도를 전달하지 못함
   (층 ③)이 겹쳐 있다.
3. 유저가 제안한 방향은 이 세 층을 **한 번에 해결**한다: 누락
   등록 + deny 확장 + `_internal`/`_external` 접미사 도입 +
   `geny_` 접두사 제거 + room 계열 전역 비활성.

## 수정 방향 (요약 — plan에서 상세화)

| 대상 | 파일 | 핵심 변경 | 규모 |
|---|---|---|---|
| **Tool surface** | `tools/built_in/geny_tools.py`, `service/environment/templates.py`, `service/tool_loader.py`, `prompts/*` | `TOOLS` export에 counterpart 추가 + 전면 rename (`geny_` 제거, `_internal`/`_external` 접미사) + room 툴 주석 비활성 + VTuber deny 확장 + 프롬프트 참조 교체 + category allowlist로 식별 | 큼 |
| **2a** | `service/execution/agent_executor.py` | `_trigger_vtuber`에서 결과를 `_save_to_chat_room` 동등 로직으로 브로드캐스트 | 중간 |
| **2b-α** | `service/langgraph/agent_session.py` | `record_message("assistant", ...)` 호출 추가 (두 경로) | 작음 |
| **2b-β** | geny-executor `memory/retriever.py` | L0 `_load_recent_turns(tail=6)` 계층 신설 | 중간 |

자연스러운 plan/PR 분할은:

- **plan/01_tool_surface_redesign.md** (Bug 1 전체)
  - PR-1 (Geny): 내장 툴 rename + `TOOLS` export에 counterpart 추가
    + room 툴 주석 비활성 + 프롬프트/테스트/템플릿 참조 업데이트
  - PR-2 (Geny): VTuber deny 확장 + `_PLATFORM_TOOL_PREFIXES`에서
    file-stem allowlist로 전환
- **plan/02_subworker_result_broadcast.md** (Bug 2a)
  - PR-3 (Geny): `_trigger_vtuber`에 chat room broadcast 추가
- **plan/03_turn_memory_continuity.md** (Bug 2b)
  - PR-4 (Geny): `_invoke_pipeline`/`_astream_pipeline`에
    `record_message("assistant", ...)` 추가
  - PR-5 (geny-executor): retriever L0 recent-turns 계층

총 5 PR, 3 plan. 각 plan 내부의 PR들만 순서 의존이 있고 plan 간
의존은 없다 (예: plan 1 머지 후 plan 2/3 진행해도 되고, 동시에
가도 됨).

## 완료 기준

1. VTuber는 카운터파트에게 보낼 때 첫 시도에
   `send_direct_message_internal`을 쓴다. `send_direct_message_external`
   / `session_list` 호출 **0회**. 로스터에 두 도구가 아예 없어야 한다.
2. ToolLoader의 `get_all_names()`에 `room_*`이 **하나도 없다**.
   기존 6개 room 툴 클래스는 여전히 정의되어 있지만 `TOOLS` export에
   빠져 있다.
3. Sub-Worker가 보낸 `[SUB_WORKER_RESULT]`에 대한 VTuber 응답이
   chat room (`_chat_room_id`)에 메시지로 추가되고 SSE notify가 간다.
4. VTuber가 그 다음 THINKING_TRIGGER 턴에서 "Sub-Worker가 방금 완료
   했다"는 사실을 맥락으로 가지고 대답한다 ("아직 답이 없다"고 말하지
   않는다).
5. 회귀 테스트:
   - (1a) Worker/VTuber env 매니페스트의 external 리스트가 새 네이밍
     규칙을 따름 (`geny_`로 시작하는 툴 이름 0개)
   - (1b) VTuber env에 `send_direct_message_internal`, `read_inbox`가
     있고 `send_direct_message_external`, `session_*`이 없음
   - (1c) ToolLoader 로드 결과에 `room_*`이 없음
   - (1d) Pipeline 매니페스트 실제 경로로 VTuber 레지스트리에
     `send_direct_message_internal`이 등록됨 (cycle 7 통합 갭 메우기)
   - (2a) `_notify_linked_vtuber` 테스트에서 `store.add_message` 가
     chat_room_id에 한 번 호출됨 + `_notify_room` 한 번 호출됨
   - (2b-α) `_invoke_pipeline` / `_astream_pipeline` 완료 후 STM에
     assistant role 메시지가 한 줄 쌓여 있음
   - (2b-β) 트리거 프롬프트로 invoke 시 retriever가 최근 STM 턴을
     주입함
6. 라이브 스모크: 위 "01:15:28 → 01:17:37" 시나리오를 재현해 네
   지점 모두 기대대로 동작 (첫 시도에 internal DM, chat 브로드캐스트,
   트리거 턴 기억, room 툴 미호출).


## 20260420_7과의 관계

7-A/7-B/7-1은 **능력(capability)**을 열어주는 작업이었다
(파일 쓰기 도구를 붙이고, 대칭형 카운터파트 DM을 추가함).
8-1/8-2는 그 능력이 *실제로 사용자 경험에 도달하는 경로*를 깔끔하게
만드는 작업이다. 툴 수렴(8-1)과 결과 가시성(8-2a), 턴 연속성(8-2b)
세 축이 맞물려야 유저가 체감하는 "Sub-Worker 연동이 된다"가 완성된다.
