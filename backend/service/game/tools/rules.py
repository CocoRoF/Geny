"""Rule tables for ``feed`` / ``play`` / ``gift`` / ``talk``.

Each table maps a ``kind`` string (LLM-controlled) to a frozen
dataclass holding the deltas the tool will append as mutations. The
data lives here — not in the tool classes themselves — so the tuning
pass in cycle 20260421_10+ can adjust numbers without touching runtime
logic, and tests can assert the exact delta for a given kind without
reaching into private attributes.

Design notes
------------

*Deltas are intentionally small.* Values in [-40, 5] per call keep a
long session from swinging vitals to saturation in a handful of turns
(see plan/01 §default tuning). The per-field 0–100 clamping happens at
``provider.apply`` time, so a tool can safely push ``+30`` even if
``vitals.hunger`` is already at 95.

*``pleasure`` is an LLM-visible hint.* The tool return string includes
``pleasure=<low|medium|high>`` so the model has a predictable
affordance for the narrated reaction ("맛있다" vs "별로네"). It does
not directly drive any state delta — those all live in the numeric
fields.

*Unknown kinds fall back.* ``FEED_RULES["snack"]`` /
``PLAY_RULES["cuddle"]`` / ``GIFT_RULES["flower"]`` are the safe
defaults the tool returns when the LLM supplies an unrecognised kind,
rather than erroring out. Erroring would surface the kind name as an
API tool error and break the LLM's narration; falling back keeps the
turn readable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Tuple

Pleasure = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class FeedRule:
    hunger_delta: float
    affection_delta: float
    pleasure: Pleasure


@dataclass(frozen=True)
class PlayRule:
    stress_delta: float
    energy_delta: float
    affection_delta: float
    pleasure: Pleasure


@dataclass(frozen=True)
class GiftRule:
    affection_delta: float
    trust_delta: float
    joy_delta: float
    pleasure: Pleasure


FEED_RULES: Mapping[str, FeedRule] = {
    "snack":    FeedRule(hunger_delta=-10.0, affection_delta=+0.5, pleasure="low"),
    "meal":     FeedRule(hunger_delta=-35.0, affection_delta=+1.5, pleasure="medium"),
    "favorite": FeedRule(hunger_delta=-25.0, affection_delta=+4.0, pleasure="high"),
    "medicine": FeedRule(hunger_delta=0.0,   affection_delta=+0.2, pleasure="low"),
}

PLAY_RULES: Mapping[str, PlayRule] = {
    "cuddle": PlayRule(stress_delta=-8.0,  energy_delta=-4.0,  affection_delta=+2.0, pleasure="medium"),
    "fetch":  PlayRule(stress_delta=-12.0, energy_delta=-12.0, affection_delta=+1.5, pleasure="high"),
    "tease":  PlayRule(stress_delta=+4.0,  energy_delta=-3.0,  affection_delta=-0.5, pleasure="low"),
    "game":   PlayRule(stress_delta=-6.0,  energy_delta=-6.0,  affection_delta=+2.5, pleasure="high"),
}

GIFT_RULES: Mapping[str, GiftRule] = {
    "flower":   GiftRule(affection_delta=+1.5, trust_delta=+0.5, joy_delta=+0.5, pleasure="medium"),
    "toy":      GiftRule(affection_delta=+2.5, trust_delta=+0.3, joy_delta=+1.5, pleasure="high"),
    "accessory":GiftRule(affection_delta=+3.5, trust_delta=+0.8, joy_delta=+1.0, pleasure="high"),
    "letter":   GiftRule(affection_delta=+1.0, trust_delta=+1.5, joy_delta=+0.2, pleasure="medium"),
}

TALK_KINDS: Tuple[str, ...] = (
    "greet",
    "topic_shift",
    "check_in",
    "farewell",
)


def feed_rule_for(kind: str) -> FeedRule:
    return FEED_RULES.get(kind, FEED_RULES["snack"])


def play_rule_for(kind: str) -> PlayRule:
    return PLAY_RULES.get(kind, PLAY_RULES["cuddle"])


def gift_rule_for(kind: str) -> GiftRule:
    return GIFT_RULES.get(kind, GIFT_RULES["flower"])


__all__ = [
    "FEED_RULES",
    "GIFT_RULES",
    "PLAY_RULES",
    "TALK_KINDS",
    "FeedRule",
    "GiftRule",
    "PlayRule",
    "feed_rule_for",
    "gift_rule_for",
    "play_rule_for",
]
