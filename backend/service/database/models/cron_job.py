"""
CronJobModel — Database model for executor CronRunner state (PR-D.1.2).

One row per cron job. The schedule itself lives in cron_expr; the
runner re-computes next_fire each tick from cron_expr +
last_fired_at, so we don't store next_fire (avoids drift).
"""

from typing import Any, Dict

from service.database.models.base_model import BaseModel


class CronJobModel(BaseModel):
    """Persisted shape of a CronJob."""

    def __init__(
        self,
        name: str = "",
        cron_expr: str = "",
        target_kind: str = "",
        payload: str = "",         # JSON-encoded
        description: str = "",
        status: str = "enabled",
        last_fired_at: str = "",
        last_task_id: str = "",
        extra_data: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = name
        self.cron_expr = cron_expr
        self.target_kind = target_kind
        self.payload = payload
        self.description = description
        self.status = status
        self.last_fired_at = last_fired_at
        self.last_task_id = last_task_id
        self.extra_data = extra_data

    def get_table_name(self) -> str:
        return "cron_jobs"

    def get_schema(self) -> Dict[str, str]:
        return {
            "name": "VARCHAR(64) NOT NULL",
            "cron_expr": "VARCHAR(64) NOT NULL DEFAULT ''",
            "target_kind": "VARCHAR(32) NOT NULL DEFAULT ''",
            "payload": "TEXT DEFAULT ''",
            "description": "TEXT DEFAULT ''",
            "status": "VARCHAR(16) NOT NULL DEFAULT 'enabled'",
            "last_fired_at": "VARCHAR(64) DEFAULT ''",
            "last_task_id": "VARCHAR(64) DEFAULT ''",
            "extra_data": "TEXT DEFAULT ''",
        }

    @classmethod
    def get_create_table_query(cls, db_type: str = "postgresql") -> str:
        base = super().get_create_table_query(db_type)
        constraint = ",\n            UNIQUE (name)"
        idx = base.rfind(")")
        if idx != -1:
            return base[:idx] + constraint + base[idx:]
        return base

    def get_indexes(self) -> list:
        return [
            ("idx_cron_jobs_name", "name"),
            ("idx_cron_jobs_status", "status"),
        ]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CronJobModel":
        known = {
            "name", "cron_expr", "target_kind", "payload", "description",
            "status", "last_fired_at", "last_task_id", "extra_data",
            "id", "created_at", "updated_at",
        }
        return cls(**{k: v for k, v in data.items() if k in known})
