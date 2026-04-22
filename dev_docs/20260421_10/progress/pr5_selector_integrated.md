# PR-X4-5 · `feat/selector-integrated-into-session-build` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 32 신규/확장 테스트 + 471 인접 회귀 pass.

plan/04 §7.4 "selector 가 session 구축 경로에 합류" 단계. PR-X4-1~4 는
모두 준비물이었다 — Selector, stage manifests, live blocks,
EventSeedPool. 이 PR 은 네 조각을 실제 세션 라이프사이클에 엮는다:
세션이 시작될 때 Selector 가 stage manifest id 를 정하고, 라이브
블록들이 persona 뒤에 붙고, EventSeed 가 마지막 한 줄을 얹는다.

## 범위

### 1. `backend/service/persona/character_provider.py` — live block + seed 주입

생성자에 두 개의 optional 인자:

```python
def __init__(
    self, *,
    characters_dir, default_vtuber_prompt, default_worker_prompt, adaptive_prompt,
    live_blocks: Optional[Sequence[PromptBlock]] = None,
    event_seed_pool: Optional[Any] = None,
):
```

`resolve(state, session_meta)` 가 리턴하는 `persona_blocks` 순서:

1. `PersonaBlock(persona_text)` — 기존 동작 그대로
2. `live_blocks` — 생성 시 주입된 순서대로. `state.shared`
   확인 없이 *항상* append. 블록 자신이 `CreatureState` 부재 시 빈
   문자열을 돌려주도록 이미 방어되어 있음 (PR-X3-8, PR-X4-3).
3. `EventSeedBlock(picked)` — **`creature_state` 가 `state.shared`
   에 있을 때만**. 풀 `pick` 이 예외를 던지면 조용히 스킵. 픽된
   시드 id 가 있으면 `cache_key` 끝에 `+E:<id>` 접미.

### 2. `backend/service/state/registry.py` — `_maybe_apply_manifest_transition`

`SessionRuntimeRegistry.__init__` 에 `manifest_selector`, `character`
두 optional 인자. `hydrate(state)` 가 catch-up + shared 키 설치
이후 새 헬퍼 `_maybe_apply_manifest_transition(state, snap)` 을 호출.

헬퍼 동작:

1. `manifest_selector` 또는 `character` 중 하나라도 None → 조용히 리턴.
2. `await selector.select(snap, character)` 실행. 예외 → debug log +
   조용히 리턴 (plan/04 §3.2 "never-raises" 계약을 호출 측에서도 유지).
3. 결과 id 가 빈 문자열 또는 현재 `progression.manifest_id` 와 같으면
   조용히 리턴.
4. `state.shared[MUTATION_BUFFER_KEY]` 에서 `MutationBuffer` 확보.
   없으면 debug log + 리턴.
5. **세 개의 mutation append (모두 `source="selector:transition"`)**:
   - `set progression.manifest_id = <new_id>`
   - `set progression.life_stage = <stage>` (파싱 가능할 때만)
   - `append progression.milestones = "enter:<new_id>"`
6. `state.shared[SESSION_META_KEY]["new_milestone"] = "enter:<new_id>"`
   stamp — **같은 턴의 EventSeedBlock 이 `SEED_MILESTONE_JUST_HIT`
   (가중 3.0) 을 뽑을 수 있도록**.
7. `state.add_event("state.manifest_transition", {...})` 방출.

### 3. `backend/service/langgraph/agent_session.py` — `_SessionCharacterLike`

아직 `backend/repo/character.py` 는 없다 (plan/04 §1.1 의 orm 확장은
다른 사이클). 대신 세션 내부에서 가볍게 합성:

```python
class _SessionCharacterLike:
    __slots__ = ("species", "growth_tree_id", "personality_archetype")
    def __init__(self, species, growth_tree_id, personality_archetype):
        ...
```

