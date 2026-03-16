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
# Tool Search Simple Template
# ============================================================================


def create_tool_search_simple_template() -> WorkflowDefinition:
    """Build a simple agent loop with tool discovery nodes.

    Topology::
        START → memory_inject → tool_summary → guard → llm_call
              → post_model → tool_discovery → END

    The tool_discovery_summary node injects previously discovered tools
    before the LLM call. The tool_discovery_post node extracts newly
    discovered tools after the LLM response.
    """

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
            id="tool_sum", node_type="tool_discovery_summary",
            label="Tool Discovery Summary",
            position={"x": 400, "y": 176},
        ),
        WorkflowNodeInstance(
            id="guard", node_type="context_guard", label="Context Guard",
            position={"x": 400, "y": 256},
            config={"position_label": "main"},
        ),
        WorkflowNodeInstance(
            id="llm", node_type="llm_call", label="LLM Call",
            position={"x": 400, "y": 368},
            config={
                "prompt_template": "{input}",
                "output_field": "last_output",
                "set_complete": True,
            },
        ),
        WorkflowNodeInstance(
            id="post", node_type="post_model", label="Post Model",
            position={"x": 400, "y": 480},
        ),
        WorkflowNodeInstance(
            id="tool_disc", node_type="tool_discovery_post",
            label="Tool Discovery Post",
            position={"x": 400, "y": 560},
        ),
        WorkflowNodeInstance(
            id="end", node_type="end", label="End",
            position={"x": 400, "y": 656},
        ),
    ]

    edges = [
        WorkflowEdge(source="start", target="mem"),
        WorkflowEdge(source="mem", target="tool_sum"),
        WorkflowEdge(source="tool_sum", target="guard"),
        WorkflowEdge(source="guard", target="llm"),
        WorkflowEdge(source="llm", target="post"),
        WorkflowEdge(source="post", target="tool_disc"),
        WorkflowEdge(source="tool_disc", target="end"),
    ]

    return WorkflowDefinition(
        id="template-tool-search-simple",
        name="Simple Agent (Tool Search)",
        description=(
            "Basic agent loop with dynamic tool discovery. "
            "Includes tool discovery summary (pre-LLM) and "
            "tool discovery post (post-LLM) nodes for tracking "
            "tools found via ToolSearch."
        ),
        nodes=nodes,
        edges=edges,
        is_template=True,
        template_name="tool-search-simple",
    )


# ============================================================================
# Tool Search Autonomous Template
# ============================================================================


