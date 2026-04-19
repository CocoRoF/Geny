# 47. Phase 7-15 — Reverse-lookup endpoint for env→sessions + drawer upgrade

## Scope

Phase 7-7 이후의 Linked sessions UX (PR #85, #89, #92, #99) 는 모두
`useAppStore.sessions` 를 클라이언트에서 필터링하는 방식이었다. 이는
두 가지 한계를 가진다.

1. soft-delete 된 세션이 전혀 보이지 않아, "이 환경이 과거에 어떤
   세션에 바인딩됐었나" 감사 (audit) 가 불가능.
2. `useAppStore.sessions` 가 비어있는 상태 (drawer 가 첫 오픈되거나
   세션 스토어 미초기화) 에선 "N sessions" 숫자가 틀릴 수 있다.

Phase 7-15 는 백엔드에 권위 있는 reverse-lookup API 를
하나 추가해서 이 두 한계를 닫는다. 드로어는 SSR-safe 초기값으로
클라이언트 집계를 계속 쓰되, mount 직후 API 를 호출해 server
데이터로 덮어쓴다. "Include soft-deleted" 체크박스도 추가해
운영 중 사라진 환경에 발목 잡혔던 세션 이력을 함께 볼 수 있다.

## PR Link

- Branch: `feat/phase7-15-env-sessions-reverse-lookup`
- PR: (커밋 푸시 시 발행)

## Summary

### Backend

`backend/service/environment/schemas.py` — 수정
- `EnvironmentSessionSummary` / `EnvironmentSessionsResponse` Pydantic
  모델 신설. 전자는 SessionStore 레코드에서 env→drill-down 에 쓰는
  필드 (id, name, status, role, env_id, created_at, is_deleted,
  deleted_at, error_message) 만 투영. 후자는 `env_id`, `sessions`,
  그리고 active/deleted/error count 를 반환.
- `__all__` 에 두 이름 추가.

`backend/controller/environment_controller.py` — 수정
- 스키마 import 확장.
- `GET /api/environments/{env_id}/sessions?include_deleted=false`
  라우트 신설. 흐름:
  1. `_env_svc(request).load(env_id)` 로 env 존재 확인 (없으면 404).
  2. `get_session_store()` 싱글톤에서 `list_all` 또는 `list_active`
     호출 (`include_deleted` 스위치).
  3. `r.get("env_id") == env_id` 로 필터.
  4. `EnvironmentSessionSummary` 로 매핑 + active / deleted / error
     카운트 집계.
- SessionStore 의 `list_*` 가 이미 `SessionInfo.model_dump(mode="json")`
  로 직렬화된 dict 를 돌려주기 때문에 env_id 필드는 record 에 그대로
  존재. 별도 어댑터 없이 dict key 매핑만 해 준다.

### Frontend

`frontend/src/types/environment.ts` — 수정
- TS 쌍둥이: `EnvironmentSessionSummary`, `EnvironmentSessionsResponse`.

`frontend/src/lib/environmentApi.ts` — 수정
- `environmentApi.linkedSessions(envId, includeDeleted = false)` 추가.
  쿼리 문자열로 `include_deleted=true|false` 전달.

`frontend/src/components/EnvironmentDetailDrawer.tsx` — 수정
- `serverSessions` / `sessionsFetching` / `sessionsError` /
  `showDeleted` 로컬 state 추가. drawer mount 와 `showDeleted` 변경
  시 API 호출, 결과를 `serverSessions` 에 넣는다.
- `clientLinkedSessions` (기존 `useAppStore.sessions` 집계) 는 fallback
  용 `EnvironmentSessionSummary` 모양으로 매핑. API 가 실패하거나
  아직 응답 전이면 이 값을 사용 → 드로어 오픈 즉시 0건 깜빡임
  제거.
- `linkedBreakdown` 에 `deleted` 카운트 추가, 헤더에 deleted 뱃지
  (rgba 148/163/184) 함께 렌더.
- 리스트 행: `is_deleted` 세션은 opacity-60 + line-through + 클릭
  disabled, 툴팁으로 "삭제된 세션" 안내.
- "Include soft-deleted" 체크박스 UI 추가. 체크 시 API 를 재호출
  (`list_all` 분기).
- fetch 실패 시 fallback 안내 문구 + 클라이언트 집계로 계속 동작.
- 로딩 중에는 `RefreshCw` 아이콘을 헤더 옆에 spin 으로 표시.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- 새 키: `environmentDetail.breakdownDeleted`, `statusDeleted`,
  `showDeleted`, `sessionDeletedHint`, `linkedSessionsFallback`.

## Verification

- `GET /api/environments/{id}/sessions` — env 존재 + 미존재 케이스
  수동 확인. include_deleted=true 시 soft-deleted 레코드 포함되는지,
  false 시 제외되는지 토글해서 확인.
- 드로어 열면 client 집계가 즉시 보이고 (인지 지연 없음), 다음 렌더
  프레임에 서버 응답으로 치환됨. 네트워크 죽은 상태에서 열어도
  이전 UX 그대로 동작 (`sessionsError` + fallback 문구만 추가).
- `Include soft-deleted` 토글 시 API 재호출, deleted 뱃지가 헤더에
  새로 뜨며 리스트에 삭제된 세션이 회색 + line-through 로 렌더.
- 삭제된 세션 row 를 클릭해도 Chat 탭으로 점프하지 않음 — disabled
  처리.

## Deviations

- API 응답에 `last_used_at` / `error_message` 는 스키마에 포함했으나
  드로어 UI 에 노출하지 않았다. 필드는 살려 두되 visual noise 를
  피하기 위해 표시는 스킵. 추후 세션 hover tooltip 으로 확장 가능.
- Drawer 가 mount 될 때 매번 API 를 때리는 single-fetch 전략. 재오픈
  자주 하는 사용자라면 `react-query` 급 캐싱이 있으면 좋겠으나,
  지금의 단일-엔드포인트-단일-드로어 페어에선 오버킬.
- Environment 카드 그리드의 `sessionsPerEnv` / `errorsPerEnv` 집계
  (PR #85, #99) 는 이 PR 에선 손대지 않았다. 카드에 실시간성이
  더 중요하고 drawer 진입 시점에 API 로 reconcile 하는 편이 읽기
  흐름에 자연스럽다.
- SessionStore 의 DB/JSON 2중 경로는 기존 `list_all` / `list_active`
  가 이미 처리하므로 controller 는 얇게 둠.

## Follow-ups

- Environments 카드 그리드에도 "Include soft-deleted" 를 반영할지
  여부 (현재는 가리고만 있음). 카드에 deleted 카운트 추가하면
  audit UX 가 일관됨.
- 삭제된 세션 row 를 클릭 시 "복구" 액션을 제공 (soft-delete 복구
  API 가 있다면 연결).
- `last_used_at` / 환경 변경 이력 같은 보조 필드를 hover tooltip
  으로 드러내는 2차 UX.
