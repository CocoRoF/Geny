# PR-X3-9 · `feat/vtuber-emitter-mood-aware` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 사이클 관련 507/507 pass (기존 479 + 신규 28).
X1 의 keyword-based VTuberEmitter / `EmotionExtractor` 는 "행복/슬픔"
같은 단어 빈도로 표정을 추측했다. 이제 hydrated `CreatureState.mood`
를 1 순위 보조 소스로 삼아 **축적된 감정 상태 → 표정** 경로를 연다.

## 범위

`plan/04 §4.3` 의 VTuberEmitter 계약에 따라, Live2D 아바타를 갱신하는
단일 경로인 `agent_executor._emit_avatar_state` 가 다음 우선순위로
동작하도록 확장:

1. **Text tags** (`[joy]`, `[anger]`, …). LLM 이 이번 턴의 표정을 명시한
   것이므로 여전히 최우선.
2. **`CreatureState.mood.dominant()` ≥ 0.15** ← *신규*. PR-X3-5 가
   하이드레이트한 mood, PR-X3-7 의 AffectTagEmitter 가 누적해 쌓은
   mutation, PR-X3-8 의 MoodBlock 이 프롬프트에 반영하는 바로 그 값.
   `calm` dominant (= basic emotion 이 모두 threshold 아래) 일 때는
   None 을 리턴해 ③ 으로 폴백.
3. **Agent state** (`executing` → surprise, `error` → fear, …). mood
   신호가 없을 때만 작동 — 운영 상태의 "바쁘다/망가졌다" 신호.
4. `"neutral"` 기본값.

classic (state_provider 미설정) 모드는 mood 가 항상 `None` → 기존
two-argument 우선순위 (text → agent_state → neutral) 를 그대로 유지.
hydration 실패·프로바이더 예외는 무소음 swallow.

## 적용된 변경

### 1. `backend/service/vtuber/emotion_extractor.py`

- 모듈 상단에 두 상수 추가:
  - `_MOOD_BASIC_THRESHOLD = 0.15` — MoodBlock 의 cutoff 와 정확히
    동일 (프롬프트와 얼굴이 따로 움직이지 않도록).
  - `_MOOD_TO_EMOTION` — MoodVector basic key → Live2D facial slot.
    `excitement → surprise` (기본 Live2D 모델이 공통으로 보유하는
    슬롯에 맞춤), `calm` 은 의도적으로 미포함 (defer 하려고).

- `EmotionExtractor.map_mood_to_emotion(mood, *, threshold=0.15)`
  staticmethod:
  - `None` / calm dominant → `None` (deferral sentinel).
  - basic emotion above threshold → mapped name.
  - `mood.dominant()` 가 예외를 던지면 `None` (avatar emission 이
    mood 버그 때문에 죽지 않게).

- `resolve_emotion(text, agent_state, *, mood=None)`:
  - `mood` 는 keyword-only 로 추가. 위 우선순위 1→2→3→4 로 분기.
  - 기존 호출자 (agent_state 두 인자만) 는 행동 변화 없음.

### 2. `backend/service/execution/agent_executor.py`

- `_load_mood_for_session(session_id)` best-effort 헬퍼 신설:
  - session manager → `state_provider` → `character_id` → `load` →
    `mood` 의 네 단계 중 어느 하나라도 falsy / 예외 면 `None` 반환.
  - 결코 raise 하지 않음. avatar emission 의 "never raises" 계약을
    유지.

- `_emit_avatar_state`:
  - 양쪽 경로 (success+output, error/timeout) 가 `resolve_emotion(...,
    mood=mood)` 를 호출하도록 수정. mood 로드는 두 분기 공통 사전
    단계 1 회.

### 3. 테스트 (신규 28)

#### `backend/tests/service/vtuber/test_emotion_extractor_mood.py` (신규 19)

순수 단위 — `resolve_emotion` / `map_mood_to_emotion` 만 검증.

- `map_mood_none_returns_none`
- `map_mood_calm_defaults_defer` — 기본 `MoodVector()` (calm=0.5) 도
  defer.
