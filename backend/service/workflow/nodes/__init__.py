"""
Workflow Nodes Package.

Auto-registers all concrete node implementations into the global NodeRegistry.
Import this package to ensure all nodes are available.

Structure::

    nodes/
        base.py               # BaseNode interface, NodeRegistry
        _helpers.py           # Shared utility functions
        i18n.py               # Centralised translations
        structured_output.py  # Pydantic schemas for LLM output
        model/                # LLM-powered processing
        logic/                # Routing, gating, state management
        resilience/           # Guards, post-processing
        task/                 # Todo management, reviews, final answers
        memory/               # Context injection, transcript recording

Each leaf module contains exactly one node class decorated with
``@register_node``.  Importing the module is sufficient to register it.
"""

from service.workflow.nodes.base import get_node_registry

# ── Model nodes ──────────────────────────────────────────────
from service.workflow.nodes.model import llm_call_node            # noqa: F401
from service.workflow.nodes.model import classify_node             # noqa: F401
from service.workflow.nodes.model import adaptive_classify_node    # noqa: F401
from service.workflow.nodes.model import direct_answer_node        # noqa: F401
from service.workflow.nodes.model import answer_node               # noqa: F401
from service.workflow.nodes.model import review_node               # noqa: F401

# ── Logic nodes ──────────────────────────────────────────────
from service.workflow.nodes.logic import conditional_router_node   # noqa: F401
from service.workflow.nodes.logic import iteration_gate_node       # noqa: F401
from service.workflow.nodes.logic import check_progress_node       # noqa: F401
from service.workflow.nodes.logic import state_setter_node         # noqa: F401
from service.workflow.nodes.logic import relevance_gate_node       # noqa: F401

# ── Resilience / Guard nodes ────────────────────────────────
from service.workflow.nodes.resilience import context_guard_node        # noqa: F401
from service.workflow.nodes.resilience import post_model_node           # noqa: F401

# ── Task nodes ───────────────────────────────────────────────
from service.workflow.nodes.task import create_todos_node         # noqa: F401
from service.workflow.nodes.task import execute_todo_node         # noqa: F401
from service.workflow.nodes.task import batch_execute_todo_node   # noqa: F401
from service.workflow.nodes.task import direct_tool_node          # noqa: F401
from service.workflow.nodes.task import final_review_node         # noqa: F401
from service.workflow.nodes.task import final_answer_node         # noqa: F401
from service.workflow.nodes.task import final_synthesis_node      # noqa: F401

# ── Memory nodes ─────────────────────────────────────────────
from service.workflow.nodes.memory import memory_inject_node        # noqa: F401
from service.workflow.nodes.memory import transcript_record_node    # noqa: F401


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
