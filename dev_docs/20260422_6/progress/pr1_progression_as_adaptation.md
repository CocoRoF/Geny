# PR1 — Progression 을 *적응 깊이* 로 재해석

**Date.** 2026-04-22
**Status.** 계획 (사이클 [20260422_6](../index.md) 의 첫 PR)
**Touches.**
[`backend/service/persona/blocks.py`](../../../backend/service/persona/blocks.py),
[`backend/tests/service/persona/test_blocks.py`](../../../backend/tests/service/persona/test_blocks.py),
[`backend/tests/integration/test_progression_e2e.py`](../../../backend/tests/integration/test_progression_e2e.py).

## 1. 원인 정밀 분석 — *왜* 첫 응답이 "갓 태어난 아기" 가 되는가

`CharacterPersonaProvider.resolve()` (B 경로) 가 매 턴 합성하는 시스템
프롬프트의 **마지막 부분** 에 `ProgressionBlock.render()` 의 출력이 박힌다.
새 캐릭터의 디폴트 상태에서 그 출력은 정확히 다음 한 줄이다:

```
[Stage] infant (just a baby) — 0 days old.
```

근거: [`service/persona/blocks.py`](../../../backend/service/persona/blocks.py)
의 `_STAGE_DESCRIPTORS["infant"] = "just a baby"`.

LLM 입장에서 이 한 줄은 **자기 자신에 대해 시스템 프롬프트가 명시한 가장
구체적인 사실**이다. `vtuber.md` 도 `vtuber_characters/default.md` 도 "넌 누구
인가" 의 *상황적 시점* 을 정의하지 않으므로, 모델은 가장 구체적인 단서인 "infant
/ just a baby / 0 days old" 를 1인칭으로 즉시 흡수한다. 그 결과:

> "… 아직 갓 태어난 아기라서 모든 게 궁금해요!"

이건 모델의 환각이 아니라 시스템 프롬프트의 거의 1:1 번역에 가깝다.

추가로 `service/langgraph/stage_manifest.py` 의 `_STAGE_DESCRIPTIONS["infant"]
= "infant life-stage — short reactive loops, feed/play only"` 는 다행히
프롬프트로 새지 않는다 (manifest metadata 전용). 하지만 같은 다마고치
어휘를 코드 곳곳에서 사용하고 있어 후속 작업 시 *프롬프트로 새는 라벨*과
*운영용 라벨* 의 경계를 혼동하기 쉽다 — PR1 에서 명확히 분리한다.

## 2. 설계 — *적응 깊이* 어휘로 재서술

