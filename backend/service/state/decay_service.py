"""``CreatureStateDecayService`` — periodic decay driver (plan/02 §5.4).

Owns a :class:`TickEngine` by default so main.py can wire this service
independently of other tick-driven services. ``set_tick_engine`` swaps
in a shared engine when the caller wants all periodic work on one loop;
in that mode ``start`` / ``stop`` register/unregister the spec but do
not toggle the engine itself.

Error isolation: a failed tick for one character must not break the
scheduled loop for others. ``StateConflictError`` is demoted to a debug
log (the next scheduled run will re-tick), while unexpected exceptions
surface via ``logger.exception`` but are still swallowed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..tick import TickEngine, TickSpec
from .decay import DEFAULT_DECAY, DecayPolicy
from .provider.interface import StateConflictError

if TYPE_CHECKING:
    from .provider.interface import CreatureStateProvider

logger = logging.getLogger(__name__)

# 15-minute cadence — long enough that per-tick cost is negligible and
# short enough that drift on an idle user reaches steady state within
# a few hours of wall-clock. Jitter staggers writes if multiple services
# share a TickEngine.
DEFAULT_DECAY_INTERVAL_SECONDS = 15 * 60
DEFAULT_DECAY_JITTER_SECONDS = 30.0


class CreatureStateDecayService:
    def __init__(
        self,
        provider: "CreatureStateProvider",
        *,
        policy: DecayPolicy = DEFAULT_DECAY,
        interval_seconds: float = DEFAULT_DECAY_INTERVAL_SECONDS,
        jitter_seconds: float = DEFAULT_DECAY_JITTER_SECONDS,
        spec_name: str = "state_decay",
    ) -> None:
        self._provider = provider
        self._policy = policy
        self._interval = interval_seconds
        self._jitter = jitter_seconds
        self._spec_name = spec_name
        self._tick_engine: TickEngine = TickEngine()
        self._owns_tick_engine: bool = True
        self._running: bool = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def spec_name(self) -> str:
        return self._spec_name

    def set_tick_engine(self, engine: TickEngine) -> None:
        """Swap in an externally-owned TickEngine.

        Must be called *before* ``start``. The owner of the injected
        engine is responsible for calling ``engine.start`` / ``stop``.
        """
        if self._running:
            raise RuntimeError(
                "set_tick_engine must be called before start()"
            )
        self._tick_engine = engine
        self._owns_tick_engine = False

    async def start(self) -> None:
        if self._running:
            return
        self._tick_engine.register(
            TickSpec(
                name=self._spec_name,
                interval=self._interval,
                handler=self._tick_handler,
                jitter=self._jitter,
            )
        )
        if self._owns_tick_engine:
            await self._tick_engine.start()
        self._running = True
        logger.info(
            "CreatureStateDecayService started (interval=%ss±%ss, owned=%s)",
            self._interval,
            self._jitter,
            self._owns_tick_engine,
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._tick_engine.unregister(self._spec_name)
        if self._owns_tick_engine:
            await self._tick_engine.stop()
        logger.info("CreatureStateDecayService stopped")

    async def _tick_handler(self) -> None:
        try:
            character_ids = await self._provider.list_characters()
        except Exception:
            logger.exception("decay: list_characters failed")
            return
        for cid in character_ids:
            await self._tick_one(cid)

    async def _tick_one(self, character_id: str) -> None:
        try:
            await self._provider.tick(character_id, self._policy)
        except StateConflictError as e:
            # Pipeline persist won the race — the next scheduled tick
            # will re-read and try again.
            logger.debug(
                "decay: OCC conflict on %s (%s)", character_id, e
            )
        except Exception:
            logger.exception("decay: tick failed for %s", character_id)
