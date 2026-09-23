"""What the 21 stages offer, and which of it a person should ever see.

The harness has 33 replaceable parts across 21 stages plus three ordered
chains. Showing all of them is the same as showing none: the five that
change how an agent behaves get lost among the twenty-eight that describe
how a pipeline is assembled.

So every slot lands in one of three tiers, and the tier is a claim about the
reader, not about the code:

``basic``
    Someone tuning THEIR agent. "How should it shorten a long conversation",
    "may it run tools at the same time", "when is a turn finished". Nine
    slots and three budgets — the whole first screen.

``advanced``
    Someone who knows what a pipeline stage is and has a reason. Everything
    else that can legitimately be swapped.

``locked``
    Things this product is, rather than things it is configured to. They are
    shown — hiding them would make the page a lie of omission — and they do
    not take input.

The catalogue is data, deliberately. Adding a stage to the library must not
require an edit here to keep the page working: an unlisted slot falls to
``advanced``, which is the safe direction.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

__all__ = [
    "BASIC_SLOTS",
    "LOCKED_SLOTS",
    "RUNTIME_INSTALLED",
    "STAGE_GROUPS",
    "tier_of",
    "lock_reason",
]

#: ``(stage order, slot)`` → the question this slot answers, in the user's
#: words. Being on this list is what puts a slot on the first screen, and the
#: text is why it earns the space.
BASIC_SLOTS: Dict[Tuple[int, str], str] = {
    (2, "compactor"): "conversationGetsLong",
    # Every turn starts from an empty history; this is what brings the last
    # few back — the ones with tools as they happened, the rest as what was
    # said. The difference between an agent that knows it already did the
    # thing and one that does it again.
    (2, "replay"): "recentTurns",
    (5, "strategy"): "promptCache",
    (8, "budget_planner"): "thinkingBudget",
    (10, "executor"): "toolsAtOnce",
    (12, "orchestrator"): "delegation",
    (14, "strategy"): "whenTurnEnds",
    (18, "strategy"): "whatItRemembers",
    (21, "formatter"): "howItAnswers",
}

#: ``(stage order, slot)`` → why it cannot be changed. Each of these is an
#: invariant the rest of the design rests on, not a setting nobody got round
#: to exposing.
LOCKED_SLOTS: Dict[Tuple[int, str], str] = {
    # The one that matters most. A provider may be a model; it may not be an
    # agent. Handing the tool loop to the backend costs the conversation its
    # portability, its permission ladder and its memory in one move.
    (6, "tool_loop"): "weOwnTheLoop",
    # There is one provider name and the session's route decides what is
    # behind it. Changing this here would put a second answer on the page.
    (6, "router"): "routeDecides",
    # One registry, one answer. The slot exists for symmetry.
    (10, "router"): "onlyOption",
}

#: Slots whose live value Geny installs at session build, replacing whatever
#: the manifest declared. Reported as ``runtime`` so the page never claims the
#: manifest's placeholder is what runs.
RUNTIME_INSTALLED: Dict[Tuple[int, str], str] = {
    # Compaction that also files each summary in the agent's memory.
    (2, "compactor"): "persistingCompactor",
    # Pulls the agent's own memory into the turn's context.
    (2, "retriever"): "memoryAware",
    # The persona: character, mood, what it has been told about itself.
    (3, "builder"): "personaBuilder",
    (4, "guards"): "guardChain",
    (15, "requester"): "hitlResume",
    (17, "emitters"): "affectTags",
    # Writes the turn to the agent's memory, without re-filing what it
    # already knows.
    (18, "strategy"): "genyMemory",
    (20, "persister"): "sessionStorage",
}

#: How the 21 stages group on the page. Purely presentational, and ordered
#: the way a turn actually moves so the page reads as a sequence.
STAGE_GROUPS: Dict[int, str] = {
    1: "intake", 2: "intake", 3: "intake",
    4: "beforeTheCall", 5: "beforeTheCall",
    6: "theCall", 7: "theCall", 8: "theCall", 9: "theCall",
    10: "tools", 11: "tools", 12: "tools", 13: "tools",
    14: "deciding", 15: "deciding", 16: "deciding",
    17: "after", 18: "after", 19: "after", 20: "after", 21: "after",
}


def tier_of(order: int, slot: str) -> str:
    """``basic`` | ``advanced`` | ``locked`` for one slot.

    An unlisted slot is ``advanced``: a stage added to the library without an
    edit here still renders, one screen deeper than the common ones, which is
    the safe direction to be wrong in.
    """
    key = (int(order), str(slot))
    if key in LOCKED_SLOTS:
        return "locked"
    if key in BASIC_SLOTS:
        return "basic"
    return "advanced"


def lock_reason(order: int, slot: str) -> Optional[str]:
    """Why this slot takes no input, or ``None`` when it does."""
    return LOCKED_SLOTS.get((int(order), str(slot)))
