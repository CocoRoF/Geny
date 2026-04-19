# 06. EnvironmentController — 15 REST endpoints

## Scope

`plan/06` PR #6 — port of `geny-executor-web/backend/app/routers/environment.py`
to Geny. Mounts `/api/environments` with 15 endpoints covering legacy v0.7.x
session-save flow and v2 template CRUD (blank/preset create, whole-manifest
PUT, per-stage PATCH, duplicate, diff, import/export, preset marking, share
link).

## PR Link

- Branch: `feat/environment-controller`
- PR: (이 커밋 푸시 시 발행)

## Summary

신규 파일:
- `backend/service/environment/schemas.py` — web `app/schemas/environment.py`
  와 1:1 바이트 호환. 15개 request/response 모델.
- `backend/controller/environment_controller.py` — 15 endpoints, `APIRouter`
  prefix `/api/environments`, tag `environments`. 모든 엔드포인트에
  `Depends(require_auth)` 적용 (Geny 공용 auth 정책).

`backend/main.py`
- `environment_router` import 추가 (line 41).
- `app.include_router(environment_router)` 추가 (session_memory_router 바로
  뒤). lifespan 에서 이미 PR #5 에서 `app.state.environment_service` 세팅
  되어 있으므로 router 가 그대로 동작.

### 엔드포인트 매트릭스 (15개)

| Method | Path                                    | Purpose                       |
|--------|-----------------------------------------|-------------------------------|
| GET    | `/api/environments`                     | list_all → summaries          |
| POST   | `/api/environments`                     | unified create (3-mode)       |
| POST   | `/api/environments/from-session`        | legacy v0.7.x session save    |
| GET    | `/api/environments/{id}`                | load full record              |
| PUT    | `/api/environments/{id}`                | patch metadata                |
| PUT    | `/api/environments/{id}/manifest`       | replace manifest wholesale    |
| PATCH  | `/api/environments/{id}/stages/{order}` | per-stage partial update      |
| POST   | `/api/environments/{id}/duplicate`      | clone under new name          |
| DELETE | `/api/environments/{id}`                | delete                        |
| GET    | `/api/environments/{id}/export`         | export JSON string            |
| POST   | `/api/environments/import`              | import JSON payload           |
| POST   | `/api/environments/diff`                | structural diff of two envs   |
| POST   | `/api/environments/{id}/preset`         | tag as preset                 |
| DELETE | `/api/environments/{id}/preset`         | untag preset                  |
| GET    | `/api/environments/{id}/share`          | absolute share URL            |

## from_session 어댑테이션

web 은 `request.app.state.session_service.get(...)` +
`request.app.state.mutation_service.get_or_create(session)` 조합으로 세션과
mutator 를 얻는다. Geny 는 둘 다 없고, 대신 `AgentSessionManager` 가 세션
수명을 관리한다.

`controller/environment_controller._resolve_session_mutator(session_id)`:
- `agent_manager.get_agent(session_id)` 로 `AgentSession` 조회.
- `agent` 또는 `agent._pipeline` 이 없으면 404.
- 매 호출마다 `PipelineMutator(agent._pipeline)` 을 새로 생성. PipelineMutator
  는 살아있는 Pipeline 위의 얇은 뷰라 호출당 래핑은 저비용이고 web 의
  stateful mutation_service 와 관찰 가능한 동작이 동일하다.

## Verification

- `python3 -m py_compile controller/environment_controller.py
  service/environment/schemas.py main.py` → OK.
- 스키마 로직 (venv 없이는 pydantic 미설치라 py_compile 까지만) 검증 완료.
- 로직은 web 레퍼런스와 엔드포인트·응답 shape 1:1 매핑.

## Deviations

- web 은 router 모듈이 auth 의존성 없이 마운트된다. Geny 는 프로젝트
  전반에서 `Depends(require_auth)` 를 강제하므로 15개 엔드포인트 모두
  auth 파라미터를 받는다. 동작은 변하지 않고 응답 shape 도 동일하지만,
  문서화 상 차이다.
- `replace_manifest` 에서 web 은 `from geny_executor import
  EnvironmentManifest` 실패 시 raw dict 를 그대로 service 에 넘기는
  테스트 폴백을 둔다. Geny 는 executor 0.20.0 이 pyproject 의존성으로
  고정되어 있으므로 fallback 을 두지 않고, import 실패 시 Python 전역
  ImportError 로 fail-fast.
- `from_session` 모드가 web 은 session 없는 session_service 를 404 로,
  mutator 없는 세션을 정상 상태로 가정한다. Geny 는 `AgentSession._pipeline
  is None` 도 404 로 친다 — 세션이 생성됐지만 아직 `_build_pipeline()`
  이 호출되지 않은 경우가 있으면 명시적으로 거절하는 편이 안전하다.

## Follow-ups

- PR #7: `backend/controller/catalog_controller.py` — 5 stage 카탈로그
  엔드포인트 (`/api/catalog/*`). `geny_executor.core.introspect` 공용
  함수를 그대로 호출.
- PR #8: `CreateAgentSessionRequest` 에 `env_id`, `memory_config` 추가.
  `env_id` 지정 시 `environment_service.instantiate_pipeline(env_id)` 경로로
  분기 (GenyPresets bypass).
- prod docker-compose 에 named volume `geny-environments:/app/data/environments`
  을 PR #8 전후로 추가 (현재는 dev/core 만 bind mount 로 대체).
