# 58. Phase 7-26 — Bundle import modal polish

## Scope

Phase 7-22 의 follow-up 두 개:

1. 번들 entry 별 name 편집 UI — 지금은 번들을 드롭하면 각 entry 의
   name 을 그대로 저장. 동일 이름의 환경을 이미 갖고 있는 경우
   사용자가 수동으로 모두 "export → 텍스트 치환 → import" 해야 했다.
2. 성공 entry 를 카드로 직접 링크 (드로어 오픈) — 번들 리포트에서
   어떤 env 가 생겼는지 이름/id 만 볼 수 있고 바로 탐색할 수 없었다.

## PR Link

- Branch: `feat/phase7-26-bundle-import-polish`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportEnvironmentModal.tsx` — 수정
- `bundleNameOverrides: Record<number, string>` 상태 추가. 각 entry
  의 index 로 키.
- 번들 프리뷰 리스트가 read-only 라벨에서 inline `<input>` 으로
  바뀜. placeholder 에 원래 name 노출, 비워두면 원본 유지.
- "Reset names" 버튼: 오버라이드가 있을 때만 노출.
- 새 헬퍼 `applyNameOverrideToBundleEntry(data, overrideName)` —
  top-level `data.name` 과 `data.manifest.metadata.name` 을 모두
  세팅 (single-env override 와 일관).
- 제출 시 각 entry 를 `cleanedEntries` 로 바꿀 때 오버라이드가 있으면
  헬퍼 적용.
- 성공 리포트의 각 success row 가 `<button>` 으로 변환. 클릭 시
  `onImported(new_id)` + `onClose()` → 부모가 drawer 오픈.
  hover 에 `ArrowUpRight` 아이콘 fade-in.
- `useMemo` 로 `parsed` 를 래핑해 불필요 재계산 제거 (덤).

`frontend/src/lib/i18n/en.ts` / `ko.ts` — 수정
- 신규 키: `importEnvironment.bundleEntryNameLabel`,
  `bundleResetNames`, `bundleNamesHint`, `bundleOpenEnv`.

## Verification

- 번들 드롭 → 각 entry 옆에 텍스트 필드가 렌더되며 원본 name 이
  placeholder 로 보임. "Reset names" 버튼은 뭔가 입력해야 나타남.
- 3 개 중 2 개의 name 을 새로 입력하고 Import → 응답 report 에서
  이름이 오버라이드대로 뜨고, 서버에 실제 생성된 env 의 name 도
  override 값 (manifest.metadata.name 기준).
- 오버라이드 필드를 비운 entry 는 원본 name 그대로.
- "Reset names" 클릭 → 모든 입력이 지워짐.
- 성공 리포트의 env row 를 클릭 → 모달 닫히고 Environments 탭의
  드로어가 해당 env 로 열림.
- 실패 row 는 클릭 불가능 (button 아님).
- 단일 env JSON 드롭은 기존 name 오버라이드 input 그대로 동작
  (분기 유지).
- ko 로케일로 키 문구 확인.

## Deviations

- 서버측 name 오버라이드 파라미터를 추가하는 대신, client 에서
  payload 수정. import 는 per-entry JSON 을 그대로 받는 구조라
  이 편이 surface 변경이 적음.
- 번들 export 는 변경하지 않음. 원본 JSON 은 그대로 두고 import
  시점에만 이름이 바뀜. rename 을 번들로 persist 하려면 export 시
  이름을 지정하는 별도 flow 가 필요하지만 범위 밖.
- `onImported` 자동 호출 로직 (전부 성공 시 첫 env 드로어) 은
  그대로 둠. 이미 drill-down 이 있으니 중복이지만, 한 번에 여러
  개일 때 사용자가 바로 확인하고 싶은 경우를 지원.

## Follow-ups

- 번들 entry 중 이미 존재하는 name 을 서버가 알려주는 conflict
  pre-check (중복 import 안내).
- `applyNameOverrideToBundleEntry` 는 shallow-clone 기반이라 깊은
  중첩 변경엔 취약. `structuredClone` 으로 바꾸는 편이 안전.
- 번들 에러 row 도 "원인 entry 의 JSON 을 따로 export" 같은 액션.
