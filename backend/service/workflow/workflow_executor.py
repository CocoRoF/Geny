"""
Workflow Executor — compile a WorkflowDefinition into a LangGraph StateGraph.

Takes the user-designed visual workflow and produces a live,
runnable LangGraph that invokes the Claude CLI model according
to the node-edge topology.
"""

from __future__ import annotations

import asyncio
import time
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from service.langgraph.state import AutonomousState, make_initial_autonomous_state
from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeRegistry,
    get_node_registry,
)
from service.workflow.workflow_model import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNodeInstance,
)

logger = getLogger(__name__)

# Special pseudo-node type IDs
_START_TYPE = "start"
_END_TYPE = "end"


class WorkflowExecutor:
    """Compile a WorkflowDefinition → LangGraph CompiledStateGraph.

    Steps:
        1. Look up every node instance's BaseNode from the registry.
        2. For each non-start/end node, create a LangGraph node function
           that delegates to ``BaseNode.execute(state, ctx, config)``.
        3. Wire edges — direct for single-port nodes, conditional for
           multi-port (router) nodes.
        4. Compile and optionally execute.

    Usage::

        executor = WorkflowExecutor(workflow, context)
        graph = executor.compile()
        result = await executor.run("Do something complex")
    """

    def __init__(
        self,
        workflow: WorkflowDefinition,
        context: ExecutionContext,
        registry: Optional[NodeRegistry] = None,
    ) -> None:
        self._workflow = workflow
        self._context = context
        self._registry = registry or get_node_registry()
        self._graph: Optional[CompiledStateGraph] = None

    # ========================================================================
    # Compilation
    # ========================================================================

    def compile(self) -> CompiledStateGraph:
        """Compile the workflow into a LangGraph StateGraph.

        Raises:
            ValueError: If validation fails.
        """
        errors = self._workflow.validate_graph()
        if errors:
            raise ValueError(
                "Workflow validation failed:\n" + "\n".join(f"  • {e}" for e in errors)
            )

        graph_builder = StateGraph(AutonomousState)

        # ── Resolve node instances → BaseNode types ──
        instance_map: Dict[str, WorkflowNodeInstance] = {}
        node_type_map: Dict[str, BaseNode] = {}

        for inst in self._workflow.nodes:
            instance_map[inst.id] = inst

            if inst.node_type in (_START_TYPE, _END_TYPE):
                continue  # pseudo-nodes

            base_node = self._registry.get(inst.node_type)
            if base_node is None:
                raise ValueError(
                    f"Unknown node type '{inst.node_type}' "
                    f"for node '{inst.label}' ({inst.id})"
                )
            node_type_map[inst.id] = base_node

        # ── Register LangGraph nodes ──
        for inst_id, base_node in node_type_map.items():
            inst = instance_map[inst_id]
            node_fn = self._make_node_function(base_node, inst)
            graph_builder.add_node(inst_id, node_fn)

        # ── Wire edges ──
        # Group edges by source
        edges_by_source: Dict[str, List[WorkflowEdge]] = {}
        for edge in self._workflow.edges:
            edges_by_source.setdefault(edge.source, []).append(edge)

        # Track which nodes already have outgoing edges configured
        wired_sources = set()

        for source_id, edges in edges_by_source.items():
            source_inst = instance_map.get(source_id)
            if not source_inst:
                continue

            # ── Handle START pseudo-node ──
            if source_inst.node_type == _START_TYPE:
                if edges:
                    first_target = self._resolve_target(edges[0].target, instance_map)
                    graph_builder.add_edge(START, first_target)
                wired_sources.add(source_id)
                continue

            # ── Handle END pseudo-node as source (shouldn't happen) ──
            if source_inst.node_type == _END_TYPE:
                continue

            base_node = node_type_map.get(source_id)
            if not base_node:
                continue

            # ── Decide wiring strategy ──
            # Use conditional routing only when edges actually go to
            # multiple distinct targets.  A conditional node whose
            # edges all converge on one target (pass-through pattern)
            # is wired with a simple edge — the routing function
            # would be pointless since all outcomes lead to the same
            # node, and calling it could fail when the edge_map
            # doesn't contain every possible return value.
            if self._has_multiple_targets(edges):
                config = source_inst.config
                routing_fn = base_node.get_routing_function(config)

                if routing_fn is None:
                    # Fallback: create a routing function from edge port mappings
                    routing_fn = self._make_fallback_router(edges, instance_map)

                edge_map = self._build_edge_map(edges, instance_map)

                # Wrap routing function with edge decision logging
                source_label = source_inst.label or source_inst.node_type
                routing_fn = self._wrap_routing_function(
                    routing_fn, source_label, edge_map,
                )

                graph_builder.add_conditional_edges(
                    source_id, routing_fn, edge_map
                )
            else:
                # ── Simple direct edge (single target) ──
                target = self._resolve_target(edges[0].target, instance_map)
                graph_builder.add_edge(source_id, target)

            wired_sources.add(source_id)

        # ── Compile ──
        self._graph = graph_builder.compile()

        node_count = len(node_type_map)
        edge_count = len(self._workflow.edges)
        logger.info(
            f"[{self._context.session_id}] Workflow '{self._workflow.name}' "
            f"compiled: {node_count} nodes, {edge_count} edges"
        )

        return self._graph

    # ========================================================================
    # Execution
    # ========================================================================

    async def run(
        self,
        input_text: str,
        max_iterations: int = 50,
        **extra_metadata: Any,
    ) -> Dict[str, Any]:
        """Compile (if needed) and execute the workflow.

        Args:
            input_text: User prompt / task description.
            max_iterations: Maximum graph iterations.

        Returns:
            Final state dictionary.
        """
        if self._graph is None:
            self.compile()

        initial_state = make_initial_autonomous_state(
            input_text, max_iterations=max_iterations, **extra_metadata
        )

        logger.info(
            f"[{self._context.session_id}] Running workflow "
            f"'{self._workflow.name}' …"
        )

        final_state = await self._graph.ainvoke(initial_state)
        return dict(final_state)

    @property
    def graph(self) -> Optional[CompiledStateGraph]:
        return self._graph

    # ========================================================================
    # Internal helpers
    # ========================================================================

    def _make_node_function(
        self, base_node: BaseNode, instance: WorkflowNodeInstance,
    ):
        """Create a LangGraph-compatible async node function.

        Wraps ``BaseNode.execute`` with the instance config and
        shared execution context.  Adds per-node enter/exit/error
        logging via the session logger.
        """
        ctx = self._context
        config = dict(instance.config)
        node_label = instance.label or instance.node_type
        node_type = instance.node_type
        node_id = instance.id
        # Capture static helpers as local references for the closure
        _state_summary = self._make_state_summary
        _output_preview = self._make_output_preview
        _summarize = self._summarize_changes

        async def _node_fn(state: AutonomousState) -> Dict[str, Any]:
            session_logger = ctx.session_logger
            iteration = state.get("iteration", 0)

            # ── Node enter ──
            if session_logger:
                state_summary = _state_summary(state)
                session_logger.log_graph_node_enter(
                    node_name=node_label,
                    iteration=iteration,
                    state_summary=state_summary,
                )

            start = time.time()
            try:
                result = await base_node.execute(state, ctx, config)
                duration_ms = int((time.time() - start) * 1000)

                # ── Node exit ──
                if session_logger:
                    output_preview = _output_preview(result)
                    state_changes = _summarize(result)
                    session_logger.log_graph_node_exit(
                        node_name=node_label,
                        iteration=iteration,
                        output_preview=output_preview,
                        duration_ms=duration_ms,
                        state_changes=state_changes,
                    )

                return result

            except Exception as e:
                duration_ms = int((time.time() - start) * 1000)
                logger.error(
                    f"[{ctx.session_id}] Node '{node_label}' ({node_type}) "
                    f"failed after {duration_ms}ms: {e}"
                )
                if session_logger:
                    session_logger.log_graph_error(
                        error_message=str(e)[:500],
                        node_name=node_label,
                        iteration=iteration,
                        error_type=type(e).__name__,
                    )
                raise

        # Give the function a useful name for debugging
        _node_fn.__name__ = f"node_{node_id}_{node_type}"
        _node_fn.__qualname__ = _node_fn.__name__
        return _node_fn

    def _wrap_routing_function(
        self,
        routing_fn: Callable,
        source_label: str,
        edge_map: Dict[str, str],
    ) -> Callable:
        """Wrap a routing function to log edge decisions."""
        ctx = self._context

        def _logged_routing(state: Dict[str, Any]) -> str:
            decision = routing_fn(state)
            if ctx.session_logger:
                # Resolve the target label for logging
                target = edge_map.get(decision, decision)
                ctx.session_logger.log_graph_edge_decision(
                    from_node=source_label,
                    decision=f"{decision} → {target}",
                    iteration=state.get("iteration", 0),
                )
            return decision

        return _logged_routing

    @staticmethod
    def _make_state_summary(state: Dict[str, Any]) -> Dict[str, Any]:
        """Build a compact state summary for enter-logging."""
        return {
            "messages_count": len(state.get("messages", [])),
            "iteration": state.get("iteration", 0),
            "is_complete": state.get("is_complete", False),
            "has_error": bool(state.get("error")),
            "difficulty": state.get("difficulty"),
            "completion_signal": state.get("completion_signal"),
        }

    @staticmethod
    def _make_output_preview(result: Dict[str, Any]) -> Optional[str]:
        """Extract a short preview string from a node's output."""
        if not result:
            return None
        # Try common output fields
        for key in ("answer", "final_answer", "last_output", "direct_answer"):
            val = result.get(key)
            if val and isinstance(val, str):
                return val[:200]
        # Fallback: list the keys that were updated
        changed_keys = [k for k in result if result[k] is not None]
        if changed_keys:
            return f"Updated: {', '.join(changed_keys)}"
        return None

    @staticmethod
    def _summarize_changes(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Produce a minimal summary of state changes from a node result."""
        if not result:
            return None
        summary: Dict[str, Any] = {}
        for key, value in result.items():
            if value is None:
                continue
            if isinstance(value, str):
                summary[key] = f"{len(value)} chars" if len(value) > 50 else value
            elif isinstance(value, list):
                summary[key] = f"{len(value)} items"
            elif isinstance(value, dict):
                summary[key] = f"{{...}} ({len(value)} keys)"
            else:
                summary[key] = value
        return summary if summary else None

    def _resolve_target(
        self,
        target_id: str,
        instance_map: Dict[str, WorkflowNodeInstance],
    ) -> str:
        """Resolve a target instance ID to a LangGraph node reference.

        Maps 'end' pseudo-nodes to LangGraph's ``END`` sentinel.
        """
        inst = instance_map.get(target_id)
        if inst and inst.node_type == _END_TYPE:
            return END
        return target_id

    def _has_multiple_targets(self, edges: List[WorkflowEdge]) -> bool:
        """Check if edges go to multiple distinct targets."""
        targets = {e.target for e in edges}
        return len(targets) > 1

    def _build_edge_map(
        self,
        edges: List[WorkflowEdge],
        instance_map: Dict[str, WorkflowNodeInstance],
    ) -> Dict[str, str]:
        """Build a port → target mapping for conditional edges."""
        edge_map: Dict[str, str] = {}
        for edge in edges:
            port = edge.source_port or "default"
            target = self._resolve_target(edge.target, instance_map)
            edge_map[port] = target
        return edge_map

    def _make_fallback_router(
        self,
        edges: List[WorkflowEdge],
        instance_map: Dict[str, WorkflowNodeInstance],
    ):
        """Create a simple router for nodes without a built-in routing function.

        Falls back to the first edge's port.
        """
        port_list = [e.source_port or "default" for e in edges]
        default_port = port_list[0] if port_list else "default"

        def _fallback(state: Dict[str, Any]) -> str:
            return default_port

        return _fallback
