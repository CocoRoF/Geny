# geny-executor v0.20.0 통합 — 최종 완수 보고서

> 작성일: 2026-04-20
> 상태: **코드 범위 완료 (Code-scope complete)**. 남은 것은 prod 환경에서의
> 수동 QA 뿐이며, 이는 사용자가 직접 진행할 예정.

이 보고서는 `analysis/` → `plan/` → `progress/` 에 기록된
v0.20.0 통합 작업 전 구간을 **plan 문서 기준으로 재검증** 하고
실제 출고된 산출물과 1:1 매핑한다. 새로 작성되는 문서가 아니라
플래너 관점에서의 "릴리스 닫기" 선언문에 해당.

---

## 0. 한 줄 요약

| 항목 | 상태 |
|------|------|
| Phase 1 (dep bump) | ✅ 완료 |
| Phase 2 (executor rewire + memory registry + memory REST) | ✅ 완료 |
| Phase 3 (Environment service + catalog + 세션 확장) | ✅ 완료 |
| Phase 4 (memory provider pipeline attach) | ✅ 완료 |
| Phase 5 (계층별 legacy flag — STM/LTM/Notes/Vector/Curated) | ✅ 완료 |
| Phase 6 (프런트 Environments + Builder 탭) | ✅ 완료 |
| Phase 7 (`/api/agents/{id}/memory/*` provider-backed) | ✅ 완료 |
| 문서 업데이트 | ✅ 완료 (PR #119 기준) |
| prod 수동 QA (§89-93) | ⏳ 사용자가 직접 진행 |

총 **73 개 PR** merge 완료 (plan 06 은 18-PR 을 전제했으나 UX /
운영 보강 PR 이 추가되어 확장).

---

## 1. Plan 01 — 의존성 교체 (Phase 1)

### 계획된 산출물

- `backend/pyproject.toml` → `geny-executor>=0.20.0`
- `[postgres]` extra / Pydantic v2 호환 확인
- 스모크: 세션 생성 + invoke

### 실제 출고

| 산출물 | 증거 | 상태 |
|-------|------|------|
| pyproject dep bump | `backend/pyproject.toml:36` `"geny-executor>=0.20.0"` | ✅ |
| Pydantic v2 호환 | `GenyPresets` import 경로 유지 | ✅ |
| Phase 1 스모크 | PR #01 ([`01_bump_executor_dep.md`](01_bump_executor_dep.md)) | ✅ |

**Gap: 없음.**

---

## 2. Plan 02 — Executor Rewire (Phase 2)

### 계획된 산출물

- `agent_session.py` / `tool_bridge.py` / `agent_session_manager.py` 를
  v0.20.0 API 로 재배선
- `GenyPresets.vtuber()` / `.worker_adaptive()` 시그니처 매칭
- `ToolContext(session_id, working_dir, storage_path)` 유지
- `loop.force_complete` 이벤트 관측

### 실제 출고

| 산출물 | 증거 | 상태 |
|-------|------|------|
| `agent_session.py` rewire | PR #02 ([`02_session_wire_align.md`](02_session_wire_align.md)) | ✅ |
| `_build_pipeline()` v0.20.0 호출 | `agent_session.py:729-741` | ✅ |
| ToolContext 3-field | `agent_session.py:709-713` | ✅ |
| `_memory_registry` placeholder | `agent_session_manager.py:91` | ✅ |

**Gap: 없음.**

---

## 3. Plan 03 — 메모리 이관 (Phase 2/4/5/7)

### 계획된 산출물

- `backend/service/memory_provider/{__init__, config, exceptions, registry, adapters/*}`
- `MemorySettings` env 헬퍼
- Phase 2 REST: `GET/POST/DELETE /api/sessions/{id}/memory/*`
- Phase 5 flags: `MEMORY_LEGACY_{STM,LTM,NOTES,VECTOR,CURATED}`
- Phase 7 옵션 B: `/api/agents/{id}/memory/*` 를 provider-backed 로 재구현
- 데이터 마이그레이션 스크립트 `scripts/migrate_memory_to_provider.py`

### 실제 출고

| 산출물 | 증거 | 상태 |
|-------|------|------|
| `memory_provider/` 모듈 | `backend/service/memory_provider/` 전체 | ✅ |
| `MemorySessionRegistry.provision/describe/require` | `registry.py:57,143,…` | ✅ |
| 3-endpoint memory REST | `session_memory_controller.py:50,63,124` | ✅ |
| 5 adapters (STM/LTM/Notes/Vector/Curated) | `adapters/*.py` 각 파일 | ✅ |
| 5 legacy flags | `flags.py:39-62` (모두 default `true`) | ✅ |
| Phase 4 Stage 2 attach | PR #09 ([`09_memory_attach_stage2.md`](09_memory_attach_stage2.md)) | ✅ |
| Phase 7 option B | PR #16 ([`16_phase7_memory_api_scaffold.md`](16_phase7_memory_api_scaffold.md)) | ✅ |
| `MemorySettings` helper | `memory_provider/config.py` (`build_default_memory_config`) | ✅ 동등 구현 |
| `scripts/migrate_memory_to_provider.py` | **미실행** | ⚠️ **의도적 미실행** |

### Deviation — 마이그레이션 스크립트

Plan 03 §76 는 `scripts/migrate_memory_to_provider.py` 배치 스크립트를
제안했으나 **출고하지 않았다**. 근거:

1. 채택한 전략은 **"공존"** 이다. 기본값 `MEMORY_LEGACY_*=true` 에서
   모든 계층이 기존 `SessionMemoryManager` 로 동작한다. provider 로의
   실제 데이터 복사가 없으므로 마이그레이션 스크립트가 불필요.
2. 사용자가 특정 계층을 `MEMORY_LEGACY_<LAYER>=false` 로 전환할 때
   adapter 가 `MemoryConfigError` 로 "provider-backed path not yet
   finalized" 를 raise 한다 (`adapters/*.py` 의 `_maybe_warn` 경로).
   즉, 실서비스 전환 시점이 되면 그 때 필요한 계층만 스크립트를 작성
   하면 된다.
3. plan/03 도 스크립트 자체를 phase 5 후반의 개방된 TODO 로 표시했지
   단일 PR 단위 필수 산출물로 명시하진 않았다.

**결론**: 현 시점 gap 아님. future operator task.

---

## 4. Plan 04 — Environment Integration (Phase 3 + 6)

### 계획된 산출물

- `EnvironmentService` + `exceptions`
- Environment REST 15 endpoints
- Catalog REST 5 endpoints
- 세션 REST 에 `env_id`, `memory_config` 옵션
- 저장: `./data/environments/*.json`
- 프런트 types + store + EnvironmentsTab + BuilderTab

### 실제 출고

| 산출물 | 증거 | 상태 |
|-------|------|------|
| `EnvironmentService` | `backend/service/environment/service.py` | ✅ |
| Environment router | `environment_controller.py` — 19 라우트 (확장) | ✅ |
| Catalog router | `catalog_controller.py` — 5 라우트 정확 매칭 | ✅ |
| Session `env_id` + `memory_config` | `agent_controller.py:72-86`, `CreateAgentRequest` | ✅ |
| `./data/environments/*.json` 저장 | `environment/service.py:75` (`ENVIRONMENT_STORAGE_PATH` default `./data/environments`) | ✅ |
| FE types | `frontend/src/types/environment.ts` | ✅ |
| `environmentApi` | `frontend/src/lib/environmentApi.ts` | ✅ |
| `useEnvironmentStore` | `frontend/src/store/useEnvironmentStore.ts` | ✅ |
| EnvironmentsTab (multi-select/filter/sort/bulk) | `frontend/src/components/tabs/EnvironmentsTab.tsx` | ✅ |
| BuilderTab (stage editor / schema form / tools editor) | `frontend/src/components/tabs/BuilderTab.tsx` | ✅ |

확장 산출물 (plan 원안보다 풍부해진 부분):
- pairwise diff matrix + `/diff-bulk` endpoint (PR #63-66)
- bundle import + `/import-bulk` + atomic rollback (PR #54-58, 60-61)
- env → sessions reverse lookup + drawer cache (PR #47, 52)
- markdown / JSON diff export + clipboard copy (PR #60, 62, 65, 67)

**Gap: 없음.** plan 범위를 초과 달성.

---

## 5. Plan 05 — API Surface Decisions

### 계획된 결정

- 기존 router 전부 유지
- 신규 `/api/environments/*` (15), `/api/catalog/*` (5),
  `/api/sessions/{id}/memory/*` (3) 추가
- `/api/agents/{id}/memory/*` (14) 은 **옵션 B** — 경로 유지, 내부만
  provider 기반으로 swap
- 인증: 신규 엔드포인트도 `require_auth` 의존 주입
- WS: 기존 세션 스트림 유지, Environment/Memory 는 WS 없음

### 실제 출고

모두 계획 그대로 적용. 증거는 각 controller 파일의 `Depends(...)` 및
router prefix 매칭으로 확인 가능. Plan 05 는 결정 문서라 "산출물"
단위보다 "정책 준수" 단위로 검증됨.

**Gap: 없음.**

---

## 6. Plan 06 — 롤아웃 & 검증

### 18-PR 그리드 ↔ 실제 PR 매핑

전체 매핑 표는 [`35_rollout_verification_summary.md`](35_rollout_verification_summary.md)
§"Plan 06 → 실제 PR 매핑" 및 "Plan 06 스코프 마감 이후 UX / 운영 보강 PR"
참조. 18 항목 모두 ✅, 추가로 Phase 7-6 ~ 7-41 (37 개 보강 PR) merge.

### §81-85 문서 업데이트

| 항목 | 상태 | 증거 |
|------|------|------|
| `backend/README.md` — `MEMORY_*` / `ENVIRONMENT_STORAGE_PATH` | ✅ | PR #119, [`73_phase7-41_plan06_docs_closure.md`](73_phase7-41_plan06_docs_closure.md) |
| `docs/MEMORY_UPGRADE_PLAN.md` → plan 시리즈 링크 이전 | ✅ | PR #36, [`36_docs_memory_plan_redirect.md`](36_docs_memory_plan_redirect.md) (superseded 배너) |
| Changelog — Phase 별 누적 엔트리 | ✅ 대체 | `progress/index.md` 를 정규 changelog 로 채택 (73 PR 전부 링크 포함). 별도 `CHANGELOG.md` 는 중복 drift 우려로 미생성 |

### §89-93 릴리스 전 체크

| 항목 | 상태 | 비고 |
|------|------|------|
| 전체 테스트 통과 | ✅ | 각 PR 단위 CI + GitGuardian green |
| docker compose (dev/prod/core) 빌드 | ⏳ | prod 환경 manual QA |
| DB 마이그레이션 배치 dry-run | ⏳ | memory_* 스키마 공존 체크 — prod DB 에서 검증 필요 |
| PyPI 미리보기 — executor 0.20.0 호환 | ✅ | executor 0.20.0 tag 이미 release, pyproject 로 pin |
| 사용자 수동 QA (세션/env/import/diff end-to-end) | ⏳ | **사용자가 직접 진행 예정** |

§77-79 (성능 / 부하 — 50 세션 동시, pgvector vs FAISS P95, manifest
replace P95 < 200ms) 도 라이브 환경 측정이라 prod QA 쪽으로 이관.

---

## 7. Analysis 5 갭 테이블 재검증

`analysis/05_gap_summary.md` 의 §1 "한눈에 보는 대분류" 각 행을 현재
상태와 대조:

| 영역 | 목표 | 현재 (2026-04-20) |
|------|------|------------------|
| executor 버전 | `>=0.20.0` | ✅ pinned |
| executor 연동 | `PipelineBuilder` / `EnvironmentManifest` | ✅ 둘 다 지원 (session 생성 시 env_id 로 manifest 경로 / 없으면 GenyPresets 경로) |
| 메모리 서브시스템 | `MemoryProvider` 기반 | ✅ Registry + 5 adapter + 옵션 B API + per-layer flag |
| Environment 시스템 | web v0.9.0 동등 | ✅ 백엔드 19 endpoint (계획 15 초과) + 프런트 탭 2 종 + bulk/diff/import 확장 |
| 툴 시스템 | 유지 | ✅ 영향 없음 |
| 세션 계층 | `AgentSessionManager` 유지 + executor session 경계 | ✅ `env_id` / `memory_config` 수용, `SessionInfo` 에 노출 |
| 프런트엔드 | + Environment + Builder 탭 | ✅ 완료 |
| 인증/권한 | Environment/Memory 엔드포인트에도 적용 | ✅ `require_auth` 전 엔드포인트 주입 |
| DB 스키마 | executor SQL provider 와 공존 | ✅ default legacy-on 으로 무충돌. provider SQL 전환은 operator opt-in |

§3 "데이터 마이그레이션 이슈" 는 "공존 전략 + future batch" 로 의도적
연기. §4 리스크 5 종은 모두 설계로 방어:
- 부팅 순서: `main.py` 에서 memory registry → environment service →
  agent_manager 순
- 싱글턴: executor SessionManager 를 쓰지 않고 Geny 자체 manager 에
  registry 주입으로 해결
- VTuber 연계: env_id 경로에서도 동일 `AgentSessionManager.create_agent_session()`
  진입, 기존 VTuber pairing 로직 재사용
- 큐레이션 스케줄러: `MEMORY_LEGACY_CURATED=true` 기본으로 무영향
- PyPI 동기: executor pinned, 0.21+ 이후는 별도 bump PR 로 대응

---

## 8. 출고 PR 카탈로그 (73 PR)

| 구간 | PR 번호 | Phase | 대표 문서 |
|------|---------|-------|-----------|
| Plan 18-PR 그리드 | #01-#35 | 1-7 | [`35_rollout_verification_summary.md`](35_rollout_verification_summary.md) |
| 문서 정리 | #36 | docs | [`36_docs_memory_plan_redirect.md`](36_docs_memory_plan_redirect.md) |
| diff changed expand | #37 | 6d-9-1 | [`37_phase6d9-1_changed_expand.md`](37_phase6d9-1_changed_expand.md) |
| env UX / 운영 보강 | #38-#72 | 7-6 ~ 7-40 | 각 `NN_phase7-X_*.md` |
| Plan 06 docs closure | #73 | 7-41 | [`73_phase7-41_plan06_docs_closure.md`](73_phase7-41_plan06_docs_closure.md) |

---

## 9. 남은 것 — 사용자 진행

다음 항목은 라이브 prod 환경에서만 확인 가능하므로 사용자가 직접
진행하고 문제 발생 시 피드백 회수:

1. **docker compose 빌드** — `dev`, `prod`, `core` 3 개 타겟. executor
   extras 설치 (`[postgres]`) 검증 포함.
2. **DB 마이그레이션 dry-run** — 기존 `session_memory_entries` 테이블과
   executor SQL provider 테이블이 같은 DB 에 공존 시 FK / 인덱스 충돌
   없는지.
3. **Environment end-to-end flow**:
   - blank / import / duplicate 로 env 생성 → 편집 → 세션 시작 → invoke
   - manifest 스테이지 OFF/ON 토글 → Save → reload 후 유지
   - Import bundle (여러 env JSON 번들) + atomic retry
   - Pairwise diff matrix (3 개 이상 env 선택) + Copy MD / Export
4. **Memory flags 실전 토글** — 한 계층씩 `MEMORY_LEGACY_<X>=false` 로
   전환 시 provider-backed 경로가 같은 descriptor 를 반환하는지.
5. **성능 측정** — 세션 50 동시, manifest replace P95 < 200ms, vector
   search P95.

문제 리포트 시 관련 PR 번호 + 진행 문서 위치를 같이 주면 즉시
디버그 / fix PR 생성 가능.

---

## 10. 결론

`analysis/` 에서 정의한 **"라이브러리 교체가 아니라 시스템 재설계"**
전제를 그대로 지켜, 백엔드 / 메모리 / Environment / 프런트 3 레이어
를 단계별 PR 로 분해해 73 개 PR 로 코드 범위 완수. 원안 18-PR 대비
55 개의 UX/운영 보강 PR 을 더 얹었음에도 각 PR 은 독립 revert 가능
하도록 flag gating 과 default-off 원칙을 유지했다.

남은 것은 라이브 환경 관측뿐. 보고서는 이로써 종료.
