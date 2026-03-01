"""
Workflow State Registry — Central source of truth for LangGraph state fields.

Defines every built-in state field used by AutonomousState, enriched with
metadata so that developers and the Workflow Editor can inspect:

    - What fields exist and their purpose
    - Type information and default values
    - Which category each field belongs to (core, iteration, difficulty, etc.)
    - Reducer semantics (append, merge, last-wins, etc.)
    - Which nodes read/write each field

Design principles:
    - Single source of truth: all state field metadata lives here.
    - Nodes declare ``state_reads`` / ``state_writes`` on the class level.
    - The ``analyze_workflow_state`` function cross-references the node
      declarations with the built-in registry to produce a per-workflow
      state usage report shown in the Compiled View modal.
    - Fields not used by any node in a workflow are flagged as "unused".
    - Unknown fields (written by nodes but not in the registry) are
      flagged for developer attention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from logging import getLogger

logger = getLogger(__name__)


# ============================================================================
# State Field Metadata
# ============================================================================


class StateFieldCategory(str, Enum):
    """Logical grouping for state fields."""
    CORE = "core"                     # Essential conversation fields
    ITERATION = "iteration"           # Loop / iteration bookkeeping
    DIFFICULTY = "difficulty"         # Difficulty classification
    REVIEW = "review"                 # Answer review loop
    TODO = "todo"                     # TODO list management (hard path)
    COMPLETION = "completion"         # Completion detection
    RESILIENCE = "resilience"         # Context budget, fallback
    MEMORY = "memory"                 # Memory injection references
    OUTPUT = "output"                 # Final output fields
    META = "meta"                     # Metadata / legacy


class ReducerType(str, Enum):
    """How the field is merged across graph steps."""
    APPEND = "append"                 # List append (e.g. messages)
    MERGE_BY_ID = "merge_by_id"       # Dict-merge by ID key (e.g. todos)
    DEDUPLICATE = "deduplicate"       # Deduplicate by key (e.g. memory_refs)
    LAST_WINS = "last_wins"           # Simple overwrite (most scalar fields)


@dataclass
class StateFieldDef:
    """Metadata for a single built-in state field.

    This is the authoritative definition of the field — its purpose,
    type, default, category, and reducer.
    """
    name: str
    type_hint: str
    description: str
    category: StateFieldCategory
    default: Any = None
    reducer: ReducerType = ReducerType.LAST_WINS
    required: bool = False
    is_list: bool = False
    is_dict: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for the frontend."""
        return {
            "name": self.name,
            "type": self.type_hint,
            "description": self.description,
            "category": self.category.value,
            "default": _serialize_default(self.default),
            "reducer": self.reducer.value,
            "required": self.required,
            "is_list": self.is_list,
            "is_dict": self.is_dict,
        }


def _serialize_default(val: Any) -> Any:
    """Safely serialize a default value for JSON."""
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return val
    return str(val)


# ============================================================================
# Built-in State Field Registry
# ============================================================================

# This is the comprehensive list of ALL fields in AutonomousState,
# each documented with type, purpose, category, and reducer semantics.

