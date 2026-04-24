# ThinkingTrigger Engine Enhancement Plan

**Date**: 2026-04-01
**Scope**: Trigger prompt 고도화, 상황 인식 분기, 한/영 로케일 지원

---

## 1. 현재 상태 분석

### 1.1 현재 Trigger Prompt 구조

```python
_TRIGGER_PROMPTS = [
    "[THINKING_TRIGGER] You've been idle for a while. Reflect on recent conversations...",
    "[THINKING_TRIGGER] 잠깐 여유가 생겼네. 최근 대화를 돌아보거나...",
    "[THINKING_TRIGGER] 조용한 시간이야. 재미있는 관찰이나 팁을...",
    "[THINKING_TRIGGER] 사용자가 잠깐 자리를 비운 것 같아...",
]

_CLI_AWARE_PROMPT = "[THINKING_TRIGGER] CLI 에이전트가 지금 작업 중이야..."
```

**문제점:**
- 한/영이 혼재되어 있음 (첫 번째만 영어, 나머지 한국어)
- 상황 구분이 CLI 작업 중 여부 하나뿐
- 모든 idle 상황에서 동일한 수준의 prompt 사용
- `[THINKING_TRIGGER]` prefix가 하드코딩

### 1.2 로케일 시스템

| 항목 | 현재 상태 |
|------|----------|
| Config 시스템 | `LanguageConfig` → `GENY_LANGUAGE` env var (en/ko) |
| 읽기 방법 | `LanguageConfig.get_language()` 또는 `os.environ.get("GENY_LANGUAGE", "en")` |
| ThinkingTrigger에서 사용 여부 | ❌ 미사용 |

### 1.3 상황 인식 가능 데이터

현재 `_build_trigger_prompt()`에서 접근 가능한 컨텍스트:

| 데이터 | 소스 | 설명 |
|--------|------|------|
| `session_id` | 파라미터 | VTuber 세션 ID |
| `is_executing(linked_id)` | agent_executor | CLI 에이전트 작업 중 여부 |
| `agent._linked_session_id` | AgentSession | 페어링된 CLI 세션 |
| `agent._session_name` | AgentSession | 세션 이름 |
| `self._consecutive_triggers[sid]` | 자체 | 연속 트리거 횟수 |
| `self._activity[sid]` | 자체 | 마지막 활동 시각 |
| `idle_seconds` | 계산 가능 | 현재 시각 - 마지막 활동 |
| 시간대 | `datetime.now()` | 현재 시각 (아침/낮/저녁/밤) |

---

## 2. 설계

### 2.1 Trigger Context Categories (상황 카테고리)

상황에 맞는 prompt를 선택하기 위해 다음 카테고리를 정의:

| Category | 조건 | 설명 |
|----------|------|------|
| `first_idle` | consecutive == 0 | 사용자가 처음 idle 상태 진입 |
| `continued_idle` | 1 ≤ consecutive ≤ 3 | idle 상태 지속 중 |
| `long_idle` | consecutive ≥ 4 | 사용자가 오래 자리를 비움 |
| `cli_working` | CLI 에이전트 실행 중 | CLI 작업 완료 대기 |
| `time_morning` | 06:00–12:00 | 아침 시간대 |
| `time_afternoon` | 12:00–18:00 | 오후 시간대 |
| `time_evening` | 18:00–22:00 | 저녁 시간대 |
| `time_night` | 22:00–06:00 | 심야 시간대 |

**선택 로직**: `cli_working`이 최우선 → idle 단계 + 시간대 조합으로 선택

### 2.2 Prompt Template 구조

```python
# 카테고리별 prompt 딕셔너리
TRIGGER_PROMPTS: Dict[str, Dict[str, List[str]]] = {
    "category_key": {
        "en": ["English prompt 1", "English prompt 2", ...],
        "ko": ["한국어 prompt 1", "한국어 prompt 2", ...],
    }
}
```

각 카테고리에 3~4개의 prompt variant를 두어 자연스러운 다양성 확보.

### 2.3 Prompt 콘텐츠 설계

#### `first_idle` — 첫 idle 진입

