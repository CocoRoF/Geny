"""J.1 (cycle 20260426_3) — settings.json-driven persona tail blocks.

The system stage's prompt builder composes a role-specific persona
block plus a tail (date / memory context). This module reads
``settings.json:persona.tail_blocks_by_role`` and returns the tail
block instances for the requested role.

When the section is absent or the role isn't listed, the historical
``[DateTimeBlock, MemoryContextBlock]`` chain is the floor.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_DEFAULT_TAIL = ("datetime", "memory_context")


def _builder_map() -> Dict[str, Any]:
    """Lazy import — keeps test isolation when geny_executor isn't
    available."""
    try:
        from geny_executor.stages.s03_system.artifact.default.builders import (
            DateTimeBlock,
            MemoryContextBlock,
        )
    except ImportError:
        return {}
    return {
        "datetime": DateTimeBlock,
        "memory_context": MemoryContextBlock,
    }


def _settings_section() -> Dict[str, Any]:
    """Best-effort read of ``settings.json:persona``."""
    try:
        from geny_executor.settings import get_default_loader
    except ImportError:
        return {}
    section = get_default_loader().get_section("persona")
    if section is None:
        return {}
    if hasattr(section, "model_dump"):
        return section.model_dump(exclude_none=True)
    if isinstance(section, dict):
        return dict(section)
    return {}


def resolve_tail_blocks(role: str) -> List[Any]:
    """Return the persona-builder tail block instances for ``role``.

    Resolution order:
      1. ``settings.json:persona.tail_blocks_by_role[role]``.
      2. ``settings.json:persona.tail_blocks_by_role["default"]``.
      3. Historical default ``["datetime", "memory_context"]``.

    Unknown block keys are skipped with a warning so a typo in
    settings.json doesn't take down session creation.
    """
    builders = _builder_map()
    if not builders:
        return []

    section = _settings_section()
    by_role = section.get("tail_blocks_by_role") or {}
    if not isinstance(by_role, dict):
        by_role = {}

    role_key = role.strip().lower() if isinstance(role, str) else "default"
    order: List[str]
    candidate = by_role.get(role_key)
    if isinstance(candidate, list) and candidate:
        order = [str(x) for x in candidate]
    else:
        fallback = by_role.get("default")
        if isinstance(fallback, list) and fallback:
            order = [str(x) for x in fallback]
        else:
            order = list(_DEFAULT_TAIL)

    blocks: List[Any] = []
    for key in order:
        cls = builders.get(key)
        if cls is None:
            logger.warning(
                "persona.tail_blocks_by_role: unknown block key %r for role %r — skipping",
                key, role_key,
            )
            continue
        try:
            blocks.append(cls())
        except Exception:  # noqa: BLE001
            logger.exception(
                "persona.tail_blocks_by_role: %r block constructor raised — skipping",
                key,
            )
    return blocks


__all__ = ["resolve_tail_blocks"]
