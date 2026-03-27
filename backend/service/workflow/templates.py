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
    _add("start",           "start",           "Start",              32, 112)
    _add("memory_inject",   "mem_inject",      "Memory Inject",     128, 224)
    _add("relevance_gate",  "relevance_gate",  "Relevance Gate",   -144, 224)
    _add("context_guard",   "guard_cls",       "Guard (Classify)",  128, 384,
         {"position_label": "classify"})
    _add("classify",        "classify",        "Classify",          288, 480)

    _edge("start", "mem_inject")
    _edge("mem_inject", "relevance_gate")
    _edge("relevance_gate", "guard_cls", port="continue", lbl="relevant")
    _edge("relevance_gate", "end",       port="skip",     lbl="not relevant")
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
# Optimized Autonomous Workflow Template
# ============================================================================


def create_optimized_autonomous_template() -> WorkflowDefinition:
    """Build the optimized autonomous graph as a WorkflowDefinition.

    Key optimizations over the standard autonomous template:
        • **P1** — AdaptiveClassify: rule-based fast path skips the LLM
          classify call for trivially-classifiable inputs (saves 8-15s).
        • **P2** — Guard/Post node reduction: removed 10 Guard/Post nodes
          that are unnecessary outside of loops.  The classify node now
          includes inline guard+post.  Guard/Post are retained only in
          the Medium retry loop and Hard execution loop where they are
          essential for context budget tracking and iteration counting.
        • **P3** — FinalSynthesis: merged FinalReview + FinalAnswer into
          a single LLM call, saving one full round-trip (10-20s).

    Topology (20 nodes, down from 28)::

        START → mem_inject → relevance_gate
          ├─ skip → END
          └─ continue → adaptive_classify  (inline guard + post)
              ├─ easy        → easy_answer (llm_call, single-shot) → END
              ├─ tool_direct → direct_tool (single-shot tool exec) → END
              ├─ medium      → answer → post_ans → review
              │    ├─ approved → END
              │    ├─ retry → gate_med → [continue→answer | stop→END]
              │    └─ end → END
              ├─ hard    → mk_todos → guard_exec → exec_todo → post_exec
              │    → chk_prog → [continue→gate_hard | complete→final_synth]
              │    gate_hard → [continue→guard_exec | stop→final_synth]
              │    final_synth → END
              ├─ extreme → mk_todos (same as hard: full TODO-based execution)
              └─ end → END
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

    # ── START & Common Entry (4 nodes) ──
    _add("start",              "start",           "Start",              0,   0)
    _add("memory_inject",      "mem_inject",      "Memory Inject",     0, 100)
    _add("relevance_gate",     "relevance_gate",  "Relevance Gate",    0, 200)
    _add("adaptive_classify",  "classify",        "Adaptive Classify", 0, 350)

    _edge("start", "mem_inject")
    _edge("mem_inject", "relevance_gate")
    _edge("relevance_gate", "classify",  port="continue", lbl="relevant")
    _edge("relevance_gate", "end",       port="skip",     lbl="not relevant")

    # ── EASY PATH (1 node) ──
    # llm_call with set_complete=true replaces direct_answer + guard + post
    _add("llm_call", "easy_answer", "Easy Answer", -200, 550, {
        "prompt_template": "{input}",
        "output_field": "final_answer",
        "output_mappings": '{"answer": true}',
        "set_complete": True,
    })

    _edge("easy_answer", "end")

    # ── TOOL_DIRECT PATH (1 node) ──
    # Single-shot tool execution — the task IS the tool operation.
    _add("direct_tool", "direct_tool", "Direct Tool", -400, 550)
    _edge("direct_tool", "end")

    # ── MEDIUM PATH (4 nodes) ──
    # Removed guard_ans (not in loop first pass) and guard_rev.
    # Kept post_ans for iteration tracking in retry loop.
    _add("answer",         "answer",   "Answer",               0, 550)
    _add("post_model",     "post_ans", "Post Answer",          0, 650, {
        "detect_completion": False,
    })
    _add("review",         "review",   "Review",               0, 800)
    _add("iteration_gate", "gate_med", "Iter Gate (Medium)",   0, 1000)

    _edge("answer", "post_ans")
    _edge("post_ans", "review")

    # Review routing (self-routing conditional node)
    _edge("review", "end",      port="approved", lbl="Approved")
    _edge("review", "gate_med", port="retry",    lbl="Retry")
    _edge("review", "end",      port="end",      lbl="End")

    # Medium iteration gate
    _edge("gate_med", "answer",  port="continue", lbl="Continue")
    _edge("gate_med", "end",     port="stop",     lbl="Stop")

    # ── HARD PATH (7 nodes) ──
    # Removed guard_todo, post_todos.  Kept guard_exec + post_exec for loop.
    # Replaced 6-node final chain with single final_synthesis.
    _add("create_todos",    "mk_todos",      "Create TODOs",    200, 550)
    _add("context_guard",   "guard_exec",    "Guard (Execute)", 200, 700, {
        "position_label": "execute",
    })
    _add("execute_todo",    "exec_todo",     "Execute TODO",    200, 800)
    _add("post_model",      "post_exec",     "Post Execute",    200, 900)
    _add("check_progress",  "chk_prog",      "Check Progress",  200, 1000)
    _add("iteration_gate",  "gate_hard",     "Iter Gate (Hard)", 200, 1150)
    _add("final_synthesis", "final_synth",   "Final Synthesis",  200, 1350)

    _edge("mk_todos", "guard_exec")
    _edge("guard_exec", "exec_todo")
    _edge("exec_todo", "post_exec")
    _edge("post_exec", "chk_prog")

    # Hard progress check routing
    _edge("chk_prog", "gate_hard",    port="continue", lbl="Continue")
    _edge("chk_prog", "final_synth",  port="complete", lbl="Complete")

    # Hard iteration gate
    _edge("gate_hard", "guard_exec",  port="continue", lbl="Continue")
    _edge("gate_hard", "final_synth", port="stop",     lbl="Stop")

    _edge("final_synth", "end")

    # ── END NODE ──
    _add("end", "end", "End", 0, 1500)

    # ── Conditional routing: adaptive_classify → 5 branches ──
    _edge("classify", "easy_answer",  port="easy",        lbl="Easy")
    _edge("classify", "direct_tool",  port="tool_direct", lbl="Tool Direct")
    _edge("classify", "answer",       port="medium",      lbl="Medium")
    _edge("classify", "mk_todos",     port="hard",        lbl="Hard")
    _edge("classify", "mk_todos",     port="extreme",     lbl="Extreme")
    _edge("classify", "end",          port="end",         lbl="End")

    return WorkflowDefinition(
        id="template-optimized-autonomous",
        name="Optimized Autonomous",
        description=(
            "Optimized autonomous execution graph. "
            "5-level difficulty classification (easy/tool_direct/medium/hard/extreme). "
            "Rule-based adaptive classify (skips LLM for easy inputs), "
            "reduced Guard/Post nodes, "
            "merged FinalSynthesis (review + answer in one LLM call). "
            "20 nodes (vs 28 original), ~25-47% faster."
        ),
        nodes=nodes,
        edges=edges,
        is_template=True,
        template_name="optimized-autonomous",
    )


# ============================================================================
# Ultra-Light Autonomous Workflow Template
# ============================================================================


def create_ultra_light_template() -> WorkflowDefinition:
    """Build the ultra-light autonomous graph with 5-level difficulty paths.

    Adds two new difficulty levels (tool_direct, extreme) so the right
    amount of LLM budget is allocated per task complexity.

    Topology (21 nodes)::

        START → mem_inject → relevance_gate
          ├─ skip → END
          └─ continue → adaptive_classify (5-level)
              ├─ easy        → easy_answer (llm_call, 1 LLM) → END
              ├─ tool_direct → direct_tool (1 LLM + tool) → END
              ├─ medium      → answer → post_ans → review
              │    ├─ approved → END
              │    ├─ retry → gate_med → [continue→answer | stop→END]
              │    └─ end → END
              ├─ hard        → mk_todos_h → batch_exec → final_synth_h → END
              ├─ extreme     → mk_todos_e → guard_exec → exec_todo
              │    → post_exec → chk_prog
              │    → [continue→gate_ext→guard_exec | complete→final_synth_e]
              │    gate_ext → [continue→guard_exec | stop→final_synth_e]
              │    final_synth_e → END
              └─ end → END

    Path LLM-call counts (typical):
        easy=1, tool_direct=1, medium=2-3, hard=2-3, extreme=N+2
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

    # ── START & Common Entry (4 nodes) ──
    _add("start",             "start",          "Start",              250,   0)
    _add("memory_inject",     "mem_inject",     "Memory Inject",     250, 100)
    _add("relevance_gate",    "relevance_gate", "Relevance Gate",    250, 200)
    _add("adaptive_classify", "classify",       "Adaptive Classify", 250, 350)

    _edge("start", "mem_inject")
    _edge("mem_inject", "relevance_gate")
    _edge("relevance_gate", "classify", port="continue", lbl="relevant")
    _edge("relevance_gate", "end",      port="skip",     lbl="not relevant")

    # ── EASY PATH (1 node) ──
    _add("llm_call", "easy_answer", "Easy Answer", -100, 550, {
        "prompt_template": "{input}",
        "output_field": "final_answer",
        "output_mappings": '{"answer": true}',
        "set_complete": True,
    })
    _edge("easy_answer", "end")

    # ── TOOL_DIRECT PATH (1 node) ──
    _add("direct_tool", "direct_tool", "Direct Tool", 50, 550)
    _edge("direct_tool", "end")

    # ── MEDIUM PATH (4 nodes) ──
    _add("answer",         "answer",   "Answer",             200, 550)
    _add("post_model",     "post_ans", "Post Answer",        200, 650,
         {"detect_completion": False})
    _add("review",         "review",   "Review",             200, 800)
    _add("iteration_gate", "gate_med", "Iter Gate (Medium)", 200, 1000)

    _edge("answer", "post_ans")
    _edge("post_ans", "review")
    _edge("review", "end",      port="approved", lbl="Approved")
    _edge("review", "gate_med", port="retry",    lbl="Retry")
    _edge("review", "end",      port="end",      lbl="End")
    _edge("gate_med", "answer", port="continue",  lbl="Continue")
    _edge("gate_med", "end",    port="stop",      lbl="Stop")

    # ── HARD PATH (3 nodes) ──
    _add("create_todos",      "mk_todos_h",    "Create TODOs (H)",  400, 550)
    _add("batch_execute_todo", "batch_exec",    "Batch Execute",     400, 700)
    _add("final_synthesis",   "final_synth_h",  "Final Synth (H)",   400, 850,
         {"skip_threshold": 3})

    _edge("mk_todos_h", "batch_exec")
    _edge("batch_exec", "final_synth_h")
    _edge("final_synth_h", "end")

    # ── EXTREME PATH (7 nodes) ──
    _add("create_todos",   "mk_todos_e",  "Create TODOs (E)",  600, 550)
    _add("context_guard",  "guard_exec",  "Guard (Execute)",   600, 700,
         {"position_label": "execute"})
    _add("execute_todo",   "exec_todo",   "Execute TODO",      600, 800)
    _add("post_model",     "post_exec",   "Post Execute",      600, 900)
    _add("check_progress", "chk_prog",    "Check Progress",    600, 1000)
    _add("iteration_gate", "gate_ext",    "Iter Gate (Ext)",   600, 1150)
    _add("final_synthesis","final_synth_e","Final Synth (E)",   600, 1350)

    _edge("mk_todos_e", "guard_exec")
    _edge("guard_exec", "exec_todo")
    _edge("exec_todo", "post_exec")
    _edge("post_exec", "chk_prog")
    _edge("chk_prog", "gate_ext",      port="continue", lbl="Continue")
    _edge("chk_prog", "final_synth_e", port="complete", lbl="Complete")
    _edge("gate_ext", "guard_exec",    port="continue", lbl="Continue")
    _edge("gate_ext", "final_synth_e", port="stop",     lbl="Stop")
    _edge("final_synth_e", "end")

    # ── END NODE ──
    _add("end", "end", "End", 250, 1500)

    # ── Conditional routing: classify → 5 branches ──
    _edge("classify", "easy_answer",  port="easy",        lbl="Easy")
    _edge("classify", "direct_tool",  port="tool_direct", lbl="Tool Direct")
    _edge("classify", "answer",       port="medium",      lbl="Medium")
    _edge("classify", "mk_todos_h",   port="hard",        lbl="Hard")
    _edge("classify", "mk_todos_e",   port="extreme",     lbl="Extreme")
    _edge("classify", "end",          port="end",         lbl="End")

    return WorkflowDefinition(
        id="template-ultra-light",
        name="Ultra-Light Autonomous",
        description=(
            "5-level difficulty classification (easy/tool_direct/medium/"
            "hard/extreme). Minimizes LLM calls: easy=1, tool_direct=1, "
            "medium=2-3, hard=2-3 (batch TODO), extreme=N+2 (full loop). "
            "Pre-warming + skip_threshold further reduce latency."
        ),
        nodes=nodes,
        edges=edges,
        is_template=True,
        template_name="ultra-light",
    )


# ============================================================================
# Template Registry
# ============================================================================

ALL_TEMPLATES = [
    create_autonomous_template,
    create_simple_template,
    create_optimized_autonomous_template,
    create_ultra_light_template,
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
