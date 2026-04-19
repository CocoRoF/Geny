# 19. Phase 6c — frontend Environments tab (read-only)

## Scope

Phase 6b (PR #64) 가 store 를 깔아뒀으니 그걸 구독하는 UI 를 붙인다.
`EnvironmentsTab` 하나만. 읽기 전용 카드 그리드 + 빈/로딩/에러 상태.
create / edit / duplicate / delete 는 후속 PR 들로 분리.

## PR Link

- Branch: `feat/frontend-phase6c-environments-tab`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 신규
- `useEnvironmentStore` 구독 (`environments`, `isLoading`, `error`,
  `loadEnvironments`). 마운트 시 `loadEnvironments()` 1 회 호출 +
  `Refresh` 버튼 수동 재로드.
- 카드 그리드: `grid-cols-[repeat(auto-fill,minmax(260px,1fr))]` —
  ToolSetsTab 과 시각 언어 동일 (같은 padding/border/hover 패턴).
- 상태:
  - 로딩 (최초): "Loading environments…"
  - 에러: 빨간 배너 (store 의 `error` 필드).
  - 빈 목록: 중앙 정렬 아이콘 + 안내 문구 + follow-up 언급.
  - 목록: 이름/설명/태그(4 개까지 + `+N` 표시)/updated_at.
- 카드는 read-only — view/edit/clone/delete 버튼 없음. create 버튼도
  아직 없음. follow-up PR 에서 모달 추가 시 함께 붙인다.

`frontend/src/components/TabNavigation.tsx` — 수정
- `GLOBAL_TAB_IDS` 에 `'environments'` 추가. 순서는 toolSets 다음,
  sharedFolder 앞 — 도메인 기준 (설정성 preset 들이 한 덩어리).
- `DEV_ONLY_GLOBAL` 에 `'environments'` 추가 — Normal mode 유저에게는
  안 보인다. v2 환경은 still 내부 기능이라 Dev 모드에서만 노출.

`frontend/src/components/TabContent.tsx` — 수정
- `EnvironmentsTab` lazy import + `TAB_MAP` 에 `environments` 매핑.

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `tabs.environments` 키 추가 (영어 "Environments" / 한국어 "환경").
- `environmentsTab.{title,subtitle,loading,empty,emptyHint,noDescription,updated}`
  번역 블록 추가. `updated` 는 `{date}` 변수 보간 사용 (i18n 의 기존
  `{var}` 포맷).

## Verification

- `useEnvironmentStore` 에 실제로 노출된 필드 (`environments`,
  `isLoading`, `error`, `loadEnvironments`) 만 구독 — 타입 에러 없음.
- `Translations = typeof en` 으로 ko.ts 의 타입이 en.ts 에서 파생되기
  때문에 `tabs.environments`, `environmentsTab.*` 누락 시 컴파일 에러.
  양쪽에 동일 키 동수 추가로 type check 통과 조건 만족.
- dev 서버를 직접 띄울 수는 없는 환경 (node_modules 미설치). CI /
  로컬 `npm run dev` 에서 실제 렌더 + API 연동 확인 권장.
- backend `/api/environments` 는 PR #52 로 이미 mount 되어 있으므로
  목록 호출은 성공해야 한다. 세션이 없고 manifest 도 아직 없다면
  빈 상태 UI 가 보인다.

## Deviations

- 별도 라우트 (`/environments`) 대신 탭으로 붙임. Geny 의 main 앱은
  모든 global 기능을 `app/page.tsx` 의 TabNavigation + TabContent 패턴
  으로 관리한다 (ToolSets, SharedFolder, Settings 전부 동일). 환경만
  라우트 분리하면 일관성이 깨진다.
- Dev 모드에서만 노출 — v2 EnvironmentManifest / Pipeline 은 v0.20.0
  런타임이 내부적으로 돌리는 레이어라 normal 유저에게 surface 하기엔
  너무 raw. UI 완성도가 올라오면 `DEV_ONLY_GLOBAL` 에서 빼면 된다.
- 카드에 액션 버튼 (view/clone/delete) 생략 — 후속 PR 의 modal/detail
  panel 과 함께 디자인하는 게 자연스럽다. 지금 읽기 전용 카드만
  배치해서 UX 리뷰를 한 번 받고 넘어간다.

## Follow-ups

- PR #20 (Phase 6c-2): Environment create modal. `mode` 선택자 (blank /
  from_session / from_preset) + 필수 필드 폼. `createEnvironment`
  호출 후 목록 자동 재로드 (store 가 이미 그렇게 동작).
- PR #21 (Phase 6c-3): Environment detail drawer. 카드 클릭 시 우측
  slide-over 로 manifest preview + delete/duplicate 버튼.
- PR #22 (Phase 6d): Builder 탭 (stage editor + artifact picker +
  manifest preview) — catalog API 본격 사용.
- PR #23 (Phase 6e): agent 생성 흐름 — session create modal 에 "Use
  Environment" 옵션 + `env_id` 전달.
