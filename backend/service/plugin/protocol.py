""":class:`GenyPlugin` — extension-surface bundle contract.

Cycle 20260422 X5 introduces :class:`GenyPlugin` as the named
Protocol that bundles Geny's existing extension surfaces (PromptBlock
/ Emitter / Tick / Tool / SessionLifecycleBus listener / attach_runtime
contribution) into a single module-shaped unit. See
``dev_docs/20260421_6/analysis/04_plugin_extensibility_and_proposed_extension_points.md §9``
for the rationale — specifically: **no 17th pipeline stage**. Plugins
compose by contributing to the seven surfaces Geny already exposes,
not by inserting new stages between existing ones.

Design pillars
--------------

- **Optional hooks.** Every ``contribute_*`` method is optional. A
  plugin implements only the surfaces it touches; the registry (PR-X5-2)
  uses ``getattr(plugin, "contribute_X", _empty)`` to read them, so a
  plugin that only adds PromptBlocks doesn't need to stub out empty
  emitter / tick / tool lists. :class:`PluginBase` provides the
  canonical no-op defaults for the typical inheritance path.
- **No side effects in ``contribute_*``.** Stateful setup (opening
  sockets, loading files, priming caches) happens in the plugin's
  ``__init__``, which runs at registry assembly time. Per-session
  contributions return values only — the registry fans them out to
  the right surfaces. This lets the registry call ``contribute_*``
  multiple times per session for diagnostics without surprising
  callers.
- **Registry-global vs. per-session contributions.** ``tickers`` and
  ``tools`` live for the life of the registry; ``prompt_blocks``,
  ``emitters``, ``attach_runtime`` are evaluated per-session with a
  :data:`SessionContext`. ``session_listeners`` is registry-global —
  the bus, not the session, owns subscriptions.
- **Duck-typing over ABC.** The Protocol is ``runtime_checkable`` so
  the registry can accept arbitrary objects that happen to implement
  the surface. The :class:`PluginBase` class is a convenience parent
  with no-op defaults; it is *not* required.

Out of scope for this PR
------------------------

PR-X5-1 introduces the contract *only*. Registry, loader, and
discovery land in PR-X5-2. Repackaging the existing X3/X4 features as
plugins lands in PR-X5-3.
"""

from __future__ import annotations

from typing import (
    Any,
    Awaitable,
    Callable,
    Mapping,
    Protocol,
    Sequence,
    Union,
    runtime_checkable,
)

# Imports below are only needed for type annotations. Keeping them
# runtime-available (not ``TYPE_CHECKING`` guarded) means an IDE or
# ``isinstance`` check in downstream plugin tests can resolve the
# annotation without jumping through hoops.
from geny_executor.stages.s03_system.interface import PromptBlock
from geny_executor.stages.s17_emit.interface import Emitter

from service.tick.engine import TickSpec

__all__ = [
    "GenyPlugin",
    "PluginBase",
    "SessionContext",
    "SessionListener",
]


SessionContext = Mapping[str, Any]
"""Per-session context handed to plugins during ``contribute_*`` calls.

A plain mapping rather than a rich dataclass — keeps the contract
unopinionated and lets the registry evolve the carried keys without
breaking plugin signatures. Expected keys (not enforced here; the
registry wraps the real :class:`PipelineState`'s ``shared`` dict
before calling):

- ``session_id`` (``str``) — opaque session identifier.
- ``character_id`` (``str``) — current character, if any.
- ``owner_user_id`` (``str``) — session owner.
- ``is_vtuber`` (``bool``) — role hint for plugins that differ by role.
- ``shared`` (``Mapping[str, Any]``) — read-only snapshot of
  ``state.shared`` (``creature_state``, ``session_meta`` …) where
  relevant.

Plugins MUST treat the mapping as read-only. Mutation semantics belong
to the surfaces themselves (MutationBuffer, state.shared writes during
stage execution), not to the ``contribute_*`` call path.
"""


SessionListener = Callable[..., Awaitable[None]]
"""Async callback shape for :class:`SessionLifecycleBus` listeners.

Kept as ``Callable[..., Awaitable[None]]`` because each bus event has
a different payload shape (``session.created``, ``session.resumed``,
``session.abandoned`` …). The bus's own dispatch code enforces the
signature at publish time; the plugin layer just hands over the
callback.
"""


