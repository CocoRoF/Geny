"""
Enhanced LangGraph State definitions.

Provides the single source-of-truth state schemas for both
AgentSession (simple graph) and AutonomousGraph (difficulty-based graph).

Design principles (referencing OpenClaw patterns):
- Every resilience concern lives IN state, not in ad-hoc instance vars
- Completion detection via structured signal enum, not string matching
- Context budget tracked as first-class state field
- Model fallback state recorded so nodes can react to degraded mode
- Memory references surfaced in state for traceability
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Optional, TypedDict


# ============================================================================
# Enums
# ============================================================================


class CompletionSignal(str, Enum):
    """Structured completion signals emitted by the agent.

    These map to the protocol section defined in service.prompt.protocols.
    The graph edge functions inspect this field instead of doing regex on raw text.
    """
    CONTINUE = "continue"       # [CONTINUE: {next_action}]
    COMPLETE = "complete"       # [TASK_COMPLETE]
    BLOCKED = "blocked"         # [BLOCKED: {reason}]
    ERROR = "error"             # [ERROR: {desc}]
    NONE = "none"               # No signal detected (first turn or legacy)


class Difficulty(str, Enum):
    """Task difficulty classification."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class ReviewResult(str, Enum):
    """Quality review verdict."""
    APPROVED = "approved"
    REJECTED = "rejected"