```
EN:
- "[THINKING_TRIGGER] It's been quiet for a bit. Think about recent conversations
   or anything interesting you might want to share when the user returns."
- "[THINKING_TRIGGER] The user seems to have stepped away. Review what you've
   discussed today and prepare something helpful for when they're back."
- "[THINKING_TRIGGER] A moment of quiet. Reflect on recent topics — is there
   anything you forgot to mention or a follow-up worth sharing?"

KO:
- "[THINKING_TRIGGER] 잠깐 조용해졌네. 최근 대화를 돌아보거나,
   사용자가 돌아왔을 때 공유할 만한 걸 생각해 봐."
- "[THINKING_TRIGGER] 사용자가 잠깐 자리를 비운 것 같아.
   오늘 나눈 이야기를 정리하고, 돌아왔을 때 도움될 만한 걸 준비해 봐."
- "[THINKING_TRIGGER] 여유가 생겼네. 최근 주제 중 빠뜨린 게 있었는지,
   추가로 알려줄 만한 게 있는지 생각해 봐."
```

#### `continued_idle` — idle 지속 (2~3회차)

```
EN:
- "[THINKING_TRIGGER] Still quiet. Maybe think of something fun or useful
   to share — a tip, an observation, or just a friendly thought."
- "[THINKING_TRIGGER] The user hasn't returned yet. Consider reviewing your
   memory for any pending items or interesting follow-ups."
- "[THINKING_TRIGGER] Quiet time continues. If there's something lighthearted
   or encouraging you'd like to say, now's a good moment."

KO:
- "[THINKING_TRIGGER] 아직 조용하네. 재미있는 팁이나 관찰,
   또는 따뜻한 한마디를 준비해 볼까?"
- "[THINKING_TRIGGER] 사용자가 아직 안 돌아왔어. 기억 속에
   미처 전하지 못한 이야기가 있는지 확인해 봐."
- "[THINKING_TRIGGER] 조용한 시간이 계속되고 있어. 가벼운 이야기나
   응원의 한마디를 건네고 싶다면 지금이 좋은 타이밍이야."
```

#### `long_idle` — 장기 idle (4회+)

```
EN:
- "[THINKING_TRIGGER] It's been a while since the user was active.
   Keep a brief, warm thought ready — no need to be chatty."
- "[THINKING_TRIGGER] Extended quiet time. Just stay ready with a gentle
   greeting for when the user returns. Keep it short and natural."

KO:
- "[THINKING_TRIGGER] 사용자가 꽤 오래 자리를 비웠어.
   짧고 따뜻한 인사를 준비해 두면 돼. 길게 말할 필요 없어."
- "[THINKING_TRIGGER] 오랫동안 조용하네. 돌아왔을 때 자연스럽게
   반겨줄 준비만 해 두자. 간단하게."
```

#### `cli_working` — CLI 에이전트 작업 중

```
EN:
- "[THINKING_TRIGGER] The CLI agent is currently working on a task.
   Prepare to summarize the results clearly when it's done."
- "[THINKING_TRIGGER] A task is being processed by the CLI agent right now.
   Think about how to present the results to the user when ready."

KO:
- "[THINKING_TRIGGER] CLI 에이전트가 지금 작업 중이야.
   작업이 끝나면 결과를 깔끔하게 정리해서 전달할 준비를 해 둬."
- "[THINKING_TRIGGER] 지금 CLI 쪽에서 작업이 진행되고 있어.
   완료되면 사용자에게 어떻게 알려줄지 생각해 봐."
```

#### 시간대별 — 시간 인사 컨텍스트

```
EN:
- time_morning: "[THINKING_TRIGGER] It's morning. If the user shows up,
   a fresh greeting and maybe a plan for the day could be nice."
- time_afternoon: "[THINKING_TRIGGER] It's afternoon — good time to think
   about what's been accomplished today or what's coming up."
- time_evening: "[THINKING_TRIGGER] Evening time. Reflect on the day's
   conversations and think about wrapping things up warmly."
- time_night: "[THINKING_TRIGGER] It's getting late. If the user is still
   here, a gentle check-in would be thoughtful. Keep it brief."

KO:
- time_morning: "[THINKING_TRIGGER] 아침이야. 사용자가 오면
   상쾌한 인사와 함께 오늘 계획을 이야기해 보면 좋겠다."
- time_afternoon: "[THINKING_TRIGGER] 오후야. 오늘 뭘 했는지
   돌아보거나, 앞으로 할 일을 정리해 볼 시간이야."
- time_evening: "[THINKING_TRIGGER] 저녁 시간이야. 오늘 대화를 되돌아보고
   부드럽게 마무리할 준비를 해 봐."
- time_night: "[THINKING_TRIGGER] 늦은 시간이야. 사용자가 아직 있다면
   가볍게 안부를 물어보는 게 좋겠어. 짧게."
```

