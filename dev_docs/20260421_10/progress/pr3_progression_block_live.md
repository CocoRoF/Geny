# PR-X4-3 · `feat/progression-block-live` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 22/22 blocks + 398 인접 회귀 pass.

X1 이 `ProgressionBlock` 를 skeleton 으로 두고 "X4 에서 채운다" 고
표시해 뒀다. PR-X4-1 이 selector 로 어느 manifest 로 갈지 결정하고,
PR-X4-2 가 그 manifest 의 *파이프라인 모양* 을 채웠다. 본 PR 은 *
LLM 이 읽는 자연어 anchor* — "이 캐릭터는 지금 어느 단계 며칠째
에 있는가" 를 prompt 에 주입.

## 범위

### 1. `backend/service/persona/blocks.py` — `ProgressionBlock.render` 실구현

기존 `return ""` 를 교체. 출력:

```
[Stage] infant (just a baby) — 0 days old.
[Stage] child (curious and learning) — 4 days old.
[Stage] teen (emotionally in flux) — 18 days old.
[Stage] adult (mature) — 60 days old.
```

단 한 줄. 다른 블록과 일관 — `[Mood]`, `[Vitals]` 은 다행 / 다 열, 하지만
`[Stage]` 는 정보량이 적어 한 줄로 충분 (stage 가중은 manifest 가 담당).

### 2. Stage descriptor 테이블

```python
_STAGE_DESCRIPTORS = {
    "infant": "just a baby",
    "child": "curious and learning",
    "teen": "emotionally in flux",
    "adult": "mature",
}
```

`plan/04 §7.5` 의 한국어 샘플 (`"아직 어린" 단계 (3일째). 이 단계의 말투
와 감정 표현을 유지한다.`) 을 기존 블록 컨벤션 (영문 라벨, 한 줄)
으로 변환. 프롬프트 문체 일관성이 LLM 스타일 mimicry 에 영향 —
`[Mood]` / `[Bond]` / `[Vitals]` 와 같은 regime 유지.

"이 단계의 말투 유지하라" 같은 LLM directive 는 넣지 않음. 이유:
- 이미 `PersonaBlock` 가 persona_prompt 를 제공 (캐릭터 고유 목소리).
- 이미 manifest (PR-X4-2) 가 `loop.max_turns` / tool 구성으로 stage 색채를
  구조적으로 강제.
- Directive 를 중복하면 over-instruction → LLM 이 "maintain the stage's
  voice" 문장을 그대로 읊는 부작용.

### 3. 단위 테스트 `test_blocks.py` (신규 7 + 기존 수정 1)

기존 `test_progression_block_is_still_a_noop_in_x3` 는 대체 —
이제 no-op 아니므로. 대신 "creature.progression = None" 의 방어적
fall-through 테스트로 바꿈.

신규:
- `test_progression_block_renders_infant_default_creature` — 기본 생성
  creature (0d infant) 렌더링.
- `test_progression_block_pluralises_day_correctly` — "1 day" vs
  "0/4 days" 단복수.
- `test_progression_block_renders_each_documented_stage` — 4 stage 전부
  descriptor 매핑 확인.
- `test_progression_block_unknown_stage_falls_back_to_bare_keyword` —
  `"elder"` 처럼 미래 stage 나 schema drift 시 `[Stage] elder — 120 days old.`
  로 graceful degrade. 빈 괄호 `()` 누락 방지.
- `test_progression_block_blank_life_stage_reports_unknown` — 빈 문자열
  life_stage → `[Stage] unknown`.
- `test_progression_block_tolerates_non_int_age_days` — `age_days = None`
  을 강제로 박아도 `0 days` 로 렌더 (TypeError 전파 금지).
- 기존 `test_live_blocks_compose_in_order_without_extra_blank_lines` 는
  ProgressionBlock 을 non-empty 로 포함하도록 업데이트 (이제 모든 live
  block 이 기여).

### 4. `_creature` helper 확장

```python
def _creature(
    *,
    mood=None, bond=None, vitals=None,
    progression=None,   # ← 추가
) -> CreatureState:
```

`progression=None` 이면 dataclass default (`life_stage="infant"`, `age_days=0`)
사용. 테스트가 `Progression(life_stage="teen", age_days=18)` 을 명시하면
그게 우선.

