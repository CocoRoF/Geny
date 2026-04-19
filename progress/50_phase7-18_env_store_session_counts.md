# 50. Phase 7-18 — Session-counts moved into env store; auto-refresh on CRUD

## Scope

Phase 7-16 은 bulk session-counts endpoint 를 도입했지만 상태를
`EnvironmentsTab` 로컬 useState 에 두었다. 이 때문에:

1. 다른 컴포넌트 (예: Create/Import 모달) 가 환경을 만들어도 탭이
   강제로 리마운트되지 않으면 카운트가 stale.
2. 드로어 등 다른 UI 가 같은 데이터를 재활용할 수 없다.
3. delete/duplicate/import 직후 Refresh 버튼을 눌러야만 카드
   카운트가 바뀌는 민망한 UX.

이 PR 은 `useEnvironmentStore` 로 `sessionCounts` 상태와
`refreshSessionCounts()` 액션을 올리고, 모든 mutation 끝에 해당
액션을 fire-and-forget 으로 호출한다. 탭 컴포넌트는 로컬 state
를 버리고 스토어만 구독한다.

## PR Link

- Branch: `feat/phase7-18-env-store-refresh-counts-hook`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/store/useEnvironmentStore.ts` — 수정
- 새 타입 `EnvSessionCountBucket` export (`{ active, deleted, error }`).
- state 에 `sessionCounts: Record<envId, EnvSessionCountBucket> | null`
  + action `refreshSessionCounts()`. 실패시 기존 값을 보존 (폴백
  유지).
- `createEnvironment`, `duplicateEnvironment`, `importEnvironment`
  끝에 `void get().refreshSessionCounts()` 추가 — 리스트 갱신과
  동시에 카운트도 최신화.
- `deleteEnvironment`: 낙관적으로 `sessionCounts` 에서 해당 env
  키 제거 후, 서버 재조회로 reconcile.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- 로컬 `serverCounts` / `refreshCounts` 제거. 대신 스토어에서
  `sessionCounts` 와 `refreshSessionCounts` 구독.
- `environmentApi` import 도 제거 (더 이상 직접 호출 안 함).
- Refresh 버튼은 스토어 액션으로 변경.
- 클라이언트 폴백 로직 (`clientCountsPerEnv`) 은 유지.

## Verification

- Create Environment 완료 직후: 카드 그리드가 새 env 를 노출하고,
  세션 0 상태이므로 모든 카운트 뱃지 없이 렌더. 기존 env 의 카운트
  도 변함 없음.
- Import Environment 성공: 새 id 의 env 가 나타나며 카운트 맵
  에도 해당 env 의 빈 bucket (없으면 `countsPerEnv[env.id] ??
  {0,0,0}`) 로 표시.
- Delete: 해당 env 카드가 즉시 사라지고 sessionCounts 에서도
  해당 key 제거. 서버 재조회 이후 동일 상태 유지.
- Duplicate: 복제된 env 가 리스트에 등장, 카운트 전부 0 으로 렌더
  (아직 세션 없음).
- 다른 탭 (InfoTab 등) 에서 store 의 `sessionCounts` 를 구독해도
  동일 데이터로 일관.
- API 실패 시: `refreshSessionCounts` 가 기존 값을 보존 → UX
  회귀 없음. 최초 mount 이후 첫 fetch 만 실패하면 `null` 유지 →
  클라이언트 폴백 경로가 동작.

## Deviations

- Polling 이나 WS 스트리밍은 도입하지 않음. 세션 state 변화
  (running ↔ error) 를 실시간 반영하려면 push 채널이 이상적이지만,
  카드 그리드가 자주 보는 뷰가 아니라 수동 Refresh 로 충분.
- `updateEnvironment` / `replaceManifest` / `updateStage` 뒤에는
  카운트 재조회를 걸지 않는다. 매니페스트 편집은 세션 bind 를
  바꾸지 않으므로 서버 카운트가 변할 리 없다.
- `sessionCounts` 를 persist 하지 않는다. 탭 전환 후 복귀시
  mount 시 재조회. localStorage 로 캐시하면 flicker 는 줄겠지만
  stale 데이터를 불러올 위험이 더 큼.

## Follow-ups

- SSE 또는 WS 기반 "세션 상태 변경 brodcast" 파이프로 연동 시
  `refreshSessionCounts` 를 구독자에서 자동 호출.
- 드로어의 단일-env `/sessions` 호출도 store 에 올려 캐시 공유
  (같은 env 를 여러 번 열 때 재조회 안 하도록).
- 카운트 TTL 기반 자동 재조회 (예: 60s 경과 시 refresh).
