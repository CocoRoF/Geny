"""
Workflow Inspector — generate a code-level view of how a
WorkflowDefinition compiles into a LangGraph CompiledStateGraph.

This mirrors the exact logic in ``WorkflowExecutor.compile()`` but
instead of building a live graph, it produces a structured report
and Python pseudo-code that shows:

* How each node is registered
* How edges are wired (simple vs conditional)
* What routing functions are generated for conditional nodes
* Input/output state fields per node
* The full compilation sequence as readable Python code
"""

from __future__ import annotations

import inspect
import json
import textwrap
from logging import getLogger
from typing import Any, Dict, List, Optional

from service.workflow.nodes.base import (
    BaseNode,
    NodeRegistry,
    OutputPort,
    get_node_registry,
)
from service.workflow.workflow_model import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNodeInstance,
)

logger = getLogger(__name__)

_START_TYPE = "start"
_END_TYPE = "end"


# ====================================================================
# Public API
# ====================================================================


def inspect_workflow(
    workflow: WorkflowDefinition,
    registry: Optional[NodeRegistry] = None,
) -> Dict[str, Any]:
    """Inspect a workflow and produce the compiled-graph report.

    Returns a dict containing:
        - ``code``       : Full Python pseudo-code of the compiled graph
        - ``nodes``      : Per-node detail list
        - ``edges``      : Per-edge detail list
        - ``summary``    : High-level stats
        - ``validation`` : Validation result
    """
    reg = registry or get_node_registry()
    errors = workflow.validate_graph()

    # Build maps
    instance_map: Dict[str, WorkflowNodeInstance] = {
        n.id: n for n in workflow.nodes
    }
    node_type_map: Dict[str, BaseNode] = {}
    for inst in workflow.nodes:
        if inst.node_type in (_START_TYPE, _END_TYPE):
            continue
        base = reg.get(inst.node_type)
        if base:
            node_type_map[inst.id] = base

    # Group edges by source
    edges_by_source: Dict[str, List[WorkflowEdge]] = {}
    for edge in workflow.edges:
        edges_by_source.setdefault(edge.source, []).append(edge)

    # Build node report
    node_details = _build_node_details(
        workflow.nodes, node_type_map, instance_map, edges_by_source,
    )

    # Build edge report
    edge_details = _build_edge_details(
        edges_by_source, instance_map, node_type_map,
    )

    # Generate code
    code = _generate_code(
        workflow, instance_map, node_type_map, edges_by_source,
    )

    # Summary
    real_nodes = [n for n in workflow.nodes if n.node_type not in (_START_TYPE, _END_TYPE)]
    conditional_count = sum(
        1 for d in edge_details if d["wiring"] == "conditional"
    )
    simple_count = sum(
        1 for d in edge_details if d["wiring"] == "simple"
    )

    return {
        "code": code,
        "nodes": node_details,
        "edges": edge_details,
        "summary": {
            "workflow_name": workflow.name,
            "workflow_id": workflow.id,
            "total_nodes": len(real_nodes),
            "total_edges": len(workflow.edges),
            "conditional_edges": conditional_count,
            "simple_edges": simple_count,
            "pseudo_nodes": len(workflow.nodes) - len(real_nodes),
            "is_valid": len(errors) == 0,
        },
        "validation": {
            "valid": len(errors) == 0,
            "errors": errors,
        },
    }


# ====================================================================
# Node detail builder
# ====================================================================