### 2.4 Prompt 선택 로직

```
1. CLI 작업 중? → cli_working 카테고리
2. 아니면 idle 단계 결정:
   - consecutive == 0 → first_idle
   - 1 ≤ consecutive ≤ 3 → continued_idle
   - consecutive ≥ 4 → long_idle
3. 시간대 체크:
   - 20% 확률로 시간대 prompt 사용 (자연스러운 혼합)
   - 80% 확률로 idle 단계 prompt 사용
4. 현재 locale (GENY_LANGUAGE) 기준으로 en/ko 선택
5. 해당 카테고리의 prompt 리스트에서 random.choice()
```

### 2.5 로케일 연동

```python
def _get_locale(self) -> str:
    """현재 시스템 locale을 반환 (en/ko)."""
    try:
        lang = os.environ.get("GENY_LANGUAGE", "en")
        return lang if lang in ("en", "ko") else "en"
    except Exception:
        return "en"
```

- `LanguageConfig` → `GENY_LANGUAGE` env var를 읽음
- Config UI에서 변경하면 `env_sync()` 콜백으로 즉시 반영
- ThinkingTrigger는 매 트리거 시 `os.environ`에서 읽으므로 런타임 언어 변경 자동 대응

---

## 3. 구현 계획

### 3.1 파일 변경 범위

| 파일 | 변경 내용 |
|------|----------|
| `backend/service/vtuber/thinking_trigger.py` | prompt 시스템 전체 리팩토링 |

**단일 파일 변경**으로 완결. 외부 의존성 추가 없음.

### 3.2 구현 단계

#### Step 1: Prompt 데이터 구조 정의 (상수)

기존 `_TRIGGER_PROMPTS` 리스트와 `_CLI_AWARE_PROMPT` 문자열을 제거하고,
카테고리별 `Dict[str, Dict[str, List[str]]]` 구조로 교체.

```python
_TRIGGER_PROMPTS: Dict[str, Dict[str, List[str]]] = {
    "first_idle": {
        "en": [...],
        "ko": [...],
    },
    "continued_idle": { ... },
    "long_idle": { ... },
    "cli_working": { ... },
    "time_morning": { ... },
    "time_afternoon": { ... },
    "time_evening": { ... },
    "time_night": { ... },
}
```

#### Step 2: `_get_locale()` 메서드 추가

`os.environ.get("GENY_LANGUAGE", "en")` 기반.

#### Step 3: `_get_time_category()` 메서드 추가

현재 시각 기반 시간대 카테고리 반환.

#### Step 4: `_build_trigger_prompt()` 리팩토링

카테고리 선택 → 로케일 선택 → 랜덤 variant 선택 체인 구현.

---

## 4. 예상 결과

### Before (현재)
```
모든 상황에서:
  "[THINKING_TRIGGER] 잠깐 여유가 생겼네. 최근 대화를 돌아보거나..."
  (한/영 혼재, 상황 무관)
```

### After (구현 후)

```
Locale: ko, 첫 idle, 아침:
  "[THINKING_TRIGGER] 아침이야. 사용자가 오면 상쾌한 인사와 함께..."

Locale: en, 3회차 idle, 저녁:
  "[THINKING_TRIGGER] Still quiet. Maybe think of something fun or useful..."

Locale: ko, CLI 작업 중:
  "[THINKING_TRIGGER] CLI 에이전트가 지금 작업 중이야. 작업이 끝나면..."

Locale: en, 장기 idle:
  "[THINKING_TRIGGER] It's been a while since the user was active..."
```

---

## 5. 검증 계획

1. 로케일 변경 테스트: Settings → Language를 en ↔ ko 전환 후 trigger prompt 확인
2. 시간대 테스트: 아침/낮/저녁/밤 시간에 trigger가 시간 인식 prompt를 사용하는지 확인
3. idle 단계 테스트: 연속 trigger가 first → continued → long 순서로 진행되는지 확인
4. CLI 작업 중 테스트: CLI 에이전트 실행 중일 때 cli_working prompt가 선택되는지 확인
5. 로그 확인: `[ThinkingTrigger]` 로그에 선택된 카테고리가 표시되는지 확인
