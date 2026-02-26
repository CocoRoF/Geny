"""
Pre-built Workflow Templates.

Provides factory functions that return ready-made
``WorkflowDefinition`` objects replicating the built-in
graph topologies (e.g. the 28-node autonomous graph).

These templates are saved to the WorkflowStore on first
startup so users can clone or study them.
"""

from __future__ import annotations

from typing import List

from service.workflow.workflow_model import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNodeInstance,
)
from service.prompt.sections import AutonomousPrompts


# ============================================================================
# Autonomous Workflow Template (mirrors AutonomousGraph topology)
# ============================================================================


def create_autonomous_template() -> WorkflowDefinition:
    """Build the full autonomous graph as a WorkflowDefinition.

    Topology::
        START → memory_inject → guard_classify → classify
          ↓ [easy / medium / hard / end]  (classify routes directly)

        EASY:   guard_direct → direct_answer → post_direct → END
        MEDIUM: guard_answer → answer → post_answer → guard_review
                → review → [approved→END | retry→iter_gate_medium | end→END]
                iter_gate_medium → [continue→guard_answer | stop→END]
        HARD:   guard_create_todos → create_todos → post_create_todos
                → guard_execute → execute_todo → post_execute → check_progress
                → [continue→iter_gate_hard | complete→guard_final_review]
                iter_gate_hard → [continue→guard_execute | stop→guard_final_review]
                → final_review → post_final_review
                → guard_final_answer → final_answer → post_final_answer → END
    """

    # Layout constants
    col_w = 260
    step_h = 140
    branch_gap = 220
    col_easy_x = 40
    col_medium_x = 40 + col_w
    col_hard_x = 40 + col_w * 2
    top_center_x = col_medium_x
    padding = 40

    nodes: List[WorkflowNodeInstance] = []
    edges: List[WorkflowEdge] = []

    def _add(ntype: str, nid: str, label: str, x: float, y: float, cfg=None):
        nodes.append(WorkflowNodeInstance(
            id=nid, node_type=ntype, label=label,
            position={"x": x, "y": y}, config=cfg or {},
        ))

    def _edge(src: str, tgt: str, port: str = "default", lbl: str = ""):
        edges.append(WorkflowEdge(
            source=src, target=tgt, source_port=port, label=lbl,
        ))

    y = padding

    # ── START ──
    _add("start", "start", "Start", top_center_x, y)
    y += step_h

    # ── Common entry ──
    _add("memory_inject", "mem_inject", "Memory Inject", top_center_x, y)
    y += step_h
    _add("context_guard", "guard_cls", "Guard (Classify)",
         top_center_x, y, {"position_label": "classify"})
    y += step_h
    _add("classify", "classify", "Classify", top_center_x, y)
    branch_base = y + branch_gap

    # Edges: common entry chain
    _edge("start", "mem_inject")
    _edge("mem_inject", "guard_cls")
    _edge("guard_cls", "classify")

    # ── EASY PATH ──
    y = branch_base
    _add("context_guard", "guard_dir", "Guard (Direct)",
         col_easy_x, y, {"position_label": "direct"})
    y += step_h
    _add("direct_answer", "dir_ans", "Direct Answer", col_easy_x, y)
    y += step_h
    _add("post_model", "post_dir", "Post Direct", col_easy_x, y)
    y += step_h

    _edge("guard_dir", "dir_ans")
    _edge("dir_ans", "post_dir")

    # ── MEDIUM PATH ──
    y = branch_base
    _add("context_guard", "guard_ans", "Guard (Answer)",
         col_medium_x, y, {"position_label": "answer"})
    y += step_h
    _add("answer", "answer", "Answer", col_medium_x, y)
    y += step_h
    _add("post_model", "post_ans", "Post Answer",
         col_medium_x, y, {"detect_completion": False})
    y += step_h
    _add("context_guard", "guard_rev", "Guard (Review)",
         col_medium_x, y, {"position_label": "review"})
    y += step_h
    _add("review", "review", "Review", col_medium_x, y)
    y += step_h
    _add("iteration_gate", "gate_med", "Iter Gate (Medium)", col_medium_x, y)
    y += step_h

    _edge("guard_ans", "answer")
    _edge("answer", "post_ans")
    _edge("post_ans", "guard_rev")
    _edge("guard_rev", "review")

    # ── HARD PATH ──
    y = branch_base
    _add("context_guard", "guard_todo", "Guard (Todos)",
         col_hard_x, y, {"position_label": "create_todos"})
    y += step_h
    _add("create_todos", "mk_todos", "Create TODOs", col_hard_x, y)
    y += step_h
    _add("post_model", "post_todos", "Post Create Todos",
         col_hard_x, y, {"detect_completion": False})
    y += step_h
    _add("context_guard", "guard_exec", "Guard (Execute)",
         col_hard_x, y, {"position_label": "execute"})
    y += step_h
    _add("execute_todo", "exec_todo", "Execute TODO", col_hard_x, y)
    y += step_h
    _add("post_model", "post_exec", "Post Execute", col_hard_x, y)
    y += step_h
    _add("check_progress", "chk_prog", "Check Progress", col_hard_x, y)
    y += step_h
    _add("iteration_gate", "gate_hard", "Iter Gate (Hard)", col_hard_x, y)
    y += step_h
    _add("context_guard", "guard_fr", "Guard (Final Review)",
         col_hard_x, y, {"position_label": "final_review"})
    y += step_h
    _add("final_review", "fin_rev", "Final Review", col_hard_x, y)
    y += step_h
    _add("post_model", "post_fr", "Post Final Review", col_hard_x, y)
    y += step_h
    _add("context_guard", "guard_fa", "Guard (Final Answer)",
         col_hard_x, y, {"position_label": "final_answer"})
    y += step_h
    _add("final_answer", "fin_ans", "Final Answer", col_hard_x, y)
    y += step_h
    _add("post_model", "post_fa", "Post Final Answer", col_hard_x, y)
    y += step_h

    _edge("guard_todo", "mk_todos")
    _edge("mk_todos", "post_todos")
    _edge("post_todos", "guard_exec")
    _edge("guard_exec", "exec_todo")
    _edge("exec_todo", "post_exec")
    _edge("post_exec", "chk_prog")

    # ── END NODE ──
    max_y = max(n.position["y"] for n in nodes) + branch_gap
    _add("end", "end", "End", top_center_x, max_y)

    # ── Conditional routing: classify → branches (direct routing) ──
    _edge("classify", "guard_dir", port="easy", lbl="Easy")
    _edge("classify", "guard_ans", port="medium", lbl="Medium")
    _edge("classify", "guard_todo", port="hard", lbl="Hard")
    _edge("classify", "end", port="end", lbl="End")

    # Easy → END
    _edge("post_dir", "end")

    # Medium review self-routing (Review is now a conditional self-router)
    _edge("review", "end", port="approved", lbl="Approved")
    _edge("review", "gate_med", port="retry", lbl="Retry")
    _edge("review", "end", port="end", lbl="End")

    # Medium iteration gate
    _edge("gate_med", "guard_ans", port="continue", lbl="Continue")
    _edge("gate_med", "end", port="stop", lbl="Stop")

    # Hard progress check routing
    _edge("chk_prog", "gate_hard", port="continue", lbl="Continue")
    _edge("chk_prog", "guard_fr", port="complete", lbl="Complete")

    # Hard iteration gate
    _edge("gate_hard", "guard_exec", port="continue", lbl="Continue")
    _edge("gate_hard", "guard_fr", port="stop", lbl="Stop")

    # Hard final chain
    _edge("guard_fr", "fin_rev")
    _edge("fin_rev", "post_fr")
    _edge("post_fr", "guard_fa")
    _edge("guard_fa", "fin_ans")
    _edge("fin_ans", "post_fa")
    _edge("post_fa", "end")

    return WorkflowDefinition(
        id="template-autonomous",
        name="Autonomous Difficulty-Based",
        description=(
            "Full autonomous execution graph with difficulty classification, "
            "easy/medium/hard paths, review loops, TODO management, "
            "and resilience infrastructure."
        ),
        nodes=nodes,
        edges=edges,
        is_template=True,
        template_name="autonomous",
    )


