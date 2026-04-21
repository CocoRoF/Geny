"""``feed`` tool — LLM-facing food interaction.

The LLM calls this tool when the player (or the creature itself, in
auto-drive scenarios) wants to offer food. The ``kind`` parameter
selects a tuning row in :data:`FEED_RULES`; unknown kinds fall back
to ``"snack"`` rather than erroring so the turn narration stays
coherent.

State effects (all via :class:`~service.state.MutationBuffer`):

- ``vitals.hunger``  += ``rule.hunger_delta``  (negative → more sated)
- ``bond.affection`` += ``rule.affection_delta``
- ``recent_events``  append ``"fed:{kind}"``

The return string is read by the LLM to compose the narrated reaction.
It includes ``pleasure=<low|medium|high>`` so the model can pick a
tonal register without inventing one (which tends to drift into
grandiose language).
"""

from __future__ import annotations

from logging import getLogger

from service.state import current_mutation_buffer
from tools.base import BaseTool

from .rules import feed_rule_for

logger = getLogger(__name__)


class FeedTool(BaseTool):
    name = "feed"
    description = (
        "Give the creature food. Use this when the player offers something "
        "to eat, or when the creature explicitly requests food. Choose a "
        "``kind`` that matches the narrated intent — ``snack`` for casual "
        "treats, ``meal`` for a full serving, ``favorite`` for something "
        "the creature loves, ``medicine`` when the narrative calls for "
        "healing rather than satiation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["snack", "meal", "favorite", "medicine"],
                "description": "Type of food offered.",
                "default": "snack",
            },
        },
        "required": [],
    }

    def run(self, kind: str = "snack", **_: object) -> str:
        rule = feed_rule_for(kind)
        buf = current_mutation_buffer()
        if buf is None:
            logger.debug("feed: no mutation buffer bound — running narrated-only")
            return (
                f"FEED_NARRATED_ONLY kind={kind} pleasure={rule.pleasure} "
                "(state unavailable — no mutation recorded)"
            )

        source = "tool:feed"
        if rule.hunger_delta != 0.0:
            buf.append(op="add", path="vitals.hunger", value=rule.hunger_delta, source=source)
        if rule.affection_delta != 0.0:
            buf.append(op="add", path="bond.affection", value=rule.affection_delta, source=source)
        buf.append(op="append", path="recent_events", value=f"fed:{kind}", source=source)

        return f"FEED_OK kind={kind} pleasure={rule.pleasure}"


__all__ = ["FeedTool"]