class TodoStatus(str, Enum):
    """TODO item execution status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ContextBudgetStatus(str, Enum):
    """Mirror of context_guard.ContextStatus, kept in state."""
    OK = "ok"
    WARN = "warn"
    BLOCK = "block"
    OVERFLOW = "overflow"


# ============================================================================
# Compound sub-types
# ============================================================================


class TodoItem(TypedDict):
    """Single TODO item for HARD-difficulty execution."""
    id: int
    title: str
    description: str
    status: TodoStatus
    result: Optional[str]


class MemoryRef(TypedDict, total=False):
    """A reference to a loaded memory chunk.

    Kept in state so that downstream nodes/edges can decide whether
    memory has already been injected (avoid double-loading).
    """
    filename: str
    source: str            # "long_term" | "short_term" | "bootstrap"
    char_count: int
    injected_at_turn: int  # which iteration the chunk was first included


class FallbackRecord(TypedDict, total=False):
    """Tracks model fallback events within a single invocation."""
    original_model: str
    current_model: str
    attempts: int
    last_failure_reason: str  # FailureReason value
    degraded: bool            # True if we are NOT on the preferred model


class ContextBudget(TypedDict, total=False):
    """Context window usage tracked in state."""
    estimated_tokens: int
    context_limit: int
    usage_ratio: float
    status: str               # ContextBudgetStatus value
    compaction_count: int      # how many times we compacted this session


# ============================================================================
# Reducers
# ============================================================================


def _add_messages(left: list, right: list) -> list:
    """Append-only message accumulator."""
    return left + right


def _merge_todos(left: List[TodoItem], right: List[TodoItem]) -> List[TodoItem]:
    """Merge TODO lists by ID (right wins on conflict)."""
    if not right:
        return left
    index = {item["id"]: item for item in left}
    for item in right:
        index[item["id"]] = item
    return list(index.values())


def _merge_memory_refs(
    left: List[MemoryRef], right: List[MemoryRef]
) -> List[MemoryRef]:
    """Deduplicate memory references by filename."""
    seen = {m["filename"] for m in left}
    merged = list(left)
    for m in right:
        if m["filename"] not in seen:
            merged.append(m)
            seen.add(m["filename"])
    return merged


def _last_wins(left: Any, right: Any) -> Any:
    """Simple last-write-wins reducer for scalar fields."""
    return right if right is not None else left


# ============================================================================
# AgentState — used by the simple (non-autonomous) graph
# ============================================================================


class AgentState(TypedDict, total=False):
    """State schema for the simple agent loop.

    Fields marked with Annotated[..., reducer] are accumulated/merged
    across graph steps; plain fields are overwritten each step.
    """

    # -- Core conversation --------------------------------------------------
    messages: Annotated[list, _add_messages]
    current_step: str
    last_output: Optional[str]

    # -- Iteration bookkeeping ----------------------------------------------
    iteration: int
    max_iterations: int

    # -- Completion detection (structured) ----------------------------------
    completion_signal: Optional[str]        # CompletionSignal value
    completion_detail: Optional[str]        # e.g. the next action from [CONTINUE: ...]

    # -- Error handling -----------------------------------------------------
    error: Optional[str]
    is_complete: bool

    # -- Context budget (populated by guard node) ---------------------------
    context_budget: Optional[ContextBudget]

    # -- Model fallback record ----------------------------------------------
    fallback: Optional[FallbackRecord]

    # -- Memory references --------------------------------------------------
    memory_refs: Annotated[List[MemoryRef], _merge_memory_refs]

    # -- Legacy metadata (for backward compat) ------------------------------
    metadata: Dict[str, Any]


# ============================================================================
# AutonomousState — used by the difficulty-based graph
# ============================================================================


class AutonomousState(TypedDict, total=False):
    """State schema for the difficulty-based autonomous graph.

    Extends the core agent fields with difficulty routing,
    review loop, and TODO tracking.
    """

    # -- Input --------------------------------------------------------------
    input: str

    # -- Core conversation --------------------------------------------------
    messages: Annotated[list, _add_messages]
    current_step: str
    last_output: Optional[str]

    # -- Iteration bookkeeping (global across all paths) --------------------
    iteration: int
    max_iterations: int

    # -- Difficulty ---------------------------------------------------------
    difficulty: Optional[str]  # Difficulty enum value

    # -- Answer & review (MEDIUM path) --------------------------------------
    answer: Optional[str]
    review_result: Optional[str]  # ReviewResult enum value
    review_feedback: Optional[str]
    review_count: int

    # -- TODO tracking (HARD path) ------------------------------------------
    todos: Annotated[List[TodoItem], _merge_todos]
    current_todo_index: int

    # -- Final result -------------------------------------------------------
    final_answer: Optional[str]

    # -- Completion detection (structured) ----------------------------------
    completion_signal: Optional[str]
    completion_detail: Optional[str]

    # -- Error handling -----------------------------------------------------
    error: Optional[str]
    is_complete: bool

    # -- Context budget -----------------------------------------------------
    context_budget: Optional[ContextBudget]

    # -- Model fallback -----------------------------------------------------
    fallback: Optional[FallbackRecord]

    # -- Memory references --------------------------------------------------
    memory_refs: Annotated[List[MemoryRef], _merge_memory_refs]

    # -- Legacy metadata ----------------------------------------------------
    metadata: Dict[str, Any]


# ============================================================================
# Helpers
# ============================================================================


def make_initial_agent_state(
    input_text: str,
    *,
    max_iterations: int = 100,
    **extra_metadata: Any,
) -> AgentState:
    """Create a well-formed initial AgentState."""
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content=input_text)],
        "current_step": "start",
        "last_output": None,
        "iteration": 0,
        "max_iterations": max_iterations,
        "completion_signal": CompletionSignal.NONE.value,
        "completion_detail": None,
        "error": None,
        "is_complete": False,
        "context_budget": None,
        "fallback": None,
        "memory_refs": [],
        "metadata": extra_metadata,
    }


def make_initial_autonomous_state(
    input_text: str,
    *,
    max_iterations: int = 50,
    **extra_metadata: Any,
) -> AutonomousState:
    """Create a well-formed initial AutonomousState."""
    return {
        "input": input_text,
        "messages": [],
        "current_step": "start",
        "last_output": None,
        "iteration": 0,
        "max_iterations": max_iterations,
        "difficulty": None,
        "answer": None,
        "review_result": None,
        "review_feedback": None,
        "review_count": 0,
        "todos": [],
        "current_todo_index": 0,
        "final_answer": None,
        "completion_signal": CompletionSignal.NONE.value,
        "completion_detail": None,
        "error": None,
        "is_complete": False,
        "context_budget": None,
        "fallback": None,
        "memory_refs": [],
        "metadata": extra_metadata,
    }
