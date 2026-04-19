# 48. Phase 7-16 — Bulk session-count endpoint + Environments card adoption

## Scope

Phase 7-15 에서 드로어는 권위 있는 endpoint 로 옮겼지만, 카드
그리드는 여전히 `useAppStore.sessions` 클라이언트 집계를 쓰고
있었다. 카드가 10 개 넘어가면 드로어마다 개별 `/sessions` 를
호출하는 건 낭비라 bulk endpoint 가 필요하다.

이 PR 은 (a) `GET /api/environments/session-counts` bulk endpoint 를
추가하고, (b) `EnvironmentsTab` 카드 그리드를 해당 endpoint 로
옮긴다. 카드에는 기존 user/error 뱃지 옆에 `Archive` 아이콘
+ deletedCount 뱃지를 추가해, soft-delete 된 세션이 묶여 있는
환경을 한눈에 볼 수 있게 한다.

## PR Link

- Branch: `feat/phase7-16-card-grid-authoritative-counts`
- PR: (커밋 푸시 시 발행)

## Summary

### Backend

`backend/service/environment/schemas.py` — 수정
- `EnvironmentSessionCountEntry` / `EnvironmentSessionCountsResponse`
  Pydantic 모델 신설 (env_id, active/deleted/error count).
- `__all__` 업데이트.

`backend/controller/environment_controller.py` — 수정
- 새 라우트 `GET /api/environments/session-counts`. **`/{env_id}`
  path-param 보다 반드시 먼저 선언** — FastAPI 는 declaration
  order 로 라우팅하므로 `/session-counts` 를 env_id 로 취급하는
  실수를 피한다.
- `get_session_store().list_all()` 한 번만 호출 → `env_id` 로 버킷
  분류 → active/deleted/error 카운트 집계. N 환경에 대해 RTT 1 회.

### Frontend

`frontend/src/types/environment.ts` — 수정
- `EnvironmentSessionCountEntry`, `EnvironmentSessionCountsResponse`
  TS 타입.

`frontend/src/lib/environmentApi.ts` — 수정
- `environmentApi.sessionCounts()` wrapper.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- `serverCounts` state + `refreshCounts` useCallback. mount 시 1 회
  호출, **Refresh 버튼** 은 `loadEnvironments()` 와 `refreshCounts()`
  를 함께 호출.
- 실패 시 `serverCounts` 는 null 로 유지 → `clientCountsPerEnv`
  (기존 useAppStore 집계) 로 폴백. UX 블록 없음.
- 집계 구조를 `CountBucket = { active, deleted, error }` 로 통합 →
  카드 props 가 3-카운트 동형이 됨.
- `EnvironmentCard` prop 에 `deletedCount` 추가. `Archive` 아이콘
  + 회색 tint 뱃지. 0 이면 렌더 skip.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.deletedCountTooltip` 추가 (en/ko).

## Verification

- Backend: `GET /api/environments/session-counts` 호출 시 active /
  deleted / error 버킷이 올바르게 집계되는지. env_id 없는 레코드는
  skip.
- FastAPI 라우트 순서 — `/session-counts` 가 `/{env_id}` 보다 먼저
  선언되어 있음 (line 94 vs line 152). 404 테스트로 혼동 없는지
  확인.
- Frontend: mount 즉시 서버 카운트로 렌더. useAppStore.sessions
  변해도 server 값이 우선. Refresh 버튼이 env list + 카운트 동시
  갱신.
- API 실패 (서버 죽인 상태) → 카드는 기존 클라이언트 집계로
  동작. 콘솔 에러 없이 폴백.
- Deleted 뱃지는 soft-deleted 세션이 있는 환경에만 뜬다.

## Deviations

- 카운트 재조회 주기는 수동 (Refresh 버튼) 로 두었다. WebSocket/SSE
  푸시 채널이 있긴 하지만 카드 그리드가 자주 보는 화면이 아니라
  polling 도 과함.
- `clientCountsPerEnv` 는 soft-deleted 를 세지 않는다. 이는 의도적
  — useAppStore 는 활성 세션만 담고 있어 client-only 모드는 "살아
  있는 현재" 를 보여주는 게 맞다.
- Drawer 와 달리 카드 그리드에서는 "include deleted toggle" 을
  추가하지 않았다. 카드는 always-on 표시가 맞고, deleted 를 숨길
  이유는 거의 없음 (badge 자체가 0 이면 안 보임).

## Follow-ups

- Environment 생성/삭제 직후 `refreshCounts()` 자동 트리거 — 지금은
  Refresh 버튼 눌러야 반영.
- Admin 에게만 deleted 뱃지 노출하는 role-based gate (필요시).
- Archive 아이콘 대신 시간 경과 tooltip (e.g. "3 days ago") 로
  deleted 세션 rich info.
