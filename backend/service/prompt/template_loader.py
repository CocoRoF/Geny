"""
Prompt Template Loader — unifies static prompts/*.md files with the builder.

This module bridges the gap between the static Markdown prompt files
(``prompts/*.md``) and the programmatic ``PromptBuilder`` system.  It
provides:

* **Loading**: Reads role-specific ``.md`` files from the ``prompts/``
  directory at build-time so the content can be injected into the builder
  as a ``PromptSection``.
* **Role mapping**: Maps role names to their corresponding ``.md`` filename.
* **Fallback**: When a file is not found, the builder's hardcoded
  ``role_protocol`` content is used.

Public API
~~~~~~~~~~
* ``PromptTemplateLoader(prompts_dir=None)``
* ``loader.load_role_template(role) -> Optional[str]``
* ``loader.list_available_roles() -> list[str]``
* ``loader.load_all() -> dict[str, str]``
"""

from __future__ import annotations

from logging import getLogger
from pathlib import Path
from typing import Dict, List, Optional

logger = getLogger(__name__)

# Project root → prompts/ directory
_DEFAULT_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

# Role → filename mapping
_ROLE_FILE_MAP: Dict[str, str] = {
    "worker":       "worker.md",
    "developer":    "developer.md",
    "manager":      "manager.md",
    "researcher":   "researcher.md",
    "self-manager": "self-manager.md",
}


class PromptTemplateLoader:
    """Loads role prompt templates from the ``prompts/`` directory.

    Usage::

        loader = PromptTemplateLoader()
        content = loader.load_role_template("developer")
        if content:
            builder.override_section("role_protocol", content)
    """

    def __init__(self, prompts_dir: Optional[Path] = None) -> None:
        self._dir = prompts_dir or _DEFAULT_PROMPTS_DIR
        self._cache: Dict[str, str] = {}

    @property
    def prompts_dir(self) -> Path:
        return self._dir

    def load_role_template(self, role: str) -> Optional[str]:
        """Load the Markdown template for *role*.

        Returns:
            The file content as a string, or None if no file exists.
        """
        if role in self._cache:
            return self._cache[role]

        filename = _ROLE_FILE_MAP.get(role)
        if not filename:
            return None

        filepath = self._dir / filename
        if not filepath.is_file():
            logger.debug("PromptTemplateLoader: %s not found at %s", filename, filepath)
            return None

        try:
            content = filepath.read_text(encoding="utf-8").strip()
            self._cache[role] = content
            logger.debug(
                "PromptTemplateLoader: loaded %s (%d chars)",
                filename,
                len(content),
            )
            return content
        except Exception as exc:
            logger.warning("PromptTemplateLoader: failed to read %s: %s", filepath, exc)
            return None

    def list_available_roles(self) -> List[str]:
        """Return role names whose template files exist on disk."""
        available: List[str] = []
        for role, filename in _ROLE_FILE_MAP.items():
            if (self._dir / filename).is_file():
                available.append(role)
        return available

    def load_all(self) -> Dict[str, str]:
        """Load all available role templates.

        Returns:
            ``{role: content}`` for every role with a file on disk.
        """
        result: Dict[str, str] = {}
        for role in _ROLE_FILE_MAP:
            content = self.load_role_template(role)
            if content:
                result[role] = content
        return result

    def clear_cache(self) -> None:
        """Clear the in-memory cache, forcing re-reads on next load."""
        self._cache.clear()
