"""``talk`` tool — meta-action for conversation events.

Natural-language dialogue is the *default* channel — the LLM doesn't
need to call a tool to hold a conversation. :class:`TalkTool` exists
only for *meta* acts that mark conversational beats:

- ``greet`` — opening of a session (post-hydrate, first turn).
- ``topic_shift`` — narrator explicitly redirects.
- ``check_in`` — mid-session pulse ("how are you feeling?").
- ``farewell`` — narrated closing before the user disconnects.

Each of these records a ``recent_events`` tag + a tiny
``bond.familiarity`` bump, and no vitals / mood changes. Familiarity
is the right channel because "we talked, we know each other slightly
better" is the semantic payload of any Talk, regardless of topic.
"""

from __future__ import annotations

from logging import getLogger

from service.state import current_mutation_buffer
from tools.base import BaseTool

from .rules import TALK_KINDS

logger = getLogger(__name__)

FAMILIARITY_DELTA = 0.3


class TalkTool(BaseTool):
    name = "talk"
    description = (
        "Mark a conversational beat. Use this for meta actions only — "
        "ordinary dialogue does NOT need this tool. Kinds: ``greet`` "
        "(session opening), ``topic_shift`` (explicit redirect), "
        "``check_in`` (pulse), ``farewell`` (session closing)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(TALK_KINDS),
                "description": "Conversational beat being marked.",
            },
            "topic": {
                "type": "string",
                "description": (
                    "Optional short label for the topic. Appended to the "
                    "recent_events tag as ``talk:{kind}:{topic}``."
                ),
            },
        },
        "required": ["kind"],
    }

    def run(self, kind: str, topic: str = "", **_: object) -> str:
        kind_clean = kind if kind in TALK_KINDS else "check_in"

        buf = current_mutation_buffer()
        tag = f"talk:{kind_clean}"
        if topic:
            tag = f"{tag}:{topic}"

        if buf is None:
            logger.debug("talk: no mutation buffer bound — running narrated-only")
            return f"TALK_NARRATED_ONLY kind={kind_clean} (state unavailable)"

        source = "tool:talk"
        buf.append(op="add", path="bond.familiarity", value=FAMILIARITY_DELTA, source=source)
        buf.append(op="append", path="recent_events", value=tag, source=source)

        return f"TALK_OK kind={kind_clean}"


__all__ = ["FAMILIARITY_DELTA", "TalkTool"]
