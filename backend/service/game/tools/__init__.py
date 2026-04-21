"""Basic interaction tools (PR-X3-6).

Four tools the LLM can call to express player action:

- :class:`FeedTool` — food kinds map to hunger / affection deltas.
- :class:`PlayTool` — play kinds map to stress / energy / affection.
- :class:`GiftTool` — gift kinds map to affection / trust / mood.
- :class:`TalkTool` — meta-action marking a topic change / chat beat.

Each tool pushes one or more :class:`~service.state.Mutation` entries
onto the current-turn :class:`~service.state.MutationBuffer` (bound
via :mod:`service.state.tool_context`) and returns a short structured
string that the LLM uses to compose the narrated response.

Registration flows through ``tools/built_in/game_tools.py`` which
re-exports the four ``TOOLS = [...]`` instances for
:class:`~service.tool_loader.ToolLoader`, which in turn feeds
:class:`~service.langgraph.geny_tool_provider.GenyToolProvider` on
every pipeline build.
"""

from __future__ import annotations

from .feed import FeedTool
from .gift import GiftTool
from .play import PlayTool
from .rules import (
    FEED_RULES,
    GIFT_RULES,
    PLAY_RULES,
    TALK_KINDS,
    FeedRule,
    GiftRule,
    PlayRule,
)
from .talk import TalkTool

__all__ = [
    "FEED_RULES",
    "GIFT_RULES",
    "PLAY_RULES",
    "TALK_KINDS",
    "FeedRule",
    "FeedTool",
    "GiftRule",
    "GiftTool",
    "PlayRule",
    "PlayTool",
    "TalkTool",
]
