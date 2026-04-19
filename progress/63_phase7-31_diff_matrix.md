# 63. Phase 7-31 — Multi-environment diff matrix

## Scope

Phase 7-23 이후로 "Compare 2" 만 있던 비교 경로에 3 개 이상 선택 시
pairwise 매트릭스를 보여 주는 `EnvironmentDiffMatrixModal` 추가.
N×N 그리드의 각 upper-triangle 셀은 `+A/-R/~C` 요약을 표시하고
클릭하면 기존 `EnvironmentDiffModal` 이 해당 쌍으로 열린다.

백엔드는 그대로. `environmentApi.diff(a, b)` 를 pair 수만큼 호출하되
동시성 4 로 bounded. 10 개 선택 = 45 쌍 = 12 배치면 끝난다.

## PR Link

- Branch: `feat/phase7-31-diff-matrix`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/EnvironmentDiffMatrixModal.tsx` — 신규
- Props: `{ envIds: string[]; onClose: () => void }`.
- `runWithConcurrency(tasks, 4)` 로 pair diff 병렬 실행.
- 각 cell 은 `pending` (Loader2) / `ok` (+A/-R/~C 또는 `=`) /
  `error` ("err" + title 툴팁) 중 하나.
- 대각선은 `—`, 하단 삼각형은 상단의 mirror (opacity 60%).
- 상단 삼각형 셀 클릭 → 내부 `EnvironmentDiffModal` 인스턴스 오픈.
- 그리드는 inline-grid + minmax 컬럼으로 가변 너비, overflow-auto.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- 신규 state `matrixIds: string[] | null`.
- Bulk 툴바에 `selectedIds.size >= 3` 일 때 "Compare N (matrix)" 버튼
  노출. 기존 Compare 2 는 정확히 2 선택 시 그대로.
- `matrixIds` 가 설정되면 `EnvironmentDiffMatrixModal` 렌더.

`frontend/src/lib/i18n/en.ts` / `ko.ts` — 수정
- 신규 namespace `diffMatrix` (title/subtitle/tooFew/cellTooltip/
  cornerLabel/legend).
- `environmentsTab.bulkCompareMatrix` (기존 bulkCompare 옆에).

## Verification

- 3 개 선택 → "Compare 3 (matrix)" 버튼 노출, 클릭 → 3×3 매트릭스 열림,
  3 개 pair (3C2) 각각 로딩 스피너 → 순차적으로 `+A/-R/~C` 또는 `=`
  로 채워짐.
- 4 개 선택 → 6 pair, 동시성 4 이라 한 번에 4 개까지만 spinner.
- 동일한 두 env 를 골라도 섞여 있으면 `=` 표시 (success 색).
- 상단 삼각형 셀 클릭 → `EnvironmentDiffModal` 이 그 pair 로 열리고,
  닫아도 매트릭스 모달은 그대로 유지.
- 한 pair 가 실패하면 `err` 표시 + hover 툴팁에 에러 메시지.
- 2 개 선택 시에는 기존 Compare 2 만 노출 (matrix 버튼 없음).
- ESC 또는 backdrop 클릭으로 닫기, 닫으면 in-flight diff 가 state
  update 안 함 (cancelled flag).
- ko 로케일에서 모든 라벨 한국어.

## Deviations

- 동시성 4 는 임시 하드코딩. 환경 수가 많으면 (20 선택 = 190 pair) 더
  큰 값이 빨라지지만 서버 부하를 우려해 낮게. 필요 시 Props 또는
  Settings 로 노출.
- 하단 삼각형을 공란으로 두지 않고 opacity 60% 미러로 표시. 매트릭스
  는 symmetric 이라 중복이지만, 한쪽이 비면 눈이 어색해서 미러 표시가
  더 자연스러움 (단 하단은 비클릭).
- 개별 pair 실패는 단독 에러로 남겨 두고 전체 재시도 버튼은 제공하지
  않음. 특정 env 하나가 망가지면 그 row/col 전체가 `err` 가 되어
  어느 env 문제인지 파악하기 쉬움 (의도된 정보 밀도).
- 셀 크기는 72–110px 가변. 긴 이름은 행 헤더에서 truncate + title 툴팁.
  매트릭스가 10+ 개면 가로 스크롤로 처리.
- "Export matrix" 같은 기능은 이번 범위 밖 (Phase 7-30 처럼 별도 PR
  에서 처리 가능).

## Follow-ups

- Matrix export (JSON/MD) — 각 pair 의 summary + 필요시 full diff 를
  한 파일로 내보내기.
- Concurrency 설정을 UI 에 노출 (서버 부하 vs 속도 trade-off 사용자
  결정).
- Matrix 에서 "가장 서로 다른 pair" 랭킹 — Phase 7-23 다른 follow-up.
- Phase 7-29 의 Auto-suffix 동선을 toast 로 알려 주기 (이번에도 이월).
