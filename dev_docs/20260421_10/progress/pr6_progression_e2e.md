# PR-X4-6 · `test/progression-e2e` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 7 신규 E2E + 486 인접 회귀 pass (493 total).

plan/20260421_10 index 의 마지막 체크포인트. PR-X4-1..5 가 각각 자기
유닛 스위트를 가지고 있지만, 사이클 전체의 계약은 *체인* 이다:
세션 시작 hydrate 에서 selector 가 호출되고 → 전환 mutation 이 큐잉되고
→ persist 가 다음 세션에서 살아남는 스냅샷에 커밋하고 → 같은 턴의
`new_milestone` 스탬프가 EventSeedPool 로 흘러 들어간다. 한 링크가
조용히 끊기면 (예: registry 가 selector 를 호출하지 않는다, pool 이
meta 에 접근 못 한다, persist 가 milestones 를 삼킨다) 모든 유닛
스위트는 여전히 초록인데 실제 플레이에선 성장이 안 일어난다.

이 PR 은 `backend/tests/integration/test_progression_e2e.py` 로 그
체인을 관찰 가능한 계약 레벨에서 7 개 시나리오 — **압축된 14일
시뮬레이션** — 으로 고정한다. `test_state_e2e.py` (X3 PR-10) 와 같은
스타일: mock 없이 실제 컴포넌트 (InMemoryCreatureStateProvider +
real DEFAULT_TREE + real ManifestSelector + real EventSeedPool) 를 쓰고,
내부 mutation 순서가 아니라 외부에서 보이는 사실만 assert.

## 시나리오

| # | 이름 | 검증 |
|---|---|---|
| S1 | `day 0→2 age gate` | age<3 + familiarity=25 → infant 유지, `state.manifest_transition` 미방출, `ProgressionBlock` "infant" |
| S2 | `day 3 infant→child hop` | age=3 + familiarity=25 → `infant_cheerful`→`child_curious`, milestones `enter:child_curious` 정확히 1회, `session_meta["new_milestone"]` 스탬프, 다음 세션 재hydrate 시 selector no-op |
| S3 | `day 5 bond gate blocks` | age≥3 이지만 familiarity=10 → infant 유지. age 타이머 단독 전환 regression guard. |
| S4 | `14-day two-hop walk` | day3 infant→child, day8 no-op, day14 + affection=50 child→teen. milestones 순서 보존 (`enter:child_*` < `enter:teen_*`) |
| S5 | `milestone_just_hit picked same-turn` | 전환 턴의 `session_meta` 로 `SEED_MILESTONE_JUST_HIT` 활성화 → `pool.pick(rng=seed(0))` 가 해당 시드 반환 (가중치 3.0 덕) |
| S6 | `unknown tree stays put` | `growth_tree_id="does_not_exist"` + `default_tree_id=None` → selector 가 조용히 현재 id 유지 |
| S7 | `no selector = pure hydrator` | selector/character 미전달 (pre-X4-5 경로) 도 여전히 hydrate/persist 동작 |

## 구현 노트

### `_prime` 헬퍼 — 시간 압축

14 일을 실제 decay tick 으로 돌리지 않고 `provider.set_absolute` 로
`progression.age_days` / `bond.familiarity` / `bond.affection` 를
직접 세팅. 이유:

- 결정론 — 14 일 간 decay 누적을 재현하려면 벽시계 tick 을 14 * 24 번
  돌리거나 catch-up 파라미터를 조작해야 함. 둘 다 테스트 목적에 비해
  과함.
- 속도 — 현재 193 ms → 7 시나리오 전체. 벽시계 압축을 쓰면 per-tick
  mutation 연산이 수천 건.
- 스코프 — 이 PR 의 계약은 **selector + registry + pool + persona
  wiring** 이지 decay 엔진이 아니다. decay 는 X3 PR-4 에서 이미 고정.

### `_run_session` 패턴

`PipelineState` 생성 → `registry.hydrate(state)` → `registry.persist(state)`.
툴/이미터는 의도적으로 호출하지 않음. selector 경로만 검증. 툴
mutation + selector 가 동시에 일어나는 케이스는 `test_state_e2e.py`
의 "full cycle" 테스트 + PR-X4-5 의 provider 테스트로 이미 커버됨.

### `_events` 헬퍼

`PipelineState.add_event(type, data)` 는 `{"type", "stage", "iteration",
"timestamp", "data"}` dict 로 `state.events` 에 append. 이 헬퍼는
`(type, data)` 쌍만 뽑아서 스크립트가 executor 내부 dict key 에
매이지 않도록 격리. 나중에 executor 가 이 스토리지를 바꾸면 여기만
고치면 됨.

### S4 의 "14-day simulation" 읽는 법

세 세션 (`d3`, `d8`, `d14`) 를 연속으로 열고 각 사이에 `set_absolute`
로 하루 경과 + 상호작용 누적을 시뮬. 하나의 `InMemoryCreatureStateProvider`
를 공유하므로 스냅샷이 진짜로 세션 간에 살아남는지도 함께 검증됨.
milestones 리스트가 두 전환을 정확한 **순서** 로 기록하는지 assert —
리스트를 set 으로 비교했으면 append 순서 regression 이 숨을 수 있음.

