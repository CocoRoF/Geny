"""Resolve the framework built-in tool list for a ToolPreset (PR-F.5.2).

Bridges the new ``built_in_mode`` / ``built_in_tools`` / ``built_in_deny``
fields (PR-F.5.1) with the executor's ``BUILT_IN_TOOL_CLASSES`` registry.
Manifest builders that want preset-aware built-ins call
:func:`resolve_built_in_tool_names` and pass the result to
``build_default_manifest(built_in_tool_names=...)``.

The legacy default behaviour ("expose every framework built-in") is
preserved when ``built_in_mode='inherit'`` — same shape as the existing
``["*"]`` semantic interpreted by the executor.
"""

from __future__ import annotations

from logging import getLogger
from typing import List, Optional

from service.tool_preset.models import ToolPresetDefinition

logger = getLogger(__name__)


def _all_framework_names() -> List[str]:
    try:
        from geny_executor.tools.built_in import BUILT_IN_TOOL_CLASSES

        return sorted(BUILT_IN_TOOL_CLASSES.keys())
    except ImportError:
        return []


def resolve_built_in_tool_names(
    preset: Optional[ToolPresetDefinition],
) -> Optional[List[str]]:
    """Return the per-preset framework built-in name list.

    Returns:
        - ``None`` to signal "use the existing default" (caller passes
          its own ``built_in_tool_names`` arg or relies on the
          manifest's stored value). Triggered when the preset is
          missing or in ``inherit`` mode.
        - ``["*"]`` when the resolved set equals the full registry —
          preserves the executor's wildcard expansion path.
        - An explicit list of names otherwise.
    """
    if preset is None or preset.built_in_mode == "inherit":
        return None

    full = _all_framework_names()
    if not full:
        # Executor not importable — best-effort fallback.
        return None

    if preset.built_in_mode == "allowlist":
        names = sorted(set(preset.built_in_tools) & set(full))
    elif preset.built_in_mode == "blocklist":
        denied = set(preset.built_in_deny)
        names = [n for n in full if n not in denied]
    else:
        logger.warning(
            "preset_built_in_mode_unknown name=%s mode=%s; falling back to inherit",
            preset.name, preset.built_in_mode,
        )
        return None

    if names == full:
        return ["*"]
    return names


__all__ = ["resolve_built_in_tool_names"]
