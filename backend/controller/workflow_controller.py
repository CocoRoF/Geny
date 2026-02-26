"""
Workflow Controller — REST API for the visual workflow editor.

Endpoints:
    GET    /api/workflows/nodes       — node type catalog
    GET    /api/workflows             — list workflows
    POST   /api/workflows             — create workflow
    GET    /api/workflows/{id}        — get workflow
    PUT    /api/workflows/{id}        — update workflow
    DELETE /api/workflows/{id}        — delete workflow
    POST   /api/workflows/{id}/clone  — clone a workflow
    GET    /api/workflows/templates   — list templates
    POST   /api/workflows/{id}/validate  — validate workflow
    POST   /api/workflows/{id}/compile-view — compiled graph inspection
    POST   /api/workflows/{id}/execute  — execute workflow on a session
"""

from __future__ import annotations

import uuid
from logging import getLogger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from service.workflow.nodes.base import get_node_registry
from service.workflow.workflow_model import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNodeInstance,
)
from service.workflow.workflow_store import get_workflow_store

logger = getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


# ============================================================================
# Request / Response Models
# ============================================================================


class NodeInstancePayload(BaseModel):
    id: str
    node_type: str
    label: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    position: Dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class EdgePayload(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: str
    target: str
    source_port: str = "default"
    label: str = ""


class CreateWorkflowRequest(BaseModel):
    name: str = "Untitled Workflow"
    description: str = ""
    nodes: List[NodeInstancePayload] = Field(default_factory=list)
    edges: List[EdgePayload] = Field(default_factory=list)


class UpdateWorkflowRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[NodeInstancePayload]] = None
    edges: Optional[List[EdgePayload]] = None


class ExecuteWorkflowRequest(BaseModel):
    session_id: str
    input_text: str
    max_iterations: int = 50


class ValidateResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)


# ============================================================================
# Node Catalog
# ============================================================================


@router.get("/nodes")
async def list_node_types():
    """Return all registered node type definitions for the frontend palette."""
    registry = get_node_registry()
    catalog = registry.to_catalog()

    # Group by category
    categories: Dict[str, List[Dict]] = {}
    for node_def in catalog:
        cat = node_def.get("category", "general")
        categories.setdefault(cat, []).append(node_def)

    return {
        "categories": categories,
        "total": len(catalog),
    }


@router.get("/nodes/{node_type}/help")
async def get_node_help(node_type: str, locale: str = "en"):
    """Return detailed help content for a specific node type.

    Query params:
        locale — 'en' or 'ko' (default: 'en')
    """
    registry = get_node_registry()
    node = registry.get(node_type)
    if not node:
        raise HTTPException(status_code=404, detail=f"Unknown node type: {node_type}")

    help_data = node.get_help(locale)
    if not help_data:
        raise HTTPException(
            status_code=404,
            detail=f"No help content for node '{node_type}' in locale '{locale}'",
        )

    return {
        "node_type": node_type,
        "locale": locale,
        "help": help_data,
    }


# ============================================================================
# CRUD
# ============================================================================


@router.get("")
async def list_workflows():
    """List all workflows (user-created and templates)."""
    store = get_workflow_store()
    workflows = store.list_all()
    return {
        "workflows": [w.model_dump() for w in workflows],
        "total": len(workflows),
    }


@router.post("")
async def create_workflow(req: CreateWorkflowRequest):
    """Create a new workflow definition."""
    nodes = [
        WorkflowNodeInstance(
            id=n.id, node_type=n.node_type, label=n.label,
            config=n.config, position=n.position,
        )
        for n in req.nodes
    ]
    edges = [
        WorkflowEdge(
            id=e.id, source=e.source, target=e.target,
            source_port=e.source_port, label=e.label,
        )
        for e in req.edges
    ]

    workflow = WorkflowDefinition(
        name=req.name,
        description=req.description,
        nodes=nodes,
        edges=edges,
    )

    store = get_workflow_store()
    store.save(workflow)

    return workflow.model_dump()


