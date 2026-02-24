"""
Workflow Data Models — definitions, node instances, and edges.

These are the serializable data structures that describe
a user-designed workflow graph. They are persisted by
``WorkflowStore`` and compiled by ``WorkflowExecutor``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkflowNodeInstance(BaseModel):
    """A single node placed on the workflow canvas.

    ``node_type`` references a registered ``BaseNode.node_type``.
    ``config`` holds user-set parameter values.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    node_type: str
    label: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    position: Dict[str, float] = Field(
        default_factory=lambda: {"x": 0, "y": 0}
    )


class WorkflowEdge(BaseModel):
    """A directed edge between two node instances.

    ``source_port`` is the output port ID on the source node.
    For non-conditional nodes, it defaults to ``"default"``.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: str  # source node instance ID
    target: str  # target node instance ID
    source_port: str = "default"
    label: str = ""


class WorkflowDefinition(BaseModel):
    """A complete workflow graph definition.

    Contains all node instances, edges, and metadata.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Workflow"
    description: str = ""
    nodes: List[WorkflowNodeInstance] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    is_template: bool = False
    template_name: Optional[str] = None

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp."""
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def get_node(self, node_id: str) -> Optional[WorkflowNodeInstance]:
        """Find a node instance by ID."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def get_edges_from(self, node_id: str) -> List[WorkflowEdge]:
        """Get all edges originating from a node."""
        return [e for e in self.edges if e.source == node_id]

    def get_edges_to(self, node_id: str) -> List[WorkflowEdge]:
        """Get all edges pointing to a node."""
        return [e for e in self.edges if e.target == node_id]

    def get_start_node(self) -> Optional[WorkflowNodeInstance]:
        """Find the node of type 'start'."""
        for n in self.nodes:
            if n.node_type == "start":
                return n
        return None

    def get_end_nodes(self) -> List[WorkflowNodeInstance]:
        """Find all nodes of type 'end'."""
        return [n for n in self.nodes if n.node_type == "end"]

    def validate_graph(self) -> List[str]:
        """Validate the workflow graph structure.

        Returns a list of error messages (empty = valid).
        """
        errors: List[str] = []

        # Check for start node
        start_nodes = [n for n in self.nodes if n.node_type == "start"]
        if len(start_nodes) == 0:
            errors.append("Workflow must have exactly one Start node.")
        elif len(start_nodes) > 1:
            errors.append("Workflow must have exactly one Start node (found multiple).")

        # Check for at least one end node
        end_nodes = self.get_end_nodes()
        if not end_nodes:
            errors.append("Workflow must have at least one End node.")

        # Check that start has outgoing edge
        if start_nodes:
            start_edges = self.get_edges_from(start_nodes[0].id)
            if not start_edges:
                errors.append("Start node must have at least one outgoing edge.")

        # Check all edge references are valid
        node_ids = {n.id for n in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge references unknown source node: {edge.source}")
            if edge.target not in node_ids:
                errors.append(f"Edge references unknown target node: {edge.target}")

        # Check for orphan nodes (no incoming and no outgoing edges, except start)
        for node in self.nodes:
            if node.node_type in ("start", "end"):
                continue
            incoming = self.get_edges_to(node.id)
            outgoing = self.get_edges_from(node.id)
            if not incoming and not outgoing:
                errors.append(
                    f"Node '{node.label or node.node_type}' ({node.id}) "
                    f"is disconnected (no edges)."
                )

        return errors
