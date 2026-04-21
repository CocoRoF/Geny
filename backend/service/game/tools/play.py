"""``play`` tool — physical / interactive activity.

``kind`` selects a row in :data:`PLAY_RULES`. ``cuddle`` is the safe
default for unknown kinds — chosen because it has the smallest
magnitude of all rules, so an unexpected fallback doesn't swing state
dramatically.

State effects:

- ``vitals.stress``  += ``rule.stress_delta``  (cuddle / fetch / game → negative)
- ``vitals.energy``  += ``rule.energy_delta``  (always ≤ 0 — play tires)
- ``bond.affection`` += ``rule.affection_delta``
- ``recent_events``  append ``"played:{kind}"``

``tease`` intentionally has a *positive* stress delta and a small
*negative* affection delta — the LLM should pick it when the player's
described action is provocative, and the creature's narrated response
should reflect the small annoyance. This shape is what lets the same
tool carry both positive and negative player actions without needing
a separate "annoy" tool.
"""

from __future__ import annotations

from logging import getLogger

from service.state import current_mutation_buffer
from tools.base import BaseTool

from .rules import play_rule_for

logger = getLogger(__name__)


class PlayTool(BaseTool):
    name = "play"
    description = (
        "Engage the creature in physical or interactive play. Choose a "
        "``kind`` matching the described action: ``cuddle`` for quiet "
        "physical affection, ``fetch`` for high-energy retrieval games, "
        "``game`` for structured interactive play, ``tease`` when the "
        "player's action is playful-but-provocative (the creature may "
        "show a touch of annoyance)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["cuddle", "fetch", "game", "tease"],
                "description": "Type of play.",
                "default": "cuddle",
            },
        },
        "required": [],
    }

    def run(self, kind: str = "cuddle", **_: object) -> str:
        rule = play_rule_for(kind)
        buf = current_mutation_buffer()
        if buf is None:
            logger.debug("play: no mutation buffer bound — running narrated-only")
            return (
                f"PLAY_NARRATED_ONLY kind={kind} pleasure={rule.pleasure} "
                "(state unavailable — no mutation recorded)"
            )

        source = "tool:play"
        if rule.stress_delta != 0.0:
            buf.append(op="add", path="vitals.stress", value=rule.stress_delta, source=source)
        if rule.energy_delta != 0.0:
            buf.append(op="add", path="vitals.energy", value=rule.energy_delta, source=source)
        if rule.affection_delta != 0.0:
            buf.append(op="add", path="bond.affection", value=rule.affection_delta, source=source)
        buf.append(op="append", path="recent_events", value=f"played:{kind}", source=source)

        return f"PLAY_OK kind={kind} pleasure={rule.pleasure}"


__all__ = ["PlayTool"]
