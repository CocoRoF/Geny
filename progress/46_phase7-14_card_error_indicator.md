# 46. Phase 7-14 — EnvironmentsTab card: error-state indicator badge

## Scope

Phase 7-11 에서 드로어 헤더에 running/error/other 브레이크다운을
붙였지만, 드로어를 열기 전까지는 "어느 환경에 에러 세션이 묶여
있느냐" 가 카드 그리드에서 보이지 않았다. 10 개 넘는 환경을 운영
중이면 문제 있는 환경을 찾기 위해 하나씩 드로어를 열어봐야 한다.

이 PR 은 `sessionCount` 옆에 작은 red-tint error count 배지를 추가해,
환경 목록에서 곧바로 triage 대상 카드를 식별할 수 있게 한다.
errorCount 가 0 이면 배지 자체가 렌더되지 않아 기존 카드 정보
밀도를 해치지 않는다.

## PR Link

- Branch: `feat/frontend-phase7-14-card-error-indicator`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- lucide `AlertTriangle` import.
- `errorsPerEnv` useMemo — `Record<envId, errorCount>`. 기존
  `sessionsPerEnv` 와 병렬 집계, `status === 'error'` 인 세션만 센다.
- `EnvironmentCard` prop 에 `errorCount: number` 추가. 카드 헤더
  오른쪽에 user count badge 왼쪽으로 error badge 배치 (에러가
  먼저 눈에 들어오도록).
- Error badge 스타일: red tint (`rgba(239,68,68,*)`) + AlertTriangle
  아이콘 + count — 기존 status badge 팔레트와 동일.
- `errorCount > 0` 일 때만 렌더 — 평소엔 노이즈 없음.
- 카드 맵 호출부에서 `errorsPerEnv[env.id] ?? 0` 전달.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.errorCountTooltip: '{n} session(s) bound to this
  environment are in error state' / '이 환경에 바인딩된 세션 중 {n}
  개가 에러 상태입니다'`

## Verification

- `useAppStore.sessions` 상태가 바뀌면 `errorsPerEnv` 가 재계산되어
  카드 배지도 실시간 반영. 세션이 error 상태로 전이된 직후 해당
  환경 카드에 배지가 뜬다.
- 에러가 0 이면 badge 자체 skip — 기존 카드 레이아웃 유지.
- 배지 순서 (error → success) 는 "문제가 있으면 먼저 보여준다"
  원칙. running badge 는 평시에 익숙한 녹색이라 오른쪽으로 밀어도
  인지에 무리 없음.
- 카드 클릭 → 드로어 → Linked sessions 브레이크다운 섹션으로
  이어지는 흐름은 그대로. 배지가 "drill-down 트리거" 역할.

## Deviations

- 에러 외 other 상태 (idle/stopped/queued) 는 카드에 노출하지 않음.
  카드는 "문제가 있느냐" 와 "얼마나 쓰이느냐" 만 답하면 되고, 세부
  분류는 드로어 브레이크다운이 이미 담당.
- 배지 클릭 시 에러 세션만 필터링해 드로어를 여는 anchor 동작은
  넣지 않았다. 드로어 진입 후 Linked sessions 섹션의 error badge
  수치와 개별 row 색으로 충분.
- 빨간 배지를 튀게 만드는 live-pulse 애니메이션은 넣지 않았다.
  정보 밀도가 높은 관리 화면에서 불필요한 주의 끌기는 피한다.

## Follow-ups

- 배지 클릭 → 드로어 + scroll-to "Linked sessions" + error 필터.
- 카드 정렬 옵션 — "error 먼저" 를 기본으로 하는 sort.
- 카드 그리드 상단에 "X environments have errors" 롤업 문구 —
  카드 수가 매우 많을 때 유용.
