"""SystemStage / ToolStage registry-rebind invariant tests.

geny-executor v0.26.1 added a post-construction rebind step in
:meth:`Pipeline.from_manifest` so that SystemStage and ToolStage —
both instantiated *before* ``_register_external_tools`` populates the
shared registry — end up pointing at the populated registry instead
of their empty construction-time references (``None`` for SystemStage,
a freshly-allocated empty ``ToolRegistry()`` for ToolStage).

v0.26.2 fixed the ToolStage half after we discovered SystemStage alone
wasn't enough. These tests lock both invariants at the Geny layer so
that any future executor upgrade that breaks the rebind triggers a
test failure here — not a silent "LLM sees no tools" at runtime.

References:
- ``dev_docs/20260420_4/progress/01_system_stage_tool_registry.md``
- ``dev_docs/20260420_4/progress/02_tool_stage_registry_bump.md``
- ``geny_executor/core/pipeline.py`` lines 320-345 (the rebind loop)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from geny_executor.tools.base import Tool, ToolContext, ToolResult


class _StubTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "stub"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(content="stub")


class _FakeProvider:
    def __init__(self, names: List[str]) -> None:
        self._names = list(names)
        self._cache: Dict[str, _StubTool] = {}

    def list_names(self) -> List[str]:
        return list(self._names)

    def get(self, name: str) -> Optional[_StubTool]:
        if name not in self._names:
            return None
        return self._cache.setdefault(name, _StubTool(name))


def _build_worker_pipeline():
    from geny_executor.core.pipeline import Pipeline

    from service.environment.templates import create_worker_env

    names = ["send_direct_message_external", "memory_read", "web_search"]
    manifest = create_worker_env(external_tool_names=names)
    return Pipeline.from_manifest(
        manifest,
        api_key="sk-test",
        strict=False,
        adhoc_providers=[_FakeProvider(names)],
    )


def test_system_stage_registry_is_pipeline_registry() -> None:
    """SystemStage ``_tool_registry`` must be the exact object that
    ``pipeline.tool_registry`` exposes.

    Identity matters — SystemStage reads ``state.tools`` from its
    registry at execute time, and the API stage serialises that into
    the Anthropic payload. If SystemStage's reference diverges from
    the populated registry, the LLM is shown no tools and gives the
    "I only have web tools" reply this cycle investigated.
    """
    pipeline = _build_worker_pipeline()

    system_stage = next(
        (s for s in pipeline.stages if getattr(s, "order", None) == 3),
        None,
    )
    assert system_stage is not None, "worker pipeline must include SystemStage (order 3)"

    assert hasattr(system_stage, "_tool_registry"), (
        "SystemStage is expected to hold a `_tool_registry` attribute for "
        "the v0.26.1 rebind invariant to have anywhere to land."
    )
    assert system_stage._tool_registry is pipeline.tool_registry, (
        "SystemStage._tool_registry is not the same object as "
        "pipeline.tool_registry — the v0.26.1 rebind broke. Tools "
        "registered after stage instantiation will be invisible at runtime."
    )


def test_tool_stage_registry_is_pipeline_registry() -> None:
    """ToolStage ``_registry`` must be the same object as
    ``pipeline.tool_registry``.

    This is the invariant v0.26.2 restored. Before the fix, Stage 10
    looked up tool instances against a freshly-allocated empty
    ``ToolRegistry()`` from its constructor, so every tool call
    resolved to ``unknown_tool`` even though SystemStage advertised
    the tool schema correctly.
    """
    pipeline = _build_worker_pipeline()

    tool_stage = next(
        (s for s in pipeline.stages if getattr(s, "order", None) == 10),
        None,
    )
    assert tool_stage is not None, "worker pipeline must include ToolStage (order 10)"

    assert hasattr(tool_stage, "_registry"), (
        "ToolStage is expected to hold a `_registry` attribute for the "
        "v0.26.2 rebind invariant to have anywhere to land."
    )
    assert tool_stage._registry is pipeline.tool_registry, (
        "ToolStage._registry is not the same object as "
        "pipeline.tool_registry — the v0.26.2 rebind broke. Tool calls "
        "will resolve to `unknown_tool` at runtime."
    )


def test_system_and_tool_stage_share_populated_tools() -> None:
    """The registry SystemStage and ToolStage share must actually
    contain the external tool names the manifest declared.

    Identity alone isn't sufficient — a trivially-correct identity
    test passes if both stages point at the same empty registry. The
    end-to-end invariant is "both stages see the populated registry",
    so check that the shared object contains the known tools."""
    pipeline = _build_worker_pipeline()

    system_stage = next(s for s in pipeline.stages if getattr(s, "order", None) == 3)
    tool_stage = next(s for s in pipeline.stages if getattr(s, "order", None) == 10)

    registered = set(pipeline.tool_registry.list_names())
    assert "send_direct_message_external" in registered, sorted(registered)
    assert "memory_read" in registered, sorted(registered)

    assert system_stage._tool_registry is tool_stage._registry, (
        "SystemStage and ToolStage must share the same registry object — "
        "if they diverge, the LLM sees one tool catalog and the router "
        "dispatches against another."
    )
