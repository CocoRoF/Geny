# 18. Phase 6b — frontend Environment Zustand store

## Scope

Phase 6a (PR #63) 가 깐 types + API client 위에 상태 관리 store 를
한 번에 깐다. UI 컴포넌트는 다음 PR (6c+). 이 PR 의 store 는 어디서도
subscribe 되지 않으므로 런타임 영향 없음.

## PR Link

- Branch: `feat/frontend-phase6b-env-store`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/store/useEnvironmentStore.ts` — 신규
- Zustand store. 기존 `useToolPresetStore` 패턴을 그대로 따름 — 같은
  파일에 데이터 필드 + 액션을 함께 선언, 에러는 store 안에 `error`
  필드로 보관, loading 플래그는 액션 단위.
- 데이터 필드: `environments` (목록), `selectedEnvironment` (상세),
  `catalog` (stage/artifact), `isLoading`, `isLoadingCatalog`, `error`.
- 액션 (`environmentApi` 1:1 wrap):
  - `loadEnvironments`, `loadEnvironment(envId)`, `clearSelection`
  - `createEnvironment`, `updateEnvironment`, `deleteEnvironment`,
    `duplicateEnvironment`
  - `replaceManifest(envId, manifest)`, `updateStage(envId, stageName, payload)`
  - `exportEnvironment`, `importEnvironment`, `markPreset`,
    `unmarkPreset`
  - `loadCatalog`
- `update*` / `delete*` 액션은 응답을 받자마자 store 의 `environments`
  / `selectedEnvironment` 캐시를 직접 갱신 (전체 reload 회피) — UI
  체감 latency 축소. 단 `create*` / `import*` / `duplicate*` 는 새
  ID 가 발생하므로 `loadEnvironments()` 로 재조회 (간단함 + 정확함).
- 모든 액션이 try/catch 으로 감싸지지는 않음 — `loadEnvironments` /
  `loadEnvironment` 같은 단순 fetcher 만 store 내부에서 에러 캐치
  (UI 가 `error` 필드를 읽을 수 있게). mutation 액션은 caller 가 try/
  catch 하도록 throw 그대로 — modal/toast 위치 결정권은 UI 에 있음.

## Verification

- TypeScript 임포트 경로 모두 유효 (`@/lib/environmentApi`,
  `@/types/environment`, `zustand` — package.json 에 zustand ^5.0.11
  존재).
- 어디서도 `useEnvironmentStore` 를 import 하지 않으므로 런타임 동작
  불변. dev/prod 빌드는 트리쉐이킹으로 store 자체가 번들에 포함되지
  않을 수도 있음.
- 액션 시그니처는 web 의 `environmentStore.ts` 와 호환되는 shape —
  Builder UI 포팅 시 dispatch call 의 변경 최소.

## Deviations

- web 의 store 는 `environmentBuilderStore.ts` 와 `environmentStore.ts`
  로 두 개 분리되어 있다. Geny 는 한 파일로 통합한 이유: Builder 가
  결국 `selectedEnvironment` + `catalog` 를 함께 본다. 분리하면 두
  store 사이 cross-update (manifest 저장 후 list 갱신 등) 가 boilerplate
  를 만든다. 단일 store 내부 `set` 으로 캐시 일관성 관리가 더 단순.
- React Query / SWR 같은 캐시 라이브러리 도입 안 함 — Geny 는 이미
  zustand 를 모든 store 에 사용 중. 일관성을 깨기보다 같은 패턴 유지.
- mutation 액션의 에러 처리는 caller 에 위임 — toast / inline error
  UI 위치를 Builder 가 결정. store 가 `error` 를 강제로 채우면 다른
  UI 가 띄운 modal 과 충돌할 수 있다.

## Follow-ups

- PR #19 (Phase 6c): Environment list 페이지 (`/environments`) 추가.
  `useEnvironmentStore.loadEnvironments()` + 카드 그리드 렌더 + 빈
  상태 / 로딩 / 에러 표시. read-only.
- PR #20 (Phase 6c-2): Environment create modal (mode selector: blank /
  from_session / from_preset). `createEnvironment` 액션 사용.
- PR #21 (Phase 6d): Builder 탭 — stage editor + artifact picker +
  manifest preview. Catalog API + manifest editor.
- PR #22 (Phase 6e): agent 생성 흐름에 env_id 통합.
