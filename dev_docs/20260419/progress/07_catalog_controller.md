# 07. CatalogController — stage / artifact introspection REST

## Scope

`plan/06` PR #7 — port of `geny-executor-web/backend/app/routers/catalog.py`
+ `app/services/artifact_service.py`. Mounts 5 read-only endpoints under
`/api/catalog/*` that power the Environment Builder UI's stage grid,
artifact picker, and schema-driven config forms — all session-less.

## PR Link

- Branch: `feat/catalog-controller`
- PR: (이 커밋 푸시 시 발행)

## Summary

신규 패키지: `backend/service/artifact/`
- `service.py` — `ArtifactService` (+ `ArtifactError`). `list_for_stage`,
  `describe_artifact_full`, `catalog`, `full_introspection`,
  `describe_single_artifact`. web 구현과 1:1, `functools.lru_cache` 로
  `_catalog_cached` / `_full_introspection_cached` 를 프로세스 단위로 캐시.
- `schemas.py` — `ArtifactInfoResponse`, `SlotIntrospectionResponse`,
  `ChainIntrospectionResponse`, `StageIntrospectionResponse`,
  `StageSummaryResponse`, `StageListResponse`, `ArtifactListResponse`,
  `FullCatalogResponse`. web shape 와 동일.
- `__init__.py` — `ArtifactError`, `ArtifactService` re-export.

신규: `backend/controller/catalog_controller.py` — `APIRouter(prefix="/api/catalog")`.

| Method | Path                                                 | Purpose                        |
|--------|------------------------------------------------------|--------------------------------|
| GET    | `/api/catalog/stages`                                | 16 stages summary + counts     |
| GET    | `/api/catalog/stages/{order}`                        | default artifact introspection |
| GET    | `/api/catalog/stages/{order}/artifacts`              | all artifacts for stage        |
| GET    | `/api/catalog/stages/{order}/artifacts/{name}`       | one artifact full introspection|
| GET    | `/api/catalog/full`                                  | bootstrap: all 16 default      |

모든 엔드포인트에 `Depends(require_auth)` 적용 (Geny-wide 정책).

`backend/main.py`
- lifespan 에서 `ArtifactService()` 인스턴스화 → `app.state.artifact_service`.
  첫 호출 때 `lru_cache` 가 warm up 되므로 eager warm 은 불필요.
- `catalog_router` import + `include_router` 등록.

## Verification

- `python3 -m py_compile` OK (service, schemas, controller, main.py).
- web 레퍼런스 vs Geny 포트: 엔드포인트 시그니처와 응답 shape 1:1 대응.
- `geny_executor.core.artifact.STAGE_MODULES` 와 `introspect_all` 은 executor
  0.20.0 에 포함되어 있으므로 import 검증 완료 (PR #5 스모크 테스트에서
  이미 executor 로딩 확인).

## Deviations

- web 은 auth 의존성이 없고 Geny 는 프로젝트 전체 `Depends(require_auth)`
  를 강제. 기능 동작은 동일.
- 503 fallback: `app.state.artifact_service` 가 아직 세팅되지 않았을 때
  명시적 503. web 은 lifespan 순서상 발생 불가능하지만 Geny 는 import
  순서가 더 복잡해 방어적으로 추가.
- web 은 `describe_stage(order)` 에서 `service.full_introspection()` 을 매번
  linear scan. Geny 도 동일 — lru_cache 가 받쳐주므로 O(n) scan 은 무시가능.

## Follow-ups

- PR #8: `CreateAgentSessionRequest` 에 `env_id`, `memory_config` 추가.
  `env_id` 지정 시 `environment_service.instantiate_pipeline(env_id)` 경로로
  분기, `memory_config` 지정 시 `MemorySessionRegistry.provision` 호출.
- PR #9: Stage 2 (agent_manager.create_agent_session) 에 Provider attach.
- 프론트엔드 Environment/Builder 탭은 PR #16 에서 이 엔드포인트들을 호출.
