# 09. Phase 4 — MemoryProvider attach to Pipeline Stage 2

## Scope

`plan/06` PR #9 / Phase 4 — flip the switch that wires a provisioned
`MemoryProvider` into a session's Pipeline Stage 2 (`ContextStage.provider`).
Gated behind `MEMORY_PROVIDER_ATTACH=true`; default `false` keeps the
legacy `SessionMemoryManager` authoritative until Phase 5 migrates each
layer (STM, LTM, Notes, Vector, Curated/Global).

## PR Link

- Branch: `feat/memory-attach-stage2`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/service/memory_provider/config.py`
- 새 함수 `is_attach_enabled()` — `MEMORY_PROVIDER_ATTACH` 환경변수를
  읽어 `1/true/yes/on` 이면 True. 기본 False.

`backend/service/langgraph/agent_session_manager.py`
- `create_agent_session` 의 provision 블록 뒤에 attach 분기 추가.
  `is_attach_enabled()` + provider 존재 + `agent._pipeline` 준비 완료
  이면 `registry.attach_to_pipeline(agent._pipeline, provider)` 호출.
- attach 실패는 세션 생성을 막지 않는다 (warning 로깅). provision 실패
  와 동일한 원칙: Phase 4 는 side effect 를 추가할 뿐 legacy 경로를
  깨뜨리지 않는다.

docker-compose 5 파일 + `.env.sample`
- `MEMORY_PROVIDER_ATTACH=${MEMORY_PROVIDER_ATTACH:-false}` 패스스루 추가.
- `.env.sample` 에 MEMORY_PROVIDER 블록 바로 아래 코멘트 + 샘플 라인.

## Verification

- `python3 -m py_compile` OK (config, agent_session_manager).
- 기본값 동작 (flag unset): attach 분기 진입 조건이 False → 기존 동작
  그대로 (PR #8 까지의 provisioning 만 수행).
- flag on + registry dormant: attach 분기가 진입 자체 안 함
  (provider is None 에서 걸러짐).
- flag on + ephemeral default + session 생성: `_memory_registry.
  attach_to_pipeline` 이 호출되어 `pipeline.get_stage(2).provider =
  provider` 로 세팅. 현재 MemorySessionRegistry 구현이 Stage 2 에 attach
  하는 경로를 이미 제공 (PR #3 `registry.py:131-139`).

## Deviations

- web 은 Phase 4 가 아닌 Phase 2 에서 attach 까지 기본값으로 켠다
  (greenfield, legacy 경로 없음). Geny 는 legacy path 가 여전히 authoritative
  이므로 flag 로 분리하고 기본 false.
- attach 실패를 warning 으로 소화. 엄격 모드 (`MEMORY_PROVIDER_ATTACH=strict`)
  는 필요 시 Phase 5 초기에 도입. 현재는 flag 단순화를 우선.
- `pipeline.get_stage(2)` 가 `provider` attribute 를 지원하지 않는 legacy
  preset 의 경우 `attach_to_pipeline` 은 no-op (기존 registry 구현이 이미
  `hasattr(stage, "provider")` guard). env_id 없이 GenyPresets 로 기동한
  세션은 attach 대상 자체가 없을 수 있으므로 warning 없이 조용히 넘어간다.

## Follow-ups

- PR #10-14 (Phase 5a-5e): 레이어별 migration. 각 단계에서
  `MEMORY_LEGACY_STM/LTM/NOTES/VECTOR/CURATED` flag 를 추가하고 읽기/쓰기
  경로를 provider 로 전환. attach flag 는 그대로 유지.
- Phase 4 수용 테스트 (plan/06): `memory_config` 지정 세션 → Stage 2
  descriptor 확인 + `POST /api/sessions/{id}/memory/retrieve` 가 실제
  chunk 반환.
- Phase 7 (PR #17): `/api/agents/{id}/memory/*` 를 provider 기반으로
  재구현. legacy endpoint 호환성을 유지하면서 내부만 교체.
