# 64. Phase 7-32 — Bulk diff endpoint + single-roundtrip matrix

## Scope

Phase 7-31 에서 도입한 `EnvironmentDiffMatrixModal` 은 N 개 환경을
비교하기 위해 `POST /api/environments/diff` 를 N·(N-1)/2 번 호출했다.
10 개 = 45 번, 15 개 = 105 번. bounded concurrency (4) 로 완화했지만
HTTP round-trip overhead 가 그대로 쌓인다.

이번 PR 은:
- 서버에 `POST /api/environments/diff-bulk` 신규 엔드포인트 추가 —
  pairs 를 받아 summary 만 묶어서 돌려줌 (entries 미포함, 매트릭스는
  summary 만 쓴다).
- 매트릭스 모달이 concurrency fan-out 대신 단일 호출로 전환.
- 500 pairs 캡 (Pydantic validator) 로 뽑아낼 수 없는 규모 보호.

## PR Link

- Branch: `feat/phase7-32-diff-bulk-endpoint`
- PR: (커밋 푸시 시 발행)

## Summary

`backend/service/environment/schemas.py` — 수정
- 신규 `DiffPairRequest`, `DiffBulkRequest`, `DiffBulkResultEntry`,
  `DiffBulkResponse`.
- `DIFF_BULK_MAX_PAIRS = 500` 상한 + `model_validator(mode='after')`
  enforcement.
- `__all__` 업데이트.

`backend/controller/environment_controller.py` — 수정
- 새 import 추가 (DiffBulkRequest/Response/ResultEntry).
- `@router.post("/diff-bulk")` 엔드포인트 — 기존 `/diff` 의 로직을
  pair 루프로 감싸고, 각 pair 를 try/except 로 격리. 실패 pair 는
  `ok=False, error=<str>` 로 결과에 남김.
- 응답: `{ total, ok, failed, results: [{env_id_a, env_id_b, ok,
  identical, summary, error}] }`. entries 는 빼서 payload 가
  N·(N-1)/2 * 500 바이트 수준으로 유지.

`frontend/src/types/environment.ts` — 수정
- 신규 타입 `DiffBulkPair`, `DiffBulkRequest`, `DiffBulkResultEntry`,
  `DiffBulkResponse`.

`frontend/src/lib/environmentApi.ts` — 수정
- `diffBulk(body: DiffBulkRequest)` 메서드 추가.

`frontend/src/components/modals/EnvironmentDiffMatrixModal.tsx` — 수정
- 기존 `runWithConcurrency` + `summarize` 헬퍼 제거.
- `EnvironmentDiffResult` 타입 import 제거.
- useEffect 가 한 번의 `environmentApi.diffBulk({ pairs })` 호출 후
  모든 cells 를 한 번에 setState.
- 전체 호출이 실패하면 모든 cell 을 `error` 상태로 표시.
- 개별 pair 실패는 결과 entry 의 `ok=false + error` 그대로 cell 에
  반영.

## Verification

### 엔드포인트

- `POST /api/environments/diff-bulk` with `{"pairs": [{"env_id_a":"X",
  "env_id_b":"Y"}]}` → `{total:1, ok:1, failed:0, results:[{ok:true,
  identical:<bool>, summary:{added,removed,changed}, ...}]}`.
- 존재하지 않는 env_id 를 섞으면 해당 entry 만 `ok=false, error="..."`,
  나머지는 정상 반환.
- 501 pairs 이상을 보내면 422 Unprocessable Entity (Pydantic 422).

### 프론트

- 3 개 env 선택 → "Compare 3 (matrix)" → 3×3 매트릭스가 한 번의 HTTP
  호출로 전체 채워짐. DevTools Network 탭에서 `/diff-bulk` 만 1 건
  (기존은 `/diff` 3 건).
- 10 개 선택 → 45 pairs 를 1 회 호출로 처리. 소요 시간이 기존 대비
  round-trip 수만큼 단축.
- 백엔드를 강제로 5xx 로 만들면 모든 cell 이 `err` 로 변하고 hover
  툴팁에 동일한 상위 메시지 노출.
- 특정 env 하나가 파일 손상으로 diff 실패 → 해당 row/col 만 `err`,
  나머지는 정상 (서버 per-pair isolation 덕).

## Deviations

- `/diff-bulk` 는 summary 만 반환. 세부 entries 가 필요하면 기존
  `/diff` 를 pair 단위로 호출 (matrix 에서 cell 클릭 시 정확히 그 동선).
- 500 pairs 캡은 `DIFF_BULK_MAX_PAIRS` 로 노출. 200 envs 는 19900
  pairs 라 캡을 초과하지만, 매트릭스가 그 규모로 스케일하는 의미가
  없으므로 UI 쪽에서 별도 제한 없이 백엔드 422 에 맡겼다.
- Concurrency/cancellation 은 사라짐. 단일 호출이므로 cancel 은
  fetch 자체를 aborting 해야 하는데, 매트릭스 모달은 닫히면 portal
  이 unmount 되어 `cancelled` flag 만으로 충분 (state update 만
  차단).
- 응답 payload 크기는 pair 당 약 100 바이트 × 500 = 50 KB 수준.
  gzip 없이도 적당.
- 서버 쪽 `_read_raw` 는 각 pair 마다 두 번 호출됨. 500 pairs × 2 =
  1000 번 fs read. 캐싱을 붙이면 N (고유 env 수) 로 줄지만, 파일
  크기가 작아서 실측 overhead 를 확인한 뒤 Follow-up 으로 처리.

## Follow-ups

- `diff-bulk` 내부에 per-env `_read_raw` 캐시. 500 pairs 에 50 env 면
  fs read 1000 → 50 회로 95% 감소.
- matrix export (JSON/MD) — 이번에도 이월 (Phase 7-31 follow-up).
- 매트릭스에 "가장 서로 다른 pair 상위 N" 랭킹 헤더.
