""":class:`EventSeedPool` — one-per-turn narrative hint picker.

Plan/04 §6.2 contract:

- Each seed declares a pure-boolean trigger
  ``(CreatureState, session_meta) -> bool`` plus a weight and a
  human-readable ``hint_text``.
- The pool evaluates every trigger at pick time and weighted-randomly
  picks ONE active seed (``None`` if nothing fires).
- Pick is non-deterministic by design — the plan's "예측 불가능성"
  layer — so the integration layer (PR-X4-5) rolls the pool's output
  into the persona cache key.

Policy — **never raises** (same stance as :class:`ManifestSelector`).
A seed whose trigger raises is logged at debug and treated as
"does not apply"; the pool continues with the rest. A buggy seed
must not brick a turn.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from backend.service.state.schema.creature_state import CreatureState

logger = logging.getLogger(__name__)


TriggerFn = Callable[[CreatureState, Mapping[str, Any]], bool]


@dataclass(frozen=True)
class EventSeed:
    """One narrative hint with a gate.

    Attributes:
        id: Stable identifier — used for logging, metrics, deterministic
            test assertions. Must be unique within a pool (the pool
            does not enforce this, but duplicate ids make diagnostics
            ambiguous).
        trigger: Pure function of ``(creature, meta)`` returning
            ``True`` when this seed is a candidate for this turn.
            Triggers must be side-effect-free — the pool may call them
            more than once across debugging tooling.
        hint_text: Short LLM-facing sentence surfaced via
            :class:`EventSeedBlock`. Written in English for
            consistency with the other CreatureState blocks; the LLM
            translates naturally at response time.
        weight: Relative pick probability among active seeds. Higher
            = more likely. ``weight <= 0.0`` means "never pick, even
            when active" — treated as zero and clamped so a negative
            doesn't silently invert a sibling's odds.
    """

    id: str
    trigger: TriggerFn
    hint_text: str
    weight: float = 1.0


class EventSeedPool:
    """Resolve at-most-one active seed per turn.

    Parameters
    ----------
    seeds:
        Iterable of :class:`EventSeed`. Snapshot-copied at construction
        (same pattern as :class:`ManifestSelector`) so callers can
        mutate their source collection without perturbing the pool.
    """

    def __init__(self, seeds: Sequence[EventSeed]) -> None:
        self._seeds: tuple[EventSeed, ...] = tuple(seeds)

    @property
    def seeds(self) -> tuple[EventSeed, ...]:
        """Immutable view of the pool's seeds (diagnostics / tests)."""
        return self._seeds

    def list_active(
        self,
        creature: CreatureState,
        meta: Mapping[str, Any],
    ) -> tuple[EventSeed, ...]:
        """All seeds whose trigger returns ``True`` — no random pick.

        Useful for tests and for an eventual "why this hint" diagnostic
        panel. Exceptions in a trigger are swallowed (see module
        docstring); this method never raises.
        """
        return tuple(self._evaluate(creature, meta))

    def pick(
        self,
        creature: CreatureState,
        meta: Mapping[str, Any],
        *,
        rng: random.Random | None = None,
    ) -> EventSeed | None:
        """Return one active seed or ``None``.

        When multiple seeds fire, picks one weighted-randomly using
        *rng* (defaults to the module-level random). All weights
        clamp to ``max(0.0, weight)`` — a non-positive total means the
        pool has active seeds but none "wants" to be picked, in which
        case we fall back to uniform random among the active set so a
        misconfigured zero-weight doesn't nullify a perfectly good
        trigger.
        """
        active = self._evaluate(creature, meta)
        if not active:
            return None
        chooser = rng if rng is not None else random
        return self._weighted_pick(active, chooser)

    # ── Internals ─────────────────────────────────────────────────────

    def _evaluate(
        self,
        creature: CreatureState,
        meta: Mapping[str, Any],
    ) -> list[EventSeed]:
        out: list[EventSeed] = []
        for seed in self._seeds:
            try:
                fired = bool(seed.trigger(creature, meta))
            except Exception:
                logger.debug(
                    "event seed %r trigger raised; skipping",
                    seed.id,
                    exc_info=True,
                )
                continue
            if fired:
                out.append(seed)
        return out

    @staticmethod
    def _weighted_pick(
        active: Sequence[EventSeed],
        chooser: Any,
    ) -> EventSeed:
        weights = [max(0.0, float(s.weight)) for s in active]
        total = sum(weights)
        if total <= 0.0:
            return chooser.choice(list(active))
        roll = chooser.random() * total
        acc = 0.0
        for seed, w in zip(active, weights):
            acc += w
            if roll < acc:
                return seed
        # Floating-point edge: if roll lands exactly at total due to
        # rounding, fall through to the last candidate.
        return active[-1]
