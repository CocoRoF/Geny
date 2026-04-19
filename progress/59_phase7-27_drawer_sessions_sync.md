# 59. Phase 7-27 — Drawer sessions cache: hover prefetch + session-lifecycle invalidation

## Scope

Phase 7-20 의 follow-up 두 개를 묶어서:

1. **Hover prefetch** — Environments 카드에 마우스를 올리면 해당
   env 의 drawer linked-sessions 를 미리 조회해 캐시. 드로어를
   열었을 때 순간적 빈 화면/로딩이 사라진다.
2. **Session-lifecycle invalidation** — `useAppStore.createSession`
   과 `deleteSession` 이 `env_id` 가 있으면 환경 store 의 drawer
   cache 를 invalidate. 지금은 focus/visibility TTL (10s) 을 기다려야
   반영되므로 방금 만든 세션이 드로어에 안 보이는 window 가 있다.

두 개 모두 drawer linked-sessions cache 의 정확성/응답성 문제.
묶어서 하나의 PR 로.

## PR Link

- Branch: `feat/phase7-27-drawer-sessions-sync`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/store/useEnvironmentStore.ts` — 수정
- 모듈 스코프 `inflightDrawerFetches: Set<string>` 로 prefetch 중복
  억제.
- 신규 액션 `prefetchDrawerSessions(envId, includeDeleted)` — 이미
  캐시되어 있거나 inflight 면 no-op, 아니면 `refreshDrawerSessions`
  fire-and-forget. 에러는 삼킴 (드로어가 열릴 때 imperative path 가
  재시도/서피스).
- 타입/액션 인터페이스에 `prefetchDrawerSessions` 추가.

`frontend/src/store/useAppStore.ts` — 수정
- `useEnvironmentStore` 를 import.
- `createSession` 에서 반환된 session 의 `env_id` 가 있으면 해당 env
  의 drawer cache 를 invalidate.
- `deleteSession` 에서 삭제 전에 `state.sessions` 에서 `env_id` 를
  찾아두고, 삭제 후 invalidate.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- `EnvironmentCard` 에 optional `onHoverPrefetch` prop. `onMouseEnter`
  와 `onFocus` (키보드 포커스 지원) 에서 호출.
- Select mode 에서는 prefetch 를 건너뜀 (드로어 열 의도 없음).

## Verification

### Hover prefetch

- Environments 그리드 위에서 카드를 한 번씩 훑기 → 네트워크 탭에
  env 별 `GET /api/environments/{id}/sessions?include_deleted=false`
  가 한 번씩만 발생 (중복 없음).
- 카드를 클릭해서 드로어를 열면 linked-sessions 섹션이 즉시 렌더
  (spinner 없이).
- 동일 카드에 여러 번 호버해도 추가 요청이 발생하지 않음.
- Select 모드에서는 호버해도 네트워크 요청이 발생하지 않음.

### Session-lifecycle invalidation

- env X 의 드로어를 열어 linked sessions 를 로드 → 캐시 warmed.
- 드로어 닫고 env X 에 바인딩된 새 session 을 생성.
- 드로어 재오픈 → 새 session 이 바로 보인다 (focus/visibility TTL
  대기 없이).
- env X 의 session 을 삭제 → 드로어 재오픈 시 해당 session 이
  active list 에서 사라진다 (include_deleted=true 로 토글하면
  deleted list 에 등장).
- env_id 가 없는 standalone session 을 만들고 지워도 drawer cache
  에는 영향 없음 (invalidate 호출 안 됨).

## Deviations

- `useAppStore.ts` 가 `useEnvironmentStore` 를 직접 import 하는 형태.
  순환 참조 없음 (환경 store 는 app store 를 참조하지 않음). 이벤트
  bus 를 빼고 직접 참조하는 편이 타입 안전하고 간단.
- Prefetch inflight 집합을 모듈 스코프에 둠. Zustand state 로
  올릴 수도 있지만 UI 에 렌더링할 필요가 없어 오히려 noisy.
- hover prefetch 는 `includeDeleted=false` (active only). 드로어
  가 기본으로 로드하는 것과 일치. 토글이 켜진 상태로 열면 그제서야
  두 번째 요청이 나간다 (TTL-gated).
- Debounce 를 걸지 않음. 이미 cache/inflight guard 가 있어 불필요한
  요청은 발생하지 않고, debounce 를 걸면 오히려 처음 한 번의 호버
  에서 캐시가 늦게 채워진다.

## Follow-ups

- `createSession` 의 반환 객체에 항상 `env_id` 가 실려오지 않을
  가능성 — 필요하면 `loadSessions` 이후 state 에서 다시 lookup 해
  보강.
- 세션 상태 변경 (error → running 등) 은 아직 cache 에 반영되지
  않음. WS/SSE broadcast 시점에 `invalidateDrawerSessionsForEnv` 를
  같이 호출하면 완전.
- 드로어 안에서 linked-session 을 클릭해 세션 상세를 보는 drill-down
  은 이미 있음 (Phase 7-7). 이제 양방향 sync 가 필요.
