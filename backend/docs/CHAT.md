# Chat Data & Storage

> Chat room and message persistence layer — dual PostgreSQL + JSON storage, DM inbox
>
> For execution flow, broadcast logic, and SSE real-time streaming, see [EXECUTION.md](EXECUTION.md).

## Architecture Overview

```
chat_controller.py
          │
          ▼
  ChatConversationStore (dual storage)
   ├── PostgreSQL (primary storage)
   └── JSON files (backup storage)

  InboxManager (DM inbox)
   └── JSON files (per-session)
```

---

## Chat Room System

### Chat Room Model

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

### Message Model

```python
{
    "id": "uuid",
    "type": "user" | "agent" | "system",
    "content": "Message content",
    "timestamp": "2026-03-21T15:30:00",
    "session_id": "Sender session ID",
    "session_name": "Sender session name",
    "role": "developer",
    "duration_ms": 3500,
    "cost_usd": 0.0557
}
```

---

## ChatConversationStore

Thread-safe persistent chat room + message store. Dual storage strategy.

### Dual Storage Strategy

- **Writes**: Recorded to **both** PostgreSQL (primary) + JSON files (backup)
- **Reads**: PostgreSQL first → JSON fallback
- Falls back to JSON-only operation when DB is unavailable

### Storage Layout (JSON)

```
service/chat_conversations/
├── rooms.json              # Room registry
├── {room_id}.json          # Per-room message history
└── inbox/
    └── {session_id}.json   # Per-session DM inbox
```

### Room CRUD

| Method | Description |
|--------|-------------|
| `create_room(name, session_ids)` | Generate UUID, write to DB + JSON simultaneously |
| `list_rooms()` | Return sorted by `updated_at` descending |
| `get_room(room_id)` | Get single room |
| `update_room_sessions(room_id, session_ids)` | Update participating sessions |
| `update_room_name(room_id, name)` | Update room name |
| `delete_room(room_id)` | Bulk delete room + message history |

### Message Management

| Method | Description |
|--------|-------------|
| `add_message(room_id, message)` | Add message (ID/timestamp auto-generated), update room metadata |
| `add_messages_batch(room_id, messages)` | Batch add (broadcast results) |
| `get_messages(room_id)` | Get full message history |

---

## InboxManager (DM Inbox)

Per-session personal message inbox. JSON file-based.

### DM Message Model

```python
{
    "id": "uuid",
    "sender_session_id": "Sender session ID",
    "sender_name": "Worker 1",
    "content": "Hello",
    "timestamp": "2026-03-21T15:30:00",
    "read": false
}
```

### Methods

| Method | Description |
|--------|-------------|
| `deliver(target_session_id, content, sender_session_id, sender_name)` | Deliver DM |
| `read(session_id, limit=20, unread_only=False)` | Read inbox (newest first) |
| `mark_read(session_id, message_ids)` | Mark as read |
| `clear(session_id)` | Clear inbox |
| `unread_count(session_id)` | Unread message count |

**Security**: Session ID path traversal prevention — only `isalnum()` + `-_` characters allowed.

---

> Broadcast execution flow, SSE events, and API endpoints are documented in [EXECUTION.md](EXECUTION.md).

---

## Related Files

```
service/chat/
├── __init__.py
├── conversation_store.py   # ChatConversationStore (dual storage)
└── inbox.py                # InboxManager (DM inbox)

controller/
└── chat_controller.py      # /api/chat — rooms, messages, broadcast, SSE
```

## See Also

- [EXECUTION.md](EXECUTION.md) — Broadcast execution, SSE event streaming, cost tracking
- [DATABASE.md](DATABASE.md) — PostgreSQL connection pool and query execution