def _build_node_details(
    nodes: List[WorkflowNodeInstance],
    node_type_map: Dict[str, BaseNode],
    instance_map: Dict[str, WorkflowNodeInstance],
    edges_by_source: Dict[str, List[WorkflowEdge]],
) -> List[Dict[str, Any]]:
    details = []
    for inst in nodes:
        if inst.node_type in (_START_TYPE, _END_TYPE):
            details.append({
                "id": inst.id,
                "label": inst.label or inst.node_type.upper(),
                "node_type": inst.node_type,
                "role": "pseudo",
                "description": "Graph entry point" if inst.node_type == _START_TYPE else "Graph terminal",
            })
            continue

        base = node_type_map.get(inst.id)
        if not base:
            details.append({
                "id": inst.id,
                "label": inst.label,
                "node_type": inst.node_type,
                "role": "unknown",
                "description": f"Unknown node type: {inst.node_type}",
            })
            continue

        # Resolve output ports (dynamic if applicable)
        ports = base.output_ports
        dynamic = base.get_dynamic_output_ports(inst.config)
        if dynamic is not None:
            ports = dynamic

        is_conditional = len(ports) > 1
        has_routing = base.get_routing_function(inst.config) is not None

        # Determine edges from this node
        outgoing = edges_by_source.get(inst.id, [])
        targets = []
        for e in outgoing:
            tgt_inst = instance_map.get(e.target)
            tgt_label = tgt_inst.label if tgt_inst else e.target
            targets.append({
                "port": e.source_port or "default",
                "target_id": e.target,
                "target_label": tgt_label,
                "label": e.label,
            })

        # Describe parameters
        config_summary = {}
        for param in base.parameters:
            val = inst.config.get(param.name)
            if val is not None:
                if isinstance(val, str) and len(val) > 100:
                    config_summary[param.name] = val[:100] + "…"
                else:
                    config_summary[param.name] = val
            else:
                config_summary[param.name] = f"(default: {_format_default(param.default)})"

        # Describe routing logic
        routing_description = None
        if is_conditional and has_routing:
            routing_description = _describe_routing(base, inst.config, ports)

        details.append({
            "id": inst.id,
            "label": inst.label or base.label,
            "node_type": inst.node_type,
            "category": base.category,
            "role": "conditional" if is_conditional else "processor",
            "description": base.description,
            "is_conditional": is_conditional,
            "has_routing_function": has_routing,
            "output_ports": [
                {"id": p.id, "label": p.label, "description": p.description}
                for p in ports
            ],
            "targets": targets,
            "config": config_summary,
            "routing_logic": routing_description,
        })

    return details


def _describe_routing(
    base: BaseNode,
    config: Dict[str, Any],
    ports: List[OutputPort],
) -> str:
    """Generate a human-readable description of the routing logic."""
    ntype = base.node_type
    port_names = [p.id for p in ports]

    if ntype == "classify":
        field = config.get("output_field", "difficulty")
        cats = config.get("categories", '["easy","medium","hard"]')
        return (
            f"Reads state[\"{field}\"] and routes to matching category port.\n"
            f"Categories: {cats}\n"
            f"If no match → \"end\" port."
        )

    if ntype == "review":
        field = config.get("output_field", "review_result")
        verdicts = config.get("verdicts", '["approved","retry"]')
        default = config.get("default_verdict", "retry")
        max_r = config.get("max_retries", 3)
        return (
            f"Reads state[\"{field}\"] and routes to matching verdict port.\n"
            f"Verdicts: {verdicts}\n"
            f"Default verdict: \"{default}\"\n"
            f"Forces first verdict after {max_r} cycles.\n"
            f"On error/is_complete → routes to first verdict or \"end\"."
        )

    if ntype == "conditional_router":
        field = config.get("routing_field", "")
        route_map = config.get("route_map", {})
        default = config.get("default_port", "default")
        return (
            f"Reads state[\"{field}\"].\n"
            f"Route map: {json.dumps(route_map, ensure_ascii=False)}\n"
            f"Default port: \"{default}\"."
        )

    if ntype == "check_progress":
        return (
            "Checks TODO completion status.\n"
            "Routes: \"complete\" (all done) or \"continue\" (more TODOs)."
        )

    if ntype == "iteration_gate":
        max_iter = config.get("max_iterations", 5)
        return (
            f"Checks iteration count against max ({max_iter}).\n"
            f"Routes: \"continue\" (under limit) or \"stop\" (limit reached)."
        )

    # Generic fallback
    return f"Custom routing function. Ports: {port_names}"


def _format_default(val: Any) -> str:
    if val is None:
        return "None"
    if isinstance(val, str):
        if len(val) > 60:
            return f'"{val[:60]}…"'
        return f'"{val}"'
    return str(val)


# ====================================================================
# Edge detail builder
# ====================================================================


