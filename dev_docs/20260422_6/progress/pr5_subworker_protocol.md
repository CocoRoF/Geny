# PR5 — Sub-Worker 회신 프로토콜 (`[SUB_WORKER_RESULT]` 구조화)

**Date.** 2026-04-22
**Status.** 계획 (PR4 머지 후, 사이클 마지막)
**Touches.**
[`backend/prompts/worker.md`](../../../backend/prompts/worker.md),
[`backend/prompts/vtuber.md`](../../../backend/prompts/vtuber.md),
(테스트만) `backend/tests/integration/` 신규 케이스.

## 1. 문제

VTuber 가 Sub-Worker 에게 작업을 위임하면 (
[`backend/docs/SUB_WORKER.md`](../../../backend/docs/SUB_WORKER.md)),
Sub-Worker 의 회신 메시지 형식에 *어떤 약속도 없다*. 현재 흐름:

1. VTuber → `send_direct_message_internal(content="...")`
2. Sub-Worker 가 도구 굴려 작업 수행
3. Sub-Worker → `send_direct_message_internal(content="...")` (free-form)
4. VTuber 가 메시지를 `[SUB_WORKER_RESULT]` 트리거로 받아 사용자에게 paraphrase

문제는 (3) 의 free-form. Sub-Worker 는 도구 출력 / 로그 / 코드 블록을 통째로
밀어넣는 경향이 있고, VTuber 는 그 raw 를 받아 매 턴 *원문 → 페르소나 톤*
변환을 한다. 결과:
- VTuber 컨텍스트에 raw 도구 출력이 누적 → 토큰 폭증.
- "summarize don't quote" 가이드와 충돌.
- 사용자가 보는 응답에 종종 코드 / 명령어 / 경로가 새어 나옴.

## 2. 설계 — 구조화된 회신 페이로드

### 약속

Sub-Worker 가 회신할 때 다음 정확한 형식을 따른다:

```
[SUB_WORKER_RESULT]
status: ok | partial | failed
summary: <one-line plain-language summary, ≤120 chars, no code>
details: |
  <multi-line; only what the VTuber needs to paraphrase to the user;
   no raw tool output, no logs, no stack traces unless they ARE the
   summary>
artifacts:
  - <relative path or URL>
  - <...>
```

규칙:
- `status` 는 enum 3종.
- `summary` 는 *반드시* 사용자에게 그대로 전해도 안전한 평문 한 줄. 도구
  이름 (`git push`), 코드 식별자 (`Foo.bar`), 경로 (`/home/...`) 금지.
- `details` 는 비어있어도 됨 (`details: ""`). VTuber 가 사용자의 후속 질문
  에 답할 때만 쓰는 정보.
- `artifacts` 는 비어있어도 됨. 산출물이 있을 때만 경로/링크 나열.

YAML-스러운 형식이지만 *파싱은 강제하지 않는다* — VTuber 가 정규식으로
`status:` / `summary:` 라인만 추출해도 충분하다. 본 PR 은 LLM 의 출력
포맷에만 약속을 박는다.

### 예시

**OK:**
```
[SUB_WORKER_RESULT]
status: ok
summary: 어제 만든 노트가 두 개 있었고, 둘 다 확인했어요.
details: |
  notes/2026-04-21-meeting.md (12 lines)
  notes/2026-04-21-todo.md (4 lines)
artifacts:
  - notes/2026-04-21-meeting.md
  - notes/2026-04-21-todo.md
```

**Failed:**
```
[SUB_WORKER_RESULT]
status: failed
summary: 그 폴더에 접근할 권한이 없어서 일단 멈췄어요.
details: |
  Filesystem returned permission denied on /etc/secret. The task
  expected read access; consider adjusting the working directory or
  asking the user to grant access.
artifacts: []
```

## 3. `prompts/worker.md` 갱신

현재 [`worker.md`](../../../backend/prompts/worker.md) 본문 (7줄) 끝에 새
섹션 추가:

```markdown
## Replying to Your Paired VTuber

When you are a Sub-Worker bound to a VTuber (your `linked_session_id`
is set), the user does NOT see your messages directly. The VTuber
paraphrases your reply in persona. Give them something paraphrasable.

When your work finishes — successful, partial, or failed — reply via
`send_direct_message_internal` using exactly this format:

    [SUB_WORKER_RESULT]
    status: ok | partial | failed
    summary: <one-line plain-language summary, ≤120 chars, no code, no paths, no tool names>
    details: |
      <optional multi-line; only what the VTuber may need if the user asks follow-up questions>
    artifacts:
      - <optional relative paths or URLs>

Rules:

- Always include the `[SUB_WORKER_RESULT]` header on its own line.
- `summary` must be safe to forward verbatim to a non-technical user.
  No code, no command lines, no absolute paths.
- `details` may be empty (`details: ""`). Do NOT dump raw tool output,
  logs, or stack traces unless THAT is genuinely the summary.
- `artifacts` lists files or URLs the user might want to look at. Omit
  or leave empty when not applicable.
- Do NOT add greetings, apologies, or persona language. The VTuber owns
  tone; you own facts.

If a task is genuinely interactive and you need the VTuber to ask the
user something on your behalf, use `status: partial` and put the
question in `summary` (e.g. `summary: 어느 폴더에 저장할지 사용자에게
확인 부탁해요.`).
```

