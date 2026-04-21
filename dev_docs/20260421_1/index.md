# Cycle 20260421_1 — VTuber↔Sub-Worker DM 연속성 (inbox drain 태그 손실 + tool-call STM 부재)

**상태.** Planning — analysis 작성 중.
**트리거.** 2026-04-21 10:20~10:23 UTC 라이브 로그. cycle 20260420_8 배포
(PR #191–#195) 직후에도 **VTuber가 2분 전 Sub-Worker 답변을 기억하지 못하는
문제가 재발**함.

## 문제 요약

cycle 20260420_8의 PR-4/5는 "trigger 입력으로 들어오는
`[SUB_WORKER_RESULT]`를 `assistant_dm`으로 분류 + assistant 응답을 STM에
기록 + L0 recent-turns"를 해결했다. 그러나 실제 프로덕션에서 관찰되는
VTuber↔Sub-Worker 대화의 **주된 경로는 다르다**:

```
10:20:45  Sub-Worker: [SYSTEM] You received a direct message from testsa
10:20:50  Sub-Worker: web_search(...)
10:20:54  Sub-Worker: [SUB_WORKER_RESULT] → 002b7d53  (VTuber에게 전달)
          ─ 이 순간 VTuber는 execute_command 중 (user의 원래 턴 처리 중)
          ─ AlreadyExecutingError → inbox 경로 사용
          ─ inbox.deliver(content="[SUB_WORKER_RESULT]...", sender="Sub-Worker")
10:20:58  VTuber: read_inbox → tool 결과로 결과 반환 (STM 기록 없음)
10:21:05  VTuber: "오! 서브워커가 뭔가 재미있는 걸..." 응답
          ─ VTuber 턴 종료 → _drain_inbox 실행
          ─ pull_unread → 메시지 마크 읽음 + 새 execute_command
          ─ prompt = "[INBOX from Sub-Worker]\n[SUB_WORKER_RESULT] Task..."
          ─ _classify_input_role("[INBOX from ...") → "user"  ← 태그 손실
          ─ VTuber가 별도 턴으로 응답 생성 + STM 기록 (role=user)
10:23:24  THINKING_TRIGGER:time_morning
10:23:27  VTuber: read_inbox → 비어있음 (이미 mark_read)
10:23:36  VTuber: "아직 새로운 소식이 없네..."  ← Bug
```

즉, PR-4/5가 고친 것은 "non-busy 경로 + trigger 입력"이었지만,
실제 프로덕션 트래픽에서는 **VTuber는 항상 자기 턴 중에 sub-worker를
호출**하므로 99%의 경우가 busy 경로로 흐른다. 그리고 busy 경로의
`[INBOX from ...]` 래퍼는 cycle 8의 분류기 업데이트를 우회한다.

## 이번 cycle이 다루는 두 버그

- **Bug A — inbox drain 경로의 태그 손실.** `_drain_inbox`가
  `[SUB_WORKER_RESULT]` 원문을 `[INBOX from {sender}]\n{content}`로
  감싸면서, `_classify_input_role`의 prefix 매칭이 `[INBOX from`에
  대해 정의되지 않았기 때문에 `user`로 폴백됨. 그 결과 VTuber의 STM
  transcript에 Sub-Worker 답변이 `[user]` 라벨로 남음 → 사용자/
  Sub-Worker 구분이 사라지고, 이후 retrieval이 이를 "사용자 메시지로
  간주".

- **Bug B — tool-call DM 기록 부재.** VTuber가
  `send_direct_message_internal`로 Sub-Worker에게 요청을 보낸 사실
  자체가 어디에도 STM으로 남지 않음. 현재 `record_message` 호출 사이트는
  (i) `_invoke_pipeline`의 입력/출력, (ii) `_astream_pipeline`의
  입력/출력 4곳뿐. Tool 결과는 `session_logger`에만 남고 STM에는
  들어가지 않음. 따라서 VTuber가 "내가 방금 뭘 부탁했지?"를 STM으로
  재구성할 수 없고, Sub-Worker의 답만 보고 맥락을 이해해야 하는 상황이
  발생.

두 버그는 **독립적으로 발현**하지만, Bug A를 고치지 않고 Bug B만 고치면
답변이 `user`로 라벨된 채 STM에 남아 여전히 망가짐. Bug B만 고치면
요청은 `assistant`로 남지만 답변은 여전히 `user`로 잘못 라벨됨. 즉,
**둘 다 같은 cycle에서 해결해야 "나→SW, SW→나" 전체 대화가 STM에
제대로 보존**된다.

## 설계 원칙

1. **기존 타입 체계 재사용.** cycle 8이 이미 도입한 네 가지 role —
   `user` / `internal_trigger` / `assistant_dm` / `assistant` — 만
   사용한다. 새 role은 만들지 않음.
2. **STM은 transcript 진실의 기준**. retrieval 계층(L0/L1/벡터)은
   STM이 정확하다는 전제로 동작한다. 태그 손실은 STM에서 먼저 막는다.
3. **Best-effort, 에러는 삼킨다.** cycle 8 PR-4처럼 `record_message`
   호출은 try/except로 감싸 LTM 쓰기나 실행 자체를 깨뜨리지 않는다.
4. **Tool 결과는 선택적으로 기록.** 모든 tool을 STM에 남기면 L0 창이
   터진다. DM/inbox류 "대화 의미를 가진" tool만 기록한다.

## 문서 구조

- `analysis/01_dm_continuity_regression.md` — 원인 3축(busy-drain 경로,
  tool-call 무기록, 트리거 시 인지 실패) 추적
- `plan/01_inbox_drain_tag_preservation.md` — Bug A: `_drain_inbox`
  래퍼 및 classifier 업데이트
- `plan/02_dm_tool_stm_recording.md` — Bug B: tool-call 레벨에서
  DM의 input/output을 STM에 기록
- `progress/` — PR 진행 기록 (cycle 8 포맷 재사용)

## 예상 PR 개수

3개 (Geny 전용, geny-executor 변경 없음):

1. **PR-1 (Bug A):** drain 래퍼가 원 태그를 보존하도록
   `_drain_inbox`를 조정하고, 분류기에 `[INBOX from` prefix 추가로
   `assistant_dm`으로 라우팅.
2. **PR-2 (Bug B):** DM tool (`send_direct_message_internal`,
   `send_direct_message_external`)에서 송수신 내용을 STM에 기록할 수
   있도록 session-aware 훅을 도입. 최소 침습.
3. **PR-3:** 이번 cycle progress 기록 문서.