def _build_edge_details(
    edges_by_source: Dict[str, List[WorkflowEdge]],
    instance_map: Dict[str, WorkflowNodeInstance],
    node_type_map: Dict[str, BaseNode],
) -> List[Dict[str, Any]]:
    details = []

    for source_id, edges in edges_by_source.items():
        source_inst = instance_map.get(source_id)
        if not source_inst:
            continue

        source_label = source_inst.label or source_inst.node_type

        if source_inst.node_type == _START_TYPE:
            for e in edges:
                tgt = instance_map.get(e.target)
                details.append({
                    "source": source_id,
                    "source_label": "START",
                    "target": e.target,
                    "target_label": tgt.label if tgt else e.target,
                    "port": "default",
                    "wiring": "start",
                    "description": f"Graph entry → {tgt.label if tgt else e.target}",
                })
            continue

        if source_inst.node_type == _END_TYPE:
            continue

        # Check multi-target
        distinct_targets = {e.target for e in edges}
        is_conditional = len(distinct_targets) > 1

        if is_conditional:
            # Build edge map description
            base = node_type_map.get(source_id)
            has_router = base and base.get_routing_function(source_inst.config) is not None

            details.append({
                "source": source_id,
                "source_label": source_label,
                "target": None,
                "target_label": None,
                "port": None,
                "wiring": "conditional",
                "has_routing_function": has_router,
                "description": f"Conditional routing from \"{source_label}\" ({len(edges)} branches)",
                "branches": [
                    {
                        "port": e.source_port or "default",
                        "target": e.target,
                        "target_label": (instance_map.get(e.target) or WorkflowNodeInstance(node_type="?")).label or _resolve_end(e.target, instance_map),
                        "label": e.label,
                    }
                    for e in edges
                ],
            })
        else:
            for e in edges:
                tgt = instance_map.get(e.target)
                tgt_label = tgt.label if tgt else e.target
                if tgt and tgt.node_type == _END_TYPE:
                    tgt_label = "END"
                details.append({
                    "source": source_id,
                    "source_label": source_label,
                    "target": e.target,
                    "target_label": tgt_label,
                    "port": e.source_port or "default",
                    "wiring": "simple",
                    "description": f"\"{source_label}\" → \"{tgt_label}\"",
                })

    return details


def _resolve_end(target_id: str, instance_map: Dict[str, WorkflowNodeInstance]) -> str:
    inst = instance_map.get(target_id)
    if inst and inst.node_type == _END_TYPE:
        return "END"
    return inst.label if inst else target_id


# ====================================================================
# Code generator
# ====================================================================