원칙 A ([index §"설계 철학"](../index.md#설계-철학-이번-사이클의-헌법)) 에
따라, 데이터 키 `life_stage` 는 호환을 위해 `infant/child/teen/adult` 그대로
두고, **프롬프트 표현만** 적응-축 어휘로 바꾼다.

### `_STAGE_DESCRIPTORS` 폐기 → `_STAGE_PROFILE` 도입

```python
@dataclass(frozen=True)
class StageProfile:
    """How a stage shows up in the system prompt.

    `register` and `observed` describe what the runtime sees about the
    persona; `guidance` is the voice direction the model should follow.
    Keeping the three slots separate so the rendered block has a clear
    "facts vs. directions" split — the model can see what's observed
    AND what to do about it without conflating the two.
    """
    register: str       # short adaptation-axis label, e.g. "newcomer"
    observed: str       # one-line factual description (no metaphors)
    guidance: str       # one-paragraph voice direction


_STAGE_PROFILE: dict[str, StageProfile] = {
    "infant": StageProfile(
        register="newcomer",
        observed=(
            "the persona has just arrived in this world; its experience "
            "with this place, this user, and its own situation is near zero"
        ),
        guidance=(
            "Speak as someone who is still calibrating to this place. "
            "Not as a literal infant — as a fully-formed mind that is "
            "simply NEW HERE. Word choices may be a touch tentative; "
            "questions are concrete and small (about this room, this "
            "user, the immediate situation), not metaphysical. Avoid "
            "performing newborn-baby tropes."
        ),
    ),
    "child": StageProfile(
        register="settling",
        observed=(
            "the persona has had several rounds of interaction; first "
            "habits and preferences are forming"
        ),
        guidance=(
            "Curious but no longer overwhelmed. Builds on prior turns. "
            "Comfortable saying 'I'm still figuring this out'."
        ),
    ),
    "teen": StageProfile(
        register="acclimated",
        observed=(
            "the persona is comfortable in this world; voice and habits "
            "have settled"
        ),
        guidance=(
            "Has a recognizable voice. Can hold opinions, make callbacks "
            "to earlier moments, use light humour."
        ),
    ),
    "adult": StageProfile(
        register="rooted",
        observed="the persona is fully at home in this world",
        guidance=(
            "Self-paced, settled, generous. Speaks from a stable centre "
            "rather than a calibrating one."
        ),
    ),
}
```

### `ProgressionBlock.render` 출력 재설계

기존 한 줄 (`[Stage] infant (just a baby) — 0 days old.`) → 다음 두 블록.

```
[StageObservation]
- adaptation: newcomer (life_stage=infant)
- factual: the persona has just arrived in this world; its experience
  with this place, this user, and its own situation is near zero
- age: 0 days

[StageVoiceGuide]
Speak as someone who is still calibrating to this place. Not as a
literal infant — as a fully-formed mind that is simply NEW HERE.
Word choices may be a touch tentative; questions are concrete and
small (about this room, this user, the immediate situation), not
metaphysical. Avoid performing newborn-baby tropes.
```

핵심 변화:
- "infant" 라는 **내부 키는 살아있되**, 모델이 1인칭으로 흉내낼 **메타포
  ("just a baby")** 는 사라진다.
- *관찰* 과 *연기 지침* 이 라벨로 분리된다 → 페르소나 본문(`vtuber.md`,
  PR2) 의 `## How to Read Your Live State Blocks` 섹션이 두 라벨을 정확히
  가리키며 "복창하지 마라, 해석해라" 를 가르칠 수 있다.
- `age_days` 는 *부산물* 로 한 줄만 남김. 적응 축의 본질이 아님 (원칙 A).

### 미지의 `life_stage` 값 처리

```python
def render(self, state: PipelineState) -> str:
    creature = _get_creature_state(state)
    progression = (
        getattr(creature, "progression", None) if creature is not None else None
    )
    if progression is None:
        return ""

    life_stage = (getattr(progression, "life_stage", "") or "").strip()
    age_days = _safe_int(getattr(progression, "age_days", 0))
    profile = _STAGE_PROFILE.get(life_stage)

    if profile is None:
        # 알 수 없는 stage 키 — 데이터 드리프트 / 향후 신규 stage.
        # 모델이 이상한 메타포를 만들지 않도록, *관찰*만 출력하고
        # *연기 지침*은 비워둠. 페르소나 본문이 "지침이 없으면 평소
        # 톤을 유지하라" 로 디폴트를 잡고 있음.
        return (
            "[StageObservation]\n"
            f"- adaptation: unknown (life_stage={life_stage or 'unset'})\n"
            f"- age: {age_days} {'day' if age_days == 1 else 'days'}"
        )

    day_word = "day" if age_days == 1 else "days"
    return (
        "[StageObservation]\n"
        f"- adaptation: {profile.register} (life_stage={life_stage})\n"
        f"- factual: {profile.observed}\n"
        f"- age: {age_days} {day_word}\n"
        "\n"
        "[StageVoiceGuide]\n"
        f"{profile.guidance}"
    )
```

원칙: **블록은 절대 raise 하지 않는다** — 기존 ProgressionBlock 의 계약을
유지 (creature_state 미하이드레이트 시 `""` 반환).

## 3. 변경 항목 체크리스트

- [ ] [`service/persona/blocks.py`](../../../backend/service/persona/blocks.py)
  - `_STAGE_DESCRIPTORS` 삭제.
  - `StageProfile` dataclass 추가.
  - `_STAGE_PROFILE` dict 추가 (위 §2 내용).
  - `ProgressionBlock.render` 위 §2 코드로 교체.
  - 모듈 docstring 의 *"infant=baby"* 류 표현이 있다면 *"newcomer
    adaptation"* 으로 교체.
- [ ] [`tests/service/persona/test_blocks.py`](../../../backend/tests/service/persona/test_blocks.py)
  - 기존 `test_progression_block_*` 테스트 — `[Stage] infant (just a baby)`
    문자열 단언 → 다음 단언 묶음으로 교체:
    - `"[StageObservation]" in out`
    - `"adaptation: newcomer" in out`
    - `"life_stage=infant" in out`
    - `"[StageVoiceGuide]" in out`
    - `"calibrating" in out` (가이드 키워드)
  - 신규 테스트 `test_progression_block_avoids_baby_metaphor`:
    - `infant + age=0` 의 출력에 다음이 **포함되지 않음**: `"baby"`,
      `"newborn"`, `"just a baby"`, `"infant ("` (괄호 메타포 패턴).
  - 신규 테스트 `test_progression_block_unknown_stage_omits_guide`:
    - `life_stage="quokka"` → `"[StageVoiceGuide]"` 가 출력에 없음.
- [ ] [`tests/integration/test_progression_e2e.py`](../../../backend/tests/integration/test_progression_e2e.py)
  - `assert "[Stage] infant"` (3곳) → `assert "life_stage=infant"`.
  - `assert "[Stage] child"` 가 있다면 `assert "life_stage=child"` 로.
- [ ] [`backend/docs/PROMPTS.md`](../../../backend/docs/PROMPTS.md) 와
  [`PROMPTS_KO.md`](../../../backend/docs/PROMPTS_KO.md) 에 `[Stage]` 예시가
  남아있다면 `[StageObservation]` / `[StageVoiceGuide]` 로 갱신.

**`backend/service/langgraph/stage_manifest.py` 는 손대지 않는다.** 거기 있는
`_STAGE_DESCRIPTIONS` 는 manifest metadata 전용 (운영 로그/디버깅용) 이라 프롬
프트로 새지 않음. 다마고치 어휘를 운영 레이어에서까지 정리하는 건 별도 사이클.

## 4. 회귀 / 단위 테스트

| ID | 위치 | 단언 |
|---|---|---|
| U1 | `test_blocks.py::test_progression_block_renders_observation_and_guide` | newcomer 라벨 + calibrating 가이드 모두 포함 |
| U2 | `test_blocks.py::test_progression_block_avoids_baby_metaphor` | baby/newborn 단어 미포함 |
| U3 | `test_blocks.py::test_progression_block_unknown_stage_omits_guide` | unknown 라벨, guide 섹션 없음 |
| U4 | `test_blocks.py::test_progression_block_returns_empty_without_creature` | 기존 계약 유지 |
| U5 | `test_blocks.py::test_progression_block_age_days_pluralization` | `1 day` / `0 days` / `5 days` |
| I1 | `test_progression_e2e.py` (기존) | `life_stage=infant` 단언으로 갱신 |

이 PR 단독으로 사이클 매트릭스 R1 (응답에 "갓 태어난" 류 단어 미포함) 의
**구조적 차단**이 만들어진다. 다만 R1 의 출력 골든 (LLM 호출 결과 검증) 은
페르소나 파일(PR2) 와 함께 묶어서 사이클 close 시 한꺼번에 검증한다.

## 5. 위험 / 롤백 시나리오

| 위험 | 완화 |
|---|---|
| 다른 모듈이 `_STAGE_DESCRIPTORS` 를 import 하고 있음 | grep 결과 외부 import 0건 (PR1 작업 전 재확인 필수). 해당 심볼은 클래스-private 이 아닌 모듈-private (`_` prefix) 이므로 외부 의존이 없어야 정상. |
| `life_stage` 값이 X4-1 selector 가 새로 만들어내는 값일 수 있음 | `_STAGE_PROFILE.get(...)` 로 None-safe; 알 수 없는 키는 unknown 분기로. |
| 기존 e2e 테스트의 `[Stage] infant` 단언 누락 시 회귀 | `grep -rn "\[Stage\]" backend/tests` 로 PR 전 전수 확인. |
| 출력 토큰이 한 줄 → 다섯 줄로 늘어남 | StageObservation+StageVoiceGuide 합 ≈ 380~450 토큰. VTuber 시스템 프롬프트 전체 (수천 토큰) 대비 미미. PR4 의 이중 vtuber.md 제거로 -2~3k 토큰 회수 예정 → 순효과는 감소. |
| 롤백 | 단일 파일(`blocks.py`) 변경 + 테스트 변경. revert 1 commit. |

## 6. 다음 PR 와의 인터페이스

PR2 (`vtuber.md` 본문 작성) 가 의존하는 라벨:
- `[StageObservation]` / `[StageVoiceGuide]` 두 개의 정확한 헤더.
- `adaptation: <register>` 의 register 어휘 (`newcomer` / `settling` /
  `acclimated` / `rooted`) — `vtuber.md` 의 *적응-축* 설명에서 인용.

PR2 는 `## How to Read Your Live State Blocks` 섹션에서 두 헤더를 명시적
으로 가리키며 "복창하지 마라, 해석해라" 를 가르친다. PR1 의 헤더 이름이
바뀌면 PR2 도 동시 갱신 필요 — 두 PR 을 같은 마일스톤에 묶을 것.
