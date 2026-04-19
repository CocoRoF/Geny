# 67. Phase 7-35 — Diff/Matrix Markdown copy-to-clipboard

## Scope

Phase 7-30 은 DiffModal 에 Markdown 다운로드를, Phase 7-33 은
MatrixModal 에 JSON/Markdown 다운로드를 추가했다. 실제 운용상
가장 흔한 사용은 "GitHub PR 코멘트에 붙여넣기" — 즉 파일을
내려받아 → 열어 → 복사 → 삭제 하는 4 단계가 필요하다. 이
번 phase 는 그 워크플로우를 한 버튼으로 축약한다.

Phase 7-33 follow-up 로 남겼던 항목: "Copy to clipboard 옵션 —
다운로드 대신 markdown 을 바로 복사해 PR 댓글에 붙여넣기."

## PR Link

- Branch: `feat/phase7-35-md-copy-clipboard`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/EnvironmentDiffModal.tsx` — 수정
- `exportDiffMarkdown` 의 markdown 문자열 생성 로직을
  `buildDiffMarkdown(stamp, leftLabel, rightLabel)` 으로 분리.
- `copyDiffMarkdown()` 추가 — `navigator.clipboard.writeText()` 로
  같은 body 를 클립보드에 복사. 성공 시 `copyStatus='copied'` 로
  버튼 라벨이 "Copied!" / 초록 tint, 실패 시 "Copy failed" / 빨간
  tint. 1.8 초 후 idle 복귀.
- `copyTimer` ref 로 타이머 추적 — 언마운트 시 clearTimeout.
- Footer 에 "Copy MD" 버튼 추가 (Export MD 옆, result 가 있을 때만).

`frontend/src/components/modals/EnvironmentDiffMatrixModal.tsx` — 수정
- 동일 패턴. `exportMatrixMarkdown` 의 string builder 를
  `buildMatrixMarkdown(stamp)` 로 추출, `copyMatrixMarkdown()` 추가,
  Footer 에 "Copy MD" 버튼 (exportable 조건부).

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `diff.copyMarkdown / copied / copyFailed` — "Copy MD" / "Copied!" /
  "Copy failed" (한국어: "MD 복사" / "복사됨!" / "복사 실패").
- `diffMatrix.copyMarkdown / copied / copyFailed` — 동일.

## Verification

- DiffModal 에서 두 env 선택 → Compare → 결과 표시 → Footer 에
  JSON / MD / "Copy MD" 세 버튼 노출.
- "Copy MD" 클릭 → 버튼이 초록 "Copied!" 로 전환, 1.8 초 후 원래
  라벨 복귀. 새 탭 에디터에 붙여넣으면 Phase 7-30 다운로드 결과와
  동일 markdown.
- MatrixModal — `pending === 0` 이 된 후 Footer 에 JSON / MD /
  "Copy MD" 세 버튼. 매트릭스 markdown (index 테이블 + symmetric
  matrix + drill-down) 전체가 그대로 클립보드에 들어감.
- `navigator.clipboard` 가 없는 환경 (insecure http 등) → catch 블록
  에서 `failed` 로 떨어지고 빨간 "Copy failed" tint, 동일하게 1.8
  초 후 idle. 실패 사유는 UI 에 노출하지 않음 (콘솔 검증 범위).
- 모달 언마운트 중 카운트다운이 돌고 있으면 `clearTimeout` 으로
  정리 — React StrictMode 이중 마운트에서도 누수 없음.
- 한국어 로케일: "MD 복사" / "복사됨!" / "복사 실패".

## Deviations

- `document.execCommand('copy')` fallback 은 추가하지 않음. 최신
  브라우저는 secure context 에서 `navigator.clipboard` 를 지원하고,
  execCommand 는 deprecated. insecure context 에서는 "Copy failed"
  안내로 충분하며 동시에 제공되는 Download 버튼이 대체 경로.
- 실패 시 버튼 tint 만 바꾸고 토스트는 띄우지 않음 — 기존 프로젝트
  의 에러 전달 방식 (`error` state / 배너) 과 맥락이 다르고,
  이 에러는 사용자 자체 환경 탓 (clipboard 권한) 이라 모달 내
  보조 indicator 로 충분.
- Clipboard 복사 시 사용하는 stamp 는 "호출 시점" 기준. 다운로드와
  분 단위는 같아도 초 단위는 다를 수 있는데, 메타 표시일 뿐이라
  중요하지 않음.
- "Copy JSON" 은 추가하지 않음. JSON 은 파일로 가져가 기계
  소비하는 경우가 많고 (diff 리포트 적재, CI 파이프라인), 클립보드
  복사 수요가 낮다. 필요하면 후속 PR 로.

## Follow-ups

- Clipboard 권한이 denied 일 때 tooltip/설명을 띄워 사용자가 원인을
  알도록.
- Markdown body 가 매우 클 때 (매트릭스 50 envs = 1225 drill-down
  라인) 클립보드 write 시간이 체감될 수 있음 — 비동기 상태 표시 중
  loading spinner.
- ImportEnvironmentModal 의 성공 리포트 / bulk-delete 경고도
  MD 요약이 있으면 PR 기록용으로 유용 (별개 phase).