def _generate_code(
    workflow: WorkflowDefinition,
    instance_map: Dict[str, WorkflowNodeInstance],
    node_type_map: Dict[str, BaseNode],
    edges_by_source: Dict[str, List[WorkflowEdge]],
) -> str:
    """Generate Python pseudo-code for the compiled graph."""
    lines: List[str] = []

    real_nodes = [n for n in workflow.nodes if n.node_type not in (_START_TYPE, _END_TYPE)]
    total_edges = sum(len(e) for e in edges_by_source.values())

    # Header
    lines.append("# " + "═" * 60)
    lines.append(f"# Compiled Graph: {workflow.name}")
    lines.append(f"# Nodes: {len(real_nodes)} | Edges: {total_edges}")
    lines.append("# " + "═" * 60)
    lines.append("")
    lines.append("from langgraph.graph import END, START, StateGraph")
    lines.append("from langgraph.graph.state import CompiledStateGraph")
    lines.append("from service.langgraph.state import AutonomousState")
    lines.append("")
    lines.append("graph = StateGraph(AutonomousState)")
    lines.append("")

    # ── Node Registration ──
    lines.append("# " + "─" * 60)
    lines.append("# Node Registration")
    lines.append("# " + "─" * 60)
    lines.append("")

    for inst in workflow.nodes:
        if inst.node_type in (_START_TYPE, _END_TYPE):
            continue

        base = node_type_map.get(inst.id)
        if not base:
            lines.append(f"# [{inst.id}] {inst.label}  — UNKNOWN TYPE: {inst.node_type}")
            lines.append("")
            continue

        # Output ports
        ports = base.output_ports
        dynamic = base.get_dynamic_output_ports(inst.config)
        if dynamic is not None:
            ports = dynamic

        is_conditional = len(ports) > 1
        label = inst.label or base.label

        lines.append(f"# [{inst.id}] {label}  ({inst.node_type})")

        # Short description
        desc = base.description
        if desc and len(desc) > 100:
            desc = desc[:100] + "…"
        lines.append(f"#   {desc}")

        # Config highlights
        important_keys = _get_important_config_keys(base)
        if important_keys:
            cfg_parts = []
            for key in important_keys:
                val = inst.config.get(key)
                if val is not None:
                    val_str = json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else f'"{val}"'
                    if len(val_str) > 60:
                        val_str = val_str[:60] + "…"
                    cfg_parts.append(f"{key}={val_str}")
            if cfg_parts:
                lines.append(f"#   Config: {', '.join(cfg_parts)}")

        if is_conditional:
            port_desc = " | ".join(f"{p.id} → {p.label}" for p in ports)
            lines.append(f"#   Ports: {port_desc}")

        # Generate the node function description
        lines.append(f"#")
        lines.append(f"# async def {inst.id}_fn(state: AutonomousState) -> dict:")
        lines.append(f"#     \"\"\"Wraps {base.__class__.__name__}.execute(state, ctx, config)\"\"\"")

        # Show key input/output fields
        input_fields = _get_input_fields(base, inst.config)
        output_fields = _get_output_fields(base, inst.config)
        if input_fields:
            lines.append(f"#     # Reads:  {', '.join(f'state[\"{f}\"]' for f in input_fields)}")
        if output_fields:
            lines.append(f"#     # Writes: {', '.join(f'state[\"{f}\"]' for f in output_fields)}")

        lines.append(f"#     result = await {base.node_type}_node.execute(state, ctx, config)")
        lines.append(f"#     return result")

        lines.append(f"graph.add_node(\"{inst.id}\", {inst.id}_fn)")
        lines.append("")

    # ── Edge Wiring ──
    lines.append("")
    lines.append("# " + "─" * 60)
    lines.append("# Edge Wiring")
    lines.append("# " + "─" * 60)
    lines.append("")

    for source_id, edges in edges_by_source.items():
        source_inst = instance_map.get(source_id)
        if not source_inst:
            continue

        source_label = source_inst.label or source_inst.node_type

        # START
        if source_inst.node_type == _START_TYPE:
            if edges:
                tgt = edges[0].target
                tgt_inst = instance_map.get(tgt)
                tgt_ref = "END" if (tgt_inst and tgt_inst.node_type == _END_TYPE) else f'"{tgt}"'
                lines.append(f"# START → {tgt_inst.label if tgt_inst else tgt}")
                lines.append(f'graph.add_edge(START, {tgt_ref})')
                lines.append("")
            continue

        if source_inst.node_type == _END_TYPE:
            continue

        base = node_type_map.get(source_id)
        if not base:
            continue

        distinct_targets = {e.target for e in edges}
        is_conditional = len(distinct_targets) > 1

        if is_conditional:
            # Build edge_map
            edge_map_items = []
            for e in edges:
                tgt_inst = instance_map.get(e.target)
                port = e.source_port or "default"
                if tgt_inst and tgt_inst.node_type == _END_TYPE:
                    tgt_ref = "END"
                else:
                    tgt_ref = f'"{e.target}"'
                edge_map_items.append((port, tgt_ref, e.label))

            has_router = base.get_routing_function(source_inst.config) is not None

            lines.append(f"# {source_label} → conditional routing ({len(edges)} branches)")
            if has_router:
                lines.append(f"# Uses {base.__class__.__name__}.get_routing_function()")
                # Generate routing pseudocode
                routing_code = _generate_routing_pseudocode(
                    base, source_inst, instance_map, edges,
                )
                for rc_line in routing_code:
                    lines.append(rc_line)
            else:
                lines.append(f"# Uses fallback router (first port: \"{edges[0].source_port or 'default'}\")")
                lines.append(f"def {source_id}_router(state):")
                lines.append(f'    return "{edges[0].source_port or "default"}"  # fallback')

            lines.append("")

            # Edge map
            lines.append(f"graph.add_conditional_edges(\"{source_id}\", {source_id}_router, {{")
            for port, tgt_ref, lbl in edge_map_items:
                comment = f"  # {lbl}" if lbl else ""
                lines.append(f'    "{port}": {tgt_ref},{comment}')
            lines.append(f"}})")
            lines.append("")

        else:
            # Simple edge
            tgt = edges[0].target
            tgt_inst = instance_map.get(tgt)
            tgt_label = tgt_inst.label if tgt_inst else tgt
            if tgt_inst and tgt_inst.node_type == _END_TYPE:
                tgt_ref = "END"
                tgt_label = "END"
            else:
                tgt_ref = f'"{tgt}"'
            lines.append(f"# {source_label} → {tgt_label}")
            lines.append(f'graph.add_edge("{source_id}", {tgt_ref})')
            lines.append("")

    # ── Compile ──
    lines.append("")
    lines.append("# " + "─" * 60)
    lines.append("# Compile")
    lines.append("# " + "─" * 60)
    lines.append("")
    lines.append("compiled_graph: CompiledStateGraph = graph.compile()")
    lines.append("")
    lines.append(f'# Ready to execute: result = await compiled_graph.ainvoke(initial_state)')

    return "\n".join(lines)