`AgentSession.__init__` 에 네 인자 추가: `manifest_selector`, `species`,
`growth_tree_id`, `personality_archetype`. `_build_state_registry`
가 `_SessionCharacterLike(species, growth_tree_id, personality_archetype)`
를 만들어 `SessionRuntimeRegistry(...)` 로 같이 넘김. 기본값은
`species="generic"`, `growth_tree_id="default"`,
`personality_archetype=""` — 모든 기존 콜사이트 무변화.

### 4. `backend/service/langgraph/agent_session_manager.py` — 프로바이더 조립

`__init__` 이 `CharacterPersonaProvider` 를 생성할 때:

```python
persona_provider = CharacterPersonaProvider(
    ...,
    live_blocks=(
        MoodBlock(),
        VitalsBlock(),
        RelationshipBlock(),
        ProgressionBlock(),
    ),
    event_seed_pool=EventSeedPool(DEFAULT_SEEDS),
)
```

`_build_manifest_selector()` 가 `ManifestSelector(DEFAULT_TREE)` 를
반환 — state provider 가 설정된 실 게임 세션에서만 호출되도록
`create_agent_session` 이 `manifest_selector=self._build_manifest_selector()
if self._state_provider is not None else None` 로 가드.

### 5. 테스트

- `backend/tests/service/state/test_registry.py` +9 (`_CharStub`,
  `_StubSelector`, `_prime_snapshot` 픽스처 포함):
  - 선택기 없음 → manifest_id 불변 + 버퍼 비어있음
  - transition → 세 mutation 정확히 (순서 + source 포함)
  - transition → `session_meta["new_milestone"]` stamp
  - transition → `state.manifest_transition` 이벤트 방출
  - 동일 id → no-op
  - selector 예외 → 조용히 무시
  - 미지 stage id → life_stage mutation 만 스킵
  - character 없음 → selector 미호출
  - 빈 id → no-op
- `backend/tests/service/persona/test_character_provider.py` +9:
  - live_blocks append 순서
  - creature_state 없어도 live_blocks 유지
  - creature_state 있음 + firing seed → EventSeedBlock append
  - creature_state 없음 → EventSeedBlock 미첨부
  - firing seed 없음 → EventSeedBlock 미첨부
  - 풀 예외 → 조용히 무시
  - cache_key `+E:<id>` 접미
  - firing seed 없음 → cache_key 접미 없음
  - live + seed 공존 순서 `[Persona, live..., EventSeed]`

## 설계 결정

- **중간 세션 pipeline rebuild 는 스코프 아웃.** plan/04 §7.4 는
  transition 이 땡기면 현재 pipeline 을 새 stage_manifest 로
  재구축하는 선택지를 언급하지만, 실행 중인 state 기반 쓰레드를
  안전하게 rebuild 하는 건 session lifecycle 재설계와 얽힌다.
  이 PR 은 **transition mutation 을 persist 에 얹는** 수준까지만.
  새 manifest 는 다음 세션 시작 시 자연스럽게 픽업된다. 같은 턴의
  narrative shift 는 `SEED_MILESTONE_JUST_HIT` 의 3.0 가중으로 보상.
- **`_SessionCharacterLike` 로 ORM 부재 브릿지.** `CharacterLike`
  프로토콜은 세 속성만 요구하므로 세션 생성 시 인자 세 개를
  받아서 로컬 슬롯 객체로 합성. ORM Character 가 추가되면
  `AgentSessionManager` 의 인자 전달만 교체하면 됨 — 프로토콜은
  이미 받아들이는 구조.
- **live_blocks 는 `Sequence` 가 아닌 `tuple` 로 스냅샷.** 생성자
  `tuple(live_blocks or ())`. 세션 수명 동안 불변 — 외부 리스트
  mutation 이 프로바이더를 바꾸면 안 된다 (EventSeedPool 과 동일
  스탠스).
- **cache_key 는 현재 advisory.** `DynamicPersonaSystemBuilder.build`
  가 아직 소비하지 않지만, `+E:<id>` 접미를 지금 넣어두면 나중에
  캐시 레이어가 붙을 때 seed 별 stale hit 이 나오지 않는다. 소비
  쪽이 없어도 producer 쪽은 이미 정확하게 기록.
