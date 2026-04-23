"""
Chat Message Model — Database model for individual chat messages.

Each message belongs to a chat room and optionally to a specific agent session.
"""
from typing import Dict, Any
from service.database.models.base_model import BaseModel


class ChatMessageModel(BaseModel):
    """Model for storing individual chat messages."""

    def __init__(
        self,
        message_id: str = "",
        room_id: str = "",
        type: str = "user",        # 'user' | 'agent' | 'system'
        content: str = "",
        session_id: str = "",
        session_name: str = "",
        role: str = "",
        duration_ms: int = 0,
        cost_usd: float = None,
        timestamp: str = "",
        file_changes: str = None,
        attachments: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.message_id = message_id
        self.room_id = room_id
        self.type = type
        self.content = content
        self.session_id = session_id
        self.session_name = session_name
        self.role = role
        self.duration_ms = duration_ms
        self.cost_usd = cost_usd
        self.timestamp = timestamp
        self.file_changes = file_changes
        # JSON-serialized list of attachment metadata (image / file refs).
        # Schema mirrors the broadcast endpoint payload — see
        # ``upload_controller.UploadedFile``. NULL when the user turn
        # had no attachments.
        self.attachments = attachments

    def get_table_name(self) -> str:
        return "chat_messages"

    def get_schema(self) -> Dict[str, str]:
        return {
            "message_id": "VARCHAR(255) NOT NULL",
            "room_id": "VARCHAR(255) NOT NULL",
            "type": "VARCHAR(50) DEFAULT 'user'",
            "content": "TEXT DEFAULT ''",
            "session_id": "VARCHAR(255) DEFAULT ''",
            "session_name": "VARCHAR(500) DEFAULT ''",
            "role": "VARCHAR(100) DEFAULT ''",
            "duration_ms": "INTEGER DEFAULT 0",
            "cost_usd": "DOUBLE PRECISION DEFAULT NULL",
            "timestamp": "VARCHAR(100) DEFAULT ''",
            "file_changes": "TEXT DEFAULT NULL",
            "attachments": "TEXT DEFAULT NULL",
        }

    @classmethod
    def get_create_table_query(cls, db_type: str = "postgresql") -> str:
        """Generate CREATE TABLE query — includes UNIQUE constraint on message_id."""
        base_query = super().get_create_table_query(db_type)
        constraint = ",\n            UNIQUE (message_id)"
        idx = base_query.rfind(")")
        if idx != -1:
            return base_query[:idx] + constraint + base_query[idx:]
        return base_query

    def get_indexes(self) -> list:
        return [
            ("idx_chat_messages_message_id", "message_id"),
            ("idx_chat_messages_room_id", "room_id"),
            ("idx_chat_messages_session_id", "session_id"),
            ("idx_chat_messages_timestamp", "timestamp"),
        ]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessageModel":
        known_fields = {
            "message_id", "room_id", "type", "content",
            "session_id", "session_name", "role", "duration_ms", "cost_usd", "timestamp",
            "file_changes", "attachments", "id", "created_at", "updated_at",
        }
        known_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**known_data)

    def __repr__(self):
        return (
            f"ChatMessageModel(id={self.id}, message_id='{self.message_id}', "
            f"room_id='{self.room_id}', type='{self.type}')"
        )
