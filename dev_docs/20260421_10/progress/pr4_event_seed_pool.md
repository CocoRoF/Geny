# PR-X4-4 · `feat/event-seed-pool` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 40/40 신규 + 528 인접 회귀 pass.

plan/04 §6 의 "예측 불가능성" 레이어. PR-X4-3 까지는 `[Mood]` /
`[Vitals]` / `[Bond]` / `[Stage]` 로 *상시* 상태를 주입했다. 하지만
같은 state 를 같은 방식으로 주입하면 같은 분위기의 응답만 나온다.
event seed pool 은 그 위에 *가끔* 끼어드는 narrative hint 를 하나
선택적으로 얹어, 같은 mood / vitals 조합에서도 턴마다 다른 향기를
낸다.

## 범위

### 1. `backend/service/game/events/pool.py` — 코어

- `EventSeed` (`@dataclass(frozen=True)`): `id`, `trigger`, `hint_text`,
  `weight=1.0`. Trigger 는 `Callable[[CreatureState, Mapping], bool]`
  — 동기 pure 함수. `TriggerFn` 타입 별명.
- `EventSeedPool`:
  - `__init__(seeds)` — `tuple(seeds)` 스냅샷. `ManifestSelector` 와
    동일한 snapshot-at-construction 스탠스.
  - `seeds` 프로퍼티 — `tuple[EventSeed, ...]`.
  - `list_active(creature, meta)` — 모든 시드를 평가, `True` 인 시드만
    반환. 예외 발생 시드는 debug log 만 찍고 조용히 제외.
  - `pick(creature, meta, *, rng=None)` — 활성 시드 중 가중치 기반
    1개 선택. 활성 시드 없으면 `None`. `rng=None` 이면 모듈 레벨
    `random` fallback.
  - `_weighted_pick` (staticmethod) — 가중치 `max(0.0, w)` 클램핑.
    총합 0 이면 uniform random 으로 폴백.
- `DEBUG` 로그는 `"event seed %r trigger raised: %s"` — prod 에선
  꺼져 있고, 로컬 debugging 시엔 어느 시드가 터지는지 즉시 확인.

### 2. `backend/service/game/events/block.py` — `EventSeedBlock`

```
[Event] It's raining outside — the creature may notice the sound...
```

`PromptBlock` 프로토콜 구현. `render(state)` 가:
1. `state.shared[CREATURE_STATE_KEY]` 에서 `CreatureState` 를 꺼내고
2. `state.shared.get("session_meta", {})` 를 meta 로
3. 풀에서 1개 pick, 있으면 `[Event] <hint_text>` 리턴, 없으면 빈 문자열

`name` 프로퍼티 = `"event_seed"`.

### 3. `backend/service/game/events/seeds/default.py` — 8개 baseline 시드

plan/04 §6.3 의 세 trigger 표면을 커버:

| id | trigger | weight |
|---|---|---|
| `infant_first_chirp` | `life_stage=="infant" and age_days==0` | 1.5 |
| `thirty_day_milestone` | `age_days>0 and age_days%30==0` | 2.0 |
| `high_stress` | `vitals.stress >= 70.0` | 1.0 |
| `high_affection` | `bond.affection >= 10.0` | 1.0 |
| `rainy_day` | `meta["weather"] == "rain"` (case / whitespace-insensitive) | 1.5 |
| `quiet_night` | `meta["local_hour"] in {22,23,0,1,2,3,4}` | 1.0 |
| `long_gap_reunion` | `meta["hours_since_last_session"] >= 168` | 2.0 |
| `milestone_just_hit` | `meta["new_milestone"]` 이 비지 않은 문자열 | 3.0 |

가중치 계층: **transition 스파이크 (3.0)** > **recurring milestone (2.0)**
> **hint 색채 (1.5)** > **ambient (1.0)**. plan §6.3 의 "rare narrative
peaks 가 ambient 를 덮어써야 한다" 를 숫자로 인코딩.

### 4. 단위 테스트 (40개)

- `test_pool.py` (14): empty/no-active, 단일 활성 시드, 시드된 RNG 로
  재현성, 500 trial 에서 80:20 가중 분포, snapshot 불변성, trigger 예외
  무시, 음수/0 가중 처리, `frozen` 검증, 디폴트 `random` 모듈 fallback.
- `test_default_seeds.py` (26): 카탈로그 shape (8개, 유일 id, non-empty
  hint) + 8개 시드 각각의 경계값 (`>` vs `>=`, 대소문자, 누락 meta) +
  `progression=None` / `vitals=None` / `bond=None` 방어.

## 설계 결정

- **Snapshot-at-construction.** `EventSeedPool([a,b])` 에 넘긴 리스트를
  나중에 비우거나 추가해도 풀의 동작은 안 변한다 — `ManifestSelector`
  와 동일. 트리 작성자가 "게임 내내 같은 pool" 이라는 멘탈 모델을
  유지하려면 외부 리스트 mutation 이 풀을 바꾸면 안 된다.
- **Trigger 예외 → `False`.** 버그 있는 시드 (또는 기대 안 한 schema
  drift) 하나 때문에 턴 전체가 hint 없이 나가는 건 과하다. debug log
  로 남기고 조용히 스킵. plan/04 §6.2 의 "never-raises" 계약.
