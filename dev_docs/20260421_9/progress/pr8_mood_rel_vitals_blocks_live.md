# PR-X3-8 · `feat/mood-rel-vitals-blocks-live` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 541/541 사이클 관련 pass (기존 528 + 신규 13).
X1 의 `MoodBlock` / `RelationshipBlock` / `VitalsBlock` no-op stub 을
실 CreatureState read 로 전환. `ProgressionBlock` 은 X4 대기이므로
no-op 유지.

## 범위

`plan/04 §1 / §2` 의 blocks 규약에 따라 persona builder 에 합쳐지는 세
블록이 이제 `state.shared[CREATURE_STATE_KEY]` 를 읽어 system prompt
fragment 를 생성. PR-X3-5 가 채워주는 snapshot + PR-X3-6 의 도구 +
PR-X3-7 의 emitter 가 쌓아올린 mutation 이 결국 *이 블록* 을 통해
LLM 의 다음 턴 프롬프트에 반영된다.

classic mode (state_provider 미설정) 는 영향 없음: `shared` 에
`creature_state` 키가 없으면 `render` 는 `""` 반환,
`ComposablePromptBuilder` 가 빈 fragment 를 드롭.

## 적용된 변경

### 1. `backend/service/persona/blocks.py` (전체 대체)

네 블록 모두 `_get_creature_state(state)` 로 safe read. 키 없거나 해당
섹션 attr 이 `None` 이면 빈 문자열 반환 (원래 stub 계약 그대로).

**MoodBlock:**

- `MoodVector.dominant(threshold=0.15)` 로 주 감정 선택.
- 보조 감정: 두 번째로 강한 basic 감정이 `0.25` 이상이면 함께 표기.
- 렌더 형태:
  - `"[Mood] calm."` (threshold 아래)
  - `"[Mood] joy (0.70)."` (보조 없음)
  - `"[Mood] joy (0.60) with excitement (0.40)."` (보조 있음)

**RelationshipBlock:**

- `bond.affection / trust / familiarity / dependency` 각 축마다 band
  label + 원값을 한 줄.
- Bands: `<=0.5 nascent`, `<=2.0 budding`, `<=5.0 growing`,
  `<=10.0 deep`, `> 10.0 profound`. 음수는 `"none"` 로 clamp (관계가
  "역방향" 이라는 label 을 프롬프트에 노출하지 않기 위해).
- 렌더 형태 (4줄 + 헤더):
  ```
  [Bond with Owner]
  - affection: deep (+6.50)
  - trust: growing (+3.00)
  - familiarity: nascent (+0.30)
  - dependency: none (+0.00)
  ```

**VitalsBlock:**

- 축별 **반대 방향** band. hunger 가 낮으면 `sated` (좋음), energy 가
  낮으면 `exhausted` (나쁨). raw 숫자와 의미를 따로 취급하는 이유:
  LLM 은 "hunger 85" 만 보면 "배고픈가?" 를 추정해야 하지만 "starving"
  label 이 있으면 즉시 행동 가능.
- Bands:
  - `hunger`: sated / satisfied / peckish / hungry / starving.
  - `energy`: exhausted / tired / steady / rested / peak.
  - `stress`: calm / tense / strained / distressed / overwhelmed.
  - `cleanliness`: filthy / grimy / okay / clean / pristine.
- 렌더 형태 (4줄 + 헤더):
  ```
  [Vitals]
  - hunger: peckish (50/100)
  - energy: steady (60/100)
  - stress: calm (20/100)
  - cleanliness: clean (80/100)
  ```

**ProgressionBlock:** no-op 유지 (PR-X4 범주).

### 2. `backend/tests/service/persona/test_blocks_stub.py` → `test_blocks.py` (이름 변경 + 확장)

X1 stub 테스트 (3개) → live rendering + stub guarantee (16개) 로 확장.

## 테스트 (신규 13, 기존 3개는 구조 유지 후 이관)

### 클래식 모드 (no hydrated state)

1. `test_all_blocks_render_empty_when_no_creature_state` — 4 블록 모두 빈.
2. `test_names_are_stable_and_unique` — X1 계약 유지.
3. `test_empty_blocks_are_dropped_from_composed_prompt` — 빈 fragment
   는 ComposablePromptBuilder 에서 사라짐.
4. `test_progression_block_is_still_a_noop_in_x3` — progression 은 아직
   빈 (live state 가 있어도).