## 설계 결정

- **한 줄 출력.** MoodBlock 은 한 줄 (`[Mood] joy (0.70).`), Vitals 와
  Relationship 은 다행 (4-5 axis). Progression 은 정보량이 `life_stage` +
  `age_days` 뿐이라 한 줄이 맞다. 다행으로 쪼개면 시각적 밀도 손해.

- **Descriptor 는 `()` 안에.** `[Stage] infant — 0 days old.` 보다 `[Stage]
  infant (just a baby) — 0 days old.` 가 LLM 에게 더 좋은 신호 —
  keyword + gloss 형태는 프롬프트 엔지니어링에서 흔한 관용. 모르는
  stage 일 때는 `()` 째로 빼서 `[Stage] elder — 120 days old.` — 빈
  `"()"` 같은 껍데기를 남기면 LLM 이 그걸 모방할 수 있음.

- **`— days old` 단복수.** `1 day old` vs `2 days old`. 프롬프트가 틀린
  영어 ("1 days old") 를 쓰면 LLM 출력도 같은 실수를 따라가는 경향.
  5 줄 추가 비용으로 회피.

- **`life_stage == ""` 은 `unknown` 앵커.** 빈 문자열로 렌더하면
  `[Stage]  — 3 days old.` (더블 스페이스) 같은 추한 출력이 나온다.
  명시적 `unknown` 으로 LLM 에게 "아직 못 정한 상태" 를 알려주는 게
  정직.

- **`age_days` non-int 방어.** `Progression.age_days: int = 0` 이 dataclass
  기본이지만, 스토리지 경로에서 `None` / 문자열 로 올 가능성 (legacy
  row, migration quirk). `int()` 시도 → 실패시 `0`. 다른 live block들이
  속성 접근 실패에 그냥 빈 문자열로 떨어지는 정책과 일관 — turn 중단
  금지.

- **LLM directive 비포함.** plan/04 §7.5 샘플은 "이 단계의 말투 유지" 를
  포함하지만, 블록 출력이 매 턴 prompt 에 반복 주입된다는 걸 고려하면
  directive 중복은 prompt bloat 과 LLM 의 "maintain voice..." 문장 복제
  를 유발. 대신 manifest (PR-X4-2) 가 **구조적** 으로 강제 (턴 수 제한 =
  짧게 말하기 강제).

## 의도적 비움

- **Milestone 출력.** `Progression.milestones` 에 쌓이는 `first_conflict_resolved`
  / `enter:teen_introvert` 같은 이벤트는 narrative 적으로 흥미롭지만,
  매 턴 prompt 에 싣기엔 bloat. 필요해지면 "최근 N 개" 만 surfacing 하는
  별도 블록 (PR-X5+) 으로.
- **XP / 레벨.** `Progression.xp` 필드는 현재 mutation 소스가 없다 (X3
  의 tool 들이 XP 를 안 올림). XP 의미가 정해지면 그때 노출.
- **Stage-transition 연출.** "방금 child 가 되었다!" 같은 원샷 이벤트는
  event seed pool (PR-X4-4) 의 책임 — 상시 prompt 영역이 아님.
- **Species-aware 문구.** `"curious and learning"` 은 종 불가지. plan §1.1
  의 `species` ("catgirl", "dragon") 가 character 모델에 들어오면
  per-species override 를 고려할 수 있지만 MVP 는 generic.

## 테스트 결과

- `backend/tests/service/persona/test_blocks.py` — **22/22**.
- 인접 회귀 (persona + progression + state + emit + game + stage_manifest +
  default_manifest + integration) — **398 passed**. X4 신규 세트 (selector
  20 + stage_manifest 60 + progression 22) 에 더해 X3 baseline 은
  불변.

## 다음 PR

PR-X4-4 `feat/event-seed-pool` — `backend/service/game/events/{pool.py,
seeds/*.py}` + 6-10 샘플 시드. plan/04 §6 의 "예측 불가능성" 레이어:
결정적 trigger + weighted pick 으로 PersonaResolution 끝에 1개 hint 를
선택적 삽입. 생일 / 오랜만 / 비 오는 날 등.
