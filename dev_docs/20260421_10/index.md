# Cycle 20260421_10 — X4 · Progression + Manifest 전환 + EventSeed

**사이클 시작.** 2026-04-22
**선행.** X3 (cycle 20260421_9, 10 PR, 515/515 pass) — `CreatureState` 본체 +
tools + `AffectTagEmitter` + live mood/rel/vitals blocks + mood-aware
avatar.
**사전 청사진.** `dev_docs/20260421_6/plan/04_tamagotchi_interaction_layering.md §6-§7`,
`plan/05_cycle_and_pr_breakdown.md §4`.

## 목표

- **생애 단계 전환** — `ManifestSelector` + growth trees. life_stage
  (infant → child → teen → adult) 가 진행도/유대 조건을 만족할 때만
  manifest 를 통째로 갈아끼움. 전환은 단조 전진.
- **stage-specific manifests** — infant/child/teen/adult 의 tool 구성,
  말투, 감정 임계. 공통 preset 을 기반으로 stage 별 덮어쓰기.
- **ProgressionBlock live** — X3 의 no-op block 을 실 구현. age_days
  + stage descriptor 를 prompt 에 투영.
- **EventSeedPool** — 예측 불가능성. 결정적 trigger + weighted pick 으로
  "생일", "오랜만", "비 오는 날" 같은 상황별 hint 를 PersonaResolution
  끝에 1 개 선택적 삽입.
- **세션 시작 시 통합** — `AgentSession._build_pipeline` 가 selector 로
  manifest 를 선택 → 필요 시 mutation 남기고 pipeline 재구성.
- **14일 시뮬레이션 E2E** — tick 을 압축해 하루씩 돌려 infant → child
  전이가 실제로 일어나는지, age_days 가 바로 올라가는지 확인.

## PR 분해

`plan/05 §4.2` 를 본 사이클 기준으로 재확정:

| PR | 브랜치 | 요약 |
|---|---|---|
| PR-X4-1 | `feat/manifest-selector` | `service/progression/{selector,trees/default}.py` + 단위 테스트 + 본 cycle 문서 |
| PR-X4-2 | `feat/stage-manifests-infant-child-teen` | `manifests/` stage-specific 파일 |
| PR-X4-3 | `feat/progression-block-live` | `persona/blocks.py` `ProgressionBlock` 실 구현 |
| PR-X4-4 | `feat/event-seed-pool` | `service/game/events/{pool,seeds/*}.py` + 6–10 시드 |
| PR-X4-5 | `feat/selector-integrated-into-session-build` | `AgentSession._build_pipeline` 통합 |
| PR-X4-6 | `test/progression-e2e` | 14 일 시뮬레이션 E2E |

## 불변식

- **Manifest 전환은 세션 시작 시에만.** 턴 중간 교체 금지 — UX 혼란.
- **단조 전진.** teen → child 같은 후퇴는 기본 트리에서 금지.
  특수 `set_absolute` 로만 가능 (운영/디버그).
- **전환은 mutation 으로 기록.** `progression.manifest_id`,
  `progression.life_stage` 를 `set`, `progression.milestones` 에
  `enter:<new_id>` 를 `append`. source = `selector:transition`.
- **선택 실패는 현재 stage 유지.** `ManifestSelector.select` 는 어떤
  상황에서도 raise 하지 않는다 — 미지의 tree / 미지의 from_stage /
  predicate 예외 전부 현재 `manifest_id` 를 그대로 반환.

## 비범위 (X5+ 로 이월)

- Plugin Protocol + Registry — X5.
- AffectAware Retrieval — X6.
- 실제 날씨 API 연동 — seed_rainy_day 는 mock trigger 로 스펙만 충족.

## 산출 문서

- `plan/`  — manifest 레이아웃 + growth tree 설계 (필요 시).
- `progress/pr1..pr6_*.md` — PR 진행 기록.
