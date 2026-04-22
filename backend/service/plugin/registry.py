""":class:`PluginRegistry` — collects :class:`GenyPlugin` instances and
fans their contributions out to the existing extension surfaces.

PR-X5-2 follows the "registry knows surfaces; plugins don't know each
other" principle from
``dev_docs/20260421_6/analysis/04_plugin_extensibility_and_proposed_extension_points.md §9``.

What this module ships
----------------------

- :class:`PluginRegistry.register` — explicit registration. Duplicate
  plugin ``name`` raises; "first wins" is deliberately *not* the policy
  because silent replacement is the hardest bug class to diagnose.
- ``collect_*`` methods — per-hook aggregation across all registered
  plugins. The registry returns flat sequences / merged mappings; it
  does *not* touch surfaces itself. Callers (``AgentSessionManager`` in
  PR-X5-3) feed these values into :class:`CharacterPersonaProvider`,
  :class:`Pipeline.attach_runtime`, s14 :class:`EmitterChain`, etc.
- ``apply_tickers`` / ``apply_session_listeners`` — convenience helpers
  for the two registry-global surfaces (:class:`TickEngine` /
  :class:`SessionLifecycleBus`) that have a clean direct-register API
  today. Per-session surfaces stay as ``collect_*`` — the session
  builder owns their wiring so the registry doesn't need to know about
  :class:`PipelineState` or the provider constructor.

Out of scope for this PR
------------------------

- **Entry-point discovery.** MVP is explicit ``register(plugin)`` only.
  ``geny.plugins`` entry-point loader lands in X6 if wanted.
- **Repackaging X3/X4 bundles as plugins.** PR-X5-3.
- **Hot-reload / unregister.** Unnecessary; the registry is assembled
  once at application startup.
- **Tool live-registration wiring.** The executor's tool registry is
  manifest-driven today. ``collect_tools`` returns the flat sequence so
  PR-X5-3 (or a later tool-registry refresh) can decide how to wire it
  in without churning this PR.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Sequence

from geny_executor.stages.s03_system.interface import PromptBlock
from geny_executor.stages.s14_emit.interface import Emitter

from backend.service.lifecycle.bus import SessionLifecycleBus
from backend.service.lifecycle.events import LifecycleEvent
from backend.service.tick.engine import TickEngine, TickSpec

from .protocol import GenyPlugin, SessionContext, SessionListener

logger = logging.getLogger(__name__)

__all__ = [
    "PluginRegistry",
    "DuplicatePluginError",
    "AttachRuntimeKeyConflict",
    "UnknownLifecycleEventError",
]


class DuplicatePluginError(ValueError):
    """Two plugins tried to register with the same :attr:`name`."""


class AttachRuntimeKeyConflict(ValueError):
    """Two plugins contributed the same ``attach_runtime`` kwarg name.

    The registry refuses to pick a winner because the merged mapping
    flows into :meth:`Pipeline.attach_runtime` and a silent overwrite
    would mask an integration bug. Plugins must namespace their keys
    (e.g. ``tamagotchi_state_provider`` rather than ``state_provider``).
    """


class UnknownLifecycleEventError(ValueError):
    """A plugin named a lifecycle event that isn't in
    :class:`LifecycleEvent`.

    Unlike the name/key collisions above we could log-and-skip here,
    but raising is consistent — a typo'd event name silently not firing
    is exactly the "silently wrong" class of bug ``register`` also
    guards against.
    """


class PluginRegistry:
    """Ordered bundle of :class:`GenyPlugin` instances with fan-out
    helpers.

    Registration order is preserved and drives iteration order in every
    ``collect_*`` method — plugin authors who care about (for example)
    prompt block placement can rely on "register A then B" meaning
    "A's blocks come before B's". The registry does *not* try to
    topologically sort by some declared dependency graph; MVP callers
    register in application startup code, so the lexical order there is
    the contract.
    """

    def __init__(self) -> None:
        self._plugins: List[GenyPlugin] = []
        self._names: Dict[str, GenyPlugin] = {}

    # ── Registration ──────────────────────────────────────────────────

    def register(self, plugin: GenyPlugin) -> None:
        """Add ``plugin`` to the registry.

        Validates that the object structurally implements the
        :class:`GenyPlugin` Protocol and that its ``name`` is unique.
        """
        if not isinstance(plugin, GenyPlugin):
            raise TypeError(
                f"{plugin!r} does not implement the GenyPlugin Protocol "
                "(missing name/version or contribute_* hook)"
            )
        name = plugin.name
        if not name:
            raise ValueError(
                f"{plugin!r} has an empty name; plugins need a stable "
                "non-empty identifier"
            )
        if name in self._names:
            existing = self._names[name]
            raise DuplicatePluginError(
                f"plugin name {name!r} is already registered "
                f"(existing version={existing.version!r}, "
                f"new version={plugin.version!r})"
            )
        self._names[name] = plugin
        self._plugins.append(plugin)

    @property
    def plugins(self) -> Sequence[GenyPlugin]:
        """Read-only snapshot of registered plugins in registration
        order."""
        return tuple(self._plugins)

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._names

    def get(self, name: str) -> GenyPlugin:
        return self._names[name]

    # ── Per-session collection ────────────────────────────────────────

    def collect_prompt_blocks(
        self, session_ctx: SessionContext,
    ) -> Sequence[PromptBlock]:
        out: List[PromptBlock] = []
        for plugin in self._plugins:
            out.extend(plugin.contribute_prompt_blocks(session_ctx))
        return tuple(out)

    def collect_emitters(
        self, session_ctx: SessionContext,
    ) -> Sequence[Emitter]:
        out: List[Emitter] = []
        for plugin in self._plugins:
            out.extend(plugin.contribute_emitters(session_ctx))
        return tuple(out)

    def collect_attach_runtime(
        self, session_ctx: SessionContext,
    ) -> Mapping[str, Any]:
        """Merge every plugin's ``contribute_attach_runtime`` into one
        dict.

        Raises :class:`AttachRuntimeKeyConflict` if two plugins
        contribute the same key — the registry refuses silent overwrite
        so integration bugs surface loudly.
        """
        merged: Dict[str, Any] = {}
        owner_of: Dict[str, str] = {}
        for plugin in self._plugins:
            contribution = plugin.contribute_attach_runtime(session_ctx)
            for key, value in contribution.items():
                if key in merged:
                    raise AttachRuntimeKeyConflict(
                        f"attach_runtime key {key!r} contributed by both "
                        f"{owner_of[key]!r} and {plugin.name!r}; "
                        "plugins must namespace their kwargs"
                    )
                merged[key] = value
                owner_of[key] = plugin.name
        return merged

    # ── Registry-global collection ────────────────────────────────────

    def collect_tickers(self) -> Sequence[TickSpec]:
        out: List[TickSpec] = []
        for plugin in self._plugins:
            out.extend(plugin.contribute_tickers())
        return tuple(out)

    def collect_tools(self) -> Sequence[Any]:
        out: List[Any] = []
        for plugin in self._plugins:
            out.extend(plugin.contribute_tools())
        return tuple(out)

    def collect_session_listeners(
        self,
    ) -> Mapping[LifecycleEvent, Sequence[SessionListener]]:
        """Aggregate session-listener contributions by lifecycle event.

        Plugin hooks return ``Mapping[str, SessionListener]`` — the
        string keys are validated against :class:`LifecycleEvent` here
        so an unknown name raises at registry assembly rather than
        silently missing publish fanout at runtime.
        """
        buckets: Dict[LifecycleEvent, List[SessionListener]] = {
            ev: [] for ev in LifecycleEvent
        }
        for plugin in self._plugins:
            contribution = plugin.contribute_session_listeners()
            for event_name, listener in contribution.items():
                event = _coerce_event(event_name, plugin_name=plugin.name)
                buckets[event].append(listener)
        return {ev: tuple(listeners) for ev, listeners in buckets.items()}

    # ── Apply helpers (registry-global surfaces) ──────────────────────

    def apply_tickers(self, engine: TickEngine) -> None:
        """Register every plugin-contributed :class:`TickSpec` with
        ``engine``.

        The engine's own ``register`` raises :class:`ValueError` on
        duplicate ticker names — plugins should namespace (e.g.
        ``tamagotchi.decay``) to avoid clashes across bundles.
        """
        for spec in self.collect_tickers():
            engine.register(spec)

    def apply_session_listeners(self, bus: SessionLifecycleBus) -> None:
        """Subscribe every plugin-contributed listener to ``bus``.

        Subscription tokens are not retained — the registry is assumed
        to outlive the bus for the process lifetime. If a future use
        case needs unsubscribe, this method can return the token list
        without breaking callers that ignore it.
        """
        for event, listeners in self.collect_session_listeners().items():
            for listener in listeners:
                bus.subscribe(event, listener)


def _coerce_event(name: str, *, plugin_name: str) -> LifecycleEvent:
    try:
        return LifecycleEvent(name)
    except ValueError as exc:
        known = ", ".join(ev.value for ev in LifecycleEvent)
        raise UnknownLifecycleEventError(
            f"plugin {plugin_name!r} subscribed to unknown lifecycle "
            f"event {name!r}; known events: {known}"
        ) from exc
