# PR-X4-1 · `feat/manifest-selector` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 사이클 관련 352/352 pass (기존 332 + 신규 20).

X3 가 `CreatureState` 를 세션 사이에 살려 두었다. 이제 **상태가 누적
되면 manifest 를 통째로 바꿔 캐릭터가 자란다** 는 X4 의 중심축이
필요하다. 본 PR 은 그 판단을 *순수 로직* 으로 고립시키는 첫 단계:
stage 전환 트리 + 선택기 자체만 작업하고, 실제 manifest 파일 /
세션 시작 시 통합은 후속 PR.

## 범위

`plan/04 §7` 의 `ManifestSelector` 계약 중 *결정 로직* 부분:

### 1. 새 패키지 `backend/service/progression/`

- `__init__.py` — 공개 API (`ManifestSelector`, `Transition`,
  `CharacterLike`, `default_manifest_naming`, `DEFAULT_TREE`,
  `DEFAULT_TREE_ID`).
- `selector.py` — `Transition` (frozen dc) + `CharacterLike` Protocol
  + `ManifestSelector` + `default_manifest_naming`.
- `trees/__init__.py` / `trees/default.py` — baseline growth tree.

### 2. `ManifestSelector.select` 계약

1. `character.growth_tree_id` 로 tree 검색. 없으면 `default_tree_id`
   로 폴백 (기본 `"default"`). 둘 다 없으면 빈 튜플 → 현재 유지.
2. tree 안에서 `t.from_stage == creature.progression.life_stage`
   인 edge 만 순회.
3. 매칭된 edge 의 predicate 를 호출. 참이면
   `naming(to_stage, character)` 로 manifest id 생성해 반환. 여러
   edge 가 같은 from_stage 를 갖는 경우 **선언 순서가 먼저인 것이
   승리**.
4. 어느 edge 도 매칭 안 되면 `progression.manifest_id` 그대로 반환
   (`""` 또는 `None` 이면 `"base"` 로 폴백).
5. **never raises.** predicate / naming / character attr 접근 예외는
   모두 debug 로그 후 현재 manifest 를 반환. 턴 중단 금지.

### 3. `DEFAULT_TREE` — plan/04 §7.3 의 샘플 그대로

| from | to | predicate |
|---|---|---|
| infant | child | `age_days ≥ 3` 그리고 `bond.familiarity ≥ 20` |
| child | teen | `age_days ≥ 14` 그리고 `bond.affection ≥ 40` |
| teen | adult | `age_days ≥ 40` 그리고 `"first_conflict_resolved" ∈ milestones` |

`first_conflict_resolved` 는 X4-4 의 `EventSeedPool` 이 심을 예정.
그전에는 teen → adult 는 조건 불충족으로 **발화하지 않음**.

### 4. Naming — `default_manifest_naming(stage, char) -> str`

- `stage_archetype` (e.g. `"teen_introvert"`) 가 기본.
- archetype 이 빈 문자열 / 공백 / 없음 → 단순 stage (`"infant"`).
- 이 전략은 selector 생성자에서 교체 가능 (`naming=...`) — X4-2 가
  manifest 파일명 규약을 바꾸면 여기만 교체.

### 5. 단위 테스트 `test_selector.py` (신규 20)

Naming 3 + happy path 6 + 견고성 6 + 의미 3 + API 2.

- `default_naming_joins_stage_and_archetype`
- `default_naming_falls_back_to_stage_when_archetype_missing`
- `default_naming_strips_archetype_whitespace`
- `select_returns_current_manifest_when_no_edge_applies`
- `select_fires_infant_to_child_at_documented_gates`
- `select_does_not_fire_below_age_gate`
- `select_does_not_fire_below_bond_gate`
- `select_fires_child_to_teen`
- `select_fires_teen_to_adult_only_with_milestone`
- `select_adult_stage_has_no_outgoing_edge`
- `select_unknown_tree_falls_back_to_default_tree`
- `select_with_no_fallback_and_unknown_tree_stays_put`
- `select_unknown_life_stage_stays_on_current_manifest`
- `select_predicate_exception_is_swallowed`
- `select_naming_exception_is_swallowed`
- `select_handles_missing_character_attrs_gracefully`
- `select_empty_manifest_id_falls_back_to_base`
- `first_matching_edge_wins`
- `trees_are_snapshotted_at_construction`
- `trees_property_returns_read_only_like_view`

