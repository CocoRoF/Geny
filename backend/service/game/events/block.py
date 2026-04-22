""":class:`EventSeedBlock` — one-line narrative hint.

Wraps the ``hint_text`` of a picked :class:`EventSeed` as a
:class:`PromptBlock` so the persona provider (PR-X4-5) can append it
to the end of its block list, exactly as plan/04 §6.4 prescribes. No
state lookup at render time — the block is stateless, carrying the
pre-picked text — because the pick is already non-deterministic and
baking it into the cache_key is the provider's job.
"""

from __future__ import annotations

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.interface import PromptBlock

from .pool import EventSeed


class EventSeedBlock(PromptBlock):
    """Render one seed's hint as a single ``[Event]`` line.

    Example output:

        ``[Event] Today marks a 30-day milestone since awakening — the
        creature can mention it if it flows naturally.``

    The ``[Event]`` bracket label mirrors ``[Mood]`` / ``[Vitals]`` /
    ``[Bond with Owner]`` / ``[Stage]`` so the LLM reads one uniform
    prompt dialect across all CreatureState-derived blocks.
    """

    def __init__(self, seed: EventSeed) -> None:
        self._seed = seed

    @property
    def name(self) -> str:
        return "event_seed"

    @property
    def seed(self) -> EventSeed:
        """The seed this block wraps — useful for tests and diagnostics."""
        return self._seed

    def render(self, state: PipelineState) -> str:
        text = (self._seed.hint_text or "").strip()
        if not text:
            return ""
        return f"[Event] {text}"