- `map_mood_joy_above_threshold`
- `map_mood_basic_below_threshold_defers`
- `map_mood_excitement_maps_to_surprise` — Live2D 슬롯 매핑 픽서.
- `map_mood_negative_emotion_wins` — anger > fear > joy.
- `map_mood_threshold_override` — 호출자가 cutoff 조정 가능.
- `map_mood_survives_dominant_exception` — 깨진 mood-like object 도
  crash 하지 않음.
- `resolve_text_tag_beats_mood` — 명시 tag 가 mood 를 이김.
- `resolve_mood_beats_agent_state` — mood 가 `completed` 기본 매핑을
  이김.
- `resolve_calm_mood_falls_through_to_agent_state` — calm → defer →
  `executing` → surprise.
- `resolve_no_mood_keeps_classic_behaviour` — kwarg 없는 호출은 X1
  경로 그대로.
- `resolve_mood_none_equivalent_to_missing_kwarg` — 키워드 전달과
  생략이 같은 결과.
- `resolve_mood_with_no_agent_state_and_no_text` — tick-driven 호출
  패턴 지원.
- `resolve_default_when_all_sources_silent` — 모두 silent → neutral.
- `resolve_mood_excitement_surfaces_as_surprise` — 전체 경로 확인.
- `resolve_mood_missing_slot_in_emotion_map_yields_zero_index` —
  모델이 `neutral` 밖에 없어도 안전.
- `resolve_text_tag_with_invalid_name_falls_to_mood` — 유효하지 않은
  태그 → mood 로 폴백.
- `resolve_mood_kwarg_is_keyword_only` — positional drift 방지.

#### `backend/tests/service/execution/test_emit_avatar_state_mood.py` (신규 9)

실제 `_emit_avatar_state` 를 돌려 `AvatarStateManager.update_state`
호출 인자를 관찰.

- `success_path_mood_overrides_completed_default`
- `success_path_calm_mood_keeps_completed_default`
- `text_tag_still_wins_over_mood`
- `error_path_mood_overrides_error_default`
- `classic_mode_no_provider_uses_completed_mapping` — gating 확인.
- `missing_character_id_skips_mood_lookup` — provider 호출 자체 생략.
- `provider_raise_is_swallowed` — 프로바이더 예외가 avatar emission
  을 죽이지 않음.
- `load_mood_returns_mood_when_everything_wired` — 헬퍼 단위 테스트.
- `load_mood_returns_none_for_unknown_session`

## 테스트 결과

- `tests/service/vtuber/test_emotion_extractor_mood.py` — **19/19**.
- `tests/service/execution/test_emit_avatar_state_mood.py` — **9/9**.
- 사이클 관련 전체 **507/507 pass** (기존 479 + 신규 28).

(사이클 무관 실패 1 + 15 errors — `test_execution_logging_gaps.py ::
test_inbox_delivery_on_busy_…`, `test_notify_linked_vtuber.py`,
`test_thinking_trigger_sanitize.py`, `test_agent_executor_sanitize.py`
— 모두 `fastapi` 미설치 환경 문제, 본 PR 전에도 실패 상태였음.)

## 설계 결정

- **Mood 는 agent_state 보다 강하지만 text tag 보다 약하다.**
  - Text tag: 이번 턴의 명시된 감정. LLM 이 캐릭터의 이번 말 톤을
    직접 지시했으므로 다른 어떤 상태도 이를 덮을 수 없다.
  - Mood: 누적된 감정. 여러 턴에 걸쳐 형성된 "기분". text tag 가
    없는 턴 (모든 영업용 답변, 에러 상황) 에서는 이게 가장 정확한
    소스.
  - Agent state: 운영 상태. "지금 뭔가 돌아가고 있다" 같은
    operational signal 은 mood 가 *calm* 일 때만 유용. 화난 캐릭터가
    코드 실행 중이라고 신나게 웃을 이유는 없다.

