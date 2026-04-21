# PR-X3-10 · `test/state-e2e` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 사이클 관련 515/515 pass (기존 507 + 신규 8).

X3 사이클은 9 개 PR 에 걸쳐 CreatureState 계층을 쌓았다. 각각 단위
테스트가 있지만 *손잡이* (tool → buffer → persist → hydrate → block /
avatar) 가 조용히 어긋났을 때 단위는 그대로 녹색이어도 세션 전체
경로는 부러질 수 있다. 본 PR 은 plan/04 §10.3 의 네 시나리오를 실제
컴포넌트로 한 번에 돌려 "state 가 살아 있다" 계약을 고정한다.

## 범위

`backend/tests/integration/test_state_e2e.py` 한 파일, 실제 구현을
그대로 쓴다 (mock 없음, provider 는 in-memory 로 고정):

- `InMemoryCreatureStateProvider`  · PR-X3-1/2
- `SessionRuntimeRegistry.hydrate` / `persist` · PR-X3-3
- `apply_decay` + catch-up · PR-X3-4
- `TalkTool` / `FAMILIARITY_DELTA` via `current_mutation_buffer` · PR-X3-6
- `AffectTagEmitter.emit` · PR-X3-7
- `MoodBlock` / `RelationshipBlock` / `VitalsBlock` · PR-X3-8
- `EmotionExtractor.resolve_emotion(mood=...)` · PR-X3-9

## 시나리오

### S1 · 첫 만남 (2 tests)

- `test_s1_first_meeting_greet_bumps_familiarity_band_to_nascent` —
  새 캐릭터 → Turn 1 `TalkTool(kind="greet", topic="opening")` →
  Turn 2 hydrate 에서 `bond.familiarity == 0.3` (= `FAMILIARITY_DELTA`),
  `RelationshipBlock` 이 `familiarity: nascent` 로 렌더, provider 에
  저장된 스냅샷도 동일, `recent_events` 에 `talk:greet:opening` 기록.
- `test_s1_greet_twice_accumulates_familiarity` — greet × 4 → 1.2 →
  `familiarity: budding` 밴드 진입. 2 회 greet 는 `nascent` 경계에
  걸려 체크가 약해지므로 4 회로 한다.

### S2 · 포만 → 굶주림 (1 test)

- `test_s2_long_gap_drives_vitals_block_to_starving` —
  `provider.set_absolute` 로 `last_tick_at` 을 20h 전, hunger=50 으로
  픽스 → hydrate 가 catch-up → DEFAULT_DECAY (+2.5/h × 20h = +50) 로
  hunger 100 clamp → `VitalsBlock` 에 `hunger: hungry` or `starving`.
  랜드된 밴드 이름은 경계를 지키기 위해 **둘 다 허용** — clock skew
  때문에 실제 elapsed 가 19.9h 가 나와 89.75 → `starving` 컷(80)
  경계 위에서 머무는 경우를 방어.

### S3 · 재접속 (2 tests)

- `test_s3_reconnect_after_24h_triggers_single_catchup_event` —
  `_CountingProvider` (InMemory + tick 호출 카운트) 에 24h 묵은 스냅샷
  설치 → hydrate → `tick_calls == ["rico"]` (정확히 1 회), `state.catchup`
  이벤트 1 회, `VitalsBlock` 에 `hunger: starving` + `energy: tired`,
  `EmotionExtractor.resolve_emotion(None, None, mood=snap.mood)` →
  `("neutral", 0)` (calm → agent_state 도 None → neutral 낙하).
- `test_s3_fresh_reconnect_does_not_trigger_catchup` — 음성 대조.
  방금 load 한 상태로 hydrate → `tick_calls == []`. hydrate 마다
  double-tick 하면 vitals 가 분 단위로 포화된다.

### S4 · 감정 태그 자동 학습 (2 tests)

- `test_s4_repeated_joy_tags_accumulate_and_surface_through_mood_block_and_avatar`
  — 3 턴에 걸쳐 `[joy]` 태그를 `state.final_text` 에 넣고 `AffectTagEmitter.emit` →
  `registry.persist` 를 반복. 마지막에 새 hydrate →
  `mood.joy == 0.45` (= 3 × MOOD_ALPHA 0.15), `MoodBlock` 이
  `[Mood] joy (0.45).`, `EmotionExtractor.resolve_emotion("plain answer", "completed", mood=mood)` → `("joy", 1)`.
  **bond.affection** 도 1.5 로 올라간 걸 함께 확인 — joy 태그의
  secondary 효과 (affection +0.5) 가 함께 라운드트립 되는지 보는
  가드.
