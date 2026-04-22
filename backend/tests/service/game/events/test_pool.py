"""Unit tests for :class:`EventSeedPool`.

Covers four invariants for plan/04 §6.2:

1. **Empty / no-active → None.** A pool with no seeds, or a pool whose
   every trigger returns ``False``, returns ``None`` from ``pick`` and
   an empty tuple from ``list_active``.
2. **Weighted pick with a seeded RNG is reproducible.** Given the same
   seeded :class:`random.Random`, two identical pools produce the same
   pick. Required for deterministic debugging and persona cache_key
   stability.
3. **Exceptions in triggers don't brick the pool.** A buggy seed is
   logged at debug and skipped; the rest of the pool still picks.
4. **Zero / negative weights don't steer the pick incorrectly.** A
   zero-weight active seed is effectively invisible; a pool where every
   active seed has zero weight falls back to uniform random (never
   returns ``None`` just because weights summed to zero).
"""

from __future__ import annotations

import random

import pytest


def _blank_creature():
    from backend.service.state.schema.creature_state import CreatureState

    return CreatureState(character_id="c1", owner_user_id="u1")


# ── Empty / no-active ──────────────────────────────────────────────────


def test_empty_pool_returns_none() -> None:
    from backend.service.game.events import EventSeedPool

    pool = EventSeedPool([])
    assert pool.pick(_blank_creature(), {}) is None
    assert pool.list_active(_blank_creature(), {}) == ()


def test_pool_with_no_active_seeds_returns_none() -> None:
    from backend.service.game.events import EventSeed, EventSeedPool

    pool = EventSeedPool(
        [
            EventSeed("a", lambda cs, m: False, "hint a"),
            EventSeed("b", lambda cs, m: False, "hint b"),
        ]
    )
    assert pool.pick(_blank_creature(), {}) is None
    assert pool.list_active(_blank_creature(), {}) == ()


def test_single_active_seed_is_always_picked() -> None:
    from backend.service.game.events import EventSeed, EventSeedPool

    only = EventSeed("only", lambda cs, m: True, "hint only")
    pool = EventSeedPool([only])
    rng = random.Random(42)

    for _ in range(10):
        assert pool.pick(_blank_creature(), {}, rng=rng) is only


def test_list_active_returns_only_firing_seeds() -> None:
    from backend.service.game.events import EventSeed, EventSeedPool

    a = EventSeed("a", lambda cs, m: True, "hint a")
    b = EventSeed("b", lambda cs, m: False, "hint b")
    c = EventSeed("c", lambda cs, m: True, "hint c")

    pool = EventSeedPool([a, b, c])
    active = pool.list_active(_blank_creature(), {})

    assert tuple(s.id for s in active) == ("a", "c")


# ── Determinism under seeded RNG ──────────────────────────────────────


def test_weighted_pick_is_reproducible_under_same_seed() -> None:
    from backend.service.game.events import EventSeed, EventSeedPool

    seeds = [
        EventSeed("low", lambda cs, m: True, "low", weight=1.0),
        EventSeed("high", lambda cs, m: True, "high", weight=4.0),
    ]
    pool_a = EventSeedPool(seeds)
    pool_b = EventSeedPool(seeds)

    rng_a = random.Random(7)
    rng_b = random.Random(7)
    picks_a = [pool_a.pick(_blank_creature(), {}, rng=rng_a).id for _ in range(20)]
    picks_b = [pool_b.pick(_blank_creature(), {}, rng=rng_b).id for _ in range(20)]

    assert picks_a == picks_b


def test_heavier_weight_wins_the_long_run() -> None:
    """80:20 weight split should bias distribution clearly over 500 trials
    (≥ 60% heavier). Uses a seeded RNG so the test is deterministic."""
    from backend.service.game.events import EventSeed, EventSeedPool

    light = EventSeed("light", lambda cs, m: True, "light", weight=1.0)
    heavy = EventSeed("heavy", lambda cs, m: True, "heavy", weight=4.0)
    pool = EventSeedPool([light, heavy])
    rng = random.Random(1)

    counts = {"light": 0, "heavy": 0}
    for _ in range(500):
        counts[pool.pick(_blank_creature(), {}, rng=rng).id] += 1

    assert counts["heavy"] >= 300, counts
    assert counts["light"] >= 50, counts


