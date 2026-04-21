# Plan 01 — Central text sanitizer module (PR-1)

**해결 대상.** TTS-전용으로 묶여 있는 `sanitize_tts_text`의 regex
셋을 독립 모듈로 끌어올려 display pipeline 전반에서 재사용 가능하게
만든다. TTS 동작은 변하지 않고 단지 새 모듈에 위임할 뿐.

## 1. 변경/신규 파일

| 경로 | 종류 | 내용 |
|---|---|---|
| `backend/service/utils/text_sanitizer.py` | 신규 | `sanitize_for_display()` + 패턴 상수 export |
| `backend/controller/tts_controller.py` | 수정 | `sanitize_tts_text`가 새 모듈 위임 |
| `backend/tests/service/utils/test_text_sanitizer.py` | 신규 | 순수 함수 pin tests |

## 2. 모듈 위치 근거

- `backend/service/utils/`가 이미 존재 (`utils.py` 1개 파일).
  display-level sanitizer는 "agent output → chat" 경로에서 공용으로
  쓰이므로 `service/utils/` 소속이 자연스럽다.
- `service/vtuber/emotion_extractor.py`는 VTuber-specific (emotion_map
  필요). 신규 sanitizer는 emotion_map과 무관한 static regex 기반이라
  `vtuber/`에 두면 응집도가 맞지 않는다.
- `controller/`에 남겨두면 service 계층이 controller 계층을 import하는
  backwards-dependency가 생긴다 — 현재 sink 4개 중 3개가 `service/` 내부.

## 3. API 설계

```python
# backend/service/utils/text_sanitizer.py
"""Strip routing/system/emotion tags + <think> blocks from agent
output before it reaches any user-visible surface (chat room,
TTS, UI).

Kept free of agent/session state so it's safe to call from any
sink — including streaming accumulation where the input may be a
partial, still-growing string.
"""

import re

# Exported so TTS controller / future consumers can extend the
# routing-prefix set without duplicating the master list.
SYSTEM_TAG_PATTERN = re.compile(
    r"\["
    r"(?:THINKING_TRIGGER(?::\w+)?|"
    r"autonomous_signal:[^]]*|"
    r"DELEGATION_REQUEST|"
    r"DELEGATION_RESULT|"
    r"SUB_WORKER_RESULT|"
    r"CLI_RESULT|"
    r"ACTIVITY_TRIGGER(?::\w+)?|"
    r"SILENT)"
    r"\]\s*",
    re.IGNORECASE,
)

_EMOTION_TAGS = (
    "neutral", "joy", "anger", "disgust", "fear", "smirk",
    "sadness", "surprise", "warmth", "curious", "calm",
    "excited", "shy", "proud", "grateful", "playful",
    "confident", "thoughtful", "concerned", "amused", "tender",
)
EMOTION_TAG_PATTERN = re.compile(
    r"\[(?:" + "|".join(_EMOTION_TAGS) + r")\]\s*",
    re.IGNORECASE,
)

THINK_BLOCK_PATTERN = re.compile(
    r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE
)
THINK_OPEN_PATTERN = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)

_WHITESPACE_COLLAPSE = re.compile(r"\s{2,}")


def sanitize_for_display(text: str) -> str:
    """Strip all special tags + think blocks; collapse whitespace.

    Safe on empty input. Returns empty string (not None) on falsy
    input, so callers can concatenate / write without None-checks.
    """
    if not text:
        return ""
    text = THINK_BLOCK_PATTERN.sub("", text)
    text = THINK_OPEN_PATTERN.sub("", text)
    text = SYSTEM_TAG_PATTERN.sub("", text)
    text = EMOTION_TAG_PATTERN.sub("", text)
    return _WHITESPACE_COLLAPSE.sub(" ", text).strip()
```

주의사항:
- `ACTIVITY_TRIGGER`가 기존 `_SYSTEM_TAG_PATTERN`에는 suffix 없는
  형태로만 있으나, `_classify_input_role`이 `[ACTIVITY_TRIGGER:…]`
  형태도 처리하므로 `(?::\w+)?` 확장. 기존 TTS 입력 중 suffix 형태가
  남아 있을 경우 TTS가 실수로 방송하는 것을 막는 효과도 있음.
- 그 외 patterns은 기존과 바이트 단위 동일 (byte-for-byte).

## 4. TTS 위임

`backend/controller/tts_controller.py`:

