# X7-follow-up 2 · `:strength` suffix leak — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 278 backend tests pass (regression 0).
사용자 피드백 **"`[excitement:0.7]` 같은 감정+점수 형식이 chat 에
그대로 보인다"** 에 대한 실행 수정.

## 원인

X7 에서 AffectTagEmitter 의 `AFFECT_TAG_RE` 는 `:strength` suffix 를
지원하도록 만들었지만, 그 외 **세 개의 경로**에 있는 regex 가
suffix 를 매칭하지 못해서 display / avatar pipeline 에서 leak:

| 지점 | 기존 regex | 문제 |
|---|---|---|
| `service.utils.text_sanitizer.EMOTION_TAG_PATTERN` | `\[(?:joy\|...)\]` | `:0.7` 못 잡음 |
| `service.utils.text_sanitizer.UNKNOWN_EMOTION_TAG_PATTERN` | `\[[a-z][a-z_]{2,19}\]` | `:0.7` 못 잡음 |
| `service.vtuber.emotion_extractor._EMOTION_TAG_PATTERN` | `\[([a-zA-Z_]+)\]` | `:0.7` 못 잡음 |
| `service.emit.affect_tag_emitter.UNKNOWN_EMOTION_TAG_RE` | `\[([a-z][a-z_]{2,19})\]` | `:0.7` 못 잡음 |

특히 **streaming 경로**에서 token 단위로 UI 에 흐를 때
`sanitize_for_display` 가 suffix 달린 태그를 지우지 못해서 raw
`[excitement:0.7]` 이 chat 에 그대로 나타났음. `AffectTagEmitter` 의
stage-14 strip 은 최종 `final_text` 에서만 동작하므로 streaming 중에는
sanitizer 가 주 방어선.

## 수정

네 regex 모두 **엄격한 숫자 payload**로 `:strength` 를 인식하도록 확장:

```
(?:\s*:\s*-?\d+(?:\.\d+)?)?
```

- **엄격 숫자** — `[note: todo]` / `[DM to Bob (internal)]` 같은 업무용
  bracket 은 non-numeric payload 라 여전히 보존.
- **선택 공백** — `[joy : 0.7]` / `[joy:0.5 ]` / `[ excitement : 0.7 ]`
  같은 slightly malformed LLM 출력 모두 strip.
- **음수 / 소수 지원** — `[fear:-1]` / `[joy:1.5]` 정상 처리.
- **Malformed colon** — `[joy:]` (숫자 없는 colon) 은 여전히 매칭 안
  됨 (pre-X7 불변식 유지).

`text_sanitizer` 는 `_STRENGTH_RE = r"(?:\s*:\s*-?\d+(?:\.\d+)?)?"` 를
module-level constant 로 빼서 EMOTION_TAG_PATTERN / UNKNOWN_EMOTION_TAG_PATTERN
이 공유.

## 13개 end-to-end 검증 (모두 통과)

**Strip 해야 하는 케이스** (7):
- `[excitement:0.7] 좋아` → `좋아`
- `[joy:1.5] hi` → `hi`
- `[fear:-1] scared` → `scared`
- `mid [calm:2] end` → `mid end`
- `[ joy : 0.7 ] space-heavy` → `space-heavy`
- `[bewildered:0.5] unknown` → `unknown` (catch-all)
- `[wonder:0.3] gated` → `gated`

**보존해야 하는 케이스** (6):
- `[note: todo] stays` → unchanged (non-numeric payload)
- `[INBOX from Alice] stays` → unchanged (uppercase + space)
- `[DM to Bob (internal)] stays` → unchanged (space + parens)
- `[joy:] malformed` → unchanged (numeric required)
- `see [a] and [1]` → unchanged (below 3-char min / numeric)
- `[joy:abc] non-numeric` → unchanged (strict numeric)

## 테스트

### 신규

- `tests/service/utils/test_text_sanitizer.py` — 4 tests:
  recognized-tag-with-strength strip, whitespace-inside-bracket strip,
  unknown-tag-with-strength strip, strength-does-not-unlock-routing.
- `tests/service/vtuber/test_emotion_extractor_mood.py` — 4 tests:
  strength-decorated tag recognized, invalid-name-with-strength still
  stripped, remove_tags handles strength, whitespace inside bracket.
- `tests/service/emit/test_affect_tag_emitter.py` — 1 test:
  unknown-tag-with-strength stripped by safety-net.

### 스위프

```
pytest backend/tests/service/emit/ \
       backend/tests/service/affect/ \
       backend/tests/service/database/ \
       backend/tests/service/state/test_registry*.py \
       backend/tests/service/state/test_tool_context.py \
       backend/tests/service/config/ \
       backend/tests/service/langgraph/test_agent_session_manager_state.py \
       backend/tests/service/vtuber/test_emotion_extractor_mood.py \
       backend/tests/integration/test_state_e2e.py \
       backend/tests/service/utils/test_text_sanitizer.py -q

278 passed
```

(fastapi import test 1개 실패는 sandbox 의 pre-existing 한계 —
`controller.tts_controller` 는 fastapi 를 직접 import 하고 sandbox
venv 는 fastapi 없음. 본 PR 무관.)

## 불변식

- **Pre-X7 primary 6 magnitude 무변.** ✅
- **`AFFECT_TAG_RE` (mutation path) 무수정.** ✅ strength 파싱은 이미
  엄격 숫자로 되어 있었고 본 PR 은 *strip-only* regex 들만 조정.
- **Routing tag 보존.** ✅ 대문자 `[SUB_WORKER_RESULT]` /
  `[THINKING_TRIGGER:x]` 등은 catch-all 에 걸리지 않음.
- **`[joy:]` malformed 보존.** ✅ pre-X7 테스트 그대로 통과.
- **`[note: todo]` / `[INBOX from Alice]` 보존.** ✅ numeric 제약 덕분에
  업무용 bracket 은 다치지 않음.

## 사용자 확인

Backend 컨테이너 재빌드 + 재시작 후 새 VTuber 세션에서:
1. `[excitement:0.7]` / `[wonder:0.5]` 같은 태그가 **chat 에 raw 로
   나타나지 않음**.
2. 태그는 mood / bond mutation 으로 적용되고 (InfoTab 의 다마고치 상태
   bar 에 반영됨).
3. VTuber 아바타 emotion extractor 도 strength 달린 태그를 정상 감지
   (Live2D emotion 전환 정상).