BUILT_IN_STATE_FIELDS: List[StateFieldDef] = [
    # ── Core Conversation ──
    StateFieldDef(
        name="input",
        type_hint="str",
        description="Original user input / task description. Set once at graph start.",
        category=StateFieldCategory.CORE,
        default="",
        required=True,
    ),
    StateFieldDef(
        name="messages",
        type_hint="List[BaseMessage]",
        description="Accumulated LLM conversation messages. Append-only across steps.",
        category=StateFieldCategory.CORE,
        default=[],
        reducer=ReducerType.APPEND,
        is_list=True,
    ),
    StateFieldDef(
        name="current_step",
        type_hint="str",
        description="Label of the current execution step (for logging/debugging).",
        category=StateFieldCategory.CORE,
        default="start",
    ),
    StateFieldDef(
        name="last_output",
        type_hint="Optional[str]",
        description="Raw text output from the most recent model call.",
        category=StateFieldCategory.CORE,
        default=None,
    ),

    # ── Iteration Bookkeeping ──
    StateFieldDef(
        name="iteration",
        type_hint="int",
        description="Global iteration counter incremented by PostModel nodes.",
        category=StateFieldCategory.ITERATION,
        default=0,
    ),
    StateFieldDef(
        name="max_iterations",
        type_hint="int",
        description="Maximum iterations before the graph force-stops.",
        category=StateFieldCategory.ITERATION,
        default=50,
    ),

    # ── Difficulty Classification ──
    StateFieldDef(
        name="difficulty",
        type_hint="Optional[str]",
        description="Task difficulty classification (easy/medium/hard or custom categories).",
        category=StateFieldCategory.DIFFICULTY,
        default=None,
    ),

    # ── Answer & Review (Medium Path) ──
    StateFieldDef(
        name="answer",
        type_hint="Optional[str]",
        description="Generated answer text (medium path, before review).",
        category=StateFieldCategory.REVIEW,
        default=None,
    ),
    StateFieldDef(
        name="review_result",
        type_hint="Optional[str]",
        description="Review verdict (approved/retry or custom verdicts).",
        category=StateFieldCategory.REVIEW,
        default=None,
    ),
    StateFieldDef(
        name="review_feedback",
        type_hint="Optional[str]",
        description="Detailed feedback from the review node.",
        category=StateFieldCategory.REVIEW,
        default=None,
    ),
    StateFieldDef(
        name="review_count",
        type_hint="int",
        description="Number of review cycles completed.",
        category=StateFieldCategory.REVIEW,
        default=0,
    ),

    # ── TODO Tracking (Hard Path) ──
    StateFieldDef(
        name="todos",
        type_hint="List[TodoItem]",
        description="Structured TODO list for complex task decomposition.",
        category=StateFieldCategory.TODO,
        default=[],
        reducer=ReducerType.MERGE_BY_ID,
        is_list=True,
    ),
    StateFieldDef(
        name="current_todo_index",
        type_hint="int",
        description="Index of the next TODO item to execute.",
        category=StateFieldCategory.TODO,
        default=0,
    ),

    # ── Final Result ──
    StateFieldDef(
        name="final_answer",
        type_hint="Optional[str]",
        description="Synthesized final answer after all processing.",
        category=StateFieldCategory.OUTPUT,
        default=None,
    ),

    # ── Completion Detection ──
    StateFieldDef(
        name="completion_signal",
        type_hint="Optional[str]",
        description="Structured completion signal (continue/complete/blocked/error/none).",
        category=StateFieldCategory.COMPLETION,
        default="none",
    ),
    StateFieldDef(
        name="completion_detail",
        type_hint="Optional[str]",
        description="Detail text from the completion signal (e.g. next action).",
        category=StateFieldCategory.COMPLETION,
        default=None,
    ),

    # ── Error Handling ──
    StateFieldDef(
        name="error",
        type_hint="Optional[str]",
        description="Error message if a node fails.",
        category=StateFieldCategory.COMPLETION,
        default=None,
    ),
    StateFieldDef(
        name="is_complete",
        type_hint="bool",
        description="Flag indicating the workflow has finished execution.",
        category=StateFieldCategory.COMPLETION,
        default=False,
    ),

    # ── Context Budget (Resilience) ──
    StateFieldDef(
        name="context_budget",
        type_hint="Optional[ContextBudget]",
        description="Context window usage tracking (tokens, limit, status).",
        category=StateFieldCategory.RESILIENCE,
        default=None,
        is_dict=True,
    ),

    # ── Model Fallback (Resilience) ──
    StateFieldDef(
        name="fallback",
        type_hint="Optional[FallbackRecord]",
        description="Model fallback tracking (original model, current model, attempts).",
        category=StateFieldCategory.RESILIENCE,
        default=None,
        is_dict=True,
    ),

    # ── Memory References ──
    StateFieldDef(
        name="memory_refs",
        type_hint="List[MemoryRef]",
        description="References to loaded memory chunks, deduplicated by filename.",
        category=StateFieldCategory.MEMORY,
        default=[],
        reducer=ReducerType.DEDUPLICATE,
        is_list=True,
    ),

    # ── Metadata ──
    StateFieldDef(
        name="metadata",
        type_hint="Dict[str, Any]",
        description="Extensible metadata dictionary for custom data and legacy compatibility.",
        category=StateFieldCategory.META,
        default={},
        is_dict=True,
    ),
]

# Index by name for fast lookup
_FIELD_INDEX: Dict[str, StateFieldDef] = {f.name: f for f in BUILT_IN_STATE_FIELDS}


def get_state_field(name: str) -> Optional[StateFieldDef]:
    """Look up a built-in state field by name."""
    return _FIELD_INDEX.get(name)


