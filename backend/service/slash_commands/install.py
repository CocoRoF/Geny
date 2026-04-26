"""Register Geny-side slash commands + discovery paths.

The executor's built-in commands (cost / status / help / etc.)
auto-install on import; this module only adds Geny-domain commands
and wires the discovery paths under ``~/.geny/commands/`` and
``.geny/commands/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def install_geny_slash_commands() -> int:
    """Returns the count of commands made available (built-in +
    Geny-specific + discovered)."""
    try:
        from geny_executor.slash_commands import get_default_registry
        # Importing built_in triggers auto-installation.
        import geny_executor.slash_commands.built_in  # noqa: F401
    except ImportError as e:
        logger.warning("slash_commands_unavailable: %s", e)
        return 0

    registry = get_default_registry()

    # Service-specific commands (none yet — Geny's `/preset` and
    # SkillPanel-driven `/skill-id` dispatch live in the frontend
    # CommandTab and bypass server-side dispatch).

    # Discovery paths.
    discovered = 0
    for p in (
        Path.home() / ".geny" / "commands",
        Path(".geny") / "commands",
    ):
        try:
            discovered += registry.discover_paths(p)
        except Exception as e:
            logger.warning("slash_discovery_failed path=%s err=%s", p, e)

    total = len(registry.list_all())
    logger.info(
        "slash_commands_installed total=%d discovered=%d", total, discovered,
    )
    return total


__all__ = ["install_geny_slash_commands"]
