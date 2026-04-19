# 73. Phase 7-41 — Plan 06 문서 클로저

## Scope

Plan 06 (`plan/06_rollout_and_verification.md`) 의 "문서 업데이트"
섹션 (§82–85) 에서 명시한 릴리스 전 필수 문서 갱신을 마감한다.
코어 18-PR 은 모두 ship 되어 있고, 이후 Phase 7-6 ~ 7-40 로
추가된 UX / 운영 보강 PR (총 34 개) 도 모두 merge 되어 있으나
`backend/README.md` 환경변수 목록은 Phase 3 / 4 에서 추가된 변수를
반영하지 않았고, 롤아웃 요약 문서 (`progress/35_…`) 는 34-PR
시점 스냅샷으로 남아있어 38–72 PR 이 매핑되지 않았다. 이 PR 에서
두 문서만 갱신해 "플래너 관점의 릴리스 닫기" 를 완료한다.

별도 `CHANGELOG.md` 는 만들지 않는다 — `progress/index.md` 가
이미 PR 단위 기록을 갖고 있어 중복 유지가 된다.

## PR Link

- Branch: `feat/phase7-41-plan06-docs-closure`
- PR: (커밋 푸시 시 발행)

## Summary

`backend/README.md` — 수정
- "Environment Variables" 섹션에 **Memory Provider** 표와
  **Environment Service** 표를 추가. `MEMORY_PROVIDER`,
  `MEMORY_ROOT`, `MEMORY_DSN`, `MEMORY_DIALECT`, `MEMORY_SCOPE`,
  `MEMORY_TIMEZONE`, `MEMORY_PROVIDER_ATTACH`,
  `MEMORY_API_PROVIDER`, `MEMORY_LEGACY_STM/LTM/NOTES/VECTOR/CURATED`,
  `ENVIRONMENT_STORAGE_PATH` 를 실제 코드의 기본값과 정확히
  매칭해 문서화. Registry 는 `MEMORY_PROVIDER` 미설정 시 dormant —
  이 점을 표 위에 별도로 기록.

`progress/35_rollout_verification_summary.md` — 수정
- "Plan 06 스코프 마감 이후 UX / 운영 보강 PR" 서브섹션 신설.
  PR #36 ~ #72 를 Phase 번호 / 요약 한 줄 표로 정리.
- "문서 이관" deviations 항목을 "Phase 36 에서 처리 완료" 로
  수정 (이전: "Follow-up 후보").
- Follow-ups 섹션에서 reverse-lookup 항목은 Phase 7-15 완료 로
  표시, `docs/MEMORY_UPGRADE_PLAN.md` 는 superseded 배너 부착
  완료로 표시, performance 측정은 라이브 환경 필요함을 명시.
- "변경 로그 / Changelog" 소섹션 추가 — `progress/index.md` 를
  정규 changelog 로 사용하는 정책을 명시.

`progress/index.md` — 수정
- 이 PR 항목 (73) 추가.

## Verification

- `backend/README.md` 의 새 표가 실제 코드와 일치함을
  교차 확인:
  - `backend/service/memory_provider/config.py` (`MEMORY_PROVIDER`
    default disabled / dormant, `MEMORY_SCOPE` default `session`,
    `MEMORY_PROVIDER_ATTACH` / `MEMORY_API_PROVIDER` default false).
  - `backend/service/memory_provider/flags.py` (`MEMORY_LEGACY_*`
    default `true`).
  - `backend/service/environment/service.py:75` (`ENVIRONMENT_STORAGE_PATH`
    default `./data/environments`).
- 요약 문서의 PR 번호 / Phase 번호는 `progress/index.md` 와 일치
  (sanity check).
- 코드 변경이 없으므로 런타임 / 빌드 회귀 없음.

## Deviations

- `CHANGELOG.md` 는 생성하지 않음. plan 06 §85 는 "changelog 누적"
  을 요구하지만, 지난 34 개 PR 전부 `progress/NN_phaseX-Y_*.md`
  파일로 상세 기록되어 있고 `progress/index.md` 가 단일 진입점
  역할을 한다. 별도 파일을 만들면 동일 정보가 두 곳에 fork 되어
  drift 위험만 증가.
- Plan 06 §89–93 (docker compose / DB 마이그레이션 dry-run / PyPI
  preview / manual QA) 는 라이브 환경에서 수행해야 하는 런타임
  검증이라 코드 PR 범위를 벗어난다 — `35_…` 에서 "라이브 환경
  필요" 로 표시만 유지. 이 항목들은 실제 릴리스 시 운영자가
  수행.
- README 표에는 `MEMORY_DSN` / `MEMORY_DIALECT` 도 포함 — 현재
  Geny 운영 시나리오에서는 file / ephemeral 중심이지만, 플랜의
  `sql` 프로바이더 옵션을 문서에서 누락하면 future 오퍼레이터가
  config.py 를 직접 읽어야 하게 된다.

## Follow-ups

- plan 06 §77–79 (성능 / 부하 수용) — 실제 50 세션 동시 / pgvector
  vs FAISS P95 / manifest replace P95 측정. 릴리스 사이클 밖의
  manual QA task 로 유지.
- `backend/docs/CONFIG.md` 와 README env vars 의 중복 경감 — 현재
  CONFIG.md 는 app-level config class, README 는 env var naming
  관점으로 내용이 겹친다. 정책 문서 재정리 후보.