@runtime_checkable
class GenyPlugin(Protocol):
    """Extension-surface bundle.

    Implementations typically inherit :class:`PluginBase` and override
    only the surfaces they touch. Direct structural-type implementers
    (dataclasses / plain classes with the right attributes) are also
    valid — :func:`isinstance` against this Protocol works because the
    Protocol is :func:`runtime_checkable`.

    Plugins are registered into a :class:`PluginRegistry` (PR-X5-2)
    whose discovery path may be explicit (``register(plugin)``) or
    entry-point based (``geny.plugins`` group). Once registered,
    contributions fan out:

    +-------------------------------+---------------------------------------+
    | Hook                          | Destination surface                   |
    +===============================+=======================================+
    | ``contribute_prompt_blocks``  | ``CharacterPersonaProvider.live_blocks`` (X1 PR-2, X4 PR-5) |
    | ``contribute_emitters``       | ``EmitterChain`` (executor s14)                             |
    | ``contribute_tickers``        | ``TickEngine.register`` (X2 PR-3)                           |
    | ``contribute_tools``          | ``ToolRegistry`` (executor tools layer)                     |
    | ``contribute_session_listeners`` | ``SessionLifecycleBus.subscribe`` (X2 PR-1)              |
    | ``contribute_attach_runtime`` | ``Pipeline.attach_runtime(**plugin_kwargs)`` (merged)       |
    +-------------------------------+---------------------------------------+
    """

    name: str
    """Stable, globally unique identifier — used for diagnostics and as
    the registry key. Plugins whose names collide are rejected at
    registration time (PR-X5-2)."""

    version: str
    """Free-form version string. MVP doesn't enforce SemVer — plugin
    authors pick a convention that works for their release cadence;
    the registry records it verbatim for diagnostics."""

    # Per-session contributions ------------------------------------------------

    def contribute_prompt_blocks(
        self, session_ctx: SessionContext,
    ) -> Sequence[PromptBlock]:
        """Prompt blocks appended after :class:`PersonaBlock` this session.

        Blocks are rendered lazily by the PersonaProvider and may
        inspect ``state.shared`` at render time — this hook only picks
        *which* blocks apply to this session (role / character /
        feature flag gating).
        """
        ...

    def contribute_emitters(
        self, session_ctx: SessionContext,
    ) -> Sequence[Emitter]:
        """s14 emitters active this session.

        Emitters are stateful per-session; ``contribute_emitters`` is
        expected to return fresh instances (or a tuple of cached
        stateless ones) each call.
        """
        ...

    def contribute_attach_runtime(
        self, session_ctx: SessionContext,
    ) -> Mapping[str, Any]:
        """Extra kwargs merged into :meth:`Pipeline.attach_runtime`.

        Bridges plugin-provided services (a ``CreatureStateProvider``,
        a custom memory store, …) into stage execution. The registry
        merges all plugins' maps before calling ``attach_runtime``
        — conflicting keys raise at registry time (PR-X5-2); plugins
        must namespace their keys.
        """
        ...

    # Registry-global contributions --------------------------------------------

    def contribute_tickers(self) -> Sequence[TickSpec]:
        """Tickers registered with :class:`TickEngine` at startup.

        :class:`TickSpec` carries its own name which doubles as the
        registry key inside the engine — ``contribute_tickers``
        returning duplicates across plugins is caught by the engine's
        own uniqueness guard, but plugin authors should prefix names
        with their plugin name (``tamagotchi.decay``) to avoid
        accidental clashes.
        """
        ...

    def contribute_tools(self) -> Sequence[Any]:
        """Tools registered with the executor's :class:`ToolRegistry`.

        Typed as ``Sequence[Any]`` because ``geny_executor.tools.Tool``
        is an ABC whose concrete shapes vary (sync / async / adaptive)
        and the registry already accepts the broader interface; a
        tighter annotation here would force every plugin test to
        import the executor's Tool class even when unused.
        """
        ...

    def contribute_session_listeners(
        self,
    ) -> Mapping[str, SessionListener]:
        """Session-lifecycle bus subscriptions.

        The returned mapping is ``event_name → async callback`` — the
        :class:`SessionLifecycleBus` (X2 PR-1) already supports
        multi-subscriber fanout so plugins don't need to worry about
        overwriting each other's listeners. Names follow the bus's
        existing vocabulary (``session.created``, ``session.resumed``,
        ``session.abandoned``, …).
        """
        ...


# ── PluginBase — canonical no-op defaults ───────────────────────────────


def _empty_sequence() -> Sequence[Any]:
    return ()


def _empty_mapping() -> Mapping[str, Any]:
    return {}


class PluginBase:
    """Convenience parent with no-op defaults for every optional hook.

    Inherit and override only the surfaces you contribute to; the
    registry will see empty lists for the rest.

    ``name`` and ``version`` remain **required** — subclasses must set
    them as class attributes or in ``__init__``. The Protocol can't
    default these because a plugin without a stable name is a bug the
    registry can't paper over.

    Example
    -------

    ::

        class TamagotchiPlugin(PluginBase):
            name = "tamagotchi"
            version = "0.1.0"

            def contribute_prompt_blocks(self, session_ctx):
                return (MoodBlock(), VitalsBlock(), RelationshipBlock())

            def contribute_tickers(self):
                return (TickSpec(name="tamagotchi.decay", ...),)
    """

    name: str
    version: str

    def contribute_prompt_blocks(
        self, session_ctx: SessionContext,
    ) -> Sequence[PromptBlock]:
        return _empty_sequence()

    def contribute_emitters(
        self, session_ctx: SessionContext,
    ) -> Sequence[Emitter]:
        return _empty_sequence()

    def contribute_attach_runtime(
        self, session_ctx: SessionContext,
    ) -> Mapping[str, Any]:
        return _empty_mapping()

    def contribute_tickers(self) -> Sequence[TickSpec]:
        return _empty_sequence()

    def contribute_tools(self) -> Sequence[Any]:
        return _empty_sequence()

    def contribute_session_listeners(
        self,
    ) -> Mapping[str, SessionListener]:
        return _empty_mapping()


# Backward-compatible alias for tests / docs that import via the
# package root. Keeps the protocol module name ``protocol`` distinct
# from the public symbol ``GenyPlugin``.
PluginLike = Union[GenyPlugin, PluginBase]
