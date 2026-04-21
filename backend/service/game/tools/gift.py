"""``gift`` tool — present an object.

Gifts give primarily *bond* deltas (affection, trust) and a mood
bump, with no vitals change. ``flower`` is the safe fallback for
unknown kinds because it has the smallest magnitudes in
:data:`GIFT_RULES`.

State effects:

- ``bond.affection`` += ``rule.affection_delta``
- ``bond.trust``     += ``rule.trust_delta``
- ``mood.joy``       += ``rule.joy_delta``
- ``recent_events``  append ``"gift:{kind}"``

Note that ``mood.joy`` is a path on :class:`~service.state.MoodVector`
rather than a free-form field — the provider's ``apply_mutations``
walks the dotted path into the dataclass, so we stay schema-safe.
"""

from __future__ import annotations

from logging import getLogger

from service.state import current_mutation_buffer
from tools.base import BaseTool

from .rules import gift_rule_for

logger = getLogger(__name__)


class GiftTool(BaseTool):
    name = "gift"
    description = (
        "Give the creature a present. ``flower`` for simple gestures, "
        "``toy`` for playful items that boost mood, ``accessory`` for "
        "items the creature wears (highest affection gain), ``letter`` "
        "for heartfelt written messages (strongest trust gain)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["flower", "toy", "accessory", "letter"],
                "description": "Type of gift.",
                "default": "flower",
            },
        },
        "required": [],
    }

    def run(self, kind: str = "flower", **_: object) -> str:
        rule = gift_rule_for(kind)
        buf = current_mutation_buffer()
        if buf is None:
            logger.debug("gift: no mutation buffer bound — running narrated-only")
            return (
                f"GIFT_NARRATED_ONLY kind={kind} pleasure={rule.pleasure} "
                "(state unavailable — no mutation recorded)"
            )

        source = "tool:gift"
        if rule.affection_delta != 0.0:
            buf.append(op="add", path="bond.affection", value=rule.affection_delta, source=source)
        if rule.trust_delta != 0.0:
            buf.append(op="add", path="bond.trust", value=rule.trust_delta, source=source)
        if rule.joy_delta != 0.0:
            buf.append(op="add", path="mood.joy", value=rule.joy_delta, source=source)
        buf.append(op="append", path="recent_events", value=f"gift:{kind}", source=source)

        return f"GIFT_OK kind={kind} pleasure={rule.pleasure}"


__all__ = ["GiftTool"]
