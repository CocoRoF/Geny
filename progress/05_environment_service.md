# 05. EnvironmentService + service exceptions

## Scope

`plan/06` PR #5 — `geny-executor-web/backend/app/services/environment_service.py`
의 바이트 호환 포팅. 라우터는 이 PR 에 포함하지 않는다 (#6 환경 라우터, #7
카탈로그 라우터는 별도 PR).

## PR Link

- Branch: `feat/environment-service-exc`
- PR: (이 커밋 푸시 시 발행)

## Summary

신규 패키지: `backend/service/environment/`
- `exceptions.py` — `EnvironmentNotFoundError`, `StageValidationError`
  (web 의 두 exception 과 정확히 동일 계약).
- `service.py` — `EnvironmentService`. 메서드 면적은 web 과 1:1:
  - 레거시 호환: `save`, `load`, `list_all`, `update`, `delete`,
    `export_json`, `import_json`.
  - v2 템플릿 CRUD: `create_blank`, `create_from_preset`, `update_manifest`,
    `update_stage`, `duplicate`, `instantiate_pipeline`.
  - `diff` 포함.
  - 내부 헬퍼 `_force_required_stages_active` / `_migrate_legacy_mock_provider`
    도 동일 구현.
- `__init__.py` — 공용 심볼 re-export.

`EnvironmentService.__init__(storage_path=None)` 이면 `ENVIRONMENT_STORAGE_PATH`
env 를 먼저 읽고, 없으면 `./data/environments` 로 폴백. web 과 같은 경로
규약이라 양쪽 앱이 같은 디렉토리를 공유할 수 있다.

`backend/main.py` lifespan 변경
- `EnvironmentService()` 인스턴스화 → `app.state.environment_service`
  로 저장. 라우터가 아직 없어도 이 시점부터 서비스 자체는 기동된다.
- 시작 로그에 `storage=...` 경로 표시.

docker-compose 5 개 + `.env.sample`
- `ENVIRONMENT_STORAGE_PATH=${ENVIRONMENT_STORAGE_PATH:-./data/environments}`
  환경변수 패스스루. 볼륨 마운트는 라우터 PR (#6) 에서 실제 UI 사용이 시작될 때
  함께 조정 (현재는 dev/core 의 bind mount `./backend:/app` 로 이미 퍼시스트됨).

## Verification

- `python -m py_compile` OK (service, exceptions, main.py).
- 실제 동작 스모크 (executor src + Geny backend 를 PYTHONPATH 에):
  - `create_blank('demo', ...)` → 16 스테이지 매니페스트 생성 ✅
  - `update_stage(env_id, 2, active=True)` → 정상 persist ✅
  - `list_all()` → UI 요약 shape 반환, `active_stage_count=5` 반영 ✅
  - `duplicate(env_id, 'demo-dup')` → 새 env 생성 ✅
  - `diff(a, b)` → 메타데이터 diff 4건 (id, name, created_at, updated_at) ✅
  - `update_stage('bogus', 1, ...)` → `EnvironmentNotFoundError` ✅
  - `delete(env_id)` 2회 → True → False (멱등) ✅

## Deviations

- web 은 `__init__(self, storage_path="./data/environments")` 로 path
  를 고정 기본값으로 받는다. Geny 는 path 를 `Optional[str]` 로 두고
  `ENVIRONMENT_STORAGE_PATH` env → `./data/environments` 순으로 해석해
  배포 환경별 덮어쓰기를 쉽게 만든다. 동작 기본값은 동일.
- `EnvironmentService.storage_path` 프로퍼티를 추가 (기동 로그에서 실제
  resolved 경로를 찍기 위함). 메서드 면적은 그대로.

## Follow-ups

- PR #6: `backend/controller/environment_controller.py` — 15 REST 엔드포인트
  (list/get/create/update/delete/import/export/diff/duplicate/stage PATCH/
  manifest PUT/instantiate 등). Auth 의존성을 Geny 스타일로 삽입.
- PR #7: `backend/controller/catalog_controller.py` — 5 stage 카탈로그
  엔드포인트. `geny_executor.core.introspect` 공용 함수 호출.
- PR #8: `CreateAgentSessionRequest` 에 `env_id`, `memory_config` 추가.
  `env_id` 지정 시 `environment_service.instantiate_pipeline(env_id)`
  경로로 분기 (GenyPresets bypass).
- prod docker-compose 에 named volume `geny-environments:/app/data/environments`
  을 PR #6 전후로 추가 (현재는 dev/core 만 bind mount 로 대체).
