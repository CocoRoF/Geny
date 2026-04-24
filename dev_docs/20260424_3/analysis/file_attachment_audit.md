# File / Image Attachment End-to-End Audit (Cycle 20260424_3)

**Date:** 2026-04-24
**Baseline:** `main @ e168932` (post-cycle 20260424_2 + hotfix PR #267)
**Trigger:** 사용자 보고 — "채팅방에서 사진 등 파일 렌더링·도달·처리 모두 안 된다"

---

## 1. End-to-end flow (확인된 구조)

```
[Frontend compose] → POST /api/uploads (multipart)
    ↓ (persists to backend/static/uploads/{shard}/{sha256}.{ext})
    ↓ response: ChatAttachment {attachment_id, url=/static/uploads/..., ...}
[Frontend] → POST /api/chat/rooms/{id}/broadcast JSON { message, attachments:[...] }
    ↓
chat_controller.broadcast_to_room()
    ↓ _rewrite_local_attachment_url():  /static/uploads/... → file:///abs/path
    ↓ store.add_message(user, {attachments: payload})
    ↓ asyncio.create_task(_run_broadcast(...))
    ↓
_run_broadcast() → execute_command(session_id, prompt, attachments=...)
    ↓
agent_executor._execute_core() → agent.invoke(input_text, attachments=...)
    ↓
AgentSession._invoke_pipeline() → attachments = kwargs.pop("attachments")
    ↓ AgentSession._pipeline_events_scoped()
    ↓ pipeline_input = {"text": ..., "attachments": [...]} if attachments else str
    ↓
geny-executor Pipeline.run_stream(pipeline_input, state)
    ↓ Stage 1 (Input) — MultimodalNormalizer
    ↓   _resolve_local_image_source(file://...) → bytes → base64
    ↓   → Anthropic {type: image, source: {type: base64, media_type, data}}
    ↓ state.add_message("user", [image_block, text_block])
    ↓
Stage 6 (APIStage) → Claude / OpenAI / Google client
    ↓ response.text
ExecutionResult.output → store.add_message("agent", {content})
    ↓ SSE / chat_store broadcast
[Frontend] renders msg.content + msg.attachments
```

## 2. 결함 인벤토리

### 2A. Messenger UI 완전 누락 (가장 눈에 띄는 원인)

| 파일 | 문제 |
|---|---|
| `frontend/src/components/messenger/MessageInput.tsx` | `<input type="file">` / drag / paste **전부 없음**. text-only stub. |
| `frontend/src/store/useMessengerStore.ts:171` | `broadcastToRoom(roomId, { message: content.trim() })` — `attachments` 파라미터 미전달 |
| `frontend/src/components/messenger/MessageList.tsx:38–101` | user / agent 메시지 렌더가 `msg.content` 만 소비. `msg.attachments` 분기 **없음** |
| `frontend/src/types/index.ts:171` | `ChatAttachment.data?: string` (inline base64) 필드는 정의되지만 어디에서도 렌더 안 됨 |

**비교 기준:** VTuber 패널은 완성돼 있음 — `frontend/src/components/live2d/VTuberChatPanel.tsx:391–475` (업로드), `587–622` (렌더).

### 2B. 인프라 — 파일 영속성·서빙

| 위치 | 문제 |
|---|---|
| `docker-compose.yml` services.backend.volumes | `/app/static/uploads` 에 대한 named volume 없음 → 컨테이너 재시작 시 업로드 전부 소실 |
| `nginx/nginx.conf` | `/static/assets/` + `/static/live2d-models/` 만 명시. `/static/uploads/` **location 없음** → request 처리 경로 불확실 |

**영향:** 업로드 직후에는 보이지만, 컨테이너 재시작이나 nginx 라우팅 차이에 따라 "도달했지만 로드 실패" 형태로 나타남.

### 2C. 파이프라인 silent drop

| 위치 | 문제 |
|---|---|
| `backend/controller/chat_controller.py:49–69` `_rewrite_local_attachment_url` | 디스크에 파일이 실제로 존재하는지 검증 없음. 없어도 `file:///...` URI 생성 후 executor 로 넘김 |
| `geny-executor/src/geny_executor/stages/s01_input/artifact/default/normalizers.py:184–189` `_resolve_local_image_source` | 파일 없거나 읽기 실패 시 `None` 반환 → 이미지 블록 소리 없이 제외. text만 Claude 로 전달 |

**증상:** "첨부가 있다고 UI 에는 찍히는데 모델이 이미지를 못 본다" — 로그에 warning 만 남고 에러 응답은 아님.

### 2D. 범위 밖 (이번 사이클에서 건드리지 않음)
- `_make_file_block` (normalizers.py:213–235) — PDF 등 문서 블록은 TODO (P1+). 메타만 텍스트로 노출.
- Claude 응답의 이미지 반환 — Anthropic API 특성상 text 만. 설계 상 정상.
- Agent 응답 메시지에 attachment 포함 — 현재 저장 안 함 (chat_controller.py:767–782). 요구사항 명확해지면 별도 사이클.

## 3. 증거 (Top 파일:라인)

**Messenger UI 누락 증거:**
- `frontend/src/components/messenger/MessageInput.tsx:32` — `sendMessage(input.trim())` text only
- `frontend/src/store/useMessengerStore.ts:171` — attachments 미전달
- `frontend/src/components/messenger/MessageList.tsx:56–60,94` — attachment 렌더 블록 부재

**Infra 증거:**
- `docker-compose.yml` volumes: `geny-tts-cache`, `geny-voices` 만
- `nginx/nginx.conf:88–101` — assets, live2d-models 만

**Silent drop 증거:**
- `chat_controller.py:60–68` — `abs_path.as_uri()` 무조건
- `normalizers.py:42–46` + `184–189` — OSError 시 warning 후 None

## 4. 우선순위 & 예상 효과

1. **PR-1 (infra volume + nginx)** — 업로드가 *살아있는* 기반 확보. 다른 모든 수정의 전제.
2. **PR-2 (silent fail → surface)** — 왜 안 됐는지 로그/에러로 즉각 드러나게. 디버깅 비용 대폭 절감.
3. **PR-3 (messenger input)** — Messenger 에서 파일 올리는 경로 자체가 열림. 사용자 보고의 직접 해결.
4. **PR-4 (messenger render)** — 올라온 파일이 Messenger 대화에도 보임.

PR-1 + PR-2 는 VTuber / Messenger 양쪽 모두에 혜택. PR-3 + PR-4 는 Messenger 에만.