```python
from service.utils.text_sanitizer import sanitize_for_display

# 기존 _SYSTEM_TAG_PATTERN / _EMOTION_TAGS / _EMOTION_TAG_PATTERN /
# _THINK_* / sanitize_tts_text 전부 제거.

def sanitize_tts_text(text: str) -> str:
    """Back-compat shim — identical to sanitize_for_display.
    Kept so any external TTS caller / test import path keeps
    working; remove in a later cycle once call sites are
    audited.
    """
    return sanitize_for_display(text)
```

모든 기존 TTS 호출부(`tts_controller.py:109` 등)는 그대로 작동.

## 5. 테스트

`backend/tests/service/utils/test_text_sanitizer.py`:

```python
import pytest
from service.utils.text_sanitizer import sanitize_for_display


@pytest.mark.parametrize("text,expected", [
    # Empty / whitespace
    ("", ""),
    (None, ""),
    ("   ", ""),
    # Plain text unchanged
    ("안녕하세요", "안녕하세요"),
    # Single emotion tag stripped
    ("[joy] 안녕!", "안녕!"),
    ("안녕! [joy]", "안녕!"),
    # Multiple emotion tags
    ("[joy] 안녕 [smirk] 반가워", "안녕 반가워"),
    # Routing prefix stripped
    ("[SUB_WORKER_RESULT] 워커 답장", "워커 답장"),
    ("[THINKING_TRIGGER:first_idle] 조용하네", "조용하네"),
    ("[CLI_RESULT] legacy", "legacy"),
    ("[ACTIVITY_TRIGGER:user_return] hi", "hi"),
    ("[DELEGATION_REQUEST] do this", "do this"),
    ("[DELEGATION_RESULT] done", "done"),
    ("[autonomous_signal:morning_check] ping", "ping"),
    ("[SILENT] quiet", "quiet"),
    # Combined routing + emotion (the user-reported case)
    (
        "[SUB_WORKER_RESULT] 워케에게서 답장이 왔어요! [joy]\n\n"
        "워커가 정말 친근하게 인사해주네요~ [surprise]",
        "워케에게서 답장이 왔어요! 워커가 정말 친근하게 인사해주네요~",
    ),
    # <think> blocks
    ("<think>internal</think>Hello", "Hello"),
    ("<think>never closed", ""),
    ("Hi <think>a</think>there<think>b</think>", "Hi there"),
    # Case insensitivity on tags
    ("[JOY] hi", "hi"),
    ("[Sub_Worker_Result] x", "x"),
    # Unknown bracket content preserved (not an emotion, not routing)
    ("[random_thing] stays", "[random_thing] stays"),
    ("[INBOX from Alice] should stay (input-only tag)", "[INBOX from Alice] should stay (input-only tag)"),
    # Whitespace collapsing
    ("a   b   c", "a b c"),
    ("[joy]    안녕", "안녕"),
])
def test_sanitize_for_display(text, expected):
    assert sanitize_for_display(text) == expected


def test_tts_shim_still_works():
    from controller.tts_controller import sanitize_tts_text
    assert sanitize_tts_text("[joy] hi") == "hi"
```

주목할 케이스:
- `[random_thing]`, `[INBOX from Alice]` 등 **보존** — routing/emotion
  whitelist에 없는 bracket은 건드리지 않는다. `emotion_extractor.extract()`
  는 모든 lowercase bracket을 날리지만, display sanitizer는 보수적으로
  화이트리스트만 처리. 사용자 텍스트의 `[note]` 같은 marker가 의도치
  않게 사라지는 사고를 막는다.
- `[INBOX from …]`은 input-only 태그라 output에는 나타나지 않지만,
  혹시 LLM이 echo해도 보존됨 (필요 시 별도 cycle에서 판단).

## 6. 롤아웃 리스크

- **Regex 중복 제거 중 미묘한 byte 차이.** 기존 `_SYSTEM_TAG_PATTERN`을
  그대로 옮기고 `ACTIVITY_TRIGGER`만 suffix 허용으로 확장. 기존 TTS
  동작에 회귀 가능성: 매우 낮음 (suffix 형태가 들어와도 더 공격적으로
  strip될 뿐 덜 strip되지는 않음).
- **Import 경로 변경.** TTS 외부에서 `_SYSTEM_TAG_PATTERN`을 import하는
  코드는 없음 (grep 확인 후 최종).

## 7. 커밋 + PR

- 브랜치: `feat/display-text-sanitizer`
- 커밋 제목: `feat(utils): extract display sanitizer from tts_controller`
- PR 제목: 동일