## 설계 결정

- **Character 는 Protocol 로.** 실제 repo 의 `Character` 모델에는
  아직 `species` / `growth_tree_id` / `personality_archetype` 가
  없다 (PR-X4-5 에서 추가). selector 를 먼저 쓰고 검증 가능하게
  하려면 구조적 duck-typing 이 옳다. `@runtime_checkable` 까지 달아
  미래에 isinstance 검사가 필요하면 그대로 쓸 수 있게.

- **`select` 는 async.** 현재 로직엔 I/O 가 없어 sync 로도 충분
  하지만, X4-5 가 `AgentSession._build_pipeline` (이미 async) 안에서
  호출하고, 미래에 tree 를 storage 에서 로드할 가능성이 있다. 시그
  니처를 미리 async 로 박아두면 그때 호출부 변경이 없다.

- **Never raises.** `_emit_avatar_state` / `_load_mood_for_session`
  과 똑같은 원칙. selector 가 매 세션 시작마다 호출되는데 여기서
  터지면 게임 전체가 못 뜬다. 모든 실패 경로는 "현재 manifest
  유지" 로 수렴.

- **Naming 을 전략으로.** plan/04 §7.2 (파일명) 와 §7.4 (코드 조각)
  가 서로 다르게 생겼다 (`{stage}_{archetype}` vs `{stage}_{species}_{archetype}`).
  어느 규약이 맞는지는 실제 manifest 를 만들 때 (X4-2) 결정해야
  하므로, selector 는 **규약을 모르게** 만들고 조립을 외부에 맡긴다.
  MVP default 는 §7.2 쪽 파일명 규약 (`{stage}_{archetype}`).

- **Tree 는 tuple 로 snapshot.** 호출자가 넘긴 dict 를 나중에 변경
  해도 selector 의 판단이 바뀌지 않도록 `tuple(v) for v in trees.items()`
  로 얼린다. 트리를 런타임 변경하려면 selector 를 재구성해야 하는
  쪽이 계약으로 명확.

- **First-match-wins.** 동일 from_stage 에서 여러 edge 가 있을 수
  있는데 (실험적 전환, A/B), 선언 순서로 우선순위를 표현하는 게
  가장 단순. 트리 저자가 "override" edge 를 맨 위에 둔다.

- **Tree fallback** 은 정책. 등록 안 된 growth_tree_id 를 받았을
  때 기본 트리로 폴백하는 게 "몰라도 자라긴 한다" 를 보장. 명시적
  `default_tree_id=None` 으로 끄면 제자리 유지.

## 의도적 비움

- **Character 모델 확장** — `species` / `growth_tree_id` /
  `personality_archetype` 필드 추가는 PR-X4-5 (세션 통합) 에서
  한 번에. 지금 스키마를 건드리면 persona provider / 기존 테스트가
  연쇄 변경되고 본 PR 의 판독이 어려워진다.

- **실제 stage manifests** — `infant_cheerful.yaml` 등은 PR-X4-2.
  selector 는 manifest id 문자열만 돌려준다; 그 id 가 파일로
  존재하는지는 이 PR 의 계약 밖.

- **전환 mutation 발행** — `buf.append(op="set", path="progression.manifest_id", …)`
  은 selector 가 아닌 *통합 레이어* 책임. selector 는 "다음 id 는
  이거" 만 반환하고, 호출자가 변경 여부를 diff 해서 mutation 을
  낸다 (PR-X4-5).

- **ProgressionBlock live** — PR-X4-3.

## 테스트 결과

- `backend/tests/service/progression/test_selector.py` — **20/20**.
- 사이클 관련 전체 (`state + persona + emit + vtuber + game +
  execution + progression + integration`) — **352 passed**
  (기존 332 + 신규 20). 1 failed + 15 errors 는 `fastapi`/`numpy`
  미설치 환경 문제, X3 baseline 과 동일.

## 다음 PR

PR-X4-2 `feat/stage-manifests-infant-child-teen` — `backend/manifests/`
(또는 적절한 위치) 에 infant/child/teen/adult × archetype(s) manifest
파일 추가. selector 가 돌려준 id 를 실제 로드 가능한 실체로 매칭.
