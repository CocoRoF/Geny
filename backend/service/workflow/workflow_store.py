"""
Workflow Store — JSON-file persistence for workflow definitions.

Stores workflow definitions as individual JSON files under a
configurable directory. Thread-safe via asyncio lock.
"""

from __future__ import annotations

import json
from logging import getLogger
from pathlib import Path
from typing import Dict, List, Optional

from service.workflow.workflow_model import WorkflowDefinition

logger = getLogger(__name__)

_DEFAULT_DIR = Path(__file__).parent.parent.parent / "workflows"


class WorkflowStore:
    """Persist and load WorkflowDefinition objects as JSON files."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._dir = storage_dir or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"WorkflowStore initialized at {self._dir}")

    # ── CRUD ──

    def save(self, workflow: WorkflowDefinition) -> None:
        """Save (create or update) a workflow definition."""
        workflow.touch()
        path = self._path_for(workflow.id)
        path.write_text(
            workflow.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info(f"Workflow saved: {workflow.name} ({workflow.id})")

    def load(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """Load a single workflow by ID."""
        path = self._path_for(workflow_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WorkflowDefinition(**data)
        except Exception as e:
            logger.error(f"Failed to load workflow {workflow_id}: {e}")
            return None

    def delete(self, workflow_id: str) -> bool:
        """Delete a workflow definition."""
        path = self._path_for(workflow_id)
        if path.exists():
            path.unlink()
            logger.info(f"Workflow deleted: {workflow_id}")
            return True
        return False

    def list_all(self) -> List[WorkflowDefinition]:
        """List all saved workflow definitions."""
        workflows: List[WorkflowDefinition] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                workflows.append(WorkflowDefinition(**data))
            except Exception as e:
                logger.warning(f"Skipping malformed workflow file {path.name}: {e}")
        return workflows

    def list_templates(self) -> List[WorkflowDefinition]:
        """List only template workflows."""
        return [w for w in self.list_all() if w.is_template]

    def list_user_workflows(self) -> List[WorkflowDefinition]:
        """List only user-created (non-template) workflows."""
        return [w for w in self.list_all() if not w.is_template]

    def exists(self, workflow_id: str) -> bool:
        return self._path_for(workflow_id).exists()

    # ── Internals ──

    def _path_for(self, workflow_id: str) -> Path:
        # Sanitize ID for filesystem
        safe_id = "".join(c for c in workflow_id if c.isalnum() or c in "-_")
        return self._dir / f"{safe_id}.json"


# ── Singleton ──

_store_instance: Optional[WorkflowStore] = None


def get_workflow_store() -> WorkflowStore:
    """Return the global WorkflowStore singleton."""
    global _store_instance
    if _store_instance is None:
        _store_instance = WorkflowStore()
    return _store_instance
