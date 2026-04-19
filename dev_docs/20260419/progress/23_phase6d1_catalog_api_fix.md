# 23. Phase 6d-1 — Catalog API path / type alignment

## Scope

Phase 6a 의 `catalogApi` + `CatalogResponse` 가 backend (`controller/
catalog_controller.py`, `service/artifact/schemas.py`) 실제 shape 와
mismatch. Builder 탭 (Phase 6d) 을 깔기 전에 catalog 클라이언트와 타입
을 백엔드에 byte-compatible 하게 맞춘다. Runtime 영향 없음 —
`loadCatalog()` 는 아직 UI 에서 호출하지 않음.

## PR Link

- Branch: `feat/frontend-phase6d1-catalog-api-fix`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/types/environment.ts` — 수정
- `ArtifactInfo` 재설계 — 백엔드 `ArtifactInfoResponse` 와 동일
  (`stage`, `name`, `description`, `version`, `stability`, `requires`,
  `is_default`, `provides_stage`, `extra`). 기존 필드 (`artifact_id`,
  `display_name`, `capabilities`, `default_config`, `available_strategies`)
  는 백엔드가 반환하지 않는 shape — 삭제.
- `SlotIntrospection` + `ChainIntrospection` 신규 — 백엔드의
  `SlotIntrospectionResponse` / `ChainIntrospectionResponse` 와 1:1.
- `StageIntrospection` 신규 — `StageIntrospectionResponse` 1:1. 기존
  `StageCatalogEntry` (stage_order/stage_name/artifacts[]) 는 백엔드
  스키마에 존재하지 않음 → 삭제.
- `StageSummary` (list 응답 row), `StageArtifactList` (artifact 나열)
  신규 추가.
- `CatalogResponse` 는 `{ stages: StageIntrospection[] }` — `/api/
  catalog/full` 의 실제 응답.

`frontend/src/lib/environmentApi.ts` — 수정
- `catalogApi.full` 경로 수정: `/api/catalog` → `/api/catalog/full`.
  (`GET /api/catalog` 는 백엔드에 존재하지 않음 → 404.)
- `catalogApi.stages()` 신규 — `GET /api/catalog/stages` (전체 stage
  요약 리스트, Builder 왼쪽 패널 렌더에 필요).
- `catalogApi.stage(order)` 파라미터 바꿈 — 이전에는 `stageName:
  string` 을 받았으나 backend 는 `order: int` 를 받는다.
  `encodeURIComponent` 제거.
- `catalogApi.listArtifacts(order)` 신규 — `GET /api/catalog/stages/
  {order}/artifacts`. 기존의 잘못된 `/api/catalog/artifacts/{id}` 경로
  제거 (backend 없음).
- `catalogApi.introspection()` 삭제 — backend 미제공. full catalog 가
  이미 same 정보를 포함.
- `catalogApi.artifactByStage(order, name)` 파라미터 정정 — 두 번째
  인자는 artifact name (string), 첫 번째는 order (int). `Stage
  Introspection` 반환.

## Verification

- `backend/controller/catalog_controller.py` 의 5 개 route 와 프론트
  엔드 `catalogApi` 함수가 1:1 매칭.
  - `/api/catalog/full` ↔ `full()`
  - `/api/catalog/stages` ↔ `stages()`
  - `/api/catalog/stages/{order}` ↔ `stage(order)`
  - `/api/catalog/stages/{order}/artifacts` ↔ `listArtifacts(order)`
  - `/api/catalog/stages/{order}/artifacts/{name}` ↔
    `artifactByStage(order, name)`
- `FullCatalogResponse = { stages: List[StageIntrospectionResponse] }`
  → 프론트 `CatalogResponse = { stages: StageIntrospection[] }`. 필드
  명 / 필드 타입 byte-compatible (검증 대상 필드 9 개: stage, artifact,
  order, name, category, artifact_info, config, strategy_slots,
  strategy_chains).
- `grep` 으로 기존 삭제 필드 (`stage_order`, `stage_name`, `artifact_id`,
  `display_name` + environment 문맥, `capabilities`,
  `available_strategies`, `StageCatalogEntry`, `ArtifactCapability`)
  이 프론트 트리 어디에서도 참조되지 않음 확인 — 타입 삭제로 인한
  컴파일 파손 없음.
- `useEnvironmentStore.loadCatalog()` 가 아직 UI 에서 호출되지 않아
  런타임 영향 zero. 다음 PR (Phase 6d-2 Builder) 가 처음으로 호출.

## Deviations

- 이번 PR 은 타입/경로 정렬만. 신규 method (e.g. `stages()`,
  `listArtifacts()`) 를 추가하면서도 store 에 바인딩하지 않는다. store
  는 `loadCatalog()` 하나만 쓰고 stage/artifact 세부 fetch 는 Builder
  UI 가 직접 `catalogApi.listArtifacts(order)` 를 호출할 예정 —
  Builder 의 local state 로 다루는 게 단순하다 (store 에 16 stage x
  아티팩트 N 개를 전부 캐시하면 더 무거워짐).
- `ArtifactInfo.extra` / `StageIntrospection.extra` 는 `Record<string,
  unknown>` 로 느슨하게 둠. 백엔드도 `Dict[str, Any]` 라 제약이 없다.
- `config_schema` 는 nullable — 일부 stage 가 JSON Schema 없이 동작
  (예: s16_yield). Builder 가 form 생성을 시도하기 전에 null 가드
  필요.

## Follow-ups

- PR #24 (Phase 6d-2): Builder 탭 — stage list (왼쪽 패널) + artifact
  picker + config schema → form + manifest preview. 본 PR 의 타입을
  전부 소비.
- 필요 시 Phase 6d-3: stage 설정 diff 저장 / manifest 일괄 업데이트.
  지금은 `replaceManifest` / `updateStage` 로 충분.
