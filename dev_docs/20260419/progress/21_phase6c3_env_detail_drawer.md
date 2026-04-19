# 21. Phase 6c-3 — Environment detail drawer

## Scope

카드 클릭 → 오른쪽 slide-over drawer. manifest preview (read-only) +
duplicate / export / delete. Create modal 도 성공 시 새로 생성된 env
의 drawer 를 바로 연다.

## PR Link

- Branch: `feat/frontend-phase6c3-env-detail-drawer`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/EnvironmentDetailDrawer.tsx` — 신규
- `createPortal` 로 `document.body` 에 렌더. backdrop + 520px (sm+)
  slide-over panel. 모바일에서는 full-width.
- 마운트 시 `loadEnvironment(envId)`, 언마운트 시 `clearSelection()` —
  store 의 `selectedEnvironment` 는 drawer 전용으로 취급.
- 본문: metadata (description, tags, created_at, updated_at, id) +
  manifest JSON preview (`<pre>` 스크롤 박스, max-h 360px).
- 푸터 액션:
  - **Delete** (danger border) → `ConfirmModal` 재사용. 확인 시
    `deleteEnvironment()` 호출 후 drawer 닫음. store 가 이미 로컬
    cache 에서 제거 → 리스트 즉시 갱신.
  - **Clone** → `window.prompt` 로 새 이름 요청 (취소/공백 시 no-op).
    `duplicateEnvironment()` 호출 성공 시 drawer 닫음 (새 env 는
    store 가 `loadEnvironments()` 로 재조회).
  - **Export** → `exportEnvironment()` 응답을 `Blob` + `<a download>`
    로 클라이언트 다운로드. 파일명은 `env-<safeName>.json`.
- load/action 에러는 배너로 분리 표기 (loadError vs actionError).
  mutation 액션 에러는 drawer 안에서 핸들 — store 가 mutation 은
  throw 하도록 되어 있으므로 (Phase 6b deviation 의 설계).

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- 카드에 `onClick` prop 추가 → 드로어 열림 (`openEnvId`).
- `CreateEnvironmentModal` 에 `onCreated={id => setOpenEnvId(id)}` 연결 —
  새 env 생성 직후 drawer 가 바로 열려 사용자가 manifest 를 확인하고
  Builder 흐름으로 넘어가기 쉬움 (Phase 6d 에서 Builder 탭과 연결
  예정).

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `environmentDetail.*` 블록 추가 (제목, 로딩/에러 메시지, 액션 라벨,
  삭제 확인 문구).

## Verification

- `selectedEnvironment.id !== envId` 인 경우를 가드 — 이전 env 의 잔재
  데이터로 잘못 표시하지 않도록 drawer 내부에서 `env = ... ? : null`.
- `typeof document === 'undefined'` 가드 유지 — SSR 초기 pass 에서
  안전.
- export 응답 타입은 `string | object` 어느 쪽이든 처리 — backend 가
  `exportEnv()` 에서 JSON 문자열을 그대로 돌려주지만 방어적 수준.
- `ConfirmModal` 의 `message` prop 이 `string | ReactNode` 라서
  `t(..., { name })` 보간 결과를 그대로 넘김.

## Deviations

- Duplicate 이름은 `window.prompt` 사용. 정식 modal 한 개 더 만드는
  것보다 훨씬 짧고, 이름 입력만 받으면 되는 단일 필드이기 때문에
  UX 손해가 크지 않다. 이상해 보이면 나중에 inline rename 패널로
  교체.
- Edit manifest / stage editor 는 이번 drawer 에 포함하지 않음 — Phase
  6d (Builder 탭) 가 풀 에디터를 갖는다. drawer 는 빠른 read/
  destructive action 만.
- `ConfirmModal` 의 확인 버튼이 `danger` 톤으로 고정이지만 그대로 사용.
  환경 삭제는 destructive 하므로 적절.
- `handleDelete` 내부 에러는 throw 로 남겨 `ConfirmModal` 의
  `loading=false` reset 으로 회귀하게 둠 — drawer 의 actionError 배너
  는 duplicate/export 에서만 표시.

## Follow-ups

- PR #22 (Phase 6d): Builder 탭 — stage editor, artifact picker,
  manifest diff preview. Catalog API (`useEnvironmentStore.loadCatalog`)
  본격 사용. drawer 의 "Open in Builder" 버튼으로 탭 전환 가능하게.
- PR #23 (Phase 6e): agent 생성 흐름에 env_id 선택 UI 통합. session
  create modal 의 "Use Environment" 옵션. drawer 에서 "Use in new
  session" shortcut 도 고려.
- PR #24 (Phase 6f): Environment diff 뷰어 — `environmentApi.diff` 를
  사용해 두 env 의 차이 시각화.
