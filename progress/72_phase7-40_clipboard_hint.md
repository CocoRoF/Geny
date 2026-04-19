# 72. Phase 7-40 — Copy MD 실패 시 원인 툴팁

## Scope

Phase 7-35 는 DiffModal / MatrixModal 에 "Copy MD" 를 추가하며
`navigator.clipboard.writeText` 실패 시 버튼이 빨간 "Copy failed"
tint 로 바뀌도록 했다. 그러나 사용자는 이 실패의 원인을 몰라
"한 번 더 눌러볼까" 하게 된다 — 반복 실패해도 똑같다. 실제 원인은
거의 항상 insecure context (http) 또는 사용자가 차단한 permission
이다. 이 경우 Export MD 다운로드로 우회 가능함을 툴팁으로
안내한다.

Phase 7-35 follow-up 으로 명시된 항목.

## PR Link

- Branch: `feat/phase7-40-clipboard-hint`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/EnvironmentDiffModal.tsx` — 수정
- "Copy MD" 버튼의 `title` 을 `copyStatus === 'failed'` 일 때만
  `t('diff.copyFailedHint')` 로 바인딩. 평상시 undefined 로 두어
  네이티브 툴팁이 뜨지 않음.

`frontend/src/components/modals/EnvironmentDiffMatrixModal.tsx` — 수정
- 동일 패턴. `diffMatrix.copyFailedHint` 사용.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `diff.copyFailedHint`, `diffMatrix.copyFailedHint` 추가.
  - en: "Clipboard access was blocked. This usually means the page
    is on http:// or the browser denied permission — try Export MD
    as a fallback."
  - ko: "클립보드 접근이 차단되었습니다. http:// 에서 접속 중이거나
    브라우저 권한이 막힌 경우일 수 있어요 — MD 내보내기를 사용해
    주세요."

## Verification

- https 또는 secure context 에서 Copy MD → "Copied!" 초록 tint,
  툴팁 없음 (undefined). mouse hover 시 빈 툴팁 문자열 없음 확인.
- `navigator.clipboard` 가 제공되지 않는 환경 (예: 로컬 http 빌드)
  에서 Copy MD → 버튼이 "Copy failed" 빨간 tint, hover 시 영문 / 국문
  tooltip 노출. 사용자가 Export MD 버튼 존재를 인지하게 됨.
- 1.8 초 후 다시 idle 복귀. idle 로 돌아가면 tooltip 도 사라짐.
- DiffModal, MatrixModal 양쪽 동일 거동.

## Deviations

- tooltip 은 native `title` attribute. 커스텀 Popover / Tooltip
  컴포넌트를 도입하지 않음 — 프로젝트 전체가 native title 을 쓰고
  있고, 에러 메시지가 장문 (80 자+) 이라 호버 지연 기반의 native
  툴팁이 더 적절.
- `title` 은 `copyStatus === 'failed'` 일 때만 문자열, 그 외에는
  `undefined`. 이렇게 해야 secure context 에서 Copy 버튼에 호버해도
  "Clipboard access was blocked…" 이 뜨지 않는다.
- 메시지에 "http:// or browser permission" 을 구체적으로 언급해
  사용자가 원인 짐작 후 조치할 수 있게. 일반적인 "Copy failed" 보다
  훨씬 actionable.
- 별도 "Help" 아이콘을 두는 대신 버튼 자체의 툴팁에 담아 추가 UI
  요소를 늘리지 않음.

## Follow-ups

- 실패 반복 시 (2 회 이상) 인라인 배너로 에스컬레이션 — 툴팁을
  놓치는 사용자 대응.
- Clipboard permission 상태를 `navigator.permissions.query({name:
  'clipboard-write'})` 로 사전 감지해 버튼 자체를 숨기고 Export
  버튼을 강조하는 모드.
- DiffModal 의 noChanges 상태에서는 Copy 내용이 거의 비어있는데,
  별도 메시지로 "no diff content" 안내.
