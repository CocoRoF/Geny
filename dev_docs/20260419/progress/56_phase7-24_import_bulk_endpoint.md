# 56. Phase 7-24 — `POST /api/environments/import-bulk` + client adoption

## Scope

Phase 7-22 의 follow-up 1번 — "`/api/environments/import-bulk`
엔드포인트로 batch 처리 추가" 를 실제 구현. 프론트는 bundle 을
N 개의 single-import 요청으로 보내고 있었다. 이로 인해:

- N × latency (네트워크 RTT 누적)
- 서버측 로깅이 N 줄로 흩어짐
- 실패 인덱스 추적이 FE 책임

이 PR 은 서버에 batch endpoint 를 추가하고, `ImportEnvironmentModal`
의 bundle path 가 이를 호출하도록 교체한다. 서버는 entry 별
success/failure 를 순서대로 반환해 FE 가 그대로 렌더할 수 있도록
한다. rollback 은 하지 않는다 (per-entry independent).

## PR Link

- Branch: `feat/phase7-24-import-bulk-endpoint`
- PR: (커밋 푸시 시 발행)

## Summary

`backend/service/environment/schemas.py` — 수정
- 신규 모델: `ImportBulkEntry`, `ImportEnvironmentsBulkRequest`,
  `ImportBulkResultEntry`, `ImportEnvironmentsBulkResponse`.
- `__all__` 에 4 모델 노출.

`backend/controller/environment_controller.py` — 수정
- `POST /import-bulk` 추가. `ImportEnvironmentsBulkRequest` 를
  받아 entry 마다 `service.import_json` 호출. 예외는 per-entry
  로 포착해 `ImportBulkResultEntry(ok=False, error=str)` 로 리턴.
  요약 (`total`, `succeeded`, `failed`) 포함.
- 실패 entry 는 `logger.warning` 으로 남긴다.

`frontend/src/types/environment.ts` — 수정
- `ImportBulkEntry`, `ImportEnvironmentsBulkRequest`,
  `ImportBulkResultEntry`, `ImportEnvironmentsBulkResponse` 타입
  4 개 신설.

`frontend/src/lib/environmentApi.ts` — 수정
- `importEnvBulk(body)` wrapper 추가.

`frontend/src/components/modals/ImportEnvironmentModal.tsx` — 수정
- Bundle 경로에서 loop-per-entry 를 제거. 단일 `importEnvBulk`
  호출 후 응답의 `results[]` 를 index 순으로 성공/실패 버킷에 분배.
- 성공이 하나라도 있으면 store 의 `loadEnvironments` + 
  `refreshSessionCounts` 를 명시적으로 호출 (store 우회 경로라
  자동 갱신이 없음).

## Verification

- 번들 JSON 드롭 → Import 클릭 → 네트워크 탭에 `POST
  /api/environments/import-bulk` 하나만 보인다. 응답의 `results`
  가 UI 의 per-entry 리포트와 같은 순서.
- 번들 entry 중 하나를 일부러 malformed 로 (manifest 제거 등)
  만든 뒤 드롭: 서버는 해당 entry 만 ok=false 로 마킹, 나머지는
  정상 create. 프론트 리포트가 실패 1 / 성공 N-1 로 구분.
- 단일 env JSON 드롭: 기존 `/import` 경로로 그대로 동작 (분기
  유지).
- `version` 필드가 없는 번들: 서버 schema 는 Optional 로 받아줌.
  응답은 동일.
- 빈 `entries: []` → 서버가 total=0, succeeded=0, failed=0 로
  응답 (FE 에서는 이 경우를 이미 empty bundle 로 차단 중, 하지만
  backend 도 안전).
- 성공 후 Environments 그리드에 새 env N 개 등장, sessionCounts
  업데이트. 드로어 열어보면 matched 환경 모두 로드.

## Deviations

- 트랜잭션/롤백은 도입하지 않음. 파일시스템 저장이라 atomicity 를
  논리적으로 보장하기 어렵고, per-entry 독립 import 가 현재
  `import_json` 의 동작과 일관.
- 서버측에서 동시성 throttle 은 하지 않음. 실 사용 빈도로는
  문제 아님. 악의적 대량 번들이 우려되면 `len(body.entries)` 상한
  을 두는 식으로 차단 가능 (향후).
- 클라이언트가 store 우회로 직접 API 를 호출. store 를 경유하려면
  `importEnvironmentsBulk` 같은 액션을 새로 뚫어야 하지만, 이 모달
  단 하나만 쓰기 때문에 과한 추상화. `loadEnvironments` +
  `refreshSessionCounts` 만 명시 호출.

## Follow-ups

- Request-level 검증: entries 길이 상한 (예: 200) 과 entry size
  상한 (예: 2 MB) 도입.
- Rollback 옵션: `atomic=true` 쿼리 플래그로 하나라도 실패 시
  모두 delete (soft-delete) 하는 변형.
- Frontend store 에 `importEnvironmentsBulk` 액션을 뚫어 다른
  곳에서도 재사용 가능하게.