## 4. `prompts/vtuber.md` 갱신

[`vtuber.md`](../../../backend/prompts/vtuber.md) 의 기존 `## Triggers`
섹션 안 `[SUB_WORKER_RESULT]` 항목을 다음으로 교체:

```markdown
- [SUB_WORKER_RESULT]: A task your Sub-Worker was running has finished.
  Parse the structured payload:
    - `status` tells you if it succeeded (`ok`), partially completed
      (`partial`), or failed (`failed`).
    - `summary` is the line you may paraphrase directly to the user.
    - `details` is for YOUR reference only — read it but do NOT dump
      it to the user unless they ask a follow-up question that needs
      it.
    - `artifacts` lists files / URLs; mention them only if relevant.
  Wrap the summary in your persona tone. On `failed`, acknowledge
  the failure honestly and (if appropriate) suggest a next step.
  On `partial`, surface the question in `summary` to the user before
  taking further action.
```

## 5. 변경 항목 체크리스트

- [ ] `prompts/worker.md` — §3 의 `## Replying to Your Paired VTuber`
  섹션 추가. 일반 Worker (페어링 없음) 도 이 섹션을 보지만 첫 줄
  ("When you are a Sub-Worker bound to a VTuber, ...") 의 조건 표현이
  무시 트리거가 됨 (PR4 §7 의 (a) 결정과 일관).
- [ ] `prompts/vtuber.md` — §4 의 트리거 항목 교체.

## 6. 회귀 / 통합 테스트

- [ ] `tests/integration/test_subworker_reply_format.py` (신규)
  - **시나리오 A**: VTuber 가 "어제 만든 노트 보여줘" 같은 위임 가능한
    질문을 함 → Sub-Worker 가 `[SUB_WORKER_RESULT]` 헤더 + `status:` +
    `summary:` 라인을 포함하는 메시지로 회신.
  - **시나리오 B**: VTuber 가 받은 회신을 사용자에게 전달할 때,
    `details:` 본문이나 `artifacts:` 경로가 사용자 응답에 그대로 등장하지
    않음.
  - **시나리오 C**: Sub-Worker 의 작업 실패 시 `status: failed` 가
    사용되고, VTuber 가 사용자에게 "실패했어요" 류 표현으로 paraphrase.
  - LLM 호출이 들어가는 통합 테스트라 CI 비용이 큼 — `pytest -m llm` 마커
    로 분리, nightly 만 돌리는 것이 합리적.
- [ ] `tests/service/.../test_worker_md_contains_subworker_protocol`
  단위 테스트 — `worker.md` 본문에 `[SUB_WORKER_RESULT]` / `status:` /
  `summary:` 키워드 모두 포함 (텍스트 회귀).

## 7. 위험 / 완화

| 위험 | 완화 |
|---|---|
| LLM 이 포맷을 정확히 따르지 않음 (특히 작은 모델) | (a) 포맷 없으면 "free-form" 으로 fallback (VTuber 가 통째로 paraphrase) — 회귀일 뿐 깨지진 않음. (b) `prompts/worker.md` 의 예시 2개를 inline 으로 보여주어 few-shot 효과. |
| `details:` 가 비어있을 때 YAML 파싱이 까다로움 | 본 사이클은 *파싱하지 않음* — VTuber 가 LLM 자체 능력으로 읽음. 미래에 파서가 필요하면 별도 사이클. |
| 일반 Worker (페어링 없음) 가 `[SUB_WORKER_RESULT]` 형식을 강제로 사용 | `worker.md` 새 섹션의 첫 문장 ("When you are a Sub-Worker bound to a VTuber...") 의 조건문이 무시 트리거. 모델이 그래도 적용한다면 별 부작용 없음 (사용자 직접 응답이 살짝 구조화될 뿐). |
| Sub-Worker 가 `summary` 에 코드를 넣음 | LLM 자체 준수에 의존. 회귀 시나리오 B 가 catch. |

## 8. 사이클 매트릭스 기여

- **R7** (Sub-Worker 회신에 `[SUB_WORKER_RESULT]` 헤더 + `status:` +
  `summary:` 라인 포함).
