"""MoodVector — 6-dim emotional state with EMA and dominant-emotion lookup.

Lives separately from ``creature_state.py`` because:

- Emotion-extraction code paths already exist and should share this type.
- Other domains (persona, logging) want a compact mood representation.
- Attaches its own utilities (EMA update, dominant-key lookup) without
  bloating ``CreatureState``.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Iterable


@dataclass
class MoodVector:
    joy: float = 0.0
    sadness: float = 0.0
    anger: float = 0.0
    fear: float = 0.0
    calm: float = 0.5
    excitement: float = 0.0

    @classmethod
    def keys(cls) -> tuple[str, ...]:
        return tuple(f.name for f in fields(cls))

    def as_dict(self) -> dict[str, float]:
        return {k: float(getattr(self, k)) for k in self.keys()}

    def ema(self, other: "MoodVector", alpha: float) -> "MoodVector":
        """Return a new vector blending ``self`` toward ``other``.

        ``alpha`` in [0.0, 1.0]; 0 keeps self, 1 returns other.
        Clamped to the unit range because unbounded EMA on out-of-range
        inputs would amplify noise from upstream extractors.
        """
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be in [0, 1]")
        return MoodVector(
            **{
                k: (1.0 - alpha) * getattr(self, k) + alpha * getattr(other, k)
                for k in self.keys()
            }
        )

    def dominant(self, *, threshold: float = 0.30) -> str:
        """Return the name of the strongest emotion above ``threshold``.

        If no basic emotion (joy/excitement/anger/fear/sadness) exceeds
        the threshold, returns ``"calm"`` regardless of the stored
        ``calm`` value — neutral mood is the fallback.

        Plan/Phase03 §3.5 — the default threshold was raised from 0.15
        to 0.30 so weak transient noise in the EMA doesn't flip the
        reported dominant emotion every turn (the symptom from the
        screenshot in the plan: joy=excitement=calm all near the cap,
        dominant flickering between them). Iteration order is the
        explicit tie-breaker — when two basic emotions are *exactly*
        equal, the first one in the canonical list wins. The
        ``+ 1e-9`` slack on the comparison guards against
        floating-point round-trip causing the same input to flip
        dominants between runs.
        """
        # Canonical priority order (Plan/Phase03 §3.5): outward-facing
        # emotions before inward-facing ones, so a true tie surfaces
        # the more legible one.
        basic: Iterable[str] = ("joy", "excitement", "anger", "fear", "sadness")
        best_key = None
        best_val = -1.0
        for k in basic:
            v = getattr(self, k)
            if v > best_val + 1e-9:
                best_val = v
                best_key = k
        if best_key is None or best_val <= threshold:
            return "calm"
        return best_key
