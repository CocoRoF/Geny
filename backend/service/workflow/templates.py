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

    Node positions are hand-tuned for optimal readability in the visual editor.
    """

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

    # ── START & Common Entry ──
    _add("start",         "start",      "Start",             288, 160)
    _add("memory_inject", "mem_inject", "Memory Inject",     288, 256)
    _add("context_guard", "guard_cls",  "Guard (Classify)",  288, 368,
         {"position_label": "classify"})
    _add("classify",      "classify",   "Classify",          288, 480)

    _edge("start", "mem_inject")
    _edge("mem_inject", "guard_cls")
    _edge("guard_cls", "classify")

    # ── EASY PATH ──
    _add("context_guard", "guard_dir", "Guard (Direct)",  32, 688,
         {"position_label": "direct"})
    _add("direct_answer", "dir_ans",   "Direct Answer",   32, 800)
    _add("post_model",    "post_dir",  "Post Direct",     32, 928)

    _edge("guard_dir", "dir_ans")
    _edge("dir_ans", "post_dir")

    # ── MEDIUM PATH ──
    _add("context_guard", "guard_ans", "Guard (Answer)",       304, 688,
         {"position_label": "answer"})
    _add("answer",        "answer",    "Answer",               304, 784)
    _add("post_model",    "post_ans",  "Post Answer",          304, 880,
         {"detect_completion": False})
    _add("context_guard", "guard_rev", "Guard (Review)",       304, 976,
         {"position_label": "review"})
    _add("review",        "review",    "Review",               304, 1120)
    _add("iteration_gate","gate_med",  "Iter Gate (Medium)",   304, 1424)

    _edge("guard_ans", "answer")
    _edge("answer", "post_ans")
    _edge("post_ans", "guard_rev")
    _edge("guard_rev", "review")

    # ── HARD PATH ──
    _add("context_guard", "guard_todo", "Guard (Todos)",        560, 688,
         {"position_label": "create_todos"})
    _add("create_todos",  "mk_todos",  "Create TODOs",         880, 688)
    _add("post_model",    "post_todos", "Post Create Todos",    560, 832,
         {"detect_completion": False})
    _add("context_guard", "guard_exec", "Guard (Execute)",      944, 1184,
         {"position_label": "execute"})
    _add("execute_todo",  "exec_todo",  "Execute TODO",         560, 960)
    _add("post_model",    "post_exec",  "Post Execute",         560, 1104)
    _add("check_progress","chk_prog",   "Check Progress",       560, 1248)
    _add("iteration_gate","gate_hard",  "Iter Gate (Hard)",     960, 1424)
    _add("context_guard", "guard_fr",   "Guard (Final Review)", 576, 1504,
         {"position_label": "final_review"})
    _add("final_review",  "fin_rev",    "Final Review",         576, 1600)
    _add("post_model",    "post_fr",    "Post Final Review",    576, 1712)
    _add("context_guard", "guard_fa",   "Guard (Final Answer)", 576, 1808,
         {"position_label": "final_answer"})
    _add("final_answer",  "fin_ans",    "Final Answer",         576, 1904)
    _add("post_model",    "post_fa",    "Post Final Answer",    576, 2000)

    _edge("guard_todo", "mk_todos")
    _edge("mk_todos", "post_todos")
    _edge("post_todos", "guard_exec")
    _edge("guard_exec", "exec_todo")
    _edge("exec_todo", "post_exec")
    _edge("post_exec", "chk_prog")

    # ── END NODE ──
    _add("end", "end", "End", 64, 2144)

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
            position={"x": 400, "y": 0},
        ),
        WorkflowNodeInstance(
            id="mem", node_type="memory_inject", label="Memory Inject",
            position={"x": 400, "y": 96},
        ),
        WorkflowNodeInstance(
            id="guard", node_type="context_guard", label="Context Guard",
            position={"x": 400, "y": 192},
            config={"position_label": "main"},
        ),
        WorkflowNodeInstance(
            id="llm", node_type="llm_call", label="LLM Call",
            position={"x": 400, "y": 304},
            config={"prompt_template": "{input}", "output_field": "last_output", "set_complete": True},
        ),
        WorkflowNodeInstance(
            id="post", node_type="post_model", label="Post Model",
            position={"x": 400, "y": 416},
        ),
        WorkflowNodeInstance(
            id="end", node_type="end", label="End",
            position={"x": 400, "y": 544},
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