def _generate_routing_pseudocode(
    base: BaseNode,
    inst: WorkflowNodeInstance,
    instance_map: Dict[str, WorkflowNodeInstance],
    edges: List[WorkflowEdge],
) -> List[str]:
    """Generate pseudo-code for a routing function."""
    lines: List[str] = []
    ntype = base.node_type
    config = inst.config

    if ntype == "classify":
        field = config.get("output_field", "difficulty")
        cats = config.get("categories", '["easy","medium","hard"]')
        lines.append(f"def {inst.id}_router(state):")
        lines.append(f'    """Route by {field} field."""')
        lines.append(f'    value = state.get("{field}", "").strip().lower()')
        lines.append(f"    categories = {cats}")
        lines.append(f"    if value in categories:")
        lines.append(f"        return value")
        lines.append(f'    return "end"  # default')
        return lines

    if ntype == "review":
        field = config.get("output_field", "review_result")
        verdicts = config.get("verdicts", '["approved","retry"]')
        default = config.get("default_verdict", "retry")
        lines.append(f"def {inst.id}_router(state):")
        lines.append(f'    """Route by {field} verdict."""')
        lines.append(f'    if state.get("error"):')
        lines.append(f'        return "end"')
        lines.append(f'    if state.get("is_complete"):')
        lines.append(f'        value = state.get("{field}", "").lower()')
        lines.append(f"        verdicts = {verdicts}")
        lines.append(f"        if value in verdicts:")
        lines.append(f"            return value")
        lines.append(f'        return verdicts[0]  # force first verdict')
        lines.append(f'    value = state.get("{field}", "").lower()')
        lines.append(f"    verdicts = {verdicts}")
        lines.append(f"    if value in verdicts:")
        lines.append(f"        return value")
        lines.append(f'    return "{default}"  # default verdict')
        return lines

    if ntype == "conditional_router":
        field = config.get("routing_field", "")
        route_map = config.get("route_map", {})
        default = config.get("default_port", "default")
        lines.append(f"def {inst.id}_router(state):")
        lines.append(f'    """Route by state["{field}"]."""')
        lines.append(f'    value = str(state.get("{field}", "")).strip().lower()')
        lines.append(f"    route_map = {json.dumps(route_map, ensure_ascii=False)}")
        lines.append(f"    if value in route_map:")
        lines.append(f"        return route_map[value]")
        lines.append(f'    return "{default}"  # default')
        return lines

    if ntype == "check_progress":
        lines.append(f"def {inst.id}_router(state):")
        lines.append(f'    """Route by TODO progress."""')
        lines.append(f'    if state.get("is_complete") or state.get("completion_signal") == "COMPLETE":')
        lines.append(f'        return "complete"')
        lines.append(f'    return "continue"')
        return lines

    if ntype == "iteration_gate":
        max_iter = config.get("max_iterations", 5)
        lines.append(f"def {inst.id}_router(state):")
        lines.append(f'    """Iteration gate (max={max_iter})."""')
        lines.append(f'    iteration = state.get("iteration", 0)')
        lines.append(f'    if state.get("is_complete") or iteration >= {max_iter}:')
        lines.append(f'        return "stop"')
        lines.append(f'    return "continue"')
        return lines

    # Generic fallback
    lines.append(f"def {inst.id}_router(state):")
    lines.append(f'    """Custom routing for {ntype}."""')
    lines.append(f"    # Node-specific routing logic")
    lines.append(f'    return "default"')
    return lines


