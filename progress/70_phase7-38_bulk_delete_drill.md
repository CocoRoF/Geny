# 70. Phase 7-38 — Bulk-delete confirm 의 env 이름 drill-down

## Scope

Phase 7-25 에서 bulk delete 를 실행하기 전에 활성/에러 세션이
바인딩된 환경 목록을 warning 박스로 보여주도록 했다. 하지만 해당
목록의 env 이름이 순수 텍스트라, 사용자가 "이 환경에 무슨 세션이
걸려 있는지" 확인하려면 confirm 을 취소 → 카드 찾기 → 드로어
열기로 3 단계를 거쳐야 했다.

이 phase 는 warning 목록의 env 이름을 클릭 가능한 버튼으로 만들어,
한 번에 confirm 을 닫고 해당 환경의 드로어를 연다. 드로어에서 세션
목록을 확인하고 필요하면 다시 select + bulk delete 를 트리거하면
된다.

## PR Link

- Branch: `feat/phase7-38-bulk-delete-drill`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- BulkDeleteConfirm 의 warning `<li>` 내부 `{e.name}` 텍스트를
  `<button>` 로 교체. 클릭 시 `setShowBulkDeleteConfirm(false)` 후
  `setOpenEnvId(e.id)` — 기존 드로어 open path 를 재사용.
- 버튼 style: `text-[var(--primary-color)]` + `hover:underline`.
  `bg-transparent / border-none / p-0` 로 li bullet 레이아웃 유지.
- `title` 에 `environmentsTab.bulkDeleteDrillTooltip` 메시지 바인딩.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.bulkDeleteDrillTooltip` — "Open {name} to inspect
  bindings" / "{name} 열어서 바인딩 확인".

## Verification

- 2 개 이상 선택 + 그 중 일부에 active/error 세션이 걸린 상태로
  bulk delete confirm 열기 → 경고 박스의 env 이름이 파란 링크
  형태로 렌더링.
- 링크 hover 시 underline + 지정된 tooltip.
- 링크 클릭 → confirm 모달이 닫히고 즉시 해당 env 의 드로어가 열림.
  드로어에서 linked sessions 섹션이 이미 캐시 된 상태로 표시.
- 드로어 닫으면 선택 상태 (selectedIds) 는 보존됨 — 사용자는 bulk
  delete 를 다시 누를 수 있음.
- 7 개 이상 세션 있는 환경 list 에서 "... 외 N 개" 는 클릭 불가
  (기존 동작 유지).
- ko 로케일: "{name} 열어서 바인딩 확인" tooltip.

## Deviations

- 드로어를 confirm 위에 중첩해서 띄우는 옵션도 고려했으나 (두
  modal 이 쌓여 백드롭이 겹침) — ConfirmModal 은 destructive action
  의 최종 관문이라 "닫고 딴 얼굴 보여주기" 보다 "드릴 다운은 맥락
  전환으로 취급" 이 의도와 맞다.
- 클릭하면 selectedIds 를 리셋할지 고민 — 하지 않기로 결정. 사용자가
  "이 환경은 빼자" 를 결정하고 다시 bulk delete 를 누를 수 있게
  선택 상태를 유지하는 게 편리.
- ConfirmModal 의 `onConfirm` 경로는 변경 없음. 링크 클릭은
  `onClose` 와 동일 경로 (confirm 취소) 를 따른다.
- tooltip 은 "open … to inspect bindings" 로 통일. "drill down" 같은
  jargon 은 비개발 사용자에게 불명확.

## Follow-ups

- 드로어를 confirm 위에 inset panel 로 띄우는 "peek" UX — 확인
  취소 없이 bindings 만 훑어보는 흐름.
- 링크 이동 후 드로어의 "Back to selection" 버튼 — 사용자가 drill
  후 bulk confirm 을 재오픈할 수 있도록.
- bulk delete 결과 리포트에도 같은 drill-down 링크를 추가해
  실패한 환경을 바로 조사할 수 있게.
