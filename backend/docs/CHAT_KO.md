# Chat 데이터 & 저장소

> 채팅방과 메시지 영속성 계층 — PostgreSQL + JSON 이중 저장소, DM 수신함
>
> 실행 흐름, 브로드캐스트 로직, SSE 실시간 스트리밍은 [EXECUTION_KO.md](EXECUTION_KO.md) 참조.

## 아키텍처 개요

```
chat_controller.py
          │
          ▼
  ChatConversationStore (이중 저장소)
   ├── PostgreSQL (주 저장소)
   └── JSON 파일 (백업 저장소)

  InboxManager (DM 수신함)
   └── JSON 파일 (세션별)
```

---

## 채팅방 시스템

### 채팅방 모델

```python
{
    "room_id": "uuid",
    "name": "Development Team",
    "session_ids": ["session-abc", "session-def"],
    "message_count": 42,
    "created_at": "2026-03-21T10:00:00",
    "updated_at": "2026-03-21T15:30:00"
}
```

### 메시지 모델

```python
{
    "id": "uuid",
    "type": "user" | "agent" | "system",
    "content": "메시지 내용",
    "timestamp": "2026-03-21T15:30:00",
    "session_id": "발신 세션 ID",
    "session_name": "발신 세션 이름",
    "role": "developer",
    "duration_ms": 3500,
    "cost_usd": 0.0557
}
```

---

## ChatConversationStore

스레드 안전한 영속적 채팅방 + 메시지 저장소. 이중 저장소 전략.

### 이중 저장소 전략

- **쓰기**: PostgreSQL (주) + JSON 파일 (백업) **모두**에 기록
- **읽기**: PostgreSQL 우선 → JSON 폴백
- DB 사용 불가 시 JSON 파일만으로 동작

### 저장소 레이아웃 (JSON)

```
service/chat_conversations/
├── rooms.json              # 방 레지스트리
├── {room_id}.json          # 방별 메시지 이력
└── inbox/
    └── {session_id}.json   # 세션별 DM 수신함
```

### 방 CRUD

| 메서드 | 설명 |
|--------|------|
| `create_room(name, session_ids)` | UUID 생성, DB + JSON 동시 기록 |
| `list_rooms()` | `updated_at` 내림차순 정렬 반환 |
| `get_room(room_id)` | 단일 방 조회 |
| `update_room_sessions(room_id, session_ids)` | 참가 세션 변경 |
| `update_room_name(room_id, name)` | 방 이름 변경 |
| `delete_room(room_id)` | 방 + 메시지 이력 일괄 삭제 |

### 메시지 관리

| 메서드 | 설명 |
|--------|------|
| `add_message(room_id, message)` | 메시지 추가 (ID/timestamp 자동 생성), 방 메타데이터 갱신 |
| `add_messages_batch(room_id, messages)` | 배치 추가 (브로드캐스트 결과) |
| `get_messages(room_id)` | 전체 메시지 이력 조회 |

---

## InboxManager (DM 수신함)

세션별 개인 메시지 수신함. JSON 파일 기반.

### DM 메시지 모델

```python
{
    "id": "uuid",
    "sender_session_id": "발신 세션 ID",
    "sender_name": "Worker 1",
    "content": "안녕하세요",
    "timestamp": "2026-03-21T15:30:00",
    "read": false
}
```

### 메서드

| 메서드 | 설명 |
|--------|------|
| `deliver(target_session_id, content, sender_session_id, sender_name)` | DM 전달 |
| `read(session_id, limit=20, unread_only=False)` | 수신함 읽기 (최신순) |
| `mark_read(session_id, message_ids)` | 읽음 표시 |
| `clear(session_id)` | 수신함 비우기 |
| `unread_count(session_id)` | 안 읽은 메시지 수 |

**보안**: 세션 ID 경로 순회 방지를 위해 `isalnum()` + `-_`만 허용.

---

> 브로드캐스트 실행 흐름, SSE 이벤트, API 엔드포인트는 [EXECUTION_KO.md](EXECUTION_KO.md)에 문서화되어 있다.

---

## 관련 파일

```
service/chat/
├── __init__.py
├── conversation_store.py   # ChatConversationStore (이중 저장소)
└── inbox.py                # InboxManager (DM 수신함)

controller/
└── chat_controller.py      # /api/chat — 방, 메시지, 브로드캐스트, SSE
```

## 참조

- [EXECUTION_KO.md](EXECUTION_KO.md) — 브로드캐스트 실행, SSE 이벤트 스트리밍, 비용 추적
- [DATABASE_KO.md](DATABASE_KO.md) — PostgreSQL 커넥션 풀 및 쿼리 실행