# ============================================================================
# Simple Agent Template
# ============================================================================


def create_simple_template() -> WorkflowDefinition:
    """Build a simple agent loop: guard → llm_call → post_model → END."""

    nodes = [
        WorkflowNodeInstance(
            id="start", node_type="start", label="Start",
            position={"x": 400, "y": 40},
        ),
        WorkflowNodeInstance(
            id="mem", node_type="memory_inject", label="Memory Inject",
            position={"x": 400, "y": 120},
        ),
        WorkflowNodeInstance(
            id="guard", node_type="context_guard", label="Context Guard",
            position={"x": 400, "y": 200},
            config={"position_label": "main"},
        ),
        WorkflowNodeInstance(
            id="llm", node_type="llm_call", label="LLM Call",
            position={"x": 400, "y": 280},
            config={"prompt_template": "{input}", "output_field": "last_output", "set_complete": True},
        ),
        WorkflowNodeInstance(
            id="post", node_type="post_model", label="Post Model",
            position={"x": 400, "y": 360},
        ),
        WorkflowNodeInstance(
            id="end", node_type="end", label="End",
            position={"x": 400, "y": 440},
        ),
    ]

    edges = [
        WorkflowEdge(source="start", target="mem"),
        WorkflowEdge(source="mem", target="guard"),
        WorkflowEdge(source="guard", target="llm"),
        WorkflowEdge(source="llm", target="post"),
        WorkflowEdge(source="post", target="end"),
    ]

    return WorkflowDefinition(
        id="template-simple",
        name="Simple Agent",
        description="Basic agent loop: memory → guard → LLM call → post-processing → end.",
        nodes=nodes,
        edges=edges,
        is_template=True,
        template_name="simple",
    )


# ============================================================================
# Template Registry
# ============================================================================

ALL_TEMPLATES = [
    create_autonomous_template,
    create_simple_template,
]


def install_templates(store) -> int:
    """Install built-in templates into the workflow store.

    Always overwrites existing templates to keep them up-to-date.
    Returns the number of templates installed.
    """
    installed = 0
    for factory in ALL_TEMPLATES:
        template = factory()
        store.save(template)
        installed += 1
    return installed
