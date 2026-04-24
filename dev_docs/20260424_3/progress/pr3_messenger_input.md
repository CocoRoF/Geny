# PR-3 Progress — Messenger `MessageInput` 파일 첨부 UI

**Branch:** `feat/20260424_3-pr3-messenger-file-input`
**Base:** `main @ 3f486a8` (PR-2 merged)

## Changes

### `frontend/src/store/useMessengerStore.ts`
- `ChatAttachment` 타입 import
- `sendMessage(content: string, attachments?: ChatAttachment[])` 시그니처 확장
- 구현: trim + attachments 조합 guard, `broadcastToRoom(roomId, { message, attachments })` 로 전달

### `frontend/src/components/messenger/MessageInput.tsx` 전면 재작성
VTuber `VTuberChatPanel` (line 127–475, 692–772) 의 attachment 흐름을 Messenger 컴포넌트 컨벤션·디자인에 맞춰 포팅:

- **State**: `pendingAttachments: ChatAttachment[]`, `uploadingCount`, `attachmentError`, `dragActive`
- **Refs**: `fileInputRef`
- **Actions**: `addFiles`, `removeAttachment`, `handleFileInputChange`, `handlePaste`, `handleDragOver/Leave/Drop`
- **Limits**: `MAX_ATTACHMENTS = 8`, `MAX_FILE_BYTES = 10 MiB` (VTuber 와 일치)
- **공유 helper**: `@/lib/imageAttachments` 의 `resizeImageIfNeeded`, `isImageFile` 재사용
- **UI**:
  - attach 버튼 (`<Paperclip>`) 좌측 추가
  - 숨겨진 `<input type="file" accept="image/*" multiple>` + `onChange`
  - textarea 에 `onPaste` 붙여 클립보드 이미지 지원
  - 컴포넌트 루트에 `onDragOver/Leave/Drop` → 드래그 오버 시 placeholder overlay
  - Chip row (attachment 썸네일 + 파일 이름 + × 제거) — textarea 위에 렌더
  - Upload 중 표시 + 에러 문구
- **Send guard**: `input.trim() || pendingAttachments.length > 0` AND `uploadingCount === 0` AND `!isSending`
- **Send 후 리셋**: `pendingAttachments = []`, `attachmentError = null`, textarea 높이 초기화

### i18n
- `frontend/src/lib/i18n/{ko,en}.ts` messenger 섹션에 `attachFile`, `uploading`, `attachmentLimit`, `dropHere`, `attachmentsLabel` 5개 키 추가 (ko/en 쌍 완성).
- 코드 내 모든 i18n 참조는 `t(...) ?? 'fallback'` 패턴이라 키 없어도 깨지지 않음.

## Verification

- 컴포넌트 렌더: attach 버튼 보임, 드래그/드롭 영역 활성화
- 이미지 드롭 → `addFiles` → `resizeImageIfNeeded` → `chatApi.uploadAttachments` → `POST /api/uploads` → chip 로 표시
- 텍스트 + 첨부 send → `sendMessage(text, attachments)` → `broadcastToRoom(roomId, { message, attachments })` → backend 전파
- 빈 텍스트 + 첨부 only 도 send 가능 (store 가 `hasAttachments` 판별)

## Scope boundary

- **렌더링 (수신 메시지의 attachment 표시) 은 PR-4**. 이 PR 은 **송신 경로** 만 복원. 지금도 VTuber 에서 누군가 attachment 달린 메시지를 보내면 Messenger 에는 attachment 없이 text 만 표시됨.

## Next

PR-4: `MessageList.tsx` 에 attachment 렌더 블록 추가 (VTuber 패널 587–622 패턴).