- **Calm → defer, not neutral.** `_MOOD_TO_EMOTION` 에 calm 을
  의도적으로 빼두었다. 그 이유: mood 가 calm 이라는 건 "감정 pressure
  없음" 이지 "neutral 표정을 강제" 는 아니다. 후순위 소스 (executing →
  surprise 등) 가 더 정보량 있는 얼굴을 만들 수 있을 때 양보.

- **Excitement → surprise.** MoodVector 는 6 basic emotion 이지만
  Geny 가 번들하는 Live2D `emotionMap` 은 `joy/sadness/anger/fear/
  surprise/neutral` 6 슬롯이다. 가장 가까운 표정은 surprise — 양쪽
  모두 "각성도 높은 반응". excitement 전용 슬롯을 만드는 건 모델
  아트웤을 바꿔야 하므로 MVP 범위 밖.

- **Threshold 0.15 = MoodBlock 과 동일.** 프롬프트에 "joy" 라고 적히면
  얼굴도 joy 여야 한다. 서로 다른 cutoff 는 디버깅 지옥.

- **Best-effort mood 로드, never raises.** `_load_mood_for_session`
  은 모든 실패 경로에서 `None` 반환. provider 가 죽어도, 세션이
  미등록이어도, character_id 가 없어도 avatar 는 text/agent_state
  fallback 으로 여전히 동작. avatar emission 이 기능 버그 때문에
  조용히 실패하는 것보다 기존 동작으로 폴백하는 게 더 중요.

- **두 분기에서 동일 mood 재사용.** success / error 양쪽에서 한 번만
  provider 호출 (두 번 부르면 경합 + 불필요한 I/O). 한 번의
  `_emit_avatar_state` 호출 동안 mood 는 단일 truth.

- **VTuberEmitter 자체는 손대지 않았다.** executor 쪽
  `VTuberEmitter` (`s14_emit.artifact.default.emitters`) 는 Geny 에서
  manifest 에 등록되지 않은 상태 (`chain_order={"emitters": []}`) —
  실제로 Geny 의 VTuber 감정 경로는 `_emit_avatar_state` 를 거친다.
  여기가 진짜 "표정 신호" 가 만들어지는 지점이므로 이 경로를
  mood-aware 하게 만드는 게 plan §4.3 의 본질. executor 의
  VTuberEmitter 를 Geny 가 주입해 쓰는 구조로 바꾸는 건 X5 (plugin
  registry) 이후에나 의미가 있음.

## 의도적 비움

- **executor VTuberEmitter 확장** — 앞서 언급한 대로 Geny 가 이
  클래스를 실제로 통과시키지 않으므로 X5 이전에는 의미 없음. 필요
  시기가 오면 플러그인으로 붙이는 것이 X5 의 핵심 소재.
- **`EmotionExtractor` 가 직접 `CreatureStateProvider` 를 품게 하기** —
  현재 mood 로딩은 `agent_executor._load_mood_for_session` 의 책임.
  Extractor 를 stateful 하게 만들면 테스트 비용이 크게 늘고 "pure
  mapper" 라는 책임도 흐려진다. 호출자가 mood 를 넣어주는 쪽을 선호.
- **Intensity / transition_ms 를 mood 강도에 비례시키기** — mood 0.7
  일 때 얼굴이 더 강하게 움직여야 하는가? 아트웤 결정이 필요한
  주제 (밴드라벨 튜닝 없이 값만 넣으면 부자연스러움). MVP 는 기존
  `intensity=1.0` 유지, 필요 시 별도 PR.
- **recent_events 읽기** — `CreatureState.recent_events` 의 마지막
  이벤트로 트랜지션을 강제하는 기능은 plan/04 의 "Phase 2 확장" 로
  기재되어 있음. 이번 PR 범위 밖.

## 다음 PR

PR-X3-10 `test/state-e2e` — CreatureState 의 end-to-end 회귀 테스트
(PR-X3-5 가 hydrate → PR-X3-6 가 tool 로 mutate → PR-X3-7 이 affect
tag 로 mutate → PR-X3-8 이 prompt 로 반영 → 본 PR 이 avatar 에
반영) 을 한 세션 라이프사이클 안에서 한 번에 돌려 X3 사이클의
"state 가 살아 있다" 계약을 확정.
