# 03. MemorySessionRegistry + /api/sessions/{id}/memory

## Scope

`plan/06` 의 PR #3 — executor v0.20.0 `MemoryProviderFactory` 를 Geny 에
처음으로 배선하는 순수 additive PR. 레거시 `/api/agents/{id}/memory/*`
경로는 이 PR 에서 건드리지 않는다.

## PR Link

- Branch: `feat/memory-session-registry`
- PR: (이 커밋 푸시 시 발행)

## Summary

신규 패키지: `backend/service/memory_provider/`
- `exceptions.py` — `MemoryConfigError`, `MemorySessionNotFoundError`.
- `registry.py` — `MemorySessionRegistry`. web 의 같은 클래스와 동일 계약
  (provision/get/require/get_config/release/attach_to_pipeline/describe/default_config).
- `schemas.py` — pydantic 모델 4종 (`MemoryDescriptorResponse`,
  `MemoryRetrievalRequest`, `MemoryRetrievalResponse`, `MemoryClearResponse`).
- `__init__.py` — 공용 심볼 re-export.

신규 컨트롤러: `backend/controller/session_memory_controller.py`
- `GET /api/sessions/{session_id}/memory` → descriptor (404 / 503 / 200).
- `POST /api/sessions/{session_id}/memory/retrieve` → `MemoryRetrievalResponse`
  (Capability.SEARCH 미지원이면 409).
- `DELETE /api/sessions/{session_id}/memory` → `{"cleared": true}`.

`backend/main.py` 변경
- 신규 라우터 import + `include_router`.
- lifespan 에서 `MemorySessionRegistry(default_config=None)` 을 만들어
  `app.state.memory_registry` 에 보관하고 `agent_manager.set_memory_registry()`
  로도 전달. 기본값 None 이므로 provision() 이 None 을 리턴 → 새 엔드포인트는
  현재 **세션이 있어도 404 "No memory provider attached"** 로 응답한다.
  MEMORY_* env 가 붙는 PR #4 에서부터 실제 provider 가 만들어짐.

## Verification

- `python -m py_compile` 통과 (main.py, controller, 4 service 모듈).
- 런타임 스모크 (executor src 를 PYTHONPATH 에 올리고 레지스트리만 직접 호출):
  - 기본 config=None 에서 `provision` → None ✅
  - config `{"provider":"ephemeral"}` → 실제 provider 빌드 + `describe()`
    가 `ephemeral/session/[link,read,search,snapshot,write]` 반환 ✅
  - `release` 2회 호출에서 True → False (멱등) ✅
  - 잘못된 override 에서 `MemoryConfigError` ✅
  - `describe("missing")` 에서 `MemorySessionNotFoundError` ✅
- pydantic schemas 실제 검증은 앱 구동 환경 (CI / docker) 에서.

## Deviations

- web 은 `backend/app/services/memory_service.py` 였다. Geny 는 이미
  `service.memory.*` 를 레거시 매니저에 쓰고 있어 충돌을 피하려고
  `service.memory_provider` 로 네임스페이스를 분리. `__init__.py`
  re-export 규약만 일치시켰다.
- web 은 `app.state.session_service` 로 세션 존재를 확인하지만 Geny 는
  `controller.agent_controller.agent_manager.has_agent()` 싱글턴 호출을
  쓴다. 동일한 "404 Session not found" 시나리오 유지.

## Follow-ups

- PR #4 (`plan/06` 엔트리 4): `MEMORY_*` env → 기본 config 해석기
  (`service.memory_provider.config` 신설) + docker-compose.* 환경변수 패스스루.
  이때부터 `session_memory_controller` 가 실제 200 응답 가능.
- Phase 4 에서 `AgentSessionManager.create_agent_session` 뒤에
  `memory_registry.provision(...)` + `attach_to_pipeline()` 를 호출하도록
  분기 삽입.
- Phase 7 에서 레거시 `/api/agents/{id}/memory/*` 의 내부를 프로바이더
  기반으로 교체.
