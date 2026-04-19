# Progress Index

geny-executor v0.20.0 통합 작업의 PR 단위 기록. 기록 규약은
[README.md](README.md) 를 참조. 실제 roadmap 은
[`plan/06_rollout_and_verification.md`](../plan/06_rollout_and_verification.md)
의 18-PR 그리드였으나, 구현 과정에서 UI/안전장치 PR 이 추가되어
총 34 개로 분할 완료.

요약 문서: [`35_rollout_verification_summary.md`](35_rollout_verification_summary.md) —
plan 06 체크리스트 vs 실제 출고물의 매핑.

## Phase 1 — Dependency bump

- [01_bump_executor_dep.md](01_bump_executor_dep.md) — `geny-executor` 0.20.0 으로 갱신, `[postgres]` extra / Pydantic v2 호환 정리.

## Phase 2 — Session rewire + memory registry

- [02_session_wire_align.md](02_session_wire_align.md) — `agent_session.py` / `tool_bridge.py` 를 v0.20.0 파이프라인 API 로 재배선.
- [03_memory_session_registry.md](03_memory_session_registry.md) — `MemorySessionRegistry` 도입 + `/sessions/{id}/memory` endpoints.
- [04_memory_env_plumbing.md](04_memory_env_plumbing.md) — `MEMORY_*` env / Settings / docker-compose 통합.

## Phase 3 — Environment service + REST

- [05_environment_service.md](05_environment_service.md) — `EnvironmentService` + service 예외.
- [06_environment_controller.md](06_environment_controller.md) — 15-endpoint environment_controller.
- [07_catalog_controller.md](07_catalog_controller.md) — stage/artifact/strategy 5-endpoint catalog.
- [08_session_env_memory_wire.md](08_session_env_memory_wire.md) — 세션 생성 시 `env_id` + `memory_config` 수용.

## Phase 4 — Memory provider attach

- [09_memory_attach_stage2.md](09_memory_attach_stage2.md) — Stage 2 (Context) 에 memory provider 붙이기.

## Phase 5 — Legacy flag migration (layer-by-layer)

- [10_phase5_flag_scaffold.md](10_phase5_flag_scaffold.md) — Legacy-vs-provider flag scaffolding.
- [11_phase5a_stm_adapter.md](11_phase5a_stm_adapter.md) — STM adapter.
- [12_phase5b_ltm_adapter.md](12_phase5b_ltm_adapter.md) — LTM adapter.
- [13_phase5c_notes_adapter.md](13_phase5c_notes_adapter.md) — Notes adapter.
- [14_phase5d_vector_adapter.md](14_phase5d_vector_adapter.md) — Vector adapter.
- [15_phase5e_curated_adapter.md](15_phase5e_curated_adapter.md) — Curated/Global (Scope) adapter.

## Phase 6 — Frontend (Environments + Builder)

### 6a–6c — Types, store, tab, modals, drawer

- [17_phase6a_frontend_env_types_api.md](17_phase6a_frontend_env_types_api.md) — TS types + `environmentApi`.
- [18_phase6b_env_store.md](18_phase6b_env_store.md) — Zustand `useEnvironmentStore`.
- [19_phase6c_environments_tab.md](19_phase6c_environments_tab.md) — EnvironmentsTab shell.
- [20_phase6c2_env_create_modal.md](20_phase6c2_env_create_modal.md) — CreateEnvironmentModal (blank / import / duplicate).
- [21_phase6c3_env_detail_drawer.md](21_phase6c3_env_detail_drawer.md) — EnvironmentDetailDrawer.
- [22_phase6e_session_env_selector.md](22_phase6e_session_env_selector.md) — CreateSessionModal 의 env 선택자.

### 6d — Builder + stage editor

- [23_phase6d1_catalog_api_fix.md](23_phase6d1_catalog_api_fix.md) — Catalog API 정비.
- [24_phase6d2_builder_tab.md](24_phase6d2_builder_tab.md) — Builder tab shell.
- [25_phase6d3_schema_form.md](25_phase6d3_schema_form.md) — JsonSchemaForm.
- [26_phase6d4_strategies_chains_editor.md](26_phase6d4_strategies_chains_editor.md) — Strategies/Chains editor.
- [27_phase6d5_env_diff_viewer.md](27_phase6d5_env_diff_viewer.md) — EnvironmentDiffModal.
- [28_phase6d6_tools_editor.md](28_phase6d6_tools_editor.md) — ToolsEditor (manifest.tools).
- [29_phase6d7_manifest_import_overwrite.md](29_phase6d7_manifest_import_overwrite.md) — ImportManifestModal (overwrite).
- [33_phase6d9_import_diff_preview.md](33_phase6d9_import_diff_preview.md) — Import diff preview (client-side).
- [34_phase6d8_import_backup.md](34_phase6d8_import_backup.md) — Auto-backup before overwrite.

## Phase 7 — Memory API rewrite + session visibility

- [16_phase7_memory_api_scaffold.md](16_phase7_memory_api_scaffold.md) — `/api/agents/{id}/memory/*` provider-backed.
- [30_phase7-3_memory_config_override.md](30_phase7-3_memory_config_override.md) — CreateSessionModal per-session override.
- [31_phase7-4_session_memory_info.md](31_phase7-4_session_memory_info.md) — SessionInfo 에 `env_id` + `memory_config` 노출.
- [32_phase7-5_env_id_drawer_link.md](32_phase7-5_env_id_drawer_link.md) — InfoTab env row → EnvironmentDetailDrawer 링크.

## 최종 통합 문서

- [35_rollout_verification_summary.md](35_rollout_verification_summary.md) —
  plan 06 체크리스트 ↔ 실제 출고물 매핑, deferred items, 릴리스 전 체크
  상태.
- [36_docs_memory_plan_redirect.md](36_docs_memory_plan_redirect.md) —
  초기 `docs/MEMORY_UPGRADE_PLAN.md` 에 superseded 배너 부착.
- [37_phase6d9-1_changed_expand.md](37_phase6d9-1_changed_expand.md) —
  Import diff "changed" 항목을 before/after 로 펼치기.
- [38_phase7-6_env_session_count_badge.md](38_phase7-6_env_session_count_badge.md) —
  Environment 카드에 "N sessions bound" badge.
- [39_phase7-7_drawer_linked_sessions.md](39_phase7-7_drawer_linked_sessions.md) —
  EnvironmentDetailDrawer 에 "Linked sessions" 섹션 + 세션 drill-down.
- [40_phase7-8_import_dragover_state.md](40_phase7-8_import_dragover_state.md) —
  ImportManifestModal 드롭존에 drag-over 시각 피드백.
- [41_phase7-9_import_environment_modal.md](41_phase7-9_import_environment_modal.md) —
  ImportEnvironmentModal 신설 — 백업 JSON 으로 새 환경 생성.
