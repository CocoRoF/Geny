"""
Session Model — Database model for agent session metadata.

Stores the lifecycle metadata for every session (active + soft-deleted)
so that session state survives server restarts and can be restored.
"""
from typing import Dict, Any
from service.database.models.base_model import BaseModel


class SessionModel(BaseModel):
    """Model for storing agent session metadata."""

    def __init__(
        self,
        session_id: str = "",
        session_name: str = "",
        status: str = "starting",
        model: str = "",
        storage_path: str = "",
        role: str = "worker",
        workflow_id: str = "",
        graph_name: str = "",
        max_turns: int = 50,
        timeout: float = 21600.0,
        max_iterations: int = 50,
        pid: int = 0,
        error_message: str = "",
        is_deleted: bool = False,
        deleted_at: str = "",
        registered_at: str = "",
        total_cost: float = 0.0,
        extra_data: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.session_id = session_id
        self.session_name = session_name
        self.status = status
        self.model = model
        self.storage_path = storage_path
        self.role = role
        self.workflow_id = workflow_id
        self.graph_name = graph_name
        self.max_turns = max_turns
        self.timeout = timeout
        self.max_iterations = max_iterations
        self.pid = pid
        self.error_message = error_message
        self.is_deleted = is_deleted
        self.deleted_at = deleted_at
        self.registered_at = registered_at
        self.total_cost = total_cost
        self.extra_data = extra_data  # JSON blob for additional fields

    def get_table_name(self) -> str:
        return "sessions"

    def get_schema(self) -> Dict[str, str]:
        return {
            "session_id": "VARCHAR(255) NOT NULL",
            "session_name": "VARCHAR(500) DEFAULT ''",
            "status": "VARCHAR(50) DEFAULT 'starting'",
            "model": "VARCHAR(255) DEFAULT ''",
            "storage_path": "TEXT DEFAULT ''",
            "role": "VARCHAR(50) DEFAULT 'worker'",
            "workflow_id": "VARCHAR(255) DEFAULT ''",
            "graph_name": "VARCHAR(255) DEFAULT ''",
            "max_turns": "INTEGER DEFAULT 100",
            "timeout": "DOUBLE PRECISION DEFAULT 21600.0",
            "max_iterations": "INTEGER DEFAULT 100",
            "pid": "INTEGER DEFAULT 0",
            "error_message": "TEXT DEFAULT ''",
            "is_deleted": "BOOLEAN DEFAULT FALSE",
            "deleted_at": "VARCHAR(100) DEFAULT ''",
            "registered_at": "VARCHAR(100) DEFAULT ''",
            "total_cost": "DOUBLE PRECISION DEFAULT 0",
            "extra_data": "TEXT DEFAULT ''",
        }

    @classmethod
    def get_create_table_query(cls, db_type: str = "postgresql") -> str:
        """Generate CREATE TABLE query — includes UNIQUE constraint on session_id."""
        base_query = super().get_create_table_query(db_type)
        constraint = ",\n            UNIQUE (session_id)"
        idx = base_query.rfind(")")
        if idx != -1:
            return base_query[:idx] + constraint + base_query[idx:]
        return base_query

    def get_indexes(self) -> list:
        return [
            ("idx_sessions_session_id", "session_id"),
            ("idx_sessions_status", "status"),
            ("idx_sessions_role", "role"),
            ("idx_sessions_is_deleted", "is_deleted"),
        ]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionModel":
        known_fields = {
            "session_id", "session_name", "status", "model", "storage_path",
            "role", "workflow_id", "graph_name",
            "max_turns", "timeout",
            "max_iterations", "pid", "error_message", "is_deleted",
            "deleted_at", "registered_at", "total_cost", "extra_data",
            "id", "created_at", "updated_at",
        }
        known_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**known_data)

    def __repr__(self):
        return (
            f"SessionModel(id={self.id}, session_id='{self.session_id}', "
            f"session_name='{self.session_name}', status='{self.status}', "
            f"role='{self.role}')"
        )
