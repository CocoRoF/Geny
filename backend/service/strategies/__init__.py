"""Optional strategy registrars for stages whose default slot
registry doesn't expose the executor's full strategy catalog.

Each function is a no-op when the underlying stage / slot isn't
present (older executor pin, custom manifest dropped the stage).
Run from ``agent_session._build_pipeline`` after attach_runtime so
the slot registry can be queried by manifest preset overrides.

G9.x sprints add one helper per Phase-7 strategy that the manifest
factory should be able to select by name.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_mcp_resource_retriever(pipeline: Any) -> bool:
    """G9.1 — add ``MCPResourceRetriever`` to Stage 2's retriever slot.

    The default ContextStage registers only ``null`` and ``static``;
    ``MCPResourceRetriever`` exists in the executor but isn't on the
    slot's name → class map. This helper extends the registry so a
    manifest entry of ``retriever: "mcp_resource"`` resolves cleanly.

    Returns True when the registration happened, False when the
    helper was a no-op (no Stage 2 / no slot / executor pin too old).
    """
    try:
        from geny_executor.stages.s02_context import MCPResourceRetriever
    except ImportError:
        logger.debug("register_mcp_resource_retriever: MCPResourceRetriever unavailable")
        return False

    getter = getattr(pipeline, "get_stage", None)
    stage = getter(2) if callable(getter) else None
    if stage is None:
        stages = getattr(pipeline, "_stages", None) or {}
        stage = stages.get(2) if isinstance(stages, dict) else None
    if stage is None:
        return False

    slots = stage.get_strategy_slots() if hasattr(stage, "get_strategy_slots") else {}
    retriever_slot = slots.get("retriever") if slots else None
    if retriever_slot is None:
        return False

    registry = getattr(retriever_slot, "_registry", None) or getattr(retriever_slot, "registry", None)
    if not isinstance(registry, dict):
        return False

    if "mcp_resource" in registry:
        return True
    registry["mcp_resource"] = MCPResourceRetriever
    logger.info(
        "register_mcp_resource_retriever: Stage 2 retriever slot now exposes 'mcp_resource'"
    )
    return True


__all__ = ["register_mcp_resource_retriever"]