- **선택기 + character 둘 다 있어야 동작.** 한쪽만 있는 건
  misconfig 가능성이 높으므로 실행하지 않고 조용히 리턴.
  옵셔널 인자 하나만 넘긴 호출 실수가 런타임에 드러나지 않도록
  registry 가 선제적으로 방어.
- **`_stage_from_manifest_id` 가 모르는 stage → `""` 반환.**
  `"base"`, `"legacy_custom"` 같은 id 가 들어와도 manifest_id 와
  milestone 은 쓰이지만 `life_stage` 만 스킵. 커스텀 manifest 가
  생물을 "legacy" 같은 bogus stage 로 밀어넣는 걸 막음.
  `_KNOWN_LIFE_STAGES` = `{"infant","child","teen","adult"}` 을
  모듈 상수로 고정.
- **`new_milestone` 은 session_meta 에만 stamp.** CreatureState 에
  `new_milestone` 필드를 추가하지 않고 세션 메타에만 기록. 다음
  세션에선 자연스레 사라져야 하는 "방금 일어난" 한 턴짜리 플래그.
  영속화하면 세션마다 재발화한다.
- **EventSeedBlock 은 `state.shared[CREATURE_STATE_KEY]` 있을 때만.**
  live_blocks 처럼 항상 append 하지 않는 이유: EventSeedBlock 은
  실제로 `hint_text` 를 렌더할 때 `creature_state` 를 읽을 필요가
  없지만 (`block.__init__` 에 이미 seed 를 박아둠), **pool.pick 이
  CreatureState 를 요구한다**. 호출 전 체크가 맞는 레이어.
- **풀 예외 삼키기.** `EventSeedPool.pick` 자체가 이미 trigger 예외를
  삼키지만, 풀 생성자가 아닌 외부 스텁이 예외를 던지는 케이스
  (테스트 / 미래의 플러그인 풀) 를 감안해 provider 레벨에서
  한 번 더 감쌈. 관측성은 debug log.

## 의도적 비움

- **Character ORM (`backend/repo/character.py`) 확장.** plan/04 §1.1
  에서 언급되지만 이 사이클 스코프 아님. `_SessionCharacterLike`
  로 브릿지. ORM 이 붙는 날 `AgentSessionManager` 한 군데만 바꾸면
  됨.
- **mid-session pipeline rebuild.** 위 설계 결정 참조.
- **`cache_key` 소비 경로.** `DynamicPersonaSystemBuilder` 가 아직
  cache_key 를 안 읽는다. 추후 캐시 레이어를 붙일 때 producer
  이미 정확하므로 추가 작업 없음.
- **Selector 가 실제 DEFAULT_TREE 를 돌리는 end-to-end 시나리오.**
  14일 시뮬레이션으로 infant→child transition 을 검증하는 건 PR-X4-6
  의 몫. 이 PR 은 wiring 만.
- **비 VTuber 워커 세션에서의 live_blocks 정책.** 현재 워커 세션에도
  live_blocks 를 제공하고 있지만, 워커는 `creature_state` 를
  hydrate 하지 않으므로 블록 자체가 빈 문자열로 렌더 — 동작에
  영향 없음. 추후 워커 전용 프로바이더가 필요하면 분리.

## 테스트 결과

- 신규/확장 (persona 9 + state registry 9 + PR-X4-1~4 에서 이미 있던 것들): **32 pass**
- 인접 회귀 (`persona + state + progression + game/events + langgraph`):
  **471 passed**. stage manifest 세트, event seed pool, live block
  세트 모두 불변.

## 다음 PR

PR-X4-6 `test/progression-e2e` — 14일 시뮬레이션으로 selector 가
infant→child transition 을 적시에 발화하는지, milestone 이 다음
턴 prompt 에 올바르게 나타나는지 end-to-end 검증. manifest_selector /
registry / persona provider / event_seed_pool 이 이 사이클 안에서
함께 돌아가는 첫 통합 테스트.