### S5 의 결정론 처리

`pool.pick` 에 `rng=random.Random(0)` 을 명시 주입. 기본 전역 RNG 를
쓰면 flaky 가능. 동시에 `list_active()` 로 "후보 집합에 포함된다"
라는 더 강한 주장도 별도로 assert — pick 이 우연히 milestone_just_hit
을 돌려준 게 아니라, 그 시드가 실제로 active 상태라는 계약이 본질.

### S6 의 silent-on-missing-tree

`ManifestSelector(..., default_tree_id=None)` 로 폴백 차단 후
`growth_tree_id="does_not_exist"` 을 주입. 실제 운영에선 디폴트
폴백이 켜져 있어 이런 상황이 거의 안 나지만, plan §7.4 의
"never-raises" 계약을 통합 레벨에서 다시 한 번 박는 것이
중요 — 한쪽에서 조용히 예외 삼키던 걸 다른 쪽에서 실수로 전파하는
regression 이 가장 잡기 어렵다.

## 설계 결정

- **실컴포넌트 + in-memory provider.** X3 e2e 와 같은 스탠스. mock
  selector / mock pool 로 통합 테스트를 만들면 wiring 의 "구멍"
  자체를 못 잡는다. 빠른 피드백을 위해 provider 만 in-memory, 나머지는
  전부 실물.
- **관찰 가능한 계약만 assert.** `buf.items` 의 순서, mutation 의
  source 같은 내부는 PR-X4-5 의 registry 유닛 테스트가 담당. e2e 는
  persisted 스냅샷 / session_meta / state events / block render 만
  본다. 덕분에 registry 구현이 "소스 라벨" 이나 "mutation 순서" 같은
  걸 리팩토링해도 이 스위트는 끄떡없음.
- **personality_archetype = "curious" 고정.** 전환된 manifest id 가
  `child_curious` / `teen_curious` 로 예측 가능해야 S2/S4 의
  milestone assertion 이 깔끔. 다른 archetype 스윕은 PR-X4-1 의
  selector 유닛에서 이미 커버.
- **teen→adult 는 제외.** 40 일 + `first_conflict_resolved` milestone
  이 필요한데, 이 milestone 을 stamping 하는 tool / flow 는 이
  사이클 스코프 밖 (plan/04 §6.3 "X4-4 가 시드 심지만 실제 쓰임은
  이후"). 검증 불가능한 걸 빌드하는 대신 생략.
- **S7 ("selector 없이") 이 왜 있어야 하나.** classic (비 게임) 세션
  경로가 pre-X4-5 와 동일하게 동작해야 함을 보증. PR-X4-5 의
  provider 테스트도 live_blocks 빈 튜플 기본값으로 이를 검증하지만,
  registry 레벨에서도 selector 인자 미전달 경로를 명시적으로
  회귀 차단.

## 의도적 비움

- **실제 Character ORM 연결.** `_Character` 는 `_SessionCharacterLike`
  를 미러하는 테스트 로컬 슬롯 클래스. Character ORM 이 붙으면
  그걸 import 해서 갈아끼움.
- **DynamicPersonaSystemBuilder / EnvironmentManifest 경로 통합.**
  이 PR 은 selector/registry/pool/block 레벨의 E2E. stage-specific
  EnvironmentManifest 를 실제로 로드해 tool roster 가 바뀌는지를
  보는 건 다른 사이클 (plan/04 §7.4 의 pipeline rebuild 스코프).
- **cache_key 기반 프롬프트 캐시 무효화.** producer (PR-X4-5 provider)
  가 `+E:<id>` 접미를 쓰는 건 검증됐지만, consumer (캐시 레이어) 는
  아직 없다. consumer 가 붙을 때 같이 검증.
- **decay + selector 교차 검증.** catch-up 이 24h 끼어든 세션에서
  age_days 가 올라가 전환을 fire 하는 시나리오. X3 PR-10 의 S3 가
  catch-up 만, 이 스위트의 S4 가 selector 만 커버 — 교차 검증은
  decay 가 `progression.age_days` 를 갱신하는 경로가 추가될 때 (현재
  DEFAULT_DECAY 는 vitals 만 건드림).

## 테스트 결과

- `backend/tests/integration/test_progression_e2e.py` — **7/7 pass**
- 전체 회귀 (`integration + persona + state + progression + game.events
  + langgraph`) — **493 passed**. X4 사이클 전 영역 불변.

## 사이클 마무리

`dev_docs/20260421_10/index.md` 의 PR 테이블 전체 체크. 6 개 PR 이
모두 머지되고 E2E 가 초록 — X4 (`Progression + Manifest 전환 +
EventSeed`) 사이클 closed.

다음 사이클은 **X5** — `GenyPlugin Protocol + Registry (+ executor
0.30.0 선택 bump)` (task #191).
