# Cycle 20260424_3 — File Attachment End-to-End Fix

**Baseline:** `main @ e168932`
**Cadence:** 4 PR. 각 머지 후 smoke (컨테이너 rebuild + 간단 업로드).

---

## PR-1 — Uploads volume + nginx `/static/uploads/` location

### Changes
- `docker-compose.yml`:
  - `services.backend.volumes` 에 `- geny-uploads:/app/static/uploads` 추가
  - 루트 `volumes:` 섹션에 `geny-uploads:` 선언
- `docker-compose.dev.yml`, `docker-compose.prod.yml`, `docker-compose.dev-core.yml`, `docker-compose.prod-core.yml` — 같은 파일군이 존재하면 동일 적용
- `nginx/nginx.conf`:
  - `/static/uploads/` location 추가. 동일한 proxy/alias 패턴을 `/static/assets/` 와 일치시킴. FastAPI `StaticFiles` 마운트가 `/static/uploads/...` 를 그대로 서빙하므로 **nginx 에서 backend 로 proxy 하는 형태** 가 안전 (또는 compose 내 shared volume alias — proxy 방식이 더 단순).

### Risk
- 기존 `/app/static/uploads` 에 이미 파일이 존재한다면, 새 empty volume 이 마운트되면서 **mask 됨**. 현재 환경은 "재시작마다 사라지던" 상태이므로 데이터 손실이 아님. 단 migration 이 필요하면 `docker cp` 로 백업 후 복원 권장 — PR 본문에 안내.

### Test
- `docker compose up -d` 후 `docker exec backend ls /app/static/uploads` 가 mount 된 volume 경로인지 확인
- 파일 업로드 → `curl /static/uploads/{shard}/{sha}.{ext}` 200 응답

---

## PR-2 — Surface silent attachment failures

### Changes
- `backend/controller/chat_controller.py` `_rewrite_local_attachment_url`:
  - `/static/uploads/...` → `file:///...` 변환 직전 `abs_path.is_file()` 체크
  - 없으면 `HTTPException(status_code=400, detail=f"attachment not found: {original_url}")`
  - 로그: `logger.warning(f"[attachment] missing on disk: {abs_path} (session_id=...)")` (있는 경우)
- `geny-executor/src/geny_executor/stages/s01_input/artifact/default/normalizers.py` `_resolve_local_image_source`:
  - 실패 시 `logger.error(...)` + 상위로 raise (또는 `NormalizedInput` 에 `errors: List[str]` 필드 추가하고 `to_message_content()` 가 텍스트로 이를 surface) — 최소 scope 으로 raise 가 간결
  - `normalize()` 레벨에서 catch 해서 `StageError` 로 포장 → Pipeline 이 해당 턴을 실패로 표시

### Risk
- executor 쪽은 PyPI 패키지. 변경은 `/home/geny-workspace/geny-executor/` 에서 하고, 버전 bump + 업로드 필요. 사용자 배포 주기 있음 — **executor 변경은 PR-2 에서 옵셔널**. Backend 검증만 먼저 머지하고 executor 는 follow-up.
- 현실적 분할: PR-2a (backend 검증만), PR-2b (executor 개선 — PyPI 릴리스 필요)

### Test
- 업로드 후 파일 수동 삭제 → broadcast → 400 에러로 사용자에게 명시적 실패
- 파일 존재 시 정상 진행

---

## PR-3 — Messenger `MessageInput` 파일 첨부 UI

### Changes
- `frontend/src/components/messenger/MessageInput.tsx`:
  - VTuber 패널의 패턴 포팅: 상태 `pendingAttachments: ChatAttachment[]`, `<input type="file" accept="image/*,..." multiple>`, drag-drop, paste handler
  - `MAX_ATTACHMENTS=8`, `MAX_FILE_BYTES=10 * 1024 * 1024` 상수 공유
  - 업로드는 `chatApi.uploadAttachments(files)` 호출 후 state 에 저장, send 시 함께 전달
- `frontend/src/store/useMessengerStore.ts`:
  - `sendMessage(content, attachments?: ChatAttachment[])` 시그니처 확장
  - `broadcastToRoom(roomId, { message, attachments })` 로 전달
- 공유 helper: `frontend/src/lib/imageAttachments.ts` 의 `resizeImageIfNeeded`, `isImageFile` 재사용

### Test
- Messenger 에서 이미지 첨부 → 업로드 → broadcast → agent 응답 확인

---

## PR-4 — Messenger `MessageList` attachment 렌더

### Changes
- `frontend/src/components/messenger/MessageList.tsx`:
  - user + agent 메시지 body 아래에 attachment 렌더 블록 추가 (VTuber 패널 `587–622` 패턴 복제)
  - image: `<img src={att.url}>` 썸네일
  - file: paperclip icon + name + download link
  - `att.url` 없고 `att.data` (base64) 있는 fallback 도 작은 처리 (future-proof)

### Test
- 이전 대화(PR-3 로 올린 파일)가 Messenger 에 썸네일로 보이는지
- 다른 세션이 올린 파일이 실시간으로 들어와도 렌더되는지 (WS event)

---

## Cycle close criteria

- [ ] `docker compose restart backend` 후 업로드 파일 살아있음
- [ ] `curl /static/uploads/{shard}/{sha}.png` 200 via nginx
- [ ] 첨부 누락 시 400 에러로 surface (silent drop 없음)
- [ ] Messenger 에서 이미지 업로드 + 송신 동작
- [ ] Messenger 에서 수신 메시지의 이미지/파일 첨부 렌더
- [ ] `dev_docs/20260424_3/progress/pr{1,2,3,4}_*.md` 기록
