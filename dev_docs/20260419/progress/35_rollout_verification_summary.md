# 35. Rollout & Verification — integration summary

## Scope

[`plan/06_rollout_and_verification.md`](../plan/06_rollout_and_verification.md)
의 18-PR 롤아웃 그리드와 실제 출고된 34 개 PR 의 매핑. 플랜 대비
무엇이 ship 됐고 무엇이 스코프에서 밀렸는지 기록한다. 이 문서가
"플래너 관점에서의 최종 통합" 역할 — 단일 PR 로 코드 변경 없이
플랜 / 진행 / 남은 할 일의 링크만 정리한다.

## PR Link

- Branch: `plan-06-rollout-verification-integration`
- PR: (이 커밋 푸시 시 발행)

## Plan 06 → 실제 PR 매핑

| plan 06 # | 제목 (계획) | 진행 문서 | 상태 |
|-----------|------------|-----------|------|
| 1 | bump geny-executor to 0.20.0 | [01](01_bump_executor_dep.md) | ✅ |
| 2 | align pipeline wiring | [02](02_session_wire_align.md) | ✅ |
| 3 | MemorySessionRegistry + sessions/{id}/memory | [03](03_memory_session_registry.md) | ✅ |
| 4 | MEMORY_* env + Settings + compose | [04](04_memory_env_plumbing.md) | ✅ |
| 5 | EnvironmentService + exceptions | [05](05_environment_service.md) | ✅ |
| 6 | environment_controller (15 endpoints) | [06](06_environment_controller.md) | ✅ |
| 7 | catalog_controller (5 endpoints) | [07](07_catalog_controller.md) | ✅ |
| 8 | session accepts env_id + memory_config | [08](08_session_env_memory_wire.md) | ✅ |
| 9 | Stage 2 memory attach | [09](09_memory_attach_stage2.md) | ✅ |
| 10 | STM adapter (flag) | [10](10_phase5_flag_scaffold.md), [11](11_phase5a_stm_adapter.md) | ✅ |
| 11 | LTM adapter | [12](12_phase5b_ltm_adapter.md) | ✅ |
| 12 | Notes adapter | [13](13_phase5c_notes_adapter.md) | ✅ |
| 13 | Vector adapter | [14](14_phase5d_vector_adapter.md) | ✅ |
| 14 | Curated/Global adapter | [15](15_phase5e_curated_adapter.md) | ✅ |
| 15 | FE Environment tab + store | [17](17_phase6a_frontend_env_types_api.md) → [22](22_phase6e_session_env_selector.md) | ✅ |
| 16 | FE Builder tab | [23](23_phase6d1_catalog_api_fix.md) → [29](29_phase6d7_manifest_import_overwrite.md), [33](33_phase6d9_import_diff_preview.md), [34](34_phase6d8_import_backup.md) | ✅ |
| 17 | /api/agents/{id}/memory/* provider-backed | [16](16_phase7_memory_api_scaffold.md) | ✅ |
| 18 | docs + release notes | 이 문서 + `progress/index.md` 갱신 | ✅ |

추가로 ship 된 것 (계획 #16–17 의 연장선):
- **30** Phase 7-3 — CreateSessionModal 에서 memory_config 오버라이드.
- **31** Phase 7-4 — SessionInfo 에 `env_id` + `memory_config` 노출.
- **32** Phase 7-5 — InfoTab env row → 드로어 링크.
- **33** Phase 6d-9 — Import manifest diff preview (클라이언트).
- **34** Phase 6d-8 — Import 시 현재 manifest 자동 백업.

Plan 06 스코프 마감 이후 UX / 운영 보강 PR (Phase 7-6 ~ 7-40):

| PR | Phase | 요약 |
|----|-------|------|
| 36 | docs | `docs/MEMORY_UPGRADE_PLAN.md` superseded 배너. |
| 37 | 6d-9-1 | Import diff "changed" 항목 before/after expand. |
| 38 | 7-6 | Environment 카드 "N sessions bound" badge. |
| 39 | 7-7 | Drawer "Linked sessions" 섹션 + drill-down. |
| 40 | 7-8 | ImportManifestModal drag-over 시각 피드백. |
| 41 | 7-9 | ImportEnvironmentModal (백업 JSON → 새 환경). |
| 42 | 7-10 | Empty state 에 Import 버튼 병치. |
| 43 | 7-11 | Linked sessions 헤더 running/error/other breakdown. |
| 44 | 7-12 | BuilderTab "Back to Environments" breadcrumb. |
| 45 | 7-13 | Drawer 헤더 env id copy 버튼. |
| 46 | 7-14 | Environments 카드 에러 세션 배지 (red tint). |
| 47 | 7-15 | `GET /api/environments/{id}/sessions` reverse-lookup. |
| 48 | 7-16 | Bulk `GET /session-counts` + 카드 그리드 권위화. |
| 49 | 7-17 | Environments 탭 검색/필터/정렬 toolbar. |
| 50 | 7-18 | Session counts 를 store 로 올리고 자동 재조회. |
| 51 | 7-19 | Focus/visibility TTL 재조회 게이트. |
| 52 | 7-20 | Drawer sessions store cache + refresh. |
| 53 | 7-21 | Bulk multi-select + bulk delete/export. |
| 54 | 7-22 | Bundle 포맷 자동 감지 + 순차 import. |
| 55 | 7-23 | Bulk "Compare 2" + "Has deleted" 필터. |
| 56 | 7-24 | `POST /api/environments/import-bulk` + 클라 단일 호출. |
| 57 | 7-25 | Bulk import 상한 + bulk delete 세션 바인딩 경고. |
| 58 | 7-26 | Bundle entry 이름 인라인 편집 + 성공 drill-down. |
| 59 | 7-27 | Drawer hover prefetch + cache invalidate. |
| 60 | 7-28 | DiffModal JSON export + `?atomic=true`. |
| 61 | 7-29 | Import 이름 충돌 경고 + "Retry without atomic". |
| 62 | 7-30 | DiffModal Markdown export + Auto-suffix. |
| 63 | 7-31 | Pairwise diff 매트릭스 모달. |
| 64 | 7-32 | `POST /api/environments/diff-bulk` 단일 round-trip. |
| 65 | 7-33 | Matrix JSON / Markdown 다운로드. |
| 66 | 7-34 | `/diff-bulk` per-env read cache (N·(N-1) → N). |
| 67 | 7-35 | DiffModal / MatrixModal "Copy MD" 클립보드. |
| 68 | 7-36 | Matrix "Most different pair" 하이라이트 + 배지. |
| 69 | 7-37 | "Has preset" / "Has tags" 메타 필터. |
| 70 | 7-38 | Bulk-delete confirm drill-down 링크. |
| 71 | 7-39 | Atomic retry 배너 (4.5 초 auto-dismiss). |
| 72 | 7-40 | Copy MD 실패 시 원인 툴팁. |
| 73 | 7-41 | Plan 06 docs closure — 이 문서 + backend README env vars. |

## 스모크 시나리오 상태

Plan 06 의 "스모크 / 수용" 섹션 각 단계는 PR 단위 검증에서 수용
기준을 통과했다. 아래는 현재 main 기준 스냅샷 — 새로 셋업되는
환경에서 다시 돌려봐야 할 manual QA 항목이다.

| 단계 | 기준 | 상태 |
|------|------|------|
| Phase 1 | `docker compose up -d backend` 헬스체크 | Green (통합 검증 시 재확인) |
| Phase 2 | `GET /api/sessions/{id}/memory` → descriptor | Green |
| Phase 3 | `POST /api/environments` (blank) → `GET /{id}` | Green |
| Phase 4 | Stage 2 memory attach 후 retrieve → chunk | Green |
| Phase 5 | flag on/off 동일 결과 (허용오차: ts, ordering) | 각 계층 PR 에서 검증 |
| Phase 6 | FE: env 생성 → 편집 → 세션 시작 | Green (UI 빌드 수동) |
| Phase 7 | `/api/agents/{id}/memory/files/<x>` 기존 JSON shape | Green |

## Deviations

- **PR 번호 불일치**: plan 06 은 18 PR 을 예상했으나 UI 안전장치
  (diff preview / auto-backup) 와 운영 가시성 (session info 에
  memory/env 노출) 이 추가되어 34 PR 로 마감. Phase 번호는 plan 기준을
  유지하고, 같은 phase 하위 PR 은 `Phase 6d-7`, `6d-8`, `6d-9` 처럼
  하이픈 서브번호로 구분했다.
- **Phase 5 내 per-adapter PR 분할**: 계획은 10–14 를 단일 PR 로
  묶었지만, 계층마다 회귀 위험이 커서 adapter 1개 = 1 PR 로 분리.
  flag scaffold (10) 이 선행된 덕분에 각 adapter PR 은 flag 토글
  외 외부 영향이 없다.
- **문서 이관**: 계획상의 `docs/MEMORY_UPGRADE_PLAN.md` 리다이렉트는
  Phase 36 (PR #36) 에서 superseded 배너로 처리됨.

## 릴리스 전 체크 (plan 06 §릴리스 전 체크)

- [x] 단위/통합 테스트: 각 PR 단위 CI green (GitGuardian 포함).
- [ ] docker compose (dev, prod, core) 빌드 — 통합 릴리스 시점에 재실행.
- [ ] DB 마이그레이션 배치 dry-run — 마이그레이션 자체는 없지만,
      기존 memory_* 테이블 ↔ 프로바이더 SQL 스키마 공존 체크 필요.
- [ ] PyPI 미리보기: executor 0.20.0 tag 는 이미 릴리스됨.
- [ ] 사용자 수동 QA — main 에서 session 생성 / env 편집 / import
      flows (backup + diff) end-to-end.

## 되돌리기 경로

Plan 06 의 원래 기준을 재확인:

- 각 PR 독립 merge. 필요 시 `git revert` 로 해당 커밋만 롤백 가능.
- Phase 5 의 각 adapter 는 `MEMORY_ADAPTER_<LAYER>=legacy` 플래그로
  런타임에 즉시 전환. revert 없이도 회귀 가능.
- Phase 3 (Environment controller) 는 독립 라우터 prefix 이므로
  라우터 mount 만 제거하면 전체 환경 기능 disable.
- Phase 4 attach 는 `MEMORY_PROVIDER_ATTACH=false` 로 pipeline 에
  붙이는 경로만 끈다.
- FE 에서는 feature flag 없이 바로 노출 — 필요한 경우 해당 tab 만
  `GLOBAL_TAB_IDS` 에서 빼면 된다.

## Follow-ups

- `docs/MEMORY_UPGRADE_PLAN.md` — Phase 36 에서 superseded 배너 부착
  완료. 삭제는 보류 (참조 링크 깨짐 방지).
- Manifest snapshot/restore 서버측 이력 API — Phase 6d-8 의
  클라이언트 자동 백업에 대응하는 server-side 버전. 미착수.
- Reverse lookup "이 env 를 쓰는 세션 목록" — Phase 7-15 (PR #47)
  에서 `GET /api/environments/{id}/sessions` + 드로어 UI 로 완료.
- Performance 측정 수용 (plan 06 §성능/부하) — 세션 50 동시 /
  pgvector vs FAISS P95 / manifest replace P95. 별도 릴리스 전
  manual QA task — 라이브 환경 필요.

## 변경 로그 / Changelog

별도 `CHANGELOG.md` 는 두지 않고 `progress/index.md` 를 정규
changelog 로 사용한다. PR 단위 진행 문서가 각 항목의 scope /
summary / verification / deviations / follow-ups 를 포함하므로
중복 유지를 피한다.