- `test_s4_anger_mood_overrides_completed_default_on_avatar_path` —
  joy 만 검증하면 `completed → joy` 기본 매핑 덕분에 mood 배선이
  안 돼도 녹색이다. 그래서 `[anger:2]` × 3 턴 → `mood.anger = 0.9`
  → `resolve_emotion(None, "completed", mood=...)` → `("anger", …)` 로
  기본값과 어긋나는 신호가 mood 쪽을 타는지 함께 고정.

### 전체 손잡이 (1 test)

- `test_full_cycle_tool_mutation_then_affect_tag_then_persist` — 한 턴
  안에서 **ContextVar 경로 (TalkTool)** 와 **state.shared 경로
  (AffectTagEmitter)** 가 모두 같은 버퍼에 쌓이는지 확인. persist 후
  provider 에 familiarity=0.3, mood.joy=0.15, bond.affection=0.5 가
  한번에 기록.

## 테스트 결과

- `backend/tests/integration/test_state_e2e.py` — **8/8**.
- 사이클 관련 전체 (`tests/service/state + persona + emit + vtuber +
  game + execution + integration`) — **515/515 pass** (기존 507 + 신규 8).

(사이클 무관 실패 1 + 15 errors — `test_execution_logging_gaps.py ::
test_inbox_delivery_on_busy_…`, `test_notify_linked_vtuber.py`,
`test_thinking_trigger_sanitize.py`, `test_agent_executor_sanitize.py`
— 모두 `fastapi`/`numpy` 미설치 환경 문제, PR-X3-9 와 동일 baseline.)

## 설계 결정

- **실제 컴포넌트, mock 금지.** 이 PR 의 가치는 "여기서만 잡히는
  regression" 이다. AffectTagEmitter / registry / provider / block /
  extractor 중 *어느 하나라도* 다른 쪽 계약을 조용히 어겼을 때
  녹색이 유지되지 않도록, 손잡이는 전부 실구현을 통과시킨다. 유일하게
  교체한 건 provider 구현 (sqlite → in-memory) — 이건 성능/결정성
  이유이고, 계약은 같다.

- **시나리오당 fixture 대신 헬퍼 1 개.** `_run_turn_with_tool(registry,
  tool_call)` 만 공유하고 나머지는 테스트 본문에서 직접 hydrate /
  persist 를 부른다. 시나리오마다 해야 할 일이 다르므로 (S2 는
  set_absolute 로 시간 위조, S3 는 _CountingProvider, S4 는 emitter
  루프) 한 fixture 로 추상화하면 각 테스트의 의도가 흐려진다.

- **밴드 어서션은 의도 기반 + 경계 허용.** S2 에서 "`hungry` or
  `starving`" 를 둘 다 통과시킨다 — 테스트 실행 중 wall-clock 이 약간
  앞서면 elapsed 가 19.99h 가 나와 경계를 왕복한다. "hunger 가 높다"
  가 의도이므로 특정 숫자에 못 박지 않는다.

- **S4 에 negative control 한 벌.** joy-only 테스트는 `completed → joy`
  기본 매핑과 우연히 같아서 mood 배선이 죽어도 통과할 수 있다.
  anger 테스트는 그 false green 을 막는다.

- **Full cycle 테스트는 "두 경로" 자체가 질문.** ContextVar 와
  state.shared 라는 두 입력 채널이 *같은* MutationBuffer 에 도달하는지
  가 X3 아키텍처 가장 미묘한 부분이었다. 한 턴 안에서 둘을 쏘고
  persist 결과를 보는 게 이 질문에 대한 가장 직접적인 답.

## 의도적 비움

- **sqlite provider 로 돌리는 variant.** InMemory 와 Sqlite 는 같은
  Protocol 을 구현하고, 각각 자체 단위 테스트가 있다. E2E 에서
  sqlite 로도 돌리는 건 CI 시간을 늘리지만 버그 검출력은 단위
  suite 보다 낮다. 필요해지는 시점 (durable storage 쪽에서 단위로 못
  잡는 regression 이 보이면) 에 별도 PR 로 추가.

- **recent_events → prompt 경로.** plan/04 "Phase 2 확장" 에
  해당하고, 현재 어떤 block 도 recent_events 를 읽지 않는다. X3
  범위 밖.

- **WS/executor 전체 라이프사이클.** `AgentSession.run_stream` 까지
  태우면 FastAPI 의존성이 얽힌다. 본 PR 은 **상태 계층** E2E 에
  초점. WebSocket / 실제 LLM 호출까지 묶는 건 X6 의 성능 체감
  테스트가 해야 할 일.

## 다음

X3 사이클 (PR-X3-1 ~ PR-X3-10) 모두 merged. 다음은 **X4 사이클**
(task #190) — Progression + Manifest 전환 + EventSeed. 24h-away
자동 태그 (`multi_day_away`) 같은 EventSeed 가 여기서 들어가고, 본
PR 의 S3 가 그 때 세대교체 테스트의 디딤돌이 된다.
