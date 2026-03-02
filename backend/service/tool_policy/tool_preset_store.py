"""
Tool Preset Store — JSON-file persistence for tool preset definitions.

Follows the same pattern as WorkflowStore: stores each preset as a
separate JSON file under a configurable directory.
"""

from __future__ import annotations

import json
from logging import getLogger
from pathlib import Path
from typing import List, Optional

from service.tool_policy.tool_preset_model import ToolPreset

logger = getLogger(__name__)

_DEFAULT_DIR = Path(__file__).parent.parent.parent / "tool_presets"


class ToolPresetStore:
    """Persist and load ToolPreset objects as JSON files."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._dir = storage_dir or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"ToolPresetStore initialized at {self._dir}")
        self._ensure_builtin_templates()

    # ── Built-in templates ──

    def _ensure_builtin_templates(self) -> None:
        """Create built-in template presets if they don't exist."""
        templates = [
            ToolPreset(
                id="preset-full",
                name="Full Access",
                description="All available MCP servers and tools — unrestricted access.",
                allowed_servers=["*"],
                allowed_tools=["*"],
                is_template=True,
            ),
            ToolPreset(
                id="preset-coding",
                name="Coding",
                description="Built-in tools + filesystem, git, and code-related MCP servers.",
                allowed_servers=[
                    "_builtin_tools",
                    "filesystem",
                    "git",
                    "github",
                    "code",
                    "lint",
                    "docker",
                    "terminal",
                ],
                allowed_tools=["*"],
                is_template=True,
            ),
            ToolPreset(
                id="preset-research",
                name="Research",
                description="Built-in tools + search, web, and knowledge MCP servers.",
                allowed_servers=[
                    "_builtin_tools",
                    "web",
                    "search",
                    "brave",
                    "perplexity",
                    "google",
                    "bing",
                    "arxiv",
                    "wikipedia",
                    "fetch",
                    "browser",
                ],
                allowed_tools=["*"],
                is_template=True,
            ),
            ToolPreset(
                id="preset-minimal",
                name="Minimal",
                description="Only built-in tools — no external MCP servers.",
                allowed_servers=["_builtin_tools"],
                allowed_tools=["*"],
                is_template=True,
            ),
        ]

        for tmpl in templates:
            if not self.exists(tmpl.id):
                self.save(tmpl)
                logger.info(f"  Created built-in tool preset: {tmpl.name}")

    # ── CRUD ──

    def save(self, preset: ToolPreset) -> None:
        """Save (create or update) a tool preset."""
        preset.touch()
        path = self._path_for(preset.id)
        path.write_text(
            preset.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info(f"Tool preset saved: {preset.name} ({preset.id})")

    def load(self, preset_id: str) -> Optional[ToolPreset]:
        """Load a single preset by ID."""
        path = self._path_for(preset_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ToolPreset(**data)
        except Exception as e:
            logger.error(f"Failed to load tool preset {preset_id}: {e}")
            return None

    def delete(self, preset_id: str) -> bool:
        """Delete a tool preset. Templates cannot be deleted."""
        preset = self.load(preset_id)
        if preset and preset.is_template:
            return False
        path = self._path_for(preset_id)
        if path.exists():
            path.unlink()
            logger.info(f"Tool preset deleted: {preset_id}")
            return True
        return False

    def list_all(self) -> List[ToolPreset]:
        """List all saved tool presets."""
        presets: List[ToolPreset] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                presets.append(ToolPreset(**data))
            except Exception as e:
                logger.warning(f"Skipping malformed tool preset {path.name}: {e}")
        return presets

    def list_templates(self) -> List[ToolPreset]:
        """List only template (built-in) presets."""
        return [p for p in self.list_all() if p.is_template]

    def list_user_presets(self) -> List[ToolPreset]:
        """List only user-created presets."""
        return [p for p in self.list_all() if not p.is_template]

    def exists(self, preset_id: str) -> bool:
        return self._path_for(preset_id).exists()

    def clone(self, preset_id: str) -> Optional[ToolPreset]:
        """Clone a preset (creates a new non-template copy)."""
        import uuid

        source = self.load(preset_id)
        if not source:
            return None

        new_id = f"preset-{uuid.uuid4().hex[:8]}"
        cloned = ToolPreset(
            id=new_id,
            name=f"{source.name} (Copy)",
            description=source.description,
            allowed_servers=list(source.allowed_servers),
            allowed_tools=list(source.allowed_tools),
            is_template=False,
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
