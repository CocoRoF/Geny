"""
Workflow Engine — Visual LangGraph Workflow Builder.

Provides the infrastructure for defining, storing, and executing
user-designed LangGraph workflows through a visual node-edge editor.

Architecture:
    nodes/          — BaseNode ABC + all concrete node implementations
    workflow_model  — Data models for workflow definitions
    workflow_executor — Compiles WorkflowDefinition → LangGraph StateGraph
    workflow_store  — Persistence layer for workflow definitions
    templates       — Pre-built workflow templates (autonomous, etc.)
"""

from service.workflow.nodes.base import (
    BaseNode,
    NodeParameter,
    OutputPort,
    ExecutionContext,
    NodeRegistry,
    get_node_registry,
)
from service.workflow.workflow_model import (
    WorkflowDefinition,
    WorkflowNodeInstance,
    WorkflowEdge,
)
from service.workflow.workflow_executor import WorkflowExecutor
from service.workflow.workflow_store import WorkflowStore, get_workflow_store
from service.workflow.workflow_state import (
    StateFieldDef,
    StateFieldCategory,
    ReducerType,
    NodeStateUsage,
    get_all_state_fields,
    get_state_field,
    get_state_fields_by_category,
    analyze_workflow_state,
)

__all__ = [
    "BaseNode",
    "NodeParameter",
    "OutputPort",
    "ExecutionContext",
    "NodeRegistry",
    "get_node_registry",
    "WorkflowDefinition",
    "WorkflowNodeInstance",
    "WorkflowEdge",
    "WorkflowExecutor",
    "WorkflowStore",
    "get_workflow_store",
    "StateFieldDef",
    "StateFieldCategory",
    "ReducerType",
    "NodeStateUsage",
    "get_all_state_fields",
    "get_state_field",
    "get_state_fields_by_category",
    "analyze_workflow_state",
]