def create_tool_search_autonomous_template() -> WorkflowDefinition:
    """Build the full autonomous graph with tool discovery nodes.

    Extends the standard autonomous template by inserting:
    - tool_discovery_summary before classify (once at start)
    - tool_discovery_post after each post_model node

    This enables tool discovery tracking across the entire
    difficulty-based execution flow.

    Topology additions (inserted into base autonomous flow):
        memory_inject → tool_summary → relevance_gate → ...
        post_direct → tool_disc_easy → END
        post_answer → tool_disc_med → guard_review
        post_execute → tool_disc_hard → check_progress
        post_final_answer → tool_disc_final → END
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
    _add("start",                   "start",           "Start",                    32, 112)
    _add("memory_inject",           "mem_inject",      "Memory Inject",           128, 224)
    _add("tool_discovery_summary",  "tool_sum",        "Tool Discovery Summary",  128, 300)
    _add("relevance_gate",          "relevance_gate",  "Relevance Gate",         -144, 300)
    _add("context_guard",           "guard_cls",       "Guard (Classify)",        128, 420,
         {"position_label": "classify"})
    _add("classify",                "classify",        "Classify",                288, 520)

    _edge("start", "mem_inject")
    _edge("mem_inject", "tool_sum")
    _edge("tool_sum", "relevance_gate")
    _edge("relevance_gate", "guard_cls", port="continue", lbl="relevant")
    _edge("relevance_gate", "end",       port="skip",     lbl="not relevant")
    _edge("guard_cls", "classify")

    # ── EASY PATH ──
    _add("context_guard",        "guard_dir",   "Guard (Direct)",          32, 728,
         {"position_label": "direct"})
    _add("direct_answer",        "dir_ans",     "Direct Answer",           32, 840)
    _add("post_model",           "post_dir",    "Post Direct",             32, 968)
    _add("tool_discovery_post",  "td_easy",     "Tool Disc (Easy)",        32, 1048)

    _edge("guard_dir", "dir_ans")
    _edge("dir_ans", "post_dir")
    _edge("post_dir", "td_easy")

    # ── MEDIUM PATH ──
    _add("context_guard",        "guard_ans",   "Guard (Answer)",         304, 728,
         {"position_label": "answer"})
    _add("answer",               "answer",      "Answer",                 304, 824)
    _add("post_model",           "post_ans",    "Post Answer",            304, 920,
         {"detect_completion": False})
    _add("tool_discovery_post",  "td_med",      "Tool Disc (Medium)",     304, 1000)
    _add("context_guard",        "guard_rev",   "Guard (Review)",         304, 1080,
         {"position_label": "review"})
    _add("review",               "review",      "Review",                 304, 1220)
    _add("iteration_gate",       "gate_med",    "Iter Gate (Medium)",     304, 1524)

    _edge("guard_ans", "answer")
    _edge("answer", "post_ans")
    _edge("post_ans", "td_med")
    _edge("td_med", "guard_rev")
    _edge("guard_rev", "review")

    # ── HARD PATH ──
    _add("context_guard",        "guard_todo",  "Guard (Todos)",          560, 728,
         {"position_label": "create_todos"})
    _add("create_todos",         "mk_todos",    "Create TODOs",           880, 728)
    _add("post_model",           "post_todos",  "Post Create Todos",      560, 872,
         {"detect_completion": False})
    _add("context_guard",        "guard_exec",  "Guard (Execute)",        944, 1284,
         {"position_label": "execute"})
    _add("execute_todo",         "exec_todo",   "Execute TODO",           560, 1000)
    _add("post_model",           "post_exec",   "Post Execute",           560, 1144)
    _add("tool_discovery_post",  "td_hard",     "Tool Disc (Hard)",       560, 1224)
    _add("check_progress",       "chk_prog",    "Check Progress",         560, 1348)
    _add("iteration_gate",       "gate_hard",   "Iter Gate (Hard)",       960, 1524)
    _add("context_guard",        "guard_fr",    "Guard (Final Review)",   576, 1604,
         {"position_label": "final_review"})
    _add("final_review",         "fin_rev",     "Final Review",           576, 1700)
    _add("post_model",           "post_fr",     "Post Final Review",      576, 1812)
    _add("context_guard",        "guard_fa",    "Guard (Final Answer)",   576, 1908,
         {"position_label": "final_answer"})
    _add("final_answer",         "fin_ans",     "Final Answer",           576, 2004)
    _add("post_model",           "post_fa",     "Post Final Answer",      576, 2100)
    _add("tool_discovery_post",  "td_final",    "Tool Disc (Final)",      576, 2180)

    _edge("guard_todo", "mk_todos")
    _edge("mk_todos", "post_todos")
    _edge("post_todos", "guard_exec")
    _edge("guard_exec", "exec_todo")
    _edge("exec_todo", "post_exec")
    _edge("post_exec", "td_hard")
    _edge("td_hard", "chk_prog")

    # ── END NODE ──
    _add("end", "end", "End", 64, 2344)

    # ── Conditional routing: classify → branches ──
    _edge("classify", "guard_dir",  port="easy",   lbl="Easy")
    _edge("classify", "guard_ans",  port="medium", lbl="Medium")
    _edge("classify", "guard_todo", port="hard",   lbl="Hard")
    _edge("classify", "end",        port="end",    lbl="End")

    # Easy → END (via tool discovery)
    _edge("td_easy", "end")

    # Medium review self-routing
    _edge("review", "end",      port="approved", lbl="Approved")
    _edge("review", "gate_med", port="retry",    lbl="Retry")
    _edge("review", "end",      port="end",      lbl="End")

    # Medium iteration gate
    _edge("gate_med", "guard_ans", port="continue", lbl="Continue")
    _edge("gate_med", "end",       port="stop",     lbl="Stop")

    # Hard progress check routing
    _edge("chk_prog", "gate_hard", port="continue", lbl="Continue")
    _edge("chk_prog", "guard_fr",  port="complete", lbl="Complete")

    # Hard iteration gate
    _edge("gate_hard", "guard_exec", port="continue", lbl="Continue")
    _edge("gate_hard", "guard_fr",   port="stop",     lbl="Stop")

    # Hard final chain
    _edge("guard_fr", "fin_rev")
    _edge("fin_rev", "post_fr")
    _edge("post_fr", "guard_fa")
    _edge("guard_fa", "fin_ans")
    _edge("fin_ans", "post_fa")
    _edge("post_fa", "td_final")
    _edge("td_final", "end")

    return WorkflowDefinition(
        id="template-tool-search-autonomous",
        name="Autonomous Difficulty-Based (Tool Search)",
        description=(
            "Full autonomous execution graph with tool discovery nodes. "
            "Extends the standard autonomous template with "
            "tool_discovery_summary (pre-LLM) and tool_discovery_post "
            "(post-LLM) nodes for dynamic tool tracking via ToolSearch."
        ),
        nodes=nodes,
        edges=edges,
        is_template=True,
        template_name="tool-search-autonomous",
    )


# ============================================================================
# Template Registry
# ============================================================================

ALL_TEMPLATES = [
    create_autonomous_template,
    create_simple_template,
    create_tool_search_simple_template,
    create_tool_search_autonomous_template,
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
