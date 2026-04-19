# 06. 롤아웃 & 검증 체크리스트

구현 링크: [`progress/35_rollout_verification_summary.md`](../progress/35_rollout_verification_summary.md)
— plan 18-PR 그리드 ↔ 실제 출고된 34 PR 매핑, 수용 상태, 남은 follow-up.

## PR 단위 로드맵

| # | 제목 | 단계 | 예상 크기 |
|---|------|------|-----------|
| 1 | chore(dep): bump geny-executor to 0.20.0 | Phase 1 | S |
| 2 | refactor(session): align pipeline wiring with 0.20.0 APIs | Phase 2 | S |
| 3 | feat(memory): introduce MemorySessionRegistry + /sessions/{id}/memory endpoints | Phase 2 | M |
| 4 | feat(memory): MEMORY_* env + Settings + docker-compose plumbing | Phase 2 | S |
| 5 | feat(environment): EnvironmentService + service exceptions | Phase 3 | M |
| 6 | feat(environment): environment_controller with 15 endpoints | Phase 3 | L |
| 7 | feat(environment): catalog_controller with 5 endpoints | Phase 3 | S |
| 8 | feat(session): accept env_id and memory_config | Phase 3 | M |
| 9 | feat(memory): attach provider to Stage 2 (Context) | Phase 4 | M |
| 10 | feat(memory): feature-flagged migration — STM layer | Phase 5a | M |
| 11 | feat(memory): LTM layer | Phase 5b | M |
| 12 | feat(memory): Notes layer | Phase 5c | M |
| 13 | feat(memory): Vector layer | Phase 5d | M |
| 14 | feat(memory): Curated/Global layers (via Scope) | Phase 5e | M |
| 15 | feat(frontend): Environment tab + store + components | Phase 6 | L |
| 16 | feat(frontend): Builder tab + stage editor | Phase 6 | L |
| 17 | refactor(memory-api): /api/agents/{id}/memory/* → provider-backed | Phase 7 | M |
| 18 | docs + release notes | 마지막 | S |

총 ~18 PR. 각 단계 내에서는 더 쪼갤 수 있다.

## 스모크 / 수용 시나리오

### Phase 1 수용

- `python -m py_compile backend/service/langgraph/*.py`.
- `docker compose up -d backend` → healthcheck 통과.
- `POST /api/agents` + `POST /api/agents/{id}/invoke` "hello" 프롬프트 → 응답.

### Phase 2 수용

- `GET /api/sessions/{id}/memory` → 200 + `provider: "ephemeral"`.
- `POST /api/sessions/{id}/memory/retrieve` → 200 (쿼리 "test") 또는 409 (capability 미지원 — ephemeral 은 SEARCH 미탑재 시).
- `DELETE /api/sessions/{id}/memory` → `{"cleared": true}`.
- `MEMORY_PROVIDER=file` + `MEMORY_ROOT=/tmp/mem` 로 재기동 → descriptor 변경.

### Phase 3 수용

- `POST /api/environments` (mode=blank) → `{id}`.
- `GET /api/environments/{id}` → `manifest` 포함.
- `PATCH /api/environments/{id}/stages/1` `{"active": true}` → 200.
- `POST /api/agents {env_id: <id>}` → 세션 생성 후 `POST .../invoke` 응답.

### Phase 4 수용

- Phase 3 + `memory_config` 지정 세션 → Stage 2 provider 세팅 확인 (descriptor 디버그).
- 동일 세션에서 `POST /api/sessions/{id}/memory/retrieve` 가 실제 chunk 반환.

### Phase 5 각 단계 수용

- flag off → 레거시 경로 동작.
- flag on → 프로바이더 경로 동작.
- `/api/agents/{id}/memory/*` 의 동일 쿼리가 flag 양 상태에서 **같은 결과** (허용 오차: timestamp, ordering).

### Phase 6 수용

- 브라우저: `/environments` 페이지 로드 → 리스트.
- 신규 env 생성 → 상세 진입 → 매니페스트 편집 (스테이지 OFF/ON) → Save → reload 후 유지.
- "Start session" → 세션 뷰 전환.

### Phase 7 수용

- 기존 UI (ChatMemoryPanel 등) 회귀 없음.
- `/api/agents/{id}/memory/files/<x>` 가 프로바이더 경로로 동일 JSON 반환.

## 성능 / 부하

- 세션 수 ≥ 50 동시 시 Registry 메모리 사용량 측정.
- Vector 검색 지연 P95 측정 (pgvector vs FAISS flat 비교).
- Environment 편집 (manifest 전체 replace) API 응답 P95 < 200ms.

## 문서 업데이트

- `backend/README.md` — 환경변수 `MEMORY_*`, `ENVIRONMENT_STORAGE_PATH` 추가.
- `docs/MEMORY_UPGRADE_PLAN.md` — 본 Plan 시리즈로 링크 이전.
- Changelog — Phase 마다 누적 엔트리.

## 릴리스 전 체크

- [ ] 전체 테스트 통과.
- [ ] docker compose (dev, prod, core) 빌드.
- [ ] DB 마이그레이션 배치 dry-run 통과.
- [ ] PyPI 미리보기 — executor 새 버전 호환 확인.
- [ ] 사용자 수동 QA.

## 되돌리기 경로

- 각 PR 은 독립. Phase 5 내 계층별 플래그로 계층 단위 롤백 가능.
- Phase 3 (Environment) 은 신규 라우터이므로 disable 만 하면 rollback.
- Phase 4 attach 는 `MEMORY_PROVIDER_ATTACH=false` 로 즉시 끔.