def test_seeds_snapshot_immutable_after_construction() -> None:
    """Caller's list mutation after construction must not change the
    pool's behaviour — matches ManifestSelector's snapshot stance."""
    from backend.service.game.events import EventSeed, EventSeedPool

    a = EventSeed("a", lambda cs, m: True, "hint a")
    b = EventSeed("b", lambda cs, m: True, "hint b")
    seeds = [a, b]

    pool = EventSeedPool(seeds)
    seeds.clear()
    seeds.append(EventSeed("c", lambda cs, m: True, "hint c"))

    assert tuple(s.id for s in pool.seeds) == ("a", "b")
    active_ids = {s.id for s in pool.list_active(_blank_creature(), {})}
    assert active_ids == {"a", "b"}


def test_seeds_property_returns_tuple() -> None:
    from backend.service.game.events import EventSeed, EventSeedPool

    pool = EventSeedPool([EventSeed("x", lambda cs, m: False, "x")])
    assert isinstance(pool.seeds, tuple)


# ── Exceptions don't brick the pool ───────────────────────────────────


def test_trigger_exception_is_swallowed_and_pool_continues() -> None:
    from backend.service.game.events import EventSeed, EventSeedPool

    def boom(cs, m):
        raise RuntimeError("trigger blew up")

    bad = EventSeed("bad", boom, "bad hint")
    good = EventSeed("good", lambda cs, m: True, "good hint")

    pool = EventSeedPool([bad, good])
    rng = random.Random(0)

    picked = pool.pick(_blank_creature(), {}, rng=rng)
    assert picked is good

    active = pool.list_active(_blank_creature(), {})
    assert tuple(s.id for s in active) == ("good",)


def test_all_triggers_raising_returns_none() -> None:
    from backend.service.game.events import EventSeed, EventSeedPool

    def boom(cs, m):
        raise ValueError()

    pool = EventSeedPool([EventSeed(f"b{i}", boom, f"h{i}") for i in range(3)])
    assert pool.pick(_blank_creature(), {}) is None


# ── Zero / negative weights ───────────────────────────────────────────


def test_negative_weight_clamps_to_zero_and_doesnt_invert_odds() -> None:
    """A -5.0 weight must not mean "pick 5× more often inverted" — it
    should clamp to 0.0 so the other candidate always wins."""
    from backend.service.game.events import EventSeed, EventSeedPool

    good = EventSeed("good", lambda cs, m: True, "good", weight=1.0)
    broken = EventSeed("broken", lambda cs, m: True, "broken", weight=-5.0)
    pool = EventSeedPool([good, broken])
    rng = random.Random(3)

    ids = {pool.pick(_blank_creature(), {}, rng=rng).id for _ in range(30)}
    assert ids == {"good"}


def test_all_zero_weight_active_seeds_falls_back_to_uniform_pick() -> None:
    """A zero-weight pool is arguably misconfigured, but it should still
    pick SOMETHING rather than silently return None — absent a pick,
    the turn gets no hint at all and that's worse UX than a random
    hint."""
    from backend.service.game.events import EventSeed, EventSeedPool

    a = EventSeed("a", lambda cs, m: True, "a", weight=0.0)
    b = EventSeed("b", lambda cs, m: True, "b", weight=0.0)
    pool = EventSeedPool([a, b])
    rng = random.Random(9)

    ids = {pool.pick(_blank_creature(), {}, rng=rng).id for _ in range(30)}
    assert ids == {"a", "b"}


# ── API shape ─────────────────────────────────────────────────────────


def test_event_seed_is_frozen() -> None:
    """EventSeed must be frozen — triggers / weights are declarative, a
    tree author mutating an instance would introduce spooky action at
    a distance."""
    from backend.service.game.events import EventSeed

    seed = EventSeed("a", lambda cs, m: True, "a")
    with pytest.raises(Exception):
        seed.weight = 999  # type: ignore[misc]


def test_pick_rng_default_uses_module_random(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``rng=None`` the pool falls back to the module ``random``
    module — verified by patching its ``random`` call and catching
    it."""
    from backend.service.game.events import EventSeed, EventSeedPool
    from backend.service.game.events import pool as pool_module

    calls: list[None] = []

    def fake_random():
        calls.append(None)
        return 0.5

    monkeypatch.setattr(pool_module.random, "random", fake_random)

    seeds = [
        EventSeed("a", lambda cs, m: True, "a", weight=1.0),
        EventSeed("b", lambda cs, m: True, "b", weight=1.0),
    ]
    picked = EventSeedPool(seeds).pick(_blank_creature(), {})
    assert picked is not None
    assert calls, "default rng must be the stdlib random module"
