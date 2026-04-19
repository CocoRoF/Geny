# 08. CreateSession request wire — env_id + memory_config

## Scope

`plan/06` PR #8 — extend `CreateAgentRequest` with two optional fields
(`env_id`, `memory_config`) and thread them through `AgentSessionManager`
→ `AgentSession` so that:

1. An `env_id` at create time bypasses `GenyPresets` and uses the stored
   `EnvironmentManifest` to instantiate the Pipeline
   (`Pipeline.from_manifest`).
2. A `memory_config` override (or the process-wide default set via
   `MEMORY_PROVIDER`) provisions a `MemoryProvider` for the session at
   create time — observable immediately through the Phase 2 REST surface.
   Actual Stage 2 attachment still waits for PR #9 (Phase 4).

## PR Link

- Branch: `feat/session-env-memory-wire`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/controller/agent_controller.py`
- `CreateAgentRequest` 에 `env_id: Optional[str]` / `memory_config:
  Optional[dict]` 두 필드 추가.
- `create_agent_session` 핸들러가 둘을 그대로 `agent_manager.create_agent_session`
  에 전달.
- `LookupError` (= `EnvironmentNotFoundError`) → 404 매핑 추가.

`backend/service/langgraph/agent_session_manager.py`
- `self._environment_service = None` 필드 + `set_environment_service(svc)`
  setter 추가. 기존 `set_memory_registry` 와 동일 패턴.
- `create_agent_session(..., env_id=None, memory_config=None)` signature
  확장.
- `env_id` 지정 시 `environment_service.instantiate_pipeline(env_id,
  api_key=api_key)` 를 호출해 `prebuilt_pipeline` 을 미리 생성. api_key 는
  env → APIConfig 순으로 해석, 둘 다 없으면 `ValueError`.
- 세션 등록 뒤 `memory_registry.provision(session_id, override=memory_config)`
  를 호출. registry 가 dormant 이면 조용히 스킵 — 기존 동작 유지.

`backend/service/langgraph/agent_session.py`
- `__init__` 에 `env_id`, `memory_config`, `prebuilt_pipeline` 파라미터 추가.
  인스턴스 필드로 저장 (`self._env_id`, `self._memory_config`,
  `self._prebuilt_pipeline`).
- `_build_pipeline` 에 env_id 분기: `prebuilt_pipeline` 이 있으면 그대로
  `self._pipeline` 에 세팅하고 `self._preset_name = f"env:{env_id}"` 로
  태깅. GenyPresets/ToolRegistry 브랜치는 건너뛴다.

`backend/main.py`
- lifespan 에서 `EnvironmentService` 생성 직후
  `agent_manager.set_environment_service(environment_service)` 호출.

## Verification

- `python3 -m py_compile` OK (4 파일).
- signature-level: request → manager → session 로 두 필드가 전파됨을
  grep/read 로 확인.
- env_id 없는 기본 케이스는 기존 create flow 와 동일: prebuilt_pipeline is
  None → GenyPresets 브랜치가 그대로 돎.

## Deviations

- web 의 `session_service.create(pipeline, preset, memory_config)` 는 단일
  호출 안에서 memory 프로비저닝을 동시에 수행. Geny 는 `AgentSession.create`
  가 먼저 반환된 뒤 `self._local_agents[session_id]` 에 등록되므로 provision
  이 그 이후에 와야 안전하다 — 그래서 호출 순서만 재배치했고, 의미는 동일.
- env_id 플로우의 tool/mcp 지원: web 은 manifest 에 포함된 config 만 사용.
  Geny 도 동일 — `prebuilt_pipeline` 이 있으면 `geny_tool_registry` /
  `mcp_config` 가 pipeline 에 바인딩되지 않는다. 이는 의도된 단순화: env 기반
  세션은 manifest 로 모든 것을 기술한다는 계약.
- provision 실패는 warning 로깅 후 세션 생성을 계속 진행. web 은 400 으로
  실패시킨다. Geny 는 memory registry 의 상태가 빠르게 변하는 legacy 호환
  경로가 있어 best-effort 로 두는 편이 안전. 다음 PR 에서 strict 모드 flag
  도입 여부를 검토한다.

## Follow-ups

- PR #9 (Phase 4): `AgentSessionManager.create_agent_session` 에서 provider
  를 pipeline Stage 2 에 attach (`registry.attach_to_pipeline(pipeline,
  provider)`). 이 시점부터 `ContextStage.provider` 가 세션별로 활성화.
- Phase 5 (PRs #10-14): 레이어별 memory 마이그레이션 (STM, LTM, Notes,
  Vector, Curated/Global). feature flag 로 legacy ↔ provider 양쪽 경로를
  공존시켜 단계적으로 전환.
- Frontend (PR #16): Environment 탭에서 env_id 를 선택해 세션을 생성하는 UI.
- prod docker-compose 에 `geny-environments:/app/data/environments` named
  volume 추가 (PR #8 범위에는 없음; Environment UI 가 실제로 사용되는
  PR #16 직전에 추가).