@router.get("/templates")
async def list_templates():
    """List built-in template workflows."""
    store = get_workflow_store()
    templates = store.list_templates()
    return {
        "templates": [t.model_dump() for t in templates],
        "total": len(templates),
    }


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get a workflow definition by ID."""
    store = get_workflow_store()
    workflow = store.load(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow.model_dump()


@router.put("/{workflow_id}")
async def update_workflow(workflow_id: str, req: UpdateWorkflowRequest):
    """Update an existing workflow definition."""
    store = get_workflow_store()
    workflow = store.load(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if workflow.is_template:
        raise HTTPException(status_code=400, detail="Cannot modify a template. Clone it first.")

    if req.name is not None:
        workflow.name = req.name
    if req.description is not None:
        workflow.description = req.description
    if req.nodes is not None:
        workflow.nodes = [
            WorkflowNodeInstance(
                id=n.id, node_type=n.node_type, label=n.label,
                config=n.config, position=n.position,
            )
            for n in req.nodes
        ]
    if req.edges is not None:
        workflow.edges = [
            WorkflowEdge(
                id=e.id, source=e.source, target=e.target,
                source_port=e.source_port, label=e.label,
            )
            for e in req.edges
        ]

    store.save(workflow)
    return workflow.model_dump()


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow definition."""
    store = get_workflow_store()
    workflow = store.load(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.is_template:
        raise HTTPException(status_code=400, detail="Cannot delete a template.")

    store.delete(workflow_id)
    return {"success": True, "deleted_id": workflow_id}


@router.post("/{workflow_id}/clone")
async def clone_workflow(workflow_id: str):
    """Clone a workflow (useful for cloning templates)."""
    store = get_workflow_store()
    original = store.load(workflow_id)
    if not original:
        raise HTTPException(status_code=404, detail="Workflow not found")

    clone = WorkflowDefinition(
        name=f"{original.name} (Copy)",
        description=original.description,
        nodes=[WorkflowNodeInstance(**n.model_dump()) for n in original.nodes],
        edges=[WorkflowEdge(**e.model_dump()) for e in original.edges],
        is_template=False,
    )
    store.save(clone)
    return clone.model_dump()


@router.post("/{workflow_id}/validate")
async def validate_workflow(workflow_id: str):
    """Validate a workflow graph structure."""
    store = get_workflow_store()
    workflow = store.load(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    errors = workflow.validate_graph()
    return ValidateResponse(valid=len(errors) == 0, errors=errors)


@router.post("/{workflow_id}/compile-view")
async def compile_view(workflow_id: str):
    """Return a code-level inspection of the compiled graph.

    Does NOT actually execute anything — it simulates the compilation
    process and produces Python pseudo-code plus structured metadata
    showing how the workflow becomes a CompiledStateGraph.
    """
    from service.workflow.workflow_inspector import inspect_workflow

    store = get_workflow_store()
    workflow = store.load(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        report = inspect_workflow(workflow)
        return report
    except Exception as e:
        logger.exception(f"Compile-view failed for {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Inspection failed: {str(e)}")


@router.post("/{workflow_id}/execute")
async def execute_workflow(workflow_id: str, req: ExecuteWorkflowRequest):
    """Execute a workflow on an existing agent session.

    This compiles the workflow definition into a LangGraph and
    runs it using the session's Claude CLI model.
    """
    from service.langgraph import get_agent_session_manager
    from service.workflow.workflow_executor import WorkflowExecutor
    from service.workflow.nodes.base import ExecutionContext
    from service.langgraph.context_guard import ContextWindowGuard

    store = get_workflow_store()
    workflow = store.load(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Validate
    errors = workflow.validate_graph()
    if errors:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow validation failed: {'; '.join(errors)}"
        )

    # Get session
    manager = get_agent_session_manager()
    session = manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build execution context from the session
    model = session._model if hasattr(session, '_model') else None
    if not model:
        raise HTTPException(status_code=400, detail="Session has no active model")

    context = ExecutionContext(
        model=model,
        session_id=req.session_id,
        memory_manager=getattr(session, '_memory_manager', None),
        session_logger=None,
        context_guard=ContextWindowGuard(model=getattr(session, '_model_name', None)),
        model_name=getattr(session, '_model_name', None),
    )

    try:
        executor = WorkflowExecutor(workflow, context)
        result = await executor.run(
            req.input_text,
            max_iterations=req.max_iterations,
        )

        return {
            "success": True,
            "workflow_id": workflow_id,
            "session_id": req.session_id,
            "final_answer": result.get("final_answer") or result.get("last_output", ""),
            "is_complete": result.get("is_complete", False),
            "iterations": result.get("iteration", 0),
            "difficulty": result.get("difficulty"),
            "error": result.get("error"),
        }

    except Exception as e:
        logger.exception(f"Workflow execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")
