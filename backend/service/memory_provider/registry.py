"""Per-session :class:`MemoryProvider` manager for Geny.

Port of ``geny_executor_web.app.services.memory_service.MemorySessionRegistry``
with two differences:

1. It sits next to Geny's legacy ``SessionMemoryManager`` rather than
   replacing it — Phase 2 keeps the two side-by-side.
2. ``attach_to_pipeline`` is present but **not yet called** by
   ``AgentSessionManager``. That wiring is deliberately deferred to Phase 4
   (``plan/03_memory_migration.md``) so this PR stays a pure additive surface.

Factory / descriptor semantics are identical to the executor contract —
this class only reshapes them for the REST layer.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Mapping, Optional

from geny_executor.memory.factory import MemoryProviderFactory
from geny_executor.memory.provider import MemoryProvider

from service.memory_provider.exceptions import (
    MemoryConfigError,
    MemorySessionNotFoundError,
)


class MemorySessionRegistry:
    """Manage a ``session_id → MemoryProvider`` map for the running app.

    A single instance is meant to live on ``app.state.memory_registry``.
    ``default_config`` — when provided — is the factory config dict used
    whenever a session is provisioned without a per-request override.
    Passing ``None`` keeps memory wiring off (``provision`` returns ``None``
    and the legacy ``SessionMemoryManager`` path remains sole owner of
    session memory).
    """

    def __init__(
        self,
        *,
        factory: Optional[MemoryProviderFactory] = None,
        default_config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._factory = factory or MemoryProviderFactory()
        self._default_config: Optional[Dict[str, Any]] = (
            dict(default_config) if default_config else None
        )
        self._providers: Dict[str, MemoryProvider] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}

    # ── lifecycle ───────────────────────────────────────────────────

    def provision(
        self,
        session_id: str,
        *,
        override: Optional[Mapping[str, Any]] = None,
    ) -> Optional[MemoryProvider]:
        """Construct and register a provider for ``session_id``.

        Returns ``None`` when memory is globally disabled (no default
        config *and* no override). Raises :class:`MemoryConfigError`
        when the factory rejects the config.
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")

        config = self._resolve_config(override)
        if config is None:
            return None

        config = dict(config)
        config.setdefault("session_id", session_id)
        try:
            provider = self._factory.build(config)
        except Exception as exc:  # noqa: BLE001 — all factory errors surface as config errors
            raise MemoryConfigError(str(exc)) from exc

        self._providers[session_id] = provider
        self._configs[session_id] = config
        return provider

    def get(self, session_id: str) -> Optional[MemoryProvider]:
        return self._providers.get(session_id)

    def require(self, session_id: str) -> MemoryProvider:
        provider = self._providers.get(session_id)
        if provider is None:
            raise MemorySessionNotFoundError(session_id)
        return provider

    def get_config(self, session_id: str) -> Optional[Dict[str, Any]]:
        cfg = self._configs.get(session_id)
        return dict(cfg) if cfg is not None else None

    def release(self, session_id: str) -> bool:
        """Drop the provider. Returns ``True`` iff one was registered.

        Providers typically expose an async ``close()``; schedule on the
        running loop if one exists, otherwise run it synchronously.
        Best-effort — teardown failures are swallowed.
        """
        provider = self._providers.pop(session_id, None)
        self._configs.pop(session_id, None)
        if provider is None:
            return False
        close = getattr(provider, "close", None)
        if not callable(close):
            return True
        try:
            result = close()
            if inspect.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    loop.create_task(result)
                else:
                    asyncio.run(result)
        except Exception:  # noqa: BLE001 — best-effort teardown
            pass
        return True

    # ── pipeline wiring ─────────────────────────────────────────────

    def attach_to_pipeline(self, pipeline: Any, provider: MemoryProvider) -> None:
        """Wire ``provider`` into memory-aware stages of a pipeline.

        Currently that is only Stage 2 (``ContextStage.provider``). Not
        invoked anywhere yet — Phase 4 flips the switch.
        """
        stage = pipeline.get_stage(2)
        if stage is not None and hasattr(stage, "provider"):
            stage.provider = provider

    # ── introspection ───────────────────────────────────────────────

    def describe(self, session_id: str) -> Dict[str, Any]:
        """Return a JSON-serialisable description of the session's provider.

        Mirrors :class:`geny_executor.memory.provider.MemoryDescriptor`
        after enum-stringification. Backend ``location`` is omitted
        on purpose (Postgres DSNs can contain credentials).
        """
        provider = self.require(session_id)
        desc = provider.descriptor
        return {
            "session_id": session_id,
            "provider": desc.name,
            "version": desc.version,
            "scope": desc.scope.value,
            "layers": sorted(layer.value for layer in desc.layers),
            "capabilities": sorted(cap.value for cap in desc.capabilities),
            "backends": [
                {"layer": b.layer.value, "backend": b.backend}
                for b in desc.backends
            ],
            "metadata": dict(desc.metadata),
            "config": self.get_config(session_id),
        }

    def default_config(self) -> Optional[Dict[str, Any]]:
        return dict(self._default_config) if self._default_config else None

    # ── internals ───────────────────────────────────────────────────

    def _resolve_config(
        self, override: Optional[Mapping[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if override is not None:
            if not isinstance(override, Mapping):
                raise MemoryConfigError("memory_config must be a mapping")
            cfg = dict(override)
            if "provider" not in cfg or not cfg["provider"]:
                raise MemoryConfigError(
                    "memory_config must include a non-empty 'provider'"
                )
            return cfg
        if self._default_config is None:
            return None
        return dict(self._default_config)
