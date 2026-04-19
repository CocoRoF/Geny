# 57. Phase 7-25 — Bulk operations safety hardening

## Scope

두 follow-up 을 하나의 "안전망" PR 로 묶는다:

1. **Phase 7-24 follow-up #1** — `POST /api/environments/import-bulk`
   에 request-level 검증 추가 (entries 길이 상한 + 엔트리 JSON
   크기 상한). 현재는 무제한이라 300 개 환경을 실수로 드롭하거나
   거대한 payload 가 포함되어도 그대로 처리된다.
2. **Phase 7-21 follow-up** — bulk delete confirm 모달이 선택된
   환경 중 활성 세션이 바인딩된 건수·에러 세션 건수를
   미리 보여준다. 현재는 일반적인 문구만 있어서 "지금 12 개의
   세션이 dangling 되겠구나" 같은 구체적 영향이 노출되지 않음.

두 개 모두 "bulk 액션 안전성" 이라는 동일 주제이며, 한쪽은 서버,
한쪽은 프론트라 서로 독립 배포 가능하지만 묶어서 하나의 PR 로
낸다 (사용자 요청: "너무 단계적으로 PR 을 넣지 말고").

## PR Link

- Branch: `feat/phase7-25-bulk-preset-and-delete-warning`
- PR: (커밋 푸시 시 발행)

## Summary

`backend/service/environment/schemas.py` — 수정
- 상수 `BULK_IMPORT_MAX_ENTRIES = 200` / `BULK_IMPORT_MAX_ENTRY_BYTES
  = 2 MiB` 모듈 레벨 선언.
- `ImportEnvironmentsBulkRequest` 에 `model_validator(mode='after')`
  로 두 제한 체크. 위반 시 422 (Pydantic `ValueError`).
- 크기는 `json.dumps(entry.data).encode('utf-8')` 길이 근사.
  payload 가 이미 메모리에 있으니 O(N) 추가비용만 발생.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- 번들 삭제 confirm 모달 `message` 를 `ReactNode` 로 교체.
- 선택된 env 들에서 `countsPerEnv` 로 active/error 합산 + 엔트리별
  breakdown 리스트 (상위 6 개 + "외 N 개") 렌더. 바인딩이 하나도
  없으면 기존 단일 문장만 노출.
- `AlertTriangle` 아이콘으로 danger 톤 유지. 기존 `note` 는 그대로.

`frontend/src/lib/i18n/en.ts` / `ko.ts` — 수정
- 신규 키: `environmentsTab.bulkDeleteSessionsSummary`,
  `bulkDeleteSessionsLine`, `bulkDeleteSessionsMore`.

## Verification

### Backend caps

- 201 개 entries 를 POST → 422, `too many entries: 201 > 200`.
- 2 MiB 넘는 payload 하나 포함 → 422, `entry N too large: ...`.
- 정상 케이스 (entries 1~3 개, 작은 JSON) → 기존처럼 200 OK,
  `{ total, succeeded, failed, results }`.
- 기존 bundle export JSON 을 그대로 import → 모두 정상 (env 수천
  개가 한 번에 export 되는 경우는 현실적으로 없음).

### Frontend warning

- bulk select 로 3 개 env 선택 (active 바인딩 없는 것들) → "Delete
  selected environments?" 만 보임. 경고 박스 없음.
- 하나가 active 세션 5 개 가진 env 라면 → 경고 박스 노출: 
  "1 of these have active bindings — 5 active, 0 in error", 그 env
  이름이 리스트에 보임.
- 7 개 이상이면 상위 6 개 + "…and N more" 라인.
- ko 로케일 전환 시 동일 문구가 한국어로 표시.
- confirm → 기존 `runBulkDelete` 흐름 그대로 (동작 변경 없음).

## Deviations

- 서버 측 크기 검사는 `json.dumps` 근사. FastAPI/Starlette 의
  원본 request body 크기를 읽는 방법도 있지만, 여기서는 per-entry
  캡이 목적이라 각 entry 의 직렬화 바이트를 직접 재는 편이 명확.
- 프론트 경고는 `countsPerEnv` (store cached) 에 의존. TTL 안
  지나면 stale 일 수 있지만, 이미 focus/visibility 시 재조회하는
  기존 정책을 그대로 사용. "실제 삭제 시점에 서버에서 재확인" 같은
  하드 체크는 하지 않음 — 삭제는 per-entry independent 이고,
  경고는 참고용.
- 에러 세션도 "바인딩" 으로 함께 표시. 기술적으로는 에러 세션도
  env 참조를 유지하므로 dangle 대상.

## Follow-ups

- 서버: `atomic=true` 쿼리 플래그로 "하나라도 실패 시 전체 롤백"
  옵션. 현재는 여전히 per-entry independent.
- 프론트: 경고 박스의 env 이름을 클릭하면 해당 env 의 드로어를
  바로 열 수 있게 (미니 drill-down).
- `countsPerEnv` 가 stale 한 경우에 대비, 경고 모달 진입 시 강제
  `refreshSessionCounts()` 1 회 호출.