def get_all_state_fields() -> List[StateFieldDef]:
    """Return all built-in state field definitions."""
    return list(BUILT_IN_STATE_FIELDS)


def get_state_fields_by_category() -> Dict[str, List[StateFieldDef]]:
    """Group built-in state fields by category."""
    result: Dict[str, List[StateFieldDef]] = {}
    for f in BUILT_IN_STATE_FIELDS:
        result.setdefault(f.category.value, []).append(f)
    return result


def get_state_field_names() -> Set[str]:
    """Return the set of all built-in state field names."""
    return set(_FIELD_INDEX.keys())


# ============================================================================
# Node State Usage Declaration
# ============================================================================


@dataclass
class NodeStateUsage:
    """State usage declaration for a single node type.

    Nodes declare at the class level which state fields they
    read and write.  The ``config_dynamic_reads`` and
    ``config_dynamic_writes`` fields list parameter names that
    can override the default field names (e.g. "output_field"
    parameter changes which field gets written).
    """
    reads: List[str] = field(default_factory=list)
    writes: List[str] = field(default_factory=list)
    config_dynamic_reads: Dict[str, str] = field(default_factory=dict)
    config_dynamic_writes: Dict[str, str] = field(default_factory=dict)

    def resolve_reads(self, config: Dict[str, Any]) -> List[str]:
        """Resolve actual read fields given a node config."""
        resolved = list(self.reads)
        for param_name, default_field in self.config_dynamic_reads.items():
            actual = config.get(param_name, default_field)
            if actual and actual not in resolved:
                resolved.append(actual)
        return resolved

    def resolve_writes(self, config: Dict[str, Any]) -> List[str]:
        """Resolve actual write fields given a node config."""
        resolved = list(self.writes)
        for param_name, default_field in self.config_dynamic_writes.items():
            actual = config.get(param_name, default_field)
            if actual and actual not in resolved:
                resolved.append(actual)
        return resolved


# ============================================================================
# Workflow State Analysis
# ============================================================================


@dataclass
class FieldUsageInfo:
    """Usage info for a single state field across the whole workflow."""
    field_def: Optional[StateFieldDef]     # None if not a built-in field
    field_name: str
    is_builtin: bool
    read_by: List[str] = field(default_factory=list)   # node labels
    written_by: List[str] = field(default_factory=list)  # node labels
    is_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.field_name,
            "is_builtin": self.is_builtin,
            "read_by": self.read_by,
            "written_by": self.written_by,
            "is_used": self.is_used,
        }
        if self.field_def:
            d.update({
                "type": self.field_def.type_hint,
                "description": self.field_def.description,
                "category": self.field_def.category.value,
                "reducer": self.field_def.reducer.value,
                "default": _serialize_default(self.field_def.default),
            })
        else:
            d.update({
                "type": "unknown",
                "description": "Custom field (not in built-in registry)",
                "category": "custom",
                "reducer": "last_wins",
                "default": None,
            })
        return d


@dataclass
class WorkflowStateAnalysis:
    """Complete state analysis for a workflow."""
    all_fields: List[FieldUsageInfo]
    used_fields: List[FieldUsageInfo]
    unused_builtin_fields: List[FieldUsageInfo]
    custom_fields: List[FieldUsageInfo]
    per_node: List[Dict[str, Any]]   # Per-node read/write summary

    def to_dict(self) -> Dict[str, Any]:
        # Group used fields by category
        by_category: Dict[str, List[Dict[str, Any]]] = {}
        for f in self.all_fields:
            cat = f.field_def.category.value if f.field_def else "custom"
            by_category.setdefault(cat, []).append(f.to_dict())

        return {
            "fields": [f.to_dict() for f in self.all_fields],
            "fields_by_category": by_category,
            "used_fields": [f.to_dict() for f in self.used_fields],
            "unused_builtin_fields": [f.to_dict() for f in self.unused_builtin_fields],
            "custom_fields": [f.to_dict() for f in self.custom_fields],
            "per_node": self.per_node,
            "summary": {
                "total_builtin": len(BUILT_IN_STATE_FIELDS),
                "used_count": len(self.used_fields),
                "unused_count": len(self.unused_builtin_fields),
                "custom_count": len(self.custom_fields),
            },
        }


