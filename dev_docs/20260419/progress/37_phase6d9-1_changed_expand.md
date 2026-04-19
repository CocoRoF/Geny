# 37. Phase 6d-9.1 — Import diff "changed" expandable before/after

## Scope

Phase 6d-9 (PR #79) 에서 diff 섹션은 변경된 path 만 리스트로 보여주고
실제 before/after 값은 생략했다. 파워유저 입장에서 "정확히 뭐가
바뀌었는지" 확인하려면 결국 diff 한번 더 외부 도구로 돌려야 했다.

이 PR 은 "changed" 섹션 각 항목을 클릭해서 펼치면 before/after 값을
바로 확인할 수 있게 만든다. added/removed 는 구조 변경이라 값보다
경로가 더 중요해서 그대로 두었다.

## PR Link

- Branch: `feat/frontend-phase6d9-1-changed-expand`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportManifestModal.tsx` — 수정
- 상태 `expandedChanged: Set<string>` 추가. `toggleChanged(path)`
  핸들러로 per-path open/close.
- 로컬 헬퍼 `formatDiffValue(v)` — `undefined` → `(undefined)`,
  object/array → `JSON.stringify(…, null, 2)`, 그 외 문자열은 as-is.
- "changed" `<li>` 를 버튼으로 감싸서 클릭 시 펼쳐지도록 교체.
  펼친 상태에서 before (빨간 배경) 와 after (초록 배경) 를 세로로
  스택. 각 블록은 `max-h-32 overflow-y-auto` 로 폭주 방지.
- added/removed 섹션은 변경 없음.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `importManifest.diffBefore` / `diffAfter` — 각 언어 2개.

## Verification

- 펼친 상태에서 값이 거대해도 `max-h-32 overflow-y-auto` 덕분에 모달
  높이가 폭주하지 않는다. 스크롤이 생김.
- `formatDiffValue` 는 `JSON.stringify` 가 throw 하는 edge case
  (circular refs 등) 를 `String(v)` 로 폴백. manifest 는 plain JSON
  이라 현실에서는 발생 확률 0.
- 초기 상태 `expandedChanged` 는 빈 셋 — 기존 UX 유지. 경로만 쭉
  나열하던 시각이 깨지지 않는다.
- Section 20 건 cap 은 유지. 초과분은 여전히 "…외 N 건" 으로 축약.

## Deviations

- added/removed 도 펼쳐서 값 보여주는 옵션은 넣지 않았다 — added
  는 새로 생긴 key 의 전체 값을 보여주면 유의미하지만, removed 는
  "사라질 거" 라 값 확인 가치가 상대적으로 낮다. 둘을 같이 확장할지
  말지 판단을 보류하고 이번엔 changed 만.
- Before/after 스택 레이아웃 (세로) 을 택했다. 좁은 모달 (680px)
  에서 가로 2열은 JSON 줄바꿈이 꼬인다.

## Follow-ups

- Added 섹션에도 동일 expand 를 붙이는 옵션 (6d-9.2 후보).
- 값 diff 를 글자 단위로 inline highlight — 라이브러리 도입 검토
  필요, 비용 대비 효용은 미지수.
- Plan 06 summary 의 남은 follow-up (reverse lookup / server-side
  snapshot) 은 별도 사이클.
