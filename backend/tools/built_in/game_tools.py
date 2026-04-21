"""Loader-facing re-export of the game interaction tools.

:class:`~service.tool_loader.ToolLoader` scans ``tools/built_in/*_tools.py``
at startup and reads each module's ``TOOLS`` attribute. The actual
implementations live under ``service/game/tools/`` — this thin file
only bridges the discovery mechanism so the loader picks them up.

The four tools here are **always available** (built-in). They become
meaningful at runtime only when ``GENY_GAME_FEATURES`` is on (which
wires the :class:`~service.state.CreatureStateProvider`): without a
provider, :func:`~service.state.current_mutation_buffer` returns
``None`` and each tool degrades to a narrated-only response so the
pipeline keeps running.
"""

from __future__ import annotations

from service.game.tools import FeedTool, GiftTool, PlayTool, TalkTool

TOOLS = [FeedTool(), PlayTool(), GiftTool(), TalkTool()]

__all__ = ["TOOLS"]