# ====================================================================
# Helpers — infer input/output state fields
# ====================================================================


def _get_important_config_keys(base: BaseNode) -> List[str]:
    """Return parameter names that are most informative for the code view."""
    skip = {"prompt_template"}
    return [
        p.name for p in base.parameters
        if p.name not in skip and p.generates_ports
    ] + [
        p.name for p in base.parameters
        if p.name not in skip and not p.generates_ports
           and p.name in (
               "output_field", "routing_field", "route_map", "default_port",
               "categories", "verdicts", "default_verdict", "max_retries",
               "max_iterations", "answer_field", "count_field",
               "detect_completion", "set_complete",
           )
    ]


def _get_input_fields(base: BaseNode, config: Dict[str, Any]) -> List[str]:
    """Infer which state fields a node reads."""
    ntype = base.node_type
    fields: List[str] = []

    if ntype in ("classify", "direct_answer", "answer", "llm_call"):
        fields.append("input")
        fields.append("messages")
    elif ntype == "review":
        fields.extend(["input", config.get("answer_field", "answer"),
                        config.get("count_field", "review_count")])
    elif ntype in ("final_review", "final_answer"):
        fields.extend(["input", "messages", "todo_results"])
    elif ntype == "execute_todo":
        fields.extend(["input", "todos", "current_todo_index"])
    elif ntype == "create_todos":
        fields.append("input")
    elif ntype == "memory_inject":
        fields.extend(["input", "messages"])
    elif ntype == "context_guard":
        fields.append("messages")
    elif ntype == "post_model":
        fields.extend(["messages", "last_output", "completion_signal"])
    elif ntype == "check_progress":
        fields.extend(["todos", "current_todo_index"])
    elif ntype == "iteration_gate":
        fields.extend(["iteration", "is_complete"])
    elif ntype == "conditional_router":
        rf = config.get("routing_field", "")
        if rf:
            fields.append(rf)
    elif ntype == "state_setter":
        pass  # writes only

    return fields


def _get_output_fields(base: BaseNode, config: Dict[str, Any]) -> List[str]:
    """Infer which state fields a node writes."""
    ntype = base.node_type
    fields: List[str] = []

    if ntype == "classify":
        fields.append(config.get("output_field", "difficulty"))
    elif ntype == "review":
        fields.extend([config.get("output_field", "review_result"),
                        "review_feedback",
                        config.get("count_field", "review_count")])
    elif ntype == "direct_answer":
        fields.extend(["direct_answer", "final_answer", "is_complete"])
    elif ntype == "answer":
        fields.extend(["answer", "last_output"])
    elif ntype in ("final_review", "final_answer"):
        fields.extend(["last_output", "messages"])
    elif ntype == "llm_call":
        of = config.get("output_field", "last_output")
        fields.append(of)
        if config.get("set_complete"):
            fields.append("is_complete")
    elif ntype == "create_todos":
        fields.extend(["todos", "current_todo_index"])
    elif ntype == "execute_todo":
        fields.extend(["todo_results", "current_todo_index"])
    elif ntype == "memory_inject":
        fields.append("messages")
    elif ntype == "context_guard":
        fields.append("messages")
    elif ntype == "post_model":
        fields.extend(["iteration", "messages", "is_complete"])
    elif ntype == "check_progress":
        fields.extend(["current_todo_index"])
    elif ntype == "iteration_gate":
        fields.extend(["iteration"])
    elif ntype == "state_setter":
        # Dynamic from config
        updates = config.get("state_updates", {})
        if isinstance(updates, dict):
            fields.extend(updates.keys())

    return fields
