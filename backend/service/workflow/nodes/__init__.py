"""
Workflow Nodes Package.

Auto-registers all concrete node implementations into the global NodeRegistry.
Import this package to ensure all nodes are available.
"""

from service.workflow.nodes.base import get_node_registry

# Import all node modules to trigger registration
from service.workflow.nodes import model_nodes    # noqa: F401
from service.workflow.nodes import logic_nodes    # noqa: F401
from service.workflow.nodes import memory_nodes   # noqa: F401
from service.workflow.nodes import guard_nodes    # noqa: F401
from service.workflow.nodes import task_nodes     # noqa: F401


def register_all_nodes() -> None:
    """Ensure all node types are registered.

    Called at application startup. The module-level imports above
    trigger ``@register_node`` decorators, but this function
    provides an explicit entry point.
    """
    registry = get_node_registry()
    count = len(registry.list_all())
    from logging import getLogger
    getLogger(__name__).info(
        f"✅ Workflow nodes registered: {count} node types"
    )


__all__ = ["register_all_nodes"]
