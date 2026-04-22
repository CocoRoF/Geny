""":class:`TamagotchiPlugin` — the X3/X4 creature-state bundle as a
:class:`GenyPlugin`.

Cycle 20260422 PR-X5-3 repackages the inline wiring that lived in
:class:`AgentSessionManager` (four live :class:`PromptBlock` s +
:class:`EventSeedPool`) into a single plugin object. This is a
*structure* change, not a behavior change: the manager still ends up
handing the same blocks and the same seed pool to
:class:`CharacterPersonaProvider`, just routed through the registry
instead of constructed inline.

Scope for this PR
-----------------

What moves into the plugin:

- **PromptBlocks.** :class:`MoodBlock`, :class:`VitalsBlock`,
  :class:`RelationshipBlock`, :class:`ProgressionBlock` — all four
  render off ``state.shared[CREATURE_STATE_KEY]`` and collapse to an
  empty string when the creature isn't hydrated, so classic-mode
  (no-state) sessions remain byte-identical.
- **EventSeedPool.** Exposed via the plugin-specific
  :attr:`event_seed_pool` accessor. The pool doesn't fit a
  ``contribute_*`` hook — the :class:`CharacterPersonaProvider` takes
  it as a distinct constructor kwarg — so we surface it as a normal
  attribute on the plugin rather than inventing a new Protocol hook.

What deliberately stays outside the plugin (for now):

- **CreatureStateProvider / DecayService.** Registered on
  :class:`AgentSessionManager` via ``set_state_provider`` at boot. Moving
  these inside the plugin means changing ``AgentSession`` 's
  ``state_provider=`` wiring and the ``main.py`` decay-service
  construction, which is larger than "repackage the four blocks".
  PR-X5-4 (executor attach_runtime bump) is the natural home.
- **ManifestSelector.** Character-driven, not plugin-driven — a
  different character's growth tree is still a character-level
  concern, not a "tamagotchi feature".
- **AffectTagEmitter.** Installed directly on the prebuilt pipeline
  today. Wiring it through ``contribute_emitters`` requires the
  session-build path to consume plugin-contributed emitters at the
  right moment — deferred to a follow-up that gives the registry a
  turn with the emit chain.
- **Game tools.** Manifest-driven today. No live
  ``ToolRegistry.register`` API to consume ``contribute_tools`` yet.
"""

from __future__ import annotations

from typing import Sequence

from service.game.events import (
    DEFAULT_SEEDS,
    EventSeed,
    EventSeedPool,
)
from service.persona.blocks import (
    AcclimationBlock,
    MoodBlock,
    ProgressionBlock,
    RelationshipBlock,
    VitalsBlock,
)
from geny_executor.stages.s03_system.interface import PromptBlock

from .protocol import PluginBase, SessionContext

__all__ = ["TamagotchiPlugin"]


class TamagotchiPlugin(PluginBase):
    """Creature-state bundle for the Geny tamagotchi ecosystem.

    Owns the four live blocks and the :class:`EventSeedPool`. Stateless
    at the block level (each ``contribute_*`` call returns fresh block
    instances), stateful at the pool level (one pool per plugin
    instance — constructed from the seed catalogue once).

    The block instances are returned fresh per call for consistency
    with the plugin contract's "may inspect state.shared at render
    time, but don't share per-session state across contribute_* calls"
    guidance. The blocks themselves are internally stateless, so the
    cost of freshly instantiating them is trivial.
    """

    name = "tamagotchi"
    version = "0.1.0"

    def __init__(
        self,
        *,
        event_seeds: Sequence[EventSeed] = DEFAULT_SEEDS,
    ) -> None:
        self._event_seed_pool = EventSeedPool(event_seeds)

    @property
    def event_seed_pool(self) -> EventSeedPool:
        """The :class:`EventSeedPool` this plugin owns.

        Not a standard ``contribute_*`` hook because
        :class:`CharacterPersonaProvider` accepts the pool as a distinct
        constructor kwarg rather than as part of the block list. The
        plugin exposes it as a named attribute so the session builder
        can read ``self._tamagotchi_plugin.event_seed_pool`` without
        reaching back through the registry.
        """
        return self._event_seed_pool

    def contribute_prompt_blocks(
        self, session_ctx: SessionContext,
    ) -> Sequence[PromptBlock]:
        # ProgressionBlock (world-adaptation) sits before AcclimationBlock
        # (relationship-adaptation) so the narrower / more situational
        # block lands later in the rendered prompt — LLMs follow guidance
        # they read last more strongly, and Acclimation is the override
        # surface (cycle 20260422_6 PR2).
        return (
            MoodBlock(),
            VitalsBlock(),
            RelationshipBlock(),
            ProgressionBlock(),
            AcclimationBlock(),
        )
