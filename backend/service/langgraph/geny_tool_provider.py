"""GenyToolProvider — adapts Geny's ToolLoader as an AdhocToolProvider.

Implements the structural shape of
:class:`geny_executor.tools.providers.AdhocToolProvider` (``list_names()``
+ ``get(name)``) so ``Pipeline.from_manifest(adhoc_providers=[...])``
can consume it directly. No inheritance — the executor Protocol is
``@runtime_checkable`` and duck-typing keeps this module importable
even against executor versions that predate the Protocol.

**Active in env_id sessions.** Wired into
:meth:`EnvironmentService.instantiate_pipeline` by the Phase C
cutover PR; the env_id flow in ``AgentSessionManager`` constructs
one of these and forwards it as ``adhoc_providers=[...]`` so that
``manifest.tools.external`` names resolve against Geny's
:class:`~service.tool_loader.ToolLoader`. The non-env_id
``AgentSession._build_pipeline`` path still uses
:class:`~geny_executor.memory.GenyPresets` directly — replacing
that path requires a follow-on PR (manifest stage chain +
post-construction memory_manager / callback attach helper).

Usage::

    from service.langgraph.geny_tool_provider import GenyToolProvider
    provider = GenyToolProvider(tool_loader)
    pipeline = await Pipeline.from_manifest_async(
        manifest, api_key=api_key, adhoc_providers=[provider],
    )
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)


class GenyToolProvider:
    """Surfaces Geny's :class:`~service.tool_loader.ToolLoader` through
    the executor's :class:`AdhocToolProvider` Protocol.

    :meth:`list_names` advertises every tool the loader knows about —
    both built-in (``tools/built_in``) and custom (``tools/custom``).
    The pipeline decides which of those get registered by consulting
    ``manifest.tools.external``; this provider never filters by preset
    itself, keeping responsibility clean.

    :meth:`get` returns a :class:`Tool` adapter on demand. The adapter
    bridges Geny's ``BaseTool.run(**kwargs)`` / ``ToolWrapper.arun``
    into executor's ``async Tool.execute(input, context)`` shape. The
    full adapter is imported lazily so *importing this module* does
    not require ``geny-executor`` at boot time — matters while this
    file still ships as dead code alongside the legacy tool_bridge.
    """

    def __init__(self, tool_loader: Any) -> None:
        """Wrap *tool_loader*.

        Args:
            tool_loader: An already-loaded
                :class:`~service.tool_loader.ToolLoader` (has
                :meth:`get_tool` + :meth:`get_all_names` methods).
        """
        self._loader = tool_loader
        self._cache: Dict[str, Any] = {}

    def list_names(self) -> List[str]:
        """Names the underlying loader can supply (built-in + custom)."""
        get_all = getattr(self._loader, "get_all_names", None)
        if get_all is not None:
            return list(get_all())
        # Fallback for older ToolLoader shapes — keeps Phase C rollout
        # robust against dev-branch drift.
        all_tools = getattr(self._loader, "get_all_tools", lambda: {})()
        return list(all_tools.keys())

    def get(self, name: str) -> Optional[Any]:
        """Return an executor-compatible :class:`Tool` adapter for
        *name*, or ``None`` if the loader does not supply that tool.

        Adapters are cached per name so the pipeline registering the
        same tool across multiple sessions does not pay for repeated
        adaptation.
        """
        if name in self._cache:
            return self._cache[name]

        base = self._loader.get_tool(name)
        if base is None:
            return None

        from service.langgraph.tool_bridge import _GenyToolAdapter

        adapter = _GenyToolAdapter(base)
        self._cache[name] = adapter
        return adapter