def analyze_workflow_state(
    nodes: list,
    node_type_map: dict,
    instance_map: dict,
) -> WorkflowStateAnalysis:
    """Analyze state field usage across all nodes in a workflow.

    Args:
        nodes:          List of WorkflowNodeInstance objects.
        node_type_map:  Dict mapping instance ID → BaseNode.
        instance_map:   Dict mapping instance ID → WorkflowNodeInstance.

    Returns:
        WorkflowStateAnalysis with complete field usage information.
    """
    builtin_names = get_state_field_names()

    # Track reads/writes per field
    field_reads: Dict[str, List[str]] = {}   # field_name → [node_labels]
    field_writes: Dict[str, List[str]] = {}  # field_name → [node_labels]
    per_node_info: List[Dict[str, Any]] = []

    for inst in nodes:
        if inst.node_type in ("start", "end"):
            continue

        base_node = node_type_map.get(inst.id)
        if not base_node:
            continue

        label = inst.label or base_node.label or inst.node_type
        config = inst.config

        # Get state usage from the node
        state_usage = getattr(base_node, "state_usage", None)
        if state_usage and isinstance(state_usage, NodeStateUsage):
            reads = state_usage.resolve_reads(config)
            writes = state_usage.resolve_writes(config)
        else:
            # Fallback: use the inspector heuristics
            reads = _infer_reads(base_node, config)
            writes = _infer_writes(base_node, config)

        for r in reads:
            field_reads.setdefault(r, []).append(label)
        for w in writes:
            field_writes.setdefault(w, []).append(label)

        per_node_info.append({
            "node_id": inst.id,
            "node_label": label,
            "node_type": inst.node_type,
            "reads": reads,
            "writes": writes,
        })

    # Build field usage info for all known fields
    all_referenced = set(field_reads.keys()) | set(field_writes.keys())
    all_field_names = builtin_names | all_referenced

    all_fields: List[FieldUsageInfo] = []
    used_fields: List[FieldUsageInfo] = []
    unused_builtin: List[FieldUsageInfo] = []
    custom_fields: List[FieldUsageInfo] = []

    # Process built-in fields first (in definition order)
    for fdef in BUILT_IN_STATE_FIELDS:
        readers = field_reads.get(fdef.name, [])
        writers = field_writes.get(fdef.name, [])
        is_used = bool(readers or writers)

        info = FieldUsageInfo(
            field_def=fdef,
            field_name=fdef.name,
            is_builtin=True,
            read_by=readers,
            written_by=writers,
            is_used=is_used,
        )
        all_fields.append(info)
        if is_used:
            used_fields.append(info)
        else:
            unused_builtin.append(info)

    # Process custom (non-built-in) fields
    for name in sorted(all_referenced - builtin_names):
        readers = field_reads.get(name, [])
        writers = field_writes.get(name, [])
        info = FieldUsageInfo(
            field_def=None,
            field_name=name,
            is_builtin=False,
            read_by=readers,
            written_by=writers,
            is_used=True,
        )
        all_fields.append(info)
        custom_fields.append(info)

    return WorkflowStateAnalysis(
        all_fields=all_fields,
        used_fields=used_fields,
        unused_builtin_fields=unused_builtin,
        custom_fields=custom_fields,
        per_node=per_node_info,
    )


# ============================================================================
# Fallback Inference (for nodes without explicit state_usage)
# ============================================================================

