# 40. Phase 7-8 — ImportManifestModal: visible drag-over state

## Scope

`ImportManifestModal` 은 원래부터 파일 drop 을 받고 있었지만
(`onDrop={handleDrop}` + `onDragOver={preventDefault}`), 사용자가 파일
을 드래그하는 동안 드롭존이 활성화됐다는 시각적 피드백이 없었다.
"여기에 정말 놓으면 되는 거냐" 는 순간의 망설임이 생기고, 특히
auto-backup 옵션이 켜진 상태에서 파일이 크면 체감된다.

이 PR 은 드래그 hover 상태에서 드롭존 테두리/배경을 primary color
로 강조하는 작은 UX 다듬기다. 파싱/업로드 로직은 변경 없음.

## PR Link

- Branch: `feat/frontend-phase7-8-import-dragover`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportManifestModal.tsx` — 수정
- `isDragOver: boolean` state 추가.
- `handleDragOver` — `preventDefault` + `setIsDragOver(true)` (이미 true 면
  skip 해 상태 churn 방지).
- `handleDragLeave` — `currentTarget === target` 이거나 `relatedTarget`
  이 드롭존 밖일 때만 `false` 로. 자식 요소에서 drag 가 튀어도 true
  를 유지.
- `handleDrop` — 드롭 후 `setIsDragOver(false)` 로 리셋.
- 드롭존 컨테이너 className 을 조건부로:
  - drag-over: `border-[var(--primary-color)] bg-[rgba(99,102,241,0.08)]`
  - idle: 기존 `border-[var(--border-color)] bg-[var(--bg-primary)]`
  - `transition-colors` 로 부드러운 전환.

## Verification

- drag enter 시 드롭존 테두리가 primary color 로 바뀌고 배경이
  인디고 틴트로 깔린다.
- drag leave (드롭존 밖으로 커서 이동) 또는 drop 완료 시 즉시
  idle 스타일로 복귀.
- 드롭존 안쪽의 button / input 위를 지나가도 상태가 깜박이지 않는다
  (`contains(relatedTarget)` 가드로 자식 dragleave 무시).
- 기존 기능 (`handleFile` 로 file.text() 읽기, `handleFileInput` 으로
  file chooser 경유) 은 변경 없음 — drag-over 상태와 무관.
- backup 토글 / diff preview / parsedOk badge 등 모두 동일.

## Deviations

- drag 중에만 드롭존 텍스트를 바꾸는 것 (예: "Drop to import") 은
  하지 않았다. 현재 힌트 문구 "Drop an exported JSON file here…"
  가 이미 그 의도를 담고 있어 중복된 인디케이션이 된다.
- 다중 파일 drop 은 여전히 `files[0]` 만 사용. manifest 는 1:1 이므로
  의도적 제한.
- 글로벌 drag-and-drop (modal 밖에서 파일을 놓으면 자동으로 이 모달
  이 열리는 흐름) 은 scope 밖. 모달이 열려있는 상황에서만 드롭존
  활성.

## Follow-ups

- CreateEnvironmentModal 의 import 모드도 동일한 drag-over 피드백을
  받으면 일관성이 좋아진다 (현재는 버튼 클릭 파일 선택만).
- drag 중 파일 타입 검증 (`.json` 이 아니면 drop 금지) — `dataTransfer.
  items` 로 MIME 을 확인해 빨간 테두리로 에러 힌트를 주는 방향.
- 모달 헤더의 "Import manifest" 옆에 drag 중일 때만 작게 "Release to
  load file" 같은 라이브 라벨 — 현재는 드롭존 자체 스타일 변화만.
