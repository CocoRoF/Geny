"""
Session Memory Entry Model — Database model for memory entries.

Stores both long-term memory (markdown content) and short-term memory
(JSONL transcript entries) in a unified table, so that memory survives
container restarts and can be queried/searched via SQL.

Affect fields
-------------

Cycle 20260422_2 PR-X6-1 adds two nullable affect fields
(``emotion_vec`` as JSON-encoded list of floats, ``emotion_intensity``
as scalar) that downstream retrievers use to score emotional
similarity alongside text similarity. Both columns are nullable with
no default — NULL distinguishes "no emotion captured for this record"
from "neutral emotion (all zeros)". Existing write paths that do not
populate these fields leave them NULL; the AffectAwareRetrieverMixin
(PR-X6-2) falls back to text-only ranking when either side is NULL.
"""
from typing import Any, Dict, Optional
from service.database.models.base_model import BaseModel


class SessionMemoryEntryModel(BaseModel):
    """Model for storing session memory entries (LTM + STM)."""

    def __init__(
        self,
        entry_id: str = "",
        session_id: str = "",
        source: str = "long_term",       # 'long_term' | 'short_term'
        entry_type: str = "text",         # 'text' | 'message' | 'event' | 'dated' | 'topic' | 'summary'
        content: str = "",
        filename: str = "",              # relative path within session (e.g. memory/MEMORY.md)
        heading: str = "",               # markdown heading for LTM entries
        topic: str = "",                 # topic slug for topic LTM entries
        role: str = "",                  # for STM messages: user/assistant/system
        event_name: str = "",            # for STM events: tool_call, state_change, etc.
        metadata_json: str = "{}",       # extra metadata stored as JSON text
        entry_timestamp: str = "",       # when the entry was created (ISO format)
        # Structured memory fields
        category: str = "",              # daily | topics | entities | projects | insights | root
        tags_json: str = "[]",           # JSON array of tag strings
        importance: str = "medium",      # critical | high | medium | low
        links_to_json: str = "[]",       # JSON array of linked filenames (outgoing)
        linked_from_json: str = "[]",    # JSON array of backlinks (incoming)
        source_type: str = "system",     # system | agent | user | execution
        summary: str = "",               # brief summary for search/display
        is_global: bool = False,         # True if promoted to global memory
        # Affect fields (cycle 20260422_2 PR-X6-1) — nullable, NULL means
        # "no emotion data captured".
        emotion_vec: Optional[str] = None,       # JSON-encoded list[float]
        emotion_intensity: Optional[float] = None,  # scalar 0.0..1.0
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.entry_id = entry_id
        self.session_id = session_id
        self.source = source
        self.entry_type = entry_type
        self.content = content
        self.filename = filename
        self.heading = heading
        self.topic = topic
        self.role = role
        self.event_name = event_name
        self.metadata_json = metadata_json
        self.entry_timestamp = entry_timestamp
        self.category = category
        self.tags_json = tags_json
        self.importance = importance
        self.links_to_json = links_to_json
        self.linked_from_json = linked_from_json
        self.source_type = source_type
        self.summary = summary
        self.is_global = is_global
        self.emotion_vec = emotion_vec
        self.emotion_intensity = emotion_intensity

    def get_table_name(self) -> str:
        return "session_memory_entries"

    def get_schema(self) -> Dict[str, str]:
        return {
            "entry_id": "VARCHAR(255) NOT NULL",
            "session_id": "VARCHAR(255) NOT NULL",
            "source": "VARCHAR(20) NOT NULL DEFAULT 'long_term'",
            "entry_type": "VARCHAR(30) NOT NULL DEFAULT 'text'",
            "content": "TEXT DEFAULT ''",
            "filename": "VARCHAR(500) DEFAULT ''",
            "heading": "VARCHAR(500) DEFAULT ''",
            "topic": "VARCHAR(255) DEFAULT ''",
            "role": "VARCHAR(50) DEFAULT ''",
            "event_name": "VARCHAR(100) DEFAULT ''",
            "metadata_json": "TEXT DEFAULT '{}'",
            "entry_timestamp": "VARCHAR(100) DEFAULT ''",
            "category": "VARCHAR(50) DEFAULT ''",
            "tags_json": "TEXT DEFAULT '[]'",
            "importance": "VARCHAR(20) DEFAULT 'medium'",
            "links_to_json": "TEXT DEFAULT '[]'",
            "linked_from_json": "TEXT DEFAULT '[]'",
            "source_type": "VARCHAR(30) DEFAULT 'system'",
            "summary": "TEXT DEFAULT ''",
            "is_global": "BOOLEAN DEFAULT FALSE",
            # Affect fields — nullable, NULL means "no emotion captured"
            "emotion_vec": "TEXT DEFAULT NULL",
            "emotion_intensity": "REAL DEFAULT NULL",
        }

    @classmethod
    def get_create_table_query(cls, db_type: str = "postgresql") -> str:
        """Generate CREATE TABLE with UNIQUE constraint on entry_id."""
        base_query = super().get_create_table_query(db_type)
        constraint = ",\n            UNIQUE (entry_id)"
        idx = base_query.rfind(")")
        if idx != -1:
            return base_query[:idx] + constraint + base_query[idx:]
        return base_query

    def get_indexes(self) -> list:
        return [
            ("idx_mem_entry_session", "session_id"),
            ("idx_mem_entry_source", "source"),
            ("idx_mem_entry_type", "entry_type"),
            ("idx_mem_entry_session_source", "session_id, source"),
            ("idx_mem_entry_role", "role"),
            ("idx_mem_entry_ts", "entry_timestamp"),
            ("idx_mem_entry_category", "category"),
            ("idx_mem_entry_importance", "importance"),
            ("idx_mem_entry_source_type", "source_type"),
            ("idx_mem_entry_is_global", "is_global"),
        ]
