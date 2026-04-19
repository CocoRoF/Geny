# 00. 전체 마이그레이션 전략

## 핵심 원칙

1. **호환 유지 → 치환 → 풍부화** 3 단계를 순차 진행한다. 각 단계가 끝나면 메인 브랜치가 항상 배포 가능한 상태여야 한다.
2. **파괴 없이 병렬 존재**시킨다. 레거시 `SessionMemoryManager` 와 `MemoryProvider` 가 한 세션 안에서 동시에 살아있을 수 있도록 설계한다 (어댑터 전략).
3. **데이터 손실 금지**. 마이그레이션 중 DB 와 파일 계층을 모두 읽기 가능 상태로 유지. 이전 포맷은 읽기전용 아카이브로 보존.
4. **작은 PR + 빈번한 머지**. 사용자 지침 "지속적으로 main 에 pr 을 넣어가면서 진행" 을 따른다. 각 PR 은 독립 녹색 CI + 스모크 통과.
5. **기능 기획은 `geny-executor-web` 을 거울로 삼는다**. 새 기능의 정답은 web 의 해당 구현이다.

## 단계

### Phase 1 — 의존성 + 호환층 (Rewire lite)
목표: executor 0.20.0 로 점프. 기존 사용자 경험 불변.

- `pyproject.toml` → `geny-executor>=0.20.0`.
- `GenyPresets` 유지하되 v0.20.0 의 `GenyPresets` 가 내부적으로 `PipelineBuilder` 를 쓰므로 Geny 호출부는 그대로 통과한다 (스모크).
- 필수: 신규 스테이지 (`s08_think`, `s11_agent`, `s12_evaluate`) 가 활성화되지 않도록 VTuber/Worker 프리셋 시그니처 확인.
- 산출물: 1 개 PR — `chore(dep): bump geny-executor to 0.20.0 + smoke` .

### Phase 2 — Memory REST + Registry 도입
목표: `MemoryProvider` 파사드를 세션 밖에 세워 **새 REST 표면**만 노출.

- `backend/service/memory_provider/registry.py` 신설 (web 의 `MemorySessionRegistry` 등가).
- 부팅시 `MEMORY_PROVIDER=ephemeral` 기본. Geny 의 기존 `SessionMemoryManager` 는 그대로 유지.
- 신규 REST `/api/sessions/{id}/memory` (3 endpoints). 기존 `/api/agents/{id}/memory/*` 는 존속.
- 이 단계에서는 실제 파이프라인에 프로바이더를 attach 하지 **않는다** — 데이터 경로 충돌을 피함.
- 산출물: 1~2 개 PR.

### Phase 3 — Environment Service + Catalog (백엔드 only)
목표: web v0.9.0 의 Environment 백엔드 상당품 이식.

- `backend/service/environment/service.py` + `exceptions.py`.
- `backend/controller/environment_controller.py` (15 endpoints).
- `backend/controller/catalog_controller.py` (5 endpoints).
- 저장 경로: `./data/environments/*.json`.
- 기존 Geny 세션 REST 에 `env_id` + `memory_config` 옵션 추가.
- 산출물: 2~3 개 PR (Service / Router / 세션 확장).

### Phase 4 — Memory Provider 를 파이프라인에 attach
목표: 세션 생성시 `MemoryProvider` 를 실제로 Stage 2 에 연결. 레거시 매니저는 동시 동작.

- `AgentSession.create()` 에서 `memory_registry.provision(session_id, override=memory_config)` 호출.
- `attach_to_pipeline(pipeline, provider)` 실행.
- 기존 `SessionMemoryManager` 와 **동시 존재**. 읽기 경로는 둘 다 시도, 쓰기는 레거시 우선.
- 산출물: 1 개 PR.

### Phase 5 — 레거시 메모리 계층 → Provider 완전 이관
목표: 지정된 계층 (STM/LTM/Notes/Vector) 을 executor 프로바이더로 대체.

- 단계별 feature flag (`MEMORY_LEGACY_STM=off` 등).
- DB 데이터 마이그레이션 배치 (`scripts/migrate_memory_to_provider.py`).
- `CurationEngine` / `ThinkingTrigger` / `record_execution` 의 읽기/쓰기 경로 치환.
- 산출물: 3~5 개 PR (계층별).

### Phase 6 — 프런트엔드 Environment + Builder UI
목표: web 의 2 탭 (Environment 탭 / Builder 탭) 을 Geny 프런트에 이식.

- `frontend/src/app/environments/page.tsx` + 컴포넌트 세트.
- `frontend/src/app/builder/page.tsx` + StageList/StageCard.
- 상태관리: Next.js + (Zustand 추정 — 확인 필요) 또는 React Context.
- 산출물: 2~3 개 PR.

### Phase 7 — 메모리 UI 업데이트 & 정리
- 신규 `/api/sessions/{id}/memory` 를 UI 에 노출 (Descriptor + Retrieve 스펙).
- 레거시 `/api/agents/{id}/memory/*` 엔드포인트 정책 결정 (deprecate? 유지?).
- 산출물: 1~2 개 PR.

## 순서의 근거

- Phase 1 먼저: 의존성 교체가 이후 모든 단계의 전제.
- Phase 2 를 Phase 3 보다 먼저: Memory 는 Environment 없이도 독립 동작. Environment 가 memory_config 를 전달하려면 Registry 가 먼저 있어야 함.
- Phase 4 가 Phase 3 직후: Environment 로 세션 생성시 memory_config 를 받을 수 있게 된 직후 실제 attach.
- Phase 5 는 Phase 4 이후: 파이프라인이 프로바이더를 alrdy 사용 중인 상태에서 레거시 매니저만 거둬들인다.
- Phase 6 을 마지막 즈음: UI 는 백엔드가 안정화된 이후가 안전.

## 되돌리기 정책

| 상황 | 복구 |
|------|------|
| Phase 1 후 스모크 실패 | pyproject rollback + `GenyPresets` 호환 이슈 조사 |
| Phase 4 에서 메모리 attach 실패 | `MEMORY_PROVIDER=ephemeral` 기본 / attach 단계 bypass 옵션 |
| Phase 5 각 계층 이관 실패 | feature flag 로 해당 계층만 레거시 복귀 |
| DB 마이그레이션 실패 | 신규 테이블 drop + Geny 원본 테이블 복원 |

## 수용 기준 (overall)

- 기존 Geny UX (agent/chat/vtuber/tts/live2d) 가 깨지지 않음.
- `/api/environments/*`, `/api/catalog/*`, `/api/sessions/{id}/memory/*` 가 web 과 동일한 스키마로 동작.
- `Pipeline.from_manifest(env_manifest)` 로 생성된 세션이 Geny 의 툴·메모리 파이프라인에서 정상 실행.
- 데이터 마이그레이션이 멱등 (idempotent).
- CI 통과 + docker compose up 통과.
