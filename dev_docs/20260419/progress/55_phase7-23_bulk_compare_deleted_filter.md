# 55. Phase 7-23 — Bulk-select "Compare 2" + "Has deleted" filter chip

## Scope

Phase 7-21 bulk-select 토대 위에, 정확히 2 개가 선택된 경우만
`EnvironmentDiffModal` 을 바로 띄우는 "Compare 2" 액션을 추가한다.
이전에는 카드를 하나 열고 드로어에서 "Compare with…" 를 눌러
두 번째 env 를 픽해야 했다. 자주 하는 "A vs B" 분석을 한 번의
shift-click 으로 완결.

동시에 필터 바에 "Has deleted" 옵션을 추가해, sessionCounts 의
deleted bucket 이 있는 env 만 추릴 수 있게 한다. 대기 중인 soft-
deleted 세션이 있는 환경을 빠르게 찾을 때 유용.

## PR Link

- Branch: `feat/phase7-23-bulk-compare-and-deleted-filter`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- `StatusFilter` 에 `'has_deleted'` 추가. `filteredEnvs` 가
  `b.deleted === 0` 이면 제외.
- 필터 토글 배열에도 `'has_deleted'` 삽입.
- Bulk action bar 에 `selectedIds.size === 2` 일 때만 나타나는
  "Compare 2" 버튼 추가. 클릭 시 `setShowDiff({ left, right })`
  로 `EnvironmentDiffModal` 을 프리필 오픈. 기존 `showDiff` state
  를 재사용하므로 별도 modal 관리 불필요.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.filterStatus.has_deleted` 추가.
- `environmentsTab.bulkCompare` 추가.

## Verification

- Select 모드에서 1 개만 선택: bulk bar 에 Compare 버튼이 나타나지
  않음.
- 2 개 선택: "Compare 2" 버튼 등장. 클릭 시 DiffModal 이 두 env 로
  prefilled 되어 열림. 드로어를 거치지 않음.
- 3 개 선택: Compare 버튼 사라짐 (다시 숨김).
- `has_deleted` 칩 클릭 시 sessionCounts.deleted > 0 인 env 만
  그리드에 노출. 0 개 매칭 시 기존 "No filter match" 상태 유지.
- storeCounts 가 아직 로드되지 않아 client fallback 만 있는 경우
  deleted bucket 은 항상 0 → 해당 필터에선 빈 결과 (의도된 동작,
  서버 권위적 bucket 없이 판단할 방법이 없음).
- 기존 필터들 (`has_errors`, `has_sessions`, `idle`, `all`) 와 동일
  해석 로직으로 조립되므로 다른 칩/검색/태그와 조합 가능.

## Deviations

- Compare 버튼은 정확히 2 개 선택일 때만 노출. 3 개 이상에서
  `Compare first 2` 같은 heuristic 은 의도를 숨겨 혼란만 줌.
- `has_deleted` 는 서버 카운트에 의존. 클라이언트 fallback 을
  확장해 `useAppStore` 의 session 리스트에 is_deleted flag 를 더
  태워주는 방법도 있으나, sessions state 는 이미 활성 세션만 담고
  있어 큰 가치 없음.
- "Compare 2" 는 selectMode 종료를 자동으로 하지 않는다 — 사용자가
  DiffModal 을 닫은 뒤 다른 2 개를 추가 비교하고 싶을 수도 있다.
- 드로어의 기존 "Compare with…" 흐름은 유지. 단일 env 를 탐색 중
  에 다른 env 와 비교하고 싶은 경로는 여전히 드로어가 최단 경로.

## Follow-ups

- Multi-diff: 3 개 이상일 때 pairwise 비교 매트릭스.
- `has_deleted` 와 짝으로 "Has preset", "Has tags" 같은 meta 필터.
- Compare 결과 export (Diff JSON 다운로드) — 현재 DiffModal 에는
  없다.
