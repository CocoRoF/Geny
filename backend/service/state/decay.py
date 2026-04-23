"""Time-based decay for ``CreatureState`` (plan/02 §5).

Decay is a **pure function** on a snapshot — no provider IO here. The
service wrapper (:class:`CreatureStateDecayService`) and the
``SessionRuntimeRegistry`` catch-up path orchestrate *when* to call it;
they read snapshots through the provider and write new snapshots back.

Design notes:

- ``apply_decay`` deep-copies its input. Callers may hold the original
  snapshot (OCC token, etc.) without worrying about it changing.
- Only numeric paths are supported — rules that target non-numeric or
  non-existent fields raise ``TypeError`` / ``KeyError`` at apply time
  rather than being silently skipped.
- ``last_tick_at`` is bumped to ``now`` unconditionally. Even a
  zero-elapsed apply advances the clock, so subsequent calls compute
  *their* elapsed from the new tick boundary.
- Negative elapsed (clock skew) clamps to 0 — we never *reverse* decay.
- ``_row_version`` (attached by sqlite provider ``load``) is preserved
  onto the returned state so the caller can still OCC an update.

``DEFAULT_DECAY`` matches plan §5.2. Affection / trust / dependency
deliberately do **not** decay — what the user built up is durable.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from .schema.creature_state import CHARACTER_ROLE_VTUBER, CreatureState


# Hydrate-side catch-up threshold: if a user returns after this long,
# the registry kicks a single tick before stages see the snapshot so
# vitals reflect the wall-clock delta. TickEngine still runs its own
# 15-min cadence — catch-up just bridges user-visible gaps.
CATCHUP_THRESHOLD = timedelta(minutes=30)


@dataclass(frozen=True)
class DecayRule:
    """One decay term — a numeric path drifting at ``rate_per_hour``.

    Two operating modes:

    * **Linear drift** (default, ``regress_to is None``): the value
      changes by ``rate_per_hour * elapsed_hours`` per tick. ``rate``
      is signed — positive grows the target (``hunger`` → starving),
      negative shrinks it (``energy`` → exhausted).
    * **Regression to target** (``regress_to`` set, Plan/Phase03 §3.1):
      the value is *pulled toward* ``regress_to`` with magnitude
      ``|rate_per_hour| * elapsed_hours`` per tick, never overshooting.
      Used for ``mood.*`` axes which must drift back to a neutral
      equilibrium so emotions don't fixate. ``rate_per_hour``'s sign
      is ignored in this mode — only its magnitude controls the pull
      strength.

    Results are clamped to ``[clamp_min, clamp_max]``.
    """

    path: str
    rate_per_hour: float
    clamp_min: float = 0.0
    clamp_max: float = 100.0
    regress_to: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("DecayRule.path must be non-empty")
        if self.clamp_min > self.clamp_max:
            raise ValueError(
                "DecayRule.clamp_min must be <= clamp_max "
                f"(got {self.clamp_min} > {self.clamp_max})"
            )


@dataclass(frozen=True)
class DecayPolicy:
    rules: Tuple[DecayRule, ...]

    def __post_init__(self) -> None:
        seen = set()
        for r in self.rules:
            if r.path in seen:
                raise ValueError(
                    f"DecayPolicy has duplicate rule for path {r.path!r}"
                )
            seen.add(r.path)


DEFAULT_DECAY = DecayPolicy(rules=(
    # Plan/Phase01 §3.1 — hunger now models *attention deprivation*
    # rather than physical hunger. Recovery happens on every user
    # message via the attention_recovery hook in AgentSession, so the
    # passive drift is dialed down from +2.5 → +1.0 to keep the
    # equilibrium roughly the same for an active user (~30 min/day).
    DecayRule("vitals.hunger", +1.0),       # ~100h unattended → attended to craving
    DecayRule("vitals.energy", -1.5),       # fatigue accumulates
    DecayRule("vitals.cleanliness", -1.0),
    DecayRule("vitals.stress", +0.5),
    DecayRule("bond.familiarity", -0.1),    # very slow forgetting

    # Plan/Phase03 §3.1 — mood natural drift. Each basic emotion is
    # pulled back to 0 (neutral) so a transient spike doesn't stay
    # pinned at 1.0 forever; ``calm`` is pulled toward 0.5 so the
    # baseline is "mildly composed" rather than "deeply tranquil".
    # Magnitudes per plan §3.1: anger/excitement decay fastest
    # (intense emotions burn out), sadness slowest (lingers), joy/fear
    # in the middle. The clamp [0.0, 1.0] is critical because mood is
    # an EMA-style distribution — values outside that range break the
    # ``dominant()`` contract.
    DecayRule("mood.joy",
              rate_per_hour=-0.15, clamp_min=0.0, clamp_max=1.0,
              regress_to=0.0),
    DecayRule("mood.sadness",
              rate_per_hour=-0.10, clamp_min=0.0, clamp_max=1.0,
              regress_to=0.0),
    DecayRule("mood.anger",
              rate_per_hour=-0.20, clamp_min=0.0, clamp_max=1.0,
              regress_to=0.0),
    DecayRule("mood.fear",
              rate_per_hour=-0.15, clamp_min=0.0, clamp_max=1.0,
              regress_to=0.0),
    DecayRule("mood.excitement",
              rate_per_hour=-0.20, clamp_min=0.0, clamp_max=1.0,
              regress_to=0.0),
    DecayRule("mood.calm",
              rate_per_hour=+0.05, clamp_min=0.0, clamp_max=1.0,
              regress_to=0.5),
))


def _read_path(state: CreatureState, path: str) -> float:
    parts = path.split(".")
    obj = state
    for p in parts:
        if not hasattr(obj, p):
            raise KeyError(f"unknown path segment {p!r} in {path!r}")
        obj = getattr(obj, p)
    if not isinstance(obj, (int, float)):
        raise TypeError(
            f"decay target {path!r} must be numeric, got {type(obj).__name__}"
        )
    return float(obj)


def _write_path(state: CreatureState, path: str, value: float) -> None:
    parts = path.split(".")
    obj = state
    for p in parts[:-1]:
        obj = getattr(obj, p)
    setattr(obj, parts[-1], value)


def apply_decay(
    state: CreatureState,
    policy: DecayPolicy,
    *,
    now: datetime | None = None,
) -> CreatureState:
    """Return a new ``CreatureState`` with time-based decay applied.

    The input ``state`` is never mutated. If the policy has no rules
    or elapsed is non-positive, the returned state is still a fresh
    copy with ``last_tick_at`` bumped — the tick boundary always
    advances so the next call computes elapsed from *here*.
    """
    now = now or datetime.now(timezone.utc)
    elapsed_seconds = (now - state.last_tick_at).total_seconds()
    elapsed_hours = max(0.0, elapsed_seconds / 3600.0)

    new_state = copy.deepcopy(state)
    # Plan/Phase04 §2.4 — VTuber-only gate. Worker / planner creatures
    # share the same dataclass shape but must NOT see vitals drift
    # (their "vitals" are meaningless and would only confuse downstream
    # prompts). Bump the tick boundary so the next call computes elapsed
    # from here, but skip the rule loop. Putting the guard inside the
    # pure function means *both* call paths (decay service tick AND
    # registry catch-up) inherit it without duplication.
    role = getattr(state, "character_role", CHARACTER_ROLE_VTUBER)
    if role != CHARACTER_ROLE_VTUBER:
        new_state.last_tick_at = now
        token = getattr(state, "_row_version", None)
        if token is not None:
            setattr(new_state, "_row_version", token)
        return new_state

    if elapsed_hours > 0:
        for rule in policy.rules:
            current = _read_path(new_state, rule.path)
            if rule.regress_to is not None:
                # Plan/Phase03 §3.1 — pull-toward-target mode. The pull
                # magnitude per tick is |rate| * elapsed_hours, but
                # never overshoots the target — once we hit ``regress_to``
                # the value sits there. ``rate``'s sign is ignored: only
                # its magnitude controls how *fast* we drift.
                diff = rule.regress_to - current
                if diff == 0.0:
                    continue
                step_max = abs(rule.rate_per_hour) * elapsed_hours
                if abs(diff) <= step_max:
                    drifted = rule.regress_to
                else:
                    direction = 1.0 if diff > 0 else -1.0
                    drifted = current + direction * step_max
            else:
                drifted = current + rule.rate_per_hour * elapsed_hours
            if drifted < rule.clamp_min:
                drifted = rule.clamp_min
            elif drifted > rule.clamp_max:
                drifted = rule.clamp_max
            _write_path(new_state, rule.path, drifted)
    new_state.last_tick_at = now

    # Preserve OCC token if the source state carried one (sqlite load()
    # attaches ``_row_version``). ``copy.deepcopy`` copies regular
    # attributes but this one is set via ``setattr`` after construction
    # so it doesn't live in __init__ — we re-attach defensively.
    token = getattr(state, "_row_version", None)
    if token is not None:
        setattr(new_state, "_row_version", token)
    return new_state
