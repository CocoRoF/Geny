# 53. Phase 7-21 — Multi-select + bulk delete/export on Environments tab

## Scope

Environments 그리드에서 지금까지는 단건 CRUD 만 가능했다. 운영
시 다수의 test/preview 환경을 한 번에 정리하고 싶을 때 카드마다
드로어를 열고 삭제해야 해서 번거롭다. 백업 관점에서도 전체를
한 파일로 스냅샷하고 싶은 니즈가 있다.

이 PR 은 Environments 탭에 "Select" 모드를 도입하고, 선택된 환경
에 대해 bulk delete / bulk export 를 제공한다. Export 는 여러 env
의 export payload 를 한 JSON 파일로 묶어 다운로드한다.

## PR Link

- Branch: `feat/phase7-21-envs-bulk-actions`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- `EnvironmentCard` 에 `selectable` / `selected` prop 추가. 선택
  가능 모드에선 좌상단의 브랜드 아이콘을 체크박스 아이콘으로 교체,
  선택 상태에서는 primary tint 로 카드를 덧칠.
- 상단 toolbar 에 "Select" 토글 버튼 (selectMode 상태 표시).
- selectMode 이면 filter 바 아래에 bulk action bar 렌더:
  `{n} selected`, `Select all ({N})`, `Clear`, `Export {n}`,
  `Delete {n}`. 실패 시 하단에 error 라인.
- 카드 클릭은 `selectMode ? toggleSelection : setOpenEnvId`.
- `runBulkDelete`: 선택된 id 를 순차적으로 `deleteEnvironment`.
  실패한 항목은 선택 상태로 남기고 부분 실패 메시지 표시. 전부
  성공이면 selectMode 를 자동 종료.
- `runBulkExport`: 각 env 를 `environmentApi.exportEnv` 로 조회
  → `{ version: "1", generated_at, exports: [{env_id, data}] }`
  형태로 묶어 `envs-bulk-YYYY-MM-DD....json` 다운로드. 부분 실패
  메시지 별도 표시.
- Bulk delete 는 `ConfirmModal` 을 거쳐 실행.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.{select, cancelSelect, bulkSelected, bulkSelectAll,
  bulkClear, bulkDelete, bulkExport, bulkDeleteTitle, bulkDeleteMessage,
  bulkDeleteNote, bulkDeleteConfirm, bulkDeleting, bulkDeleteFailed,
  bulkExportFailed}` 신설.

## Verification

- Select 클릭 → selectMode ON, 카드 아이콘이 체크박스로 변경.
  다시 클릭 (Cancel) → selectMode OFF, 선택 초기화.
- 여러 카드 클릭: 체크 on/off 토글, bulk bar 의 `{n} selected`
  카운트 업데이트.
- `Select all ({N})`: 현재 필터/검색에 살아남은 카드 전부 선택.
  필터가 살아있으면 N 에 필터 결과만 반영.
- Export 버튼: 선택이 0 개면 disabled. 선택 후 클릭 시 브라우저
  다운로드 다이얼로그에 `envs-bulk-....json` 이 뜬다. 파일 내
  `exports: [{env_id, data}]` 구조 확인.
- 일부 env export 실패: 성공한 항목은 번들에 포함되어 다운로드,
  하단에 "X of Y failed" 노출.
- Delete 버튼: ConfirmModal 이 뜨고 Count 가 메시지에 정확히
  반영. 확인 시 순차 삭제, 성공 시 selectMode 자동 종료.
- Delete 실패(예: 네트워크 단절 중 일부 실패): 성공 id 는 그리드
  에서 사라지고, 실패 id 는 여전히 selectedIds 에 남아 재시도
  가능. 하단 에러 라인 노출.
- selectMode 중 카드 클릭이 드로어를 열지 않는지 확인. ESC 등으로
  실수로 드로어 뜨는 경로 없음.
- Filter 바와 bulk bar 가 동시에 노출되어도 레이아웃 안전.

## Deviations

- Bulk export 는 zip 파일이 아닌 단일 JSON. jszip 의존성 추가는
  과도하고, 한 JSON 이 API payload 와 동일 구조라 import 측에서도
  복원이 단순.
- Bulk import 는 범위 바깥. 현재 `ImportEnvironmentModal` 이
  단일 env 만 받는데, bulk 를 지원하려면 스키마 분기가 필요해
  별도 PR 로 분리.
- Partial-failure 시에도 성공한 항목에 대한 rollback 은 하지
  않는다. 이미 backend 에서 soft-delete 이므로 복구 경로가 별도로
  존재해야 함(추후 과제).
- Bulk delete 중 toast/progress bar 는 도입하지 않음. 소수 환경
  대상이라 serial await 가 충분히 빠르고, 버튼 busy state 로
  신호를 준다.
- selectMode 시에도 create/import 버튼은 활성. 이 흐름은 제한할
  근거가 없고, 새 env 가 추가되면 자동으로 선택 상태는 유지됨.

## Follow-ups

- Bulk import: 이 PR 이 만든 `envs-bulk-....json` 포맷을 읽어
  서버에 `/api/environments/import` 를 여러 번 호출 (혹은 신설될
  bulk import endpoint 사용).
- Bulk 태그 추가/삭제, bulk preset mark/unmark 추가.
- Partial-failure 시 실패한 env 별 개별 에러를 표로 보여주는
  리포트 모달.
- Bulk delete 전 세션 바인딩 경고 — 현재는 generic note 로만 표시.