### MoodBlock

5. `dominant_emotion_with_value`.
6. `includes_secondary_when_above_threshold`.
7. `omits_secondary_below_threshold`.
8. `reports_calm_when_no_basic_emotion_clears_threshold`.
9. `empty_when_creature_has_no_mood_attr` (partial 하이드레이션 방어).

### RelationshipBlock

10. `bands_each_axis` — 4 축 모두 라벨/값 확인.
11. `band_labels_cover_range` — 파라메트릭, 6 샘플 (none/nascent/
    budding/growing/deep/profound).
12. `negative_bond_clamps_to_none_label` — 음수값 방어.

### VitalsBlock

13. `per_axis_band_semantics` — 낮은 hunger=sated, 낮은 energy=
    exhausted 등 축별 반대 방향.
14. `extreme_highs_use_right_labels` — starving/peak/overwhelmed/filthy.
15. `empty_when_creature_has_no_vitals_attr`.

### 구성(Composition)

16. `live_blocks_compose_in_order_without_extra_blank_lines` — 4 라이브
    블록 + 페르소나 bookend 조합 시 triple-newline 없음.

## 테스트 결과

- `tests/service/persona/test_blocks.py` — **16/16**.
- `tests/service/persona/` — **49/49** (기존 36 + 신규 13).
- 사이클 관련 전체 **541/541 pass** (528 기존 + 13 신규).

(사이클 무관 실패 4 건 — `environment/test_templates.py` × 3,
`utils/test_text_sanitizer.py` × 1 — `fastapi` / `numpy` 환경 문제,
본 PR 와 무관.)

## 설계 결정

- **Band label + raw value 동시 표기.** Band 만 있으면 "stress:
  strained" 만 보고 정확한 강도를 모름. Raw 만 있으면 LLM 이 55 의
  의미를 해석해야 함 (sequence 로는 "중간" 인데 체감으론 불편).
  둘 다 넣어 상보적으로 쓴다.
- **축별 반대방향 band.** Vitals 는 raw 숫자의 "크다/작다" 가 축마다
  다른 의미 (hunger 낮음=좋음, cleanliness 낮음=나쁨). Label 은 *체감*
  에 맞춤.
- **Dominant 기준 + 보조 감정.** 감정은 mixed 가 자연스럽다. 주 +
  보조 2개면 텍스트 길이 적당, LLM 이 미세한 감정 혼합을 반영 가능.
  `0.15 / 0.25` 의 두 threshold 는 플랜 본문의 0.15 와 일관.
- **Bond 음수 clamp.** affection = -2.0 을 "강한 반감" 으로 label 하는
  prompt 조각은 게임적으로 다소 무거운 서사. 현재 MVP 는 `"none"` 으로
  부드럽게 처리. X4 에서 부정적 bond 모델이 들어오면 별도 label.
- **ProgressionBlock 은 의도적으로 no-op.** `life_stage` / `manifest_id`
  를 프롬프트에 노출하는 건 X4 의 Manifest selector 와 같이 움직여야
  함 (선택 하나만 봐선 정보 부족). 분리해 병합.
- **Defensive partial hydrate.** `creature.mood / vitals / bond` 가
  `None` 일 수 있는 부분적 하이드레이션 상황에서도 render 가 empty
  string 으로 안전 종료. 절대 raise 하지 않음 — system prompt 생성이
  중단되면 전체 턴이 무너진다.

## 의도적 비움

- **ProgressionBlock 구현** — X4.
- **국제화된 label 텍스트** — 현재 영문. persona prompt 와 인터랙션
  타깃 LLM 에 맞춰 필요 시 지역화 PR.
- **Historical bond delta ("지난 턴보다 +0.3" 같은 미분 표기).**
  MVP 는 절대값만. 감성 변화 감지가 필요하면 X6 의 AffectAware 쪽.
- **Recent events 섹션.** `state.recent_events` 를 프롬프트에 주입
  하는 별도 block 은 본 PR 범위 밖. PR 10 에서 필요하면 별 블록 추가.

## 다음 PR

PR-X3-9 `feat/vtuber-emitter-mood-aware` — VTuberEmitter 가 keyword
기반 감정 추측 대신 hydrated `CreatureState.mood.dominant()` 를 직접
읽어 표정 신호 결정. 본 PR 의 mood read 경로를 emitter 가 공유.
