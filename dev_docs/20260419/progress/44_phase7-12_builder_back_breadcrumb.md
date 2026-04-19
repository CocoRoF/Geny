# 44. Phase 7-12 — BuilderTab "Back to Environments" breadcrumb

## Scope

BuilderTab 에서 환경을 편집하다가 목록으로 돌아가려면 사이드바의
Environments 탭 탭을 직접 눌러야 했다. builderEnvId 를 정리하지
않으면 다시 Builder 를 열 때 이전 env 가 그대로 남아있어 "지금
무슨 env 를 편집 중인지" 가 일순간 혼란스러운 순간이 있다.

이 PR 은 Builder 헤더 좌측에 작은 "← Back to Environments" 링크를
붙여, 한 클릭으로 `closeBuilder()` + `setActiveTab('environments')`
를 함께 수행한다.

## PR Link

- Branch: `feat/frontend-phase7-12-builder-back-breadcrumb`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/BuilderTab.tsx` — 수정
- lucide `ArrowLeft` import.
- 헤더의 `<h2>env.name</h2>` 위에 작은 back-link 버튼 추가. 클릭 시
  `closeBuilder()` 로 `builderEnvId` 를 null 로, 이어서
  `setActiveTab('environments')`.
- 스타일: muted 텍스트 + 좌측 ArrowLeft 아이콘, hover 시 primary
  텍스트 색. bg-transparent, border-none, padding 0 — 눈에 띄지
  않지만 항상 클릭 가능한 position.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `builderTab.backToEnvironments: 'Back to Environments' /
  'Environments 로 돌아가기'`

## Verification

- `closeBuilder` 는 `useEnvironmentStore.closeBuilder` — `builderEnvId`
  를 null 로 세팅 (`useEnvironmentStore.ts:159`). 이후 BuilderTab 이
  리마운트 되면 empty state 로 돌아가므로 stale 편집 상태가
  lingering 되지 않는다.
- `setActiveTab('environments')` 는 이미 empty-state 에서도 쓰는
  패턴이라 새 동작 없음. 두 호출 순서는 state update 가 batch 되어
  깜박임 없음.
- 기존 헤더의 name + id 는 그대로 유지. back 링크는 name 위 단독
  라인에 배치되어 수직 공간은 ~14px 증가.

## Deviations

- 브라우저 history (back button) 과는 연동하지 않음. Next.js app
  router 라 URL 이 탭 상태를 반영하지 않는 구조라 scope 밖.
- "Discard unsaved changes?" confirmation 은 넣지 않았다. 현재
  BuilderTab 의 edit flow 는 per-stage 로 save 를 명시적으로 눌러야
  persist 되므로 탭 전환이 곧 discard 와 동등. 별도 경고는 과도.
- 헤더 우측의 기존 view toggle (stages / tools) 와 closeLabel 버튼
  은 변경 없음.

## Follow-ups

- EnvironmentsTab 카드 → Builder 진입 시 brief "opened in builder"
  toast (현재는 탭만 바뀜).
- Builder 진입 시 자동으로 drawer 를 띄워 "변경 전 백업 export"
  prompt — 대규모 편집 전 안전망.
- Back 링크를 드로어로 돌려보내는 variant (직전 경로 기억). 현재는
  목록 탭 루트로 단순 회귀.