def _infer_reads(base_node: Any, config: Dict[str, Any]) -> List[str]:
    """Infer which state fields a node reads (heuristic fallback)."""
    ntype = base_node.node_type
    fields: List[str] = []

    if ntype in ("classify", "direct_answer", "answer", "llm_call"):
        fields.extend(["input", "messages"])
        if ntype == "llm_call":
            cond = config.get("conditional_field", "")
            if cond:
                fields.append(cond)
        if ntype == "answer":
            fields.append(config.get("feedback_field", "review_feedback"))
            fields.append(config.get("count_field", "review_count"))
    elif ntype == "review":
        fields.extend([
            "input",
            config.get("answer_field", "answer"),
            config.get("count_field", "review_count"),
        ])
    elif ntype in ("final_review", "final_answer"):
        fields.extend(["input", "messages"])
        fields.append(config.get("list_field", "todos"))
        if ntype == "final_answer":
            fields.append(config.get("feedback_field", "review_feedback"))
    elif ntype == "execute_todo":
        fields.extend(["input"])
        fields.append(config.get("list_field", "todos"))
        fields.append(config.get("index_field", "current_todo_index"))
        fields.append("context_budget")
    elif ntype == "create_todos":
        fields.append("input")
    elif ntype == "memory_inject":
        fields.append(config.get("search_field", "input"))
    elif ntype == "context_guard":
        fields.append(config.get("messages_field", "messages"))
    elif ntype == "post_model":
        fields.append(config.get("source_field", "last_output"))
        fields.append(config.get("increment_field", "iteration"))
    elif ntype == "check_progress":
        fields.append(config.get("list_field", "todos"))
        fields.append(config.get("index_field", "current_todo_index"))
        fields.extend(["is_complete", "completion_signal", "error"])
    elif ntype == "iteration_gate":
        fields.extend(["iteration", "max_iterations", "is_complete",
                        "error", "completion_signal", "context_budget"])
        custom = config.get("custom_stop_field", "")
        if custom:
            fields.append(custom)
    elif ntype == "conditional_router":
        rf = config.get("routing_field", "")
        if rf:
            fields.append(rf)
    elif ntype == "state_setter":
        pass
    elif ntype == "transcript_record":
        fields.append(config.get("source_field", "last_output"))

    return list(dict.fromkeys(fields))  # deduplicate preserving order


def _infer_writes(base_node: Any, config: Dict[str, Any]) -> List[str]:
    """Infer which state fields a node writes (heuristic fallback)."""
    ntype = base_node.node_type
    fields: List[str] = []

    if ntype == "classify":
        fields.append(config.get("output_field", "difficulty"))
        fields.extend(["current_step", "messages", "last_output"])
    elif ntype == "review":
        fields.append(config.get("output_field", "review_result"))
        fields.extend(["review_feedback"])
        fields.append(config.get("count_field", "review_count"))
        fields.extend(["messages", "last_output", "current_step", "final_answer", "is_complete"])
    elif ntype == "direct_answer":
        fields.extend(["messages", "last_output", "current_step", "is_complete"])
        of_raw = config.get("output_fields", '["answer", "final_answer"]')
        if isinstance(of_raw, list):
            fields.extend(of_raw)
    elif ntype == "answer":
        fields.extend(["messages", "last_output", "current_step"])
        of_raw = config.get("output_fields", '["answer"]')
        if isinstance(of_raw, list):
            fields.extend(of_raw)
    elif ntype == "llm_call":
        fields.append(config.get("output_field", "last_output"))
        fields.extend(["messages", "last_output", "current_step"])
        if config.get("set_complete"):
            fields.append("is_complete")
    elif ntype == "create_todos":
        fields.append(config.get("output_list_field", "todos"))
        fields.append(config.get("output_index_field", "current_todo_index"))
        fields.extend(["messages", "last_output", "current_step"])
    elif ntype == "execute_todo":
        fields.append(config.get("list_field", "todos"))
        fields.append(config.get("index_field", "current_todo_index"))
        fields.extend(["messages", "last_output", "current_step"])
    elif ntype in ("final_review", "final_answer"):
        fields.append(config.get("output_field", "review_feedback" if ntype == "final_review" else "final_answer"))
        fields.extend(["messages", "last_output", "current_step", "metadata"])
        if ntype == "final_answer":
            fields.append("is_complete")
    elif ntype == "memory_inject":
        fields.append("memory_refs")
    elif ntype == "context_guard":
        fields.append("context_budget")
    elif ntype == "post_model":
        fields.append(config.get("increment_field", "iteration"))
        fields.extend(["current_step", "completion_signal", "completion_detail", "is_complete"])
    elif ntype == "check_progress":
        fields.extend(["current_step", "metadata"])
    elif ntype == "iteration_gate":
        fields.extend(["is_complete", "metadata"])
    elif ntype == "conditional_router":
        fields.append("current_step")
    elif ntype == "state_setter":
        updates = config.get("state_updates", {})
        if isinstance(updates, dict):
            fields.extend(updates.keys())
        elif isinstance(updates, str):
            import json
            try:
                parsed = json.loads(updates)
                if isinstance(parsed, dict):
                    fields.extend(parsed.keys())
            except (json.JSONDecodeError, TypeError):
                pass
    elif ntype == "transcript_record":
        pass  # writes to external memory, not state

    return list(dict.fromkeys(fields))  # deduplicate preserving order
