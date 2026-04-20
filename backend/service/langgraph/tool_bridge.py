"""Tool Bridge — adapts Geny's BaseTool instances to geny-executor's Tool interface.

Bridges the gap between Geny's tool system (BaseTool with run(**kwargs))
and geny-executor's tool system (Tool ABC with async execute(input, context)).

The single public type exported is :class:`_GenyToolAdapter`, consumed
by :class:`service.langgraph.geny_tool_provider.GenyToolProvider` —
the :class:`AdhocToolProvider` that the manifest path hands to
``Pipeline.from_manifest_async(adhoc_providers=[...])`` so that
``manifest.tools.external`` names resolve against Geny's loader.

The old ``build_geny_tool_registry`` helper that pre-populated a
fully-built :class:`ToolRegistry` up front is gone — tool
registration now flows through the manifest + provider path and is
no longer computed session-by-session in Geny.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class _GenyToolAdapter:
    """Adapts a Geny BaseTool to geny-executor's Tool interface.

    Implements all methods required by geny-executor's Tool ABC:
    - name, description, input_schema (properties)
    - execute(input, context) -> ToolResult
    - to_api_format() -> dict (Anthropic API tool definition)
    """

    def __init__(self, geny_tool: Any):
        self._tool = geny_tool
        self._name = getattr(geny_tool, "name", "unknown_tool")
        self._description = getattr(geny_tool, "description", "")
        self._parameters = getattr(geny_tool, "parameters", None) or {
            "type": "object",
            "properties": {},
        }
        self._accepts_session_id = self._probe_session_id_support(geny_tool)

    @staticmethod
    def _probe_session_id_support(tool: Any) -> bool:
        """Return True iff injecting ``session_id`` into this tool's call
        kwargs is safe.

        The adapter's kwargs flow through ``arun(**input)`` →
        ``run(**input)`` via :meth:`BaseTool.arun`'s inherited
        ``**kwargs`` forwarder, so the signature that actually
        *accepts* the kwargs is ``run``'s, not ``arun``'s. Probing
        ``arun`` first — as this did before — trips on the forwarder's
        bare ``**kwargs`` and returns a false positive for every
        BaseTool subclass regardless of its concrete ``run``
        signature (see cycle ``dev_docs/20260420_6/analysis/01``).

        For a ``@tool``-decorated function wrapped in
        :class:`~tools.base.ToolWrapper`, the kwargs reach ``func``
        through ``ToolWrapper.run``'s fixed ``**kwargs`` forwarder —
        so the authoritative signature is ``func``'s.

        Resolution order:
          1. ``tool.func`` — wrapped function inside a ToolWrapper.
          2. ``tool.run`` — concrete override on a BaseTool subclass.
          3. ``tool.arun`` — fallback for duck-typed objects that expose
             only the async method.

        A target accepts ``session_id`` if it declares the parameter
        explicitly OR accepts ``**kwargs``. If inspection fails
        (C-implemented callables, unreadable partials), return False
        — safer to omit the injection than to crash the call.
        """
        for fn in (
            getattr(tool, "func", None),
            getattr(tool, "run", None),
            getattr(tool, "arun", None),
        ):
            if fn is None:
                continue
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            for param in sig.parameters.values():
                if param.name == "session_id":
                    return True
                if param.kind is inspect.Parameter.VAR_KEYWORD:
                    return True
            return False  # first inspectable target is authoritative
        return False

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> Dict[str, Any]:
        return self._parameters

    def to_api_format(self) -> Dict[str, Any]:
        """Convert to Anthropic API tools parameter format.

        Required by ToolRegistry.to_api_format() which is called
        by s03_system stage to build the API request tools list.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    async def execute(
        self, input: Dict[str, Any], context: Any = None
    ) -> Any:
        """Execute the Geny tool and wrap result as ToolResult.

        Injects ``session_id`` from the Pipeline ``ToolContext`` only
        when the wrapped tool's signature accepts it — decided once
        at construction time by :meth:`_probe_session_id_support` and
        cached on ``self._accepts_session_id``.
        """
        from geny_executor.tools.base import ToolResult

        # Copy the caller's dict so our injection doesn't mutate the
        # state.pending_tool_calls entry Stage 10 passed in. Adapters
        # are cached in GenyToolProvider, and stages can retry on
        # transient failure; a mutated input would persist across turns.
        call_input = dict(input)
        if (
            self._accepts_session_id
            and context
            and getattr(context, "session_id", None)
        ):
            call_input.setdefault("session_id", context.session_id)

        try:
            # Try async first (arun), fall back to sync (run)
            if hasattr(self._tool, "arun"):
                result = await self._tool.arun(**call_input)
            elif hasattr(self._tool, "run"):
                run_fn = self._tool.run
                if asyncio.iscoroutinefunction(run_fn):
                    result = await run_fn(**call_input)
                else:
                    result = await asyncio.to_thread(lambda: run_fn(**call_input))
            else:
                return ToolResult(
                    content=f"Tool '{self._name}' has no run/arun method",
                    is_error=True,
                )

            # Normalize result to string
            if not isinstance(result, str):
                import json
                try:
                    result = json.dumps(result, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    result = str(result)

            return ToolResult(content=result)

        except Exception as exc:
            logger.warning("tool_bridge: '%s' execution failed: %s", self._name, exc, exc_info=True)
            return ToolResult(
                content=f"Error executing {self._name}: {exc}",
                is_error=True,
            )
