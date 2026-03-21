"""
Tool Preset Store — JSON-file persistence for tool preset definitions.

Mirrors WorkflowStore pattern: individual JSON files under a
configurable directory.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path
from typing import List, Optional

from service.tool_preset.models import ToolPresetDefinition

logger = getLogger(__name__)

_DEFAULT_DIR = Path(__file__).parent.parent.parent / "tool_presets"


class ToolPresetStore:
    """Persist and load ToolPresetDefinition objects as JSON files."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._dir = storage_dir or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"ToolPresetStore initialized at {self._dir}")

    # ── CRUD ──

    def save(self, preset: ToolPresetDefinition) -> None:
        """Save (create or update) a tool preset definition."""
        preset.touch()
        path = self._path_for(preset.id)
        path.write_text(
            preset.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info(f"Tool preset saved: {preset.name} ({preset.id})")

    def load(self, preset_id: str) -> Optional[ToolPresetDefinition]:
        """Load a single preset by ID."""
        path = self._path_for(preset_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ToolPresetDefinition(**data)
        except Exception as e:
            logger.error(f"Failed to load tool preset {preset_id}: {e}")
            return None

    def delete(self, preset_id: str) -> bool:
        """Delete a tool preset definition."""
        path = self._path_for(preset_id)
        if path.exists():
            path.unlink()
            logger.info(f"Tool preset deleted: {preset_id}")
            return True
        return False

    def list_all(self) -> List[ToolPresetDefinition]:
        """List all saved tool preset definitions."""
        presets: List[ToolPresetDefinition] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                presets.append(ToolPresetDefinition(**data))
            except Exception as e:
                logger.warning(f"Skipping malformed preset file {path.name}: {e}")
        return presets

    def list_templates(self) -> List[ToolPresetDefinition]:
        """List only template presets."""
        return [p for p in self.list_all() if p.is_template]

    def list_user_presets(self) -> List[ToolPresetDefinition]:
        """List only user-created (non-template) presets."""
        return [p for p in self.list_all() if not p.is_template]

    def exists(self, preset_id: str) -> bool:
        """Check if a preset exists."""
        return self._path_for(preset_id).exists()

    def clone(self, preset_id: str, new_name: str) -> Optional[ToolPresetDefinition]:
        """Clone an existing preset with a new name and ID."""
        source = self.load(preset_id)
        if not source:
            return None

        cloned = ToolPresetDefinition(
            id=str(uuid.uuid4()),
            name=new_name,
            description=source.description,
            icon=source.icon,
            custom_tools=list(source.custom_tools),
            mcp_servers=list(source.mcp_servers),
            is_template=False,
            template_name=None,
        )
        self.save(cloned)
        return cloned

    # ── Internals ──

    def _path_for(self, preset_id: str) -> Path:
        safe_id = "".join(c for c in preset_id if c.isalnum() or c in "-_")
        return self._dir / f"{safe_id}.json"


# ── Singleton ──

_store_instance: Optional[ToolPresetStore] = None


def get_tool_preset_store() -> ToolPresetStore:
    """Return the global ToolPresetStore singleton."""
    global _store_instance
    if _store_instance is None:
        _store_instance = ToolPresetStore()
    return _store_instance
