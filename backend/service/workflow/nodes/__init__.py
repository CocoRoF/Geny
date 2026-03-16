"""
Workflow Nodes Package.

Auto-registers all concrete node implementations into the global NodeRegistry.
Import this package to ensure all nodes are available.

Each module below contains exactly one node class decorated with
``@register_node``.  Importing the module is sufficient to register it.
"""

from service.workflow.nodes.base import get_node_registry

# ── Model nodes ──────────────────────────────────────────────
from service.workflow.nodes import llm_call_node            # noqa: F401
from service.workflow.nodes import classify_node             # noqa: F401
from service.workflow.nodes import direct_answer_node        # noqa: F401
from service.workflow.nodes import answer_node               # noqa: F401
from service.workflow.nodes import review_node               # noqa: F401

# ── Logic nodes ──────────────────────────────────────────────
from service.workflow.nodes import conditional_router_node   # noqa: F401
from service.workflow.nodes import iteration_gate_node       # noqa: F401
from service.workflow.nodes import check_progress_node       # noqa: F401
from service.workflow.nodes import state_setter_node         # noqa: F401
from service.workflow.nodes import relevance_gate_node       # noqa: F401

# ── Resilience / Guard nodes ────────────────────────────────
from service.workflow.nodes import context_guard_node        # noqa: F401
from service.workflow.nodes import post_model_node           # noqa: F401
from service.workflow.nodes import tool_discovery_post_node     # noqa: F401
from service.workflow.nodes import tool_discovery_summary_node  # noqa: F401

# ── Task nodes ───────────────────────────────────────────────
from service.workflow.nodes import create_todos_node         # noqa: F401
from service.workflow.nodes import execute_todo_node         # noqa: F401
from service.workflow.nodes import final_review_node         # noqa: F401
from service.workflow.nodes import final_answer_node         # noqa: F401

# ── Memory nodes ─────────────────────────────────────────────
from service.workflow.nodes import memory_inject_node        # noqa: F401
from service.workflow.nodes import transcript_record_node    # noqa: F401


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