- **음수 가중 클램프.** `weight=-5.0` 은 "5배 덜 자주" 가 아니라 "절대
  안 뽑히는" 으로 해석. 음수를 "반대로 자주" 로 쓰는 건 한 번도
  의도가 아님. `max(0.0, w)` 로 고정.
- **모두 0 가중 → uniform fallback.** 활성 시드가 있는데 `pick` 이
  `None` 을 돌려주면 턴이 hint 없이 지나간다. 0 가중 풀은 오인보다
  미스설정이 대부분이라, 디폴트 uniform random 으로 "뭐라도 내기" 를
  택함. 테스트로 고정.
- **시드 트리거의 방어적 속성 접근.** `progression=None`, `vitals=None`,
  `bond=None` 도 raise 안 함. `getattr(...,None)` 첫 가드 + 내부
  `_int_or_zero` / `_float_or_zero` 헬퍼. pool 이 어차피 예외를 삼키긴
  하지만, 매 턴 debug log 에 noise 를 남기지 않으려면 트리거가 조용한
  게 낫다.
- **`thirty_day_milestone` 이 아닌 365일 birthday.** plan 은 "생일"
  예시를 들지만 1년짜리 트리거는 MVP 테스트 루프에서 재현 불가.
  30일 주기로 낮춰 14-day e2e 시뮬레이션 (PR-X4-6) 바깥에서도
  관측 가능. 나중에 365-day birthday 를 추가해도 30-day 는 유지.
- **영어 hint_text.** 다른 live block (`[Mood]`, `[Vitals]`, `[Bond]`,
  `[Stage]`) 과 같은 언어 — mixed language 는 LLM 이 영어 응답 모드에
  있을 때 스타일 흐트림. persona_prompt 레벨은 per-character i18n 가능
  하지만 framing block 은 일관 영어.
- **0-day 는 `infant_first_chirp` 의 소유.** `thirty_day_milestone` 의
  조건은 `age_days > 0 and age_days % 30 == 0` — 수학적으로는 0 도
  30 의 배수지만 "갓 깨어난 0일" 은 별개의 시드가 책임 지는 게 낫다.
  두 시드 동시 활성화 + 3.0/2.0 가중 경합은 나중에 필요 시 튜닝.
- **transition flag `new_milestone` 은 메타에서만.** 생물 상태가
  "방금 teen 됨" 을 스스로 알 방법이 없다 (진입 시점은 mutation 함수
  가 아는 이벤트). plan 은 PR-X4-5 의 wiring 에서 `progression.mutate`
  결과로 `session_meta["new_milestone"]` 을 stamp 하도록 예정. 이 PR
  은 **읽기 쪽** 만 준비.

## 의도적 비움

- **`CharacterPersonaProvider.resolve()` 에 `EventSeedBlock` 주입.**
  Provider 가 여전히 `[PersonaBlock(persona_text)]` 만 리턴. 블록은
  준비됐지만 wiring 은 PR-X4-5 의 책임 — 그 PR 이 session 구축
  경로 전체를 손댄다 (`build_default_manifest` 를 `ManifestSelector`
  로 치환하면서 동시에 live block 묶음도 붙임).
- **`session_meta["new_milestone"]` stamping.** `progression.mutate`
  가 "teen 진입" 같은 이벤트를 어디에 기록할지 (현재 `milestones` 리스트
  에만 append) 그리고 session_meta 로 어떻게 bridge 할지 — 역시 PR-X4-5.
- **Species / archetype 별 시드 세트.** `seeds/` 를 서브패키지로 둔 건
  `seeds/catgirl.py`, `seeds/dragon.py` 가 나중에 붙을 자리를 두기
  위함. 지금은 `DEFAULT_SEEDS` 만.
- **시드 "쿨다운".** 같은 시드가 연속 3턴 뽑히는 게 거슬릴 수 있지만,
  cooldown 은 상태 저장 (마지막 pick timestamp) 을 요구한다. pool 은
  의도적으로 stateless. 필요하면 외부에서 "최근 뽑힌 시드 id" 집합을
  trigger 가 거부하도록 만들면 됨 — framework 수정 없이.
- **A/B test hook.** hint 포함/제외를 캐릭터별로 토글하는 플래그는
  X5 `GenyPlugin.Registry` 합류 때 결정.

## 테스트 결과

- `backend/tests/service/game/events/` — **40/40** (pool 14 + default 26).
- 인접 회귀 (`game + persona + progression + state + emit + langgraph`) —
  **528 passed**. 스테이지 매니페스트 세트와 PR-X4-3 progression 블록
  포함 전 영역 불변.

## 다음 PR

PR-X4-5 `feat/selector-integrated-into-session-build` — `agent_session.py`
가 세션 시작 시 (a) `ManifestSelector` 로 stage manifest id 를 계산
해 `build_stage_manifest` 로 교체, (b) 모든 live persona block
(Mood / Vitals / Bond / Progression / EventSeed) 을 `CharacterPersonaProvider.
resolve()` 출력에 합류, (c) `progression.mutate` 의 transition 이벤트를
`session_meta["new_milestone"]` 로 stamp. 캐릭터 모델에 `species` /
`growth_tree_id` / `personality_archetype` 확장도 포함.
