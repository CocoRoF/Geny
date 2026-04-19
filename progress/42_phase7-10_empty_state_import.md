# 42. Phase 7-10 — Environments empty state: surface Import alongside Create

## Scope

Phase 7-9 에서 Environments 탭 툴바에 Import 버튼을 추가했지만, 첫
환경이 아직 없을 때 뜨는 empty state 엔 "Create your first
environment" 버튼 하나만 있었다. 실제로는 백업 JSON 을 가지고
들어오는 사용자 (다른 머신에서 Export 해온 경우) 가 Import 를
쓰고 싶어하는데, empty state 에서는 Import 가 스크롤 위 툴바에만
있어 동선이 어긋났다.

이 PR 은 empty state 에도 Import 버튼을 추가해, 첫 환경을 "만들기"
와 "가져오기" 두 경로 모두에서 즉시 시작할 수 있게 한다.

## PR Link

- Branch: `feat/frontend-phase7-10-empty-state-import`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- empty state 의 primary 버튼 옆에 secondary 스타일 Import 버튼 추가.
- primary (Create first) + secondary (Import from backup) 를 `gap-2`
  로 한 줄 정렬.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.importFirst: 'Import from backup' / '백업으로부터 가져오기'`

## Verification

- empty state 는 `environments.length === 0` 에서만 렌더링 — 이미
  카드가 있는 경우엔 기존 툴바 Import 버튼만 노출되므로 UI 중복
  없음.
- secondary 스타일 ( `bg-[var(--bg-secondary)]` + border) 은 툴바의
  refresh/compare 버튼과 동일 — 스타일 시스템 일관성 유지.
- 새 i18n 키는 두 로케일에 모두 추가됐고 키 누락에 의한 타입 에러는
  없다.

## Deviations

- empty state 의 카피 (`emptyHint`) 는 변경하지 않았다. 이미 "create
  from a session snapshot or an existing preset" 문구이므로 Import
  가능성을 포함하도록 다시 고치려면 카피 리뷰가 필요. 후속으로.
- "Import from backup" 만 추가했고 "Paste JSON" 은 버튼으로 분리하지
  않았다. 모달 안에서 drop / chooser / paste 가 모두 가능하므로 단일
  entry 로 충분.

## Follow-ups

- emptyHint 카피 개선 — "Create a new one, or import a previously
  exported backup." 식으로 Import 경로를 명시.
- 첫 환경 onboarding tour (tooltip 연결) — 현재는 단순 버튼 pair.
