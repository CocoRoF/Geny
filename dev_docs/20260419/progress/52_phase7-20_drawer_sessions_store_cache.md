# 52. Phase 7-20 — Lift drawer linked-sessions into the env store with TTL cache

## Scope

Phase 7-18/7-19 가 카드 그리드의 `/session-counts` 는 store 로
올렸지만, `EnvironmentDetailDrawer` 의 `/environments/{id}/sessions`
호출은 여전히 컴포넌트 로컬 state (`serverSessions`) + `useEffect`
에 직접 묶여 있었다. 결과적으로:

1. 같은 env 드로어를 닫았다 다시 열면 매번 네트워크 호출.
2. 다른 브라우저 탭이 세션을 만들면 드로어가 stale — 수동
   reload 까지는 visibility 이벤트도 반응하지 않음.
3. 여러 뷰가 같은 데이터를 공유할 hook 이 없음.

이 PR 은 drawer-sessions 를 `useEnvironmentStore` 의 캐시로
올리고, (envId, includeDeleted) 키로 버킷팅한다. focus/visibility
전환 시 10 초 TTL 로 재조회를 게이트한다. 수동 Refresh 버튼도
헤더에 추가.

## PR Link

- Branch: `feat/phase7-20-drawer-sessions-store-cache`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/store/useEnvironmentStore.ts` — 수정
- 타입 `DrawerSessionsEntry = { sessions, fetchedAt }` export.
- state 추가: `drawerSessions: Record<"envId:active|all", entry>`.
- 액션 추가:
  - `loadDrawerSessions(envId, includeDeleted)` — 캐시 hit 이면
    즉시 반환, miss 면 `refreshDrawerSessions` 위임.
  - `refreshDrawerSessions(envId, includeDeleted)` — 무조건 재조회,
    성공 시 캐시 덮어쓰기.
  - `refreshDrawerSessionsIfStale(envId, includeDeleted, ttlMs)` —
    TTL 내면 no-op.
  - `invalidateDrawerSessionsForEnv(envId)` — active/all 두 키 드롭.
- `deleteEnvironment` 도 해당 env 의 drawer-sessions 캐시를
  함께 비운다.

`frontend/src/components/EnvironmentDetailDrawer.tsx` — 수정
- `environmentApi` 직접 import 제거.
- `drawerSessionsCache` 구독 + 로컬 `serverSessions` useState 삭제.
  대신 캐시에서 `cachedEntry` 를 읽고 파생값으로 넘긴다.
- mount / showDeleted 변경 시 `loadDrawerSessions` 호출 (캐시 hit 이면
  네트워크 호출 없음, 스피너 즉시 생략).
- `visibilitychange` + `focus` 리스너 attach, 핸들러에서
  `refreshDrawerSessionsIfStale(envId, showDeleted, 10_000)`.
- 헤더에 수동 Refresh 아이콘 버튼 (RefreshCw) 추가 — 클릭 시
  무조건 `refreshDrawerSessions`.

`frontend/src/lib/i18n/{en,ko}.ts` — 수정
- `environmentDetail.refreshSessions` 키 추가 (버튼 title).

## Verification

- 드로어 최초 오픈: cache miss → `refreshDrawerSessions` 가
  API 호출 → 캐시에 entry 기록, 기존 UX 와 동일한 스피너/리스트.
- 드로어 닫고 다시 열기 (같은 env, 같은 showDeleted): cache hit
  이라 network 호출 없이 즉시 렌더. 스피너는 안 뜬다.
- `Include soft-deleted` 토글: 새 key (`envId:all`) 캐시 miss →
  즉시 fetch. 반대로 토글하면 기존 active key 캐시에서 즉시 복귀.
- 드로어 열린 채 브라우저 탭 전환 → 10 초 경과 후 복귀:
  visibility 이벤트 → TTL 체크 통과 → 캐시 갱신. 리스트 자연스럽게
  업데이트.
- 10 초 이내 탭 전환 후 복귀: TTL 게이트로 no-op, API 호출 없음.
- 드로어 헤더의 Refresh 버튼: 즉시 refetch, 스피너 애니메이션.
- `deleteEnvironment` 후: 해당 env 의 drawer-sessions 캐시가
  비워지므로 나중에 같은 id 로 다시 열리는 일이 있어도 stale
  데이터를 보여주지 않는다.
- 네트워크 단절: `refreshDrawerSessionsIfStale` 이 예외를 삼키므로
  TTL 도 갱신되지 않아 다음 focus 에 재시도. 수동 Refresh 버튼은
  예외를 `sessionsError` 로 노출.

## Deviations

- 캐시 TTL 을 10 초로 고정 (카드 그리드와 동일). 환경별 customize
  훅은 과도.
- 세션 CRUD (다른 컴포넌트의 create/delete) 시 drawer-sessions 를
  직접 invalidate 하지는 않는다. 드로어는 focus/visibility 에 반응
  하므로 다음 재진입 시 자연스럽게 갱신. WS/SSE push 가 생기면 그때
  `invalidateDrawerSessionsForEnv` 를 구독자에서 호출.
- `loadDrawerSessions` 는 미리 fetch-on-miss 만 한다. 프리페치
  (hover 시) 같은 최적화는 향후 과제.
- 캐시를 persist 하지 않는다. 새로고침 후엔 다시 miss.

## Follow-ups

- SSE/WS 채널이 붙으면 "세션 상태 변경 broadcast" 를 받아 해당
  env 의 drawer cache 를 즉시 invalidate.
- 카드 hover 시 `loadDrawerSessions` 프리페치 — 드로어 오픈 시 flash
  회피.
- `createSession` / `deleteSession` 이 env 에 속한 경우 해당 env 의
  drawer cache 를 optimistic 으로 갱신.
