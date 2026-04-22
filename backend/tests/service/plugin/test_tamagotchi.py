""":class:`TamagotchiPlugin` — X5-3 repackaging of the X3/X4 live-block
bundle.

Covers the plugin's own surface plus the behavioural invariants
callers depend on: the four known block types appear in the documented
order, the seed pool is the DEFAULT_SEEDS catalogue by default, and
the plugin is accepted by :class:`PluginRegistry` and fans out via
``collect_prompt_blocks``.
"""

from __future__ import annotations

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

from service.plugin import (
    GenyPlugin,
    PluginRegistry,
    TamagotchiPlugin,
)


def test_tamagotchi_plugin_satisfies_protocol() -> None:
    plugin = TamagotchiPlugin()
    assert isinstance(plugin, GenyPlugin)
    assert plugin.name == "tamagotchi"
    assert plugin.version  # non-empty


def test_contribute_prompt_blocks_returns_live_blocks_in_order() -> None:
    plugin = TamagotchiPlugin()
    blocks = plugin.contribute_prompt_blocks({})
    assert [type(b) for b in blocks] == [
        MoodBlock,
        VitalsBlock,
        RelationshipBlock,
        ProgressionBlock,
        AcclimationBlock,
    ]


def test_contribute_prompt_blocks_returns_fresh_instances_per_call() -> None:
    """Plugin contract says contribute_* should be side-effect-free
    and safe to call repeatedly. Blocks are stateless, so freshly
    minted per call is fine — but two calls must not hand back the
    same instances (which would let a cached render mutation leak
    across sessions)."""
    plugin = TamagotchiPlugin()
    a = plugin.contribute_prompt_blocks({})
    b = plugin.contribute_prompt_blocks({})
    assert [type(x) for x in a] == [type(x) for x in b]
    # Each call yields fresh instances.
    for x, y in zip(a, b):
        assert x is not y


def test_event_seed_pool_exposes_default_catalogue() -> None:
    plugin = TamagotchiPlugin()
    pool = plugin.event_seed_pool
    assert isinstance(pool, EventSeedPool)
    # The pool was constructed from DEFAULT_SEEDS (8 seeds).
    # We can't inspect pool internals without API, but pick() on a
    # minimal creature/meta must not raise, confirming the pool is live.
    from dataclasses import dataclass

    @dataclass
    class _MinimalCreature:
        affection: float = 0.0
        stress: float = 0.0

    # pick never raises per the pool contract; empty-match is a valid
    # outcome and returns None.
    result = pool.pick(_MinimalCreature(), {"gap_since_last_turn_seconds": 0})
    assert result is None or hasattr(result, "hint_text")


def test_event_seed_pool_accepts_custom_seed_catalogue() -> None:
    custom_seed = EventSeed(
        id="custom.one",
        trigger=lambda creature, meta: True,
        hint_text="custom hint",
        weight=1.0,
    )
    plugin = TamagotchiPlugin(event_seeds=(custom_seed,))
    pool = plugin.event_seed_pool
    assert isinstance(pool, EventSeedPool)
    # pick may return the custom seed or None depending on rng — we
    # just confirm it doesn't raise.
    pool.pick(object(), {})


def test_unused_hooks_inherit_pluginbase_defaults() -> None:
    plugin = TamagotchiPlugin()
    assert tuple(plugin.contribute_emitters({})) == ()
    assert dict(plugin.contribute_attach_runtime({})) == {}
    assert tuple(plugin.contribute_tickers()) == ()
    assert tuple(plugin.contribute_tools()) == ()
    assert dict(plugin.contribute_session_listeners()) == {}


def test_tamagotchi_plugin_in_registry_fans_out_blocks() -> None:
    reg = PluginRegistry()
    reg.register(TamagotchiPlugin())

    blocks = reg.collect_prompt_blocks({})
    assert [type(b) for b in blocks] == [
        MoodBlock,
        VitalsBlock,
        RelationshipBlock,
        ProgressionBlock,
        AcclimationBlock,
    ]


def test_default_seeds_count_is_eight() -> None:
    """Pin the catalogue size — if DEFAULT_SEEDS changes, this forces
    a review of plugin behaviour rather than silent drift."""
    assert len(DEFAULT_SEEDS) == 8
