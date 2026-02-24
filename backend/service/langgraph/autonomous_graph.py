"""Autonomous Graph — difficulty-based LangGraph StateGraph with full resilience.

Routes task execution by difficulty classification:
    - Easy:   direct answer → END
    - Medium: answer → review → (approved → END | rejected → retry)
    - Hard:   create TODOs → execute each → progress check → final review → END

Enhanced with resilience nodes (Approach B — LangGraph philosophy):
    - memory_inject:   loads relevant memory context at graph start
    - context_guard:   checks context budget before each model call
    - post_model:      detects completion signals, records transcript, increments iteration
    - iteration_gate:  prevents infinite loops by checking global iteration cap

Graph topology::

    START → memory_inject → guard_classify → classify_difficulty → post_classify
              ↓ [easy/medium/hard/end]

    [easy]  → guard_direct → direct_answer → post_direct → END

    [medium] → guard_answer → answer → post_answer
             → guard_review → review → post_review → [approved/retry/end]
                → approved: END
                → retry: iter_gate_medium → [continue/stop]
                    → continue: guard_answer
                    → stop: END

    [hard]  → guard_create_todos → create_todos → post_create_todos
            → guard_execute → execute_todo → post_execute
            → check_progress → [continue/complete]
                → continue: iter_gate_hard → [continue/stop]
                    → continue: guard_execute
                    → stop: guard_final_review
                → complete: guard_final_review
            → final_review → post_final_review
            → guard_final_answer → final_answer → post_final_answer → END

Total: 28 nodes, 4 conditional routers.
"""

import asyncio
import json
import time
from logging import getLogger
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
)

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from service.langgraph.checkpointer import create_checkpointer
from service.langgraph.claude_cli_model import ClaudeCLIChatModel
from service.langgraph.context_guard import ContextWindowGuard
from service.langgraph.model_fallback import (
    classify_error,
    is_recoverable,
    FailureReason,
)
from service.langgraph.resilience_nodes import detect_completion_signal
from service.langgraph.state import (
    AutonomousState,
    CompletionSignal,
    ContextBudget,
    Difficulty,
    MemoryRef,
    ReviewResult,
    TodoItem,
    TodoStatus,
    make_initial_autonomous_state,
)
from service.prompt.sections import AutonomousPrompts
from service.logging.session_logger import get_session_logger, SessionLogger

logger = getLogger(__name__)


# ============================================================================
# Autonomous Graph Class
# ============================================================================


class AutonomousGraph:
    """Difficulty-based autonomous execution graph with full resilience.

    Classifies the task difficulty automatically and routes to the
    appropriate execution path (easy / medium / hard) while maintaining:

    - Context budget monitoring via guard nodes
    - Transient error retry via resilient invoke
    - Completion signal detection via post-model nodes
    - Memory context injection at graph start
    - Global iteration cap via iteration gate nodes
    - Transcript recording for observability
    """

    # Maximum review retries for the medium path
    MAX_REVIEW_RETRIES = 3
    # Default global iteration cap across all paths
    DEFAULT_MAX_ITERATIONS = 50
    # Retries per individual model call (for transient errors)
    MAX_RETRIES_PER_CALL = 2
    # Maximum TODO items for hard path
    MAX_TODO_ITEMS = 20

    def __init__(
        self,
        model: ClaudeCLIChatModel,
        session_id: Optional[str] = None,
        enable_checkpointing: bool = False,
        max_review_retries: int = 3,
        storage_path: Optional[str] = None,
        memory_manager: Optional[Any] = None,
        max_iterations: int = 50,
        model_name: Optional[str] = None,
    ):
        """Initialize AutonomousGraph.

        Args:
            model: Claude CLI model instance.
            session_id: Session ID for logging.
            enable_checkpointing: Enable LangGraph checkpointing.
            max_review_retries: Maximum review retries for the medium path.
            storage_path: Session storage directory (for persistent checkpointer).
            memory_manager: SessionMemoryManager instance for memory injection.
            max_iterations: Global iteration cap across all paths.
            model_name: Model name for context limit lookup.
        """
        self._model = model
        self._session_id = session_id or (model.session_id if model else "unknown")
        self._enable_checkpointing = enable_checkpointing
        self._max_review_retries = max_review_retries
        self._storage_path = storage_path
        self._memory_manager = memory_manager
        self._max_iterations = max_iterations
        self._model_name = model_name
        self._checkpointer: Optional[object] = None
        self._graph: Optional[CompiledStateGraph] = None

        # Resilience infrastructure
        self._context_guard = ContextWindowGuard(model=model_name)

        logger.info(
            f"[{self._session_id}] AutonomousGraph initialized "
            f"(max_iter={max_iterations}, "
            f"memory={'yes' if memory_manager else 'no'}, "
            f"model={model_name})"
        )

    def _get_logger(self) -> Optional[SessionLogger]:
        """Get session logger (lazy)."""
        return get_session_logger(self._session_id, create_if_missing=True)

    # ========================================================================
    # Resilience Infrastructure
    # ========================================================================

    async def _resilient_invoke(
        self,
        messages: list,
        node_name: str,
        state: AutonomousState,
    ) -> tuple:
        """Invoke model with retry on transient errors.

        Uses error classification from model_fallback module to determine
        if a failure is recoverable. On recoverable errors (rate_limit,
        overloaded, timeout, network), retries with exponential backoff.

        Args:
            messages: LangChain messages to send.
            node_name: Name of the calling node (for logging).
            state: Current state (for context, not mutated).

        Returns:
            Tuple of (response, fallback_state_updates).
            fallback_state_updates is a dict to merge into the node's
            return value for observability tracking.
        """
        model_name = self._model_name or "unknown"
        last_error = None
        max_retries = self.MAX_RETRIES_PER_CALL

        for attempt in range(max_retries + 1):
            try:
                start = time.time()
                response = await self._model.ainvoke(messages)
                duration_ms = int((time.time() - start) * 1000)

                if attempt > 0:
                    logger.info(
                        f"[{self._session_id}] {node_name}: "
                        f"succeeded on retry {attempt} ({duration_ms}ms)"
                    )
                    return response, {
                        "fallback": {
                            "original_model": model_name,
                            "current_model": model_name,
                            "attempts": attempt + 1,
                            "last_failure_reason": (
                                str(last_error)[:200] if last_error else ""
                            ),
                            "degraded": False,
                        }
                    }

                return response, {}

            except Exception as e:
                last_error = e
                reason = classify_error(e)

                logger.warning(
                    f"[{self._session_id}] {node_name}: "
                    f"attempt {attempt + 1}/{max_retries + 1} failed "
                    f"({reason.value}): {str(e)[:100]}"
                )

                if not is_recoverable(reason) or attempt >= max_retries:
                    raise

                delay = {
                    FailureReason.RATE_LIMITED: 5.0,
                    FailureReason.OVERLOADED: 3.0,
                    FailureReason.TIMEOUT: 2.0,
                    FailureReason.NETWORK_ERROR: 2.0,
                }.get(reason, 2.0)

                wait_time = delay * (attempt + 1)
                logger.info(
                    f"[{self._session_id}] {node_name}: "
                    f"retrying in {wait_time:.1f}s..."
                )
                await asyncio.sleep(wait_time)

        # Should not reach here, but satisfy the type checker.
        raise last_error  # type: ignore[misc]

    # ========================================================================
    # Resilience Nodes (Approach B — separate graph nodes)
    # ========================================================================

    async def _memory_inject_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Load relevant memory context into state before processing.

        Runs once at graph start. Searches SessionMemoryManager for
        memories relevant to the input, and writes MemoryRef entries
        to state for traceability. Also records the user input to
        short-term transcript.
        """
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="memory_inject",
                iteration=0,
                state_summary={
                    "input_length": len(state.get("input", "")),
                },
            )

        if not self._memory_manager:
            logger.debug(
                f"[{self._session_id}] memory_inject: "
                f"no memory manager available"
            )
            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="memory_inject",
                    iteration=0,
                    output_preview="No memory manager",
                    duration_ms=0,
                    state_changes={},
                )
            return {}

        try:
            input_text = state.get("input", "")

            # Record user input to transcript
            try:
                self._memory_manager.record_message(
                    "user", input_text[:5000]
                )
            except Exception:
                logger.debug(
                    f"[{self._session_id}] memory_inject: "
                    f"user transcript record failed (non-critical)"
                )

            # Search for relevant memories
            results = self._memory_manager.search(
                input_text[:500], max_results=5
            )

            refs: List[MemoryRef] = []
            for r in results:
                refs.append({
                    "filename": r.entry.filename or "unknown",
                    "source": r.entry.source.value,
                    "char_count": r.entry.char_count,
                    "injected_at_turn": 0,
                })

            if refs:
                logger.info(
                    f"[{self._session_id}] memory_inject: "
                    f"loaded {len(refs)} refs "
                    f"({sum(r['char_count'] for r in refs)} chars total)"
                )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="memory_inject",
                    iteration=0,
                    output_preview=f"Loaded {len(refs)} memory refs",
                    duration_ms=0,
                    state_changes={"memory_refs_count": len(refs)},
                )

            return {"memory_refs": refs} if refs else {}

        except Exception as e:
            logger.warning(
                f"[{self._session_id}] memory_inject: "
                f"failed (non-critical): {e}"
            )
            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="memory_inject",
                    iteration=0,
                    output_preview=f"Failed: {str(e)[:100]}",
                    duration_ms=0,
                    state_changes={},
                )
            return {}

    def _make_context_guard_node(self, position: str):
        """Factory for context guard nodes at specific graph positions.

        Each guard node estimates context token usage from accumulated
        messages and writes the budget status to state. Downstream
        model-calling nodes read the budget to compact prompts if needed.

        Args:
            position: Descriptive position name (e.g. "classify", "execute").

        Returns:
            Async node function for LangGraph.
        """

        async def _guard_node(state: AutonomousState) -> Dict[str, Any]:
            iteration = state.get("iteration", 0)
            session_logger = self._get_logger()

            if session_logger:
                session_logger.log_graph_node_enter(
                    node_name=f"guard_{position}",
                    iteration=iteration,
                    state_summary={
                        "messages_count": len(state.get("messages", [])),
                    },
                )

            messages = state.get("messages", [])

            # Convert LangChain messages to dicts for the guard
            msg_dicts = []
            for msg in messages:
                if hasattr(msg, "content"):
                    msg_dicts.append({
                        "role": getattr(msg, "type", "unknown"),
                        "content": msg.content,
                    })
                elif isinstance(msg, dict):
                    msg_dicts.append(msg)

            result = self._context_guard.check(msg_dicts)

            prev_budget = state.get("context_budget") or {}
            budget: ContextBudget = {
                "estimated_tokens": result.estimated_tokens,
                "context_limit": result.context_limit,
                "usage_ratio": result.usage_ratio,
                "status": result.status.value,
                "compaction_count": prev_budget.get("compaction_count", 0),
            }

            if result.should_block:
                logger.warning(
                    f"[{self._session_id}] guard_{position}: "
                    f"BLOCK at {result.usage_ratio:.0%} "
                    f"({result.estimated_tokens}/{result.context_limit} tokens)"
                )
                budget["compaction_count"] = budget["compaction_count"] + 1

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name=f"guard_{position}",
                    iteration=iteration,
                    output_preview=(
                        f"Budget: {result.status.value} "
                        f"({result.usage_ratio:.0%})"
                    ),
                    duration_ms=0,
                    state_changes={
                        "context_budget_status": budget["status"],
                    },
                )

            return {"context_budget": budget}

        return _guard_node

    def _make_post_model_node(
        self,
        position: str,
        detect_completion: bool = True,
    ):
        """Factory for post-model processing nodes.

        Each post-model node performs three sequential concerns:
        1. Global iteration increment
        2. Completion signal detection from last_output
        3. Transcript recording to short-term memory

        Args:
            position: Descriptive position name.
            detect_completion: Whether to parse completion signals.

        Returns:
            Async node function for LangGraph.
        """

        async def _post_model_node(
            state: AutonomousState,
        ) -> Dict[str, Any]:
            iteration = state.get("iteration", 0) + 1
            session_logger = self._get_logger()

            if session_logger:
                session_logger.log_graph_node_enter(
                    node_name=f"post_{position}",
                    iteration=iteration,
                    state_summary={
                        "last_output_length": len(
                            state.get("last_output", "") or ""
                        ),
                    },
                )

            updates: Dict[str, Any] = {
                "iteration": iteration,
                "current_step": f"post_{position}",
            }

            last_output = state.get("last_output", "") or ""

            # 1. Completion signal detection
            if detect_completion and last_output:
                signal, detail = detect_completion_signal(last_output)
                updates["completion_signal"] = signal.value
                updates["completion_detail"] = detail

                if signal in (
                    CompletionSignal.COMPLETE,
                    CompletionSignal.BLOCKED,
                    CompletionSignal.ERROR,
                ):
                    logger.info(
                        f"[{self._session_id}] post_{position}: "
                        f"signal={signal.value}"
                        + (f", detail={detail}" if detail else "")
                    )

            # 2. Transcript recording
            if self._memory_manager and last_output:
                try:
                    self._memory_manager.record_message(
                        "assistant", last_output[:5000]
                    )
                except Exception:
                    logger.debug(
                        f"[{self._session_id}] post_{position}: "
                        f"transcript record failed (non-critical)"
                    )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name=f"post_{position}",
                    iteration=iteration,
                    output_preview=(
                        f"iter={iteration}, "
                        f"signal={updates.get('completion_signal', 'n/a')}"
                    ),
                    duration_ms=0,
                    state_changes={
                        "iteration": iteration,
                        "completion_signal": updates.get(
                            "completion_signal"
                        ),
                    },
                )

            return updates

        return _post_model_node

    def _make_iteration_gate_node(self, position: str):
        """Factory for iteration gate nodes.

        Checks three conditions before allowing a loop to continue:
        1. Global iteration count vs max_iterations
        2. Context budget status (block/overflow)
        3. Completion signal from previous output

        Sets ``is_complete = True`` if any limit is exceeded.

        Args:
            position: Descriptive position name (e.g. "medium", "hard").

        Returns:
            Async node function for LangGraph.
        """

        async def _gate_node(state: AutonomousState) -> Dict[str, Any]:
            iteration = state.get("iteration", 0)
            max_iterations = state.get(
                "max_iterations", self._max_iterations
            )
            session_logger = self._get_logger()

            if session_logger:
                session_logger.log_graph_node_enter(
                    node_name=f"iter_gate_{position}",
                    iteration=iteration,
                    state_summary={
                        "iteration": iteration,
                        "max_iterations": max_iterations,
                    },
                )

            updates: Dict[str, Any] = {}
            stop_reason = None

            # Check 1: iteration limit
            if iteration >= max_iterations:
                stop_reason = (
                    f"Global iteration limit "
                    f"({iteration}/{max_iterations})"
                )

            # Check 2: context budget
            if not stop_reason:
                budget = state.get("context_budget") or {}
                if budget.get("status") in ("block", "overflow"):
                    stop_reason = f"Context budget {budget['status']}"

            # Check 3: completion signal
            if not stop_reason:
                signal = state.get("completion_signal")
                if signal in (
                    CompletionSignal.COMPLETE.value,
                    CompletionSignal.BLOCKED.value,
                    CompletionSignal.ERROR.value,
                ):
                    stop_reason = f"Completion signal: {signal}"

            if stop_reason:
                logger.warning(
                    f"[{self._session_id}] iter_gate_{position}: "
                    f"STOP — {stop_reason}"
                )
                updates["is_complete"] = True

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name=f"iter_gate_{position}",
                    iteration=iteration,
                    output_preview=(
                        f"Gate: {'STOP — ' + stop_reason if stop_reason else 'CONTINUE'}"
                    ),
                    duration_ms=0,
                    state_changes=updates,
                )

            return updates

        return _gate_node

    # ========================================================================
    # Core Graph Nodes
    # ========================================================================

    async def _classify_difficulty_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Classify task difficulty as easy/medium/hard.

        Analyzes the input and determines the appropriate execution path.
        """
        logger.info(
            f"[{self._session_id}] classify_difficulty: "
            f"classifying input difficulty"
        )
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="classify_difficulty",
                iteration=state.get("iteration", 0),
                state_summary={
                    "input_length": len(state.get("input", "")),
                },
            )

        try:
            input_text = state.get("input", "")

            prompt = AutonomousPrompts.classify_difficulty().format(
                input=input_text
            )
            messages = [HumanMessage(content=prompt)]

            response, fallback_updates = await self._resilient_invoke(
                messages, "classify_difficulty", state
            )
            response_text = response.content.strip().lower()

            # Extract difficulty from response
            if "easy" in response_text:
                difficulty = Difficulty.EASY
            elif "medium" in response_text:
                difficulty = Difficulty.MEDIUM
            elif "hard" in response_text:
                difficulty = Difficulty.HARD
            else:
                logger.warning(
                    f"[{self._session_id}] classify_difficulty: "
                    f"could not parse from: {response_text[:80]}, "
                    f"defaulting to medium"
                )
                difficulty = Difficulty.MEDIUM

            logger.info(
                f"[{self._session_id}] classify_difficulty: "
                f"{difficulty.value}"
            )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="classify_difficulty",
                    iteration=state.get("iteration", 0),
                    output_preview=f"Difficulty: {difficulty.value}",
                    duration_ms=0,
                    state_changes={"difficulty": difficulty.value},
                )

            result: Dict[str, Any] = {
                "difficulty": difficulty,
                "current_step": "difficulty_classified",
                "messages": [HumanMessage(content=input_text)],
                "last_output": response.content,
            }
            result.update(fallback_updates)
            return result

        except Exception as e:
            logger.exception(
                f"[{self._session_id}] classify_difficulty: error: {e}"
            )
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="classify_difficulty",
                    iteration=state.get("iteration", 0),
                    error_type=type(e).__name__,
                )
            return {"error": str(e), "is_complete": True}

    async def _direct_answer_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Generate direct answer for easy tasks.

        Single-shot model call without review.
        """
        logger.info(
            f"[{self._session_id}] direct_answer: generating answer"
        )
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="direct_answer",
                iteration=state.get("iteration", 0),
                state_summary={"difficulty": "easy"},
            )

        try:
            input_text = state.get("input", "")
            messages = [HumanMessage(content=input_text)]

            response, fallback_updates = await self._resilient_invoke(
                messages, "direct_answer", state
            )
            answer = response.content

            logger.info(
                f"[{self._session_id}] direct_answer: "
                f"answer generated ({len(answer)} chars)"
            )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="direct_answer",
                    iteration=state.get("iteration", 0),
                    output_preview=answer[:200] if answer else None,
                    duration_ms=0,
                    state_changes={
                        "answer_generated": True,
                        "is_complete": True,
                    },
                )

            result: Dict[str, Any] = {
                "answer": answer,
                "final_answer": answer,
                "messages": [response],
                "last_output": answer,
                "current_step": "direct_answer_complete",
                "is_complete": True,
            }
            result.update(fallback_updates)
            return result

        except Exception as e:
            logger.exception(
                f"[{self._session_id}] direct_answer: error: {e}"
            )
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="direct_answer",
                    iteration=state.get("iteration", 0),
                    error_type=type(e).__name__,
                )
            return {"error": str(e), "is_complete": True}

    async def _answer_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Generate answer for medium-difficulty tasks.

        Incorporates review feedback on retries. Reads context_budget
        to compact feedback when under budget pressure.
        """
        review_count = state.get("review_count", 0)
        logger.info(
            f"[{self._session_id}] answer: generating "
            f"(review_count={review_count})"
        )
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="answer",
                iteration=state.get("iteration", 0),
                state_summary={
                    "difficulty": "medium",
                    "review_count": review_count,
                    "has_feedback": bool(state.get("review_feedback")),
                },
            )

        try:
            input_text = state.get("input", "")
            previous_feedback = state.get("review_feedback")

            if previous_feedback and review_count > 0:
                # Budget-aware prompt compaction
                budget = state.get("context_budget") or {}
                if budget.get("status") in ("block", "overflow"):
                    previous_feedback = (
                        previous_feedback[:500] + "... (truncated)"
                    )

                prompt = AutonomousPrompts.retry_with_feedback().format(
                    previous_feedback=previous_feedback,
                    input_text=input_text,
                )
            else:
                prompt = input_text

            messages = [HumanMessage(content=prompt)]

            response, fallback_updates = await self._resilient_invoke(
                messages, "answer", state
            )
            answer = response.content

            logger.info(
                f"[{self._session_id}] answer: "
                f"generated ({len(answer)} chars)"
            )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="answer",
                    iteration=state.get("iteration", 0),
                    output_preview=answer[:200] if answer else None,
                    duration_ms=0,
                    state_changes={"answer_generated": True},
                )

            result: Dict[str, Any] = {
                "answer": answer,
                "messages": [response],
                "last_output": answer,
                "current_step": "answer_generated",
            }
            result.update(fallback_updates)
            return result

        except Exception as e:
            logger.exception(
                f"[{self._session_id}] answer: error: {e}"
            )
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="answer",
                    iteration=state.get("iteration", 0),
                    error_type=type(e).__name__,
                )
            return {"error": str(e), "is_complete": True}

    async def _review_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Review generated answer (medium path).

        Parses VERDICT/FEEDBACK from model response.
        Forces approval when max review retries are exhausted.
        """
        review_count = state.get("review_count", 0) + 1
        logger.info(
            f"[{self._session_id}] review: reviewing "
            f"(count={review_count})"
        )
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="review",
                iteration=state.get("iteration", 0),
                state_summary={
                    "review_count": review_count,
                    "answer_length": len(state.get("answer", "")),
                },
            )

        try:
            input_text = state.get("input", "")
            answer = state.get("answer", "")

            prompt = AutonomousPrompts.review().format(
                question=input_text, answer=answer
            )
            messages = [HumanMessage(content=prompt)]

            response, fallback_updates = await self._resilient_invoke(
                messages, "review", state
            )
            review_text = response.content

            # Parse review result
            review_result = ReviewResult.APPROVED
            feedback = ""

            if "VERDICT:" in review_text:
                lines = review_text.split("\n")
                for line in lines:
                    if line.startswith("VERDICT:"):
                        verdict = (
                            line.replace("VERDICT:", "").strip().lower()
                        )
                        if "rejected" in verdict:
                            review_result = ReviewResult.REJECTED
                    elif line.startswith("FEEDBACK:"):
                        feedback = (
                            line.replace("FEEDBACK:", "").strip()
                        )
                        idx = lines.index(line)
                        feedback = "\n".join(
                            [feedback] + lines[idx + 1:]
                        )
                        break
            else:
                feedback = review_text

            logger.info(
                f"[{self._session_id}] review: "
                f"result={review_result.value}"
            )

            # Force approval if max retry count reached
            is_complete = False
            if (
                review_result == ReviewResult.REJECTED
                and review_count >= self._max_review_retries
            ):
                logger.warning(
                    f"[{self._session_id}] review: "
                    f"max retries ({self._max_review_retries}), "
                    f"forcing approval"
                )
                review_result = ReviewResult.APPROVED
                is_complete = True
            elif review_result == ReviewResult.APPROVED:
                is_complete = True

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="review",
                    iteration=state.get("iteration", 0),
                    output_preview=f"Result: {review_result.value}",
                    duration_ms=0,
                    state_changes={
                        "review_result": review_result.value,
                        "review_count": review_count,
                        "is_complete": is_complete,
                    },
                )

            result: Dict[str, Any] = {
                "review_result": review_result,
                "review_feedback": feedback,
                "review_count": review_count,
                "messages": [response],
                "last_output": review_text,
                "current_step": "review_complete",
            }

            if is_complete:
                result["final_answer"] = answer
                result["is_complete"] = True

            result.update(fallback_updates)
            return result

        except Exception as e:
            logger.exception(
                f"[{self._session_id}] review: error: {e}"
            )
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="review",
                    iteration=state.get("iteration", 0),
                    error_type=type(e).__name__,
                )
            return {"error": str(e), "is_complete": True}

    async def _create_todos_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Break down complex task into TODO items (hard path).

        Parses JSON TODO list from model response. Caps TODO count to
        MAX_TODO_ITEMS to prevent runaway execution.
        """
        logger.info(
            f"[{self._session_id}] create_todos: creating TODO list"
        )
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="create_todos",
                iteration=state.get("iteration", 0),
                state_summary={"difficulty": "hard"},
            )

        try:
            input_text = state.get("input", "")

            prompt = AutonomousPrompts.create_todos().format(
                input=input_text
            )
            messages = [HumanMessage(content=prompt)]

            response, fallback_updates = await self._resilient_invoke(
                messages, "create_todos", state
            )
            response_text = response.content.strip()

            # Parse JSON — handle markdown code block wrappers
            if "```json" in response_text:
                response_text = (
                    response_text.split("```json")[1].split("```")[0]
                )
            elif "```" in response_text:
                response_text = (
                    response_text.split("```")[1].split("```")[0]
                )

            try:
                todos_raw = json.loads(response_text.strip())
            except json.JSONDecodeError as je:
                logger.warning(
                    f"[{self._session_id}] create_todos: "
                    f"JSON parse failed, single TODO fallback: {je}"
                )
                todos_raw = [
                    {
                        "id": 1,
                        "title": "Execute task",
                        "description": input_text,
                    }
                ]

            # Convert to TodoItem format
            todos: List[TodoItem] = []
            for item in todos_raw:
                todos.append({
                    "id": item.get("id", len(todos) + 1),
                    "title": item.get(
                        "title", f"Task {len(todos) + 1}"
                    ),
                    "description": item.get("description", ""),
                    "status": TodoStatus.PENDING,
                    "result": None,
                })

            # Cap TODO count
            if len(todos) > self.MAX_TODO_ITEMS:
                logger.warning(
                    f"[{self._session_id}] create_todos: "
                    f"capping {len(todos)} TODOs to {self.MAX_TODO_ITEMS}"
                )
                todos = todos[: self.MAX_TODO_ITEMS]

            logger.info(
                f"[{self._session_id}] create_todos: "
                f"{len(todos)} items created"
            )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="create_todos",
                    iteration=state.get("iteration", 0),
                    output_preview=f"Created {len(todos)} TODOs",
                    duration_ms=0,
                    state_changes={"todos_count": len(todos)},
                )

            result: Dict[str, Any] = {
                "todos": todos,
                "current_todo_index": 0,
                "messages": [response],
                "last_output": response.content,
                "current_step": "todos_created",
            }
            result.update(fallback_updates)
            return result

        except Exception as e:
            logger.exception(
                f"[{self._session_id}] create_todos: error: {e}"
            )
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="create_todos",
                    iteration=state.get("iteration", 0),
                    error_type=type(e).__name__,
                )
            return {"error": str(e), "is_complete": True}

    async def _execute_todo_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Execute a single TODO item (hard path).

        Builds prompt with previous results (budget-aware compaction)
        and executes the current TODO. On error, marks the TODO as
        FAILED and advances to the next one.
        """
        current_index = state.get("current_todo_index", 0)
        todos = state.get("todos", [])

        logger.info(
            f"[{self._session_id}] execute_todo: "
            f"item {current_index + 1}/{len(todos)}"
        )
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="execute_todo",
                iteration=state.get("iteration", 0),
                state_summary={
                    "current_index": current_index,
                    "total_todos": len(todos),
                },
            )

        try:
            if current_index >= len(todos):
                logger.warning(
                    f"[{self._session_id}] execute_todo: "
                    f"index {current_index} out of range"
                )
                return {"current_step": "todos_complete"}

            input_text = state.get("input", "")
            todo = todos[current_index]

            # Budget-aware previous results compaction
            budget = state.get("context_budget") or {}
            compact_mode = budget.get("status") in (
                "block", "overflow",
            )
            max_result_chars = 200 if compact_mode else 500

            previous_results = ""
            for i, t in enumerate(todos):
                if i < current_index and t.get("result"):
                    truncated = t["result"][:max_result_chars]
                    previous_results += (
                        f"\n[{t['title']}]: {truncated}"
                    )
                    if len(t["result"]) > max_result_chars:
                        previous_results += "..."
                    previous_results += "\n"

            if not previous_results:
                previous_results = "(No previous items completed)"

            prompt = AutonomousPrompts.execute_todo().format(
                goal=input_text,
                title=todo["title"],
                description=todo["description"],
                previous_results=previous_results,
            )
            messages = [HumanMessage(content=prompt)]

            response, fallback_updates = await self._resilient_invoke(
                messages, "execute_todo", state
            )
            result_text = response.content

            # Update TODO status
            updated_todo: TodoItem = {
                **todo,
                "status": TodoStatus.COMPLETED,
                "result": result_text,
            }

            logger.info(
                f"[{self._session_id}] execute_todo: "
                f"TODO {current_index + 1} completed"
            )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="execute_todo",
                    iteration=state.get("iteration", 0),
                    output_preview=(
                        result_text[:200] if result_text else None
                    ),
                    duration_ms=0,
                    state_changes={
                        "todo_completed": todo["title"],
                        "new_index": current_index + 1,
                    },
                )

            node_result: Dict[str, Any] = {
                "todos": [updated_todo],
                "current_todo_index": current_index + 1,
                "messages": [response],
                "last_output": result_text,
                "current_step": f"todo_{current_index + 1}_complete",
            }
            node_result.update(fallback_updates)
            return node_result

        except Exception as e:
            logger.exception(
                f"[{self._session_id}] execute_todo: error: {e}"
            )
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="execute_todo",
                    iteration=state.get("iteration", 0),
                    error_type=type(e).__name__,
                )

            # Mark failed TODO and advance to the next
            if current_index < len(todos):
                failed_todo: TodoItem = {
                    **todos[current_index],
                    "status": TodoStatus.FAILED,
                    "result": f"Error: {str(e)}",
                }
                return {
                    "todos": [failed_todo],
                    "current_todo_index": current_index + 1,
                    "last_output": f"Error: {str(e)}",
                    "current_step": (
                        f"todo_{current_index + 1}_failed"
                    ),
                }

            return {"error": str(e), "is_complete": True}

    async def _check_progress_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Check TODO completion progress (hard path).

        Pure state-checking node — no model call. Reports completed,
        failed, and remaining TODO counts.
        """
        current_index = state.get("current_todo_index", 0)
        todos = state.get("todos", [])
        completed = sum(
            1
            for t in todos
            if t.get("status") == TodoStatus.COMPLETED
        )
        failed = sum(
            1
            for t in todos
            if t.get("status") == TodoStatus.FAILED
        )

        logger.info(
            f"[{self._session_id}] check_progress: "
            f"{completed} done, {failed} failed, "
            f"{current_index}/{len(todos)} processed"
        )
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="check_progress",
                iteration=state.get("iteration", 0),
                state_summary={
                    "current_index": current_index,
                    "total_todos": len(todos),
                    "completed": completed,
                    "failed": failed,
                },
            )

        if session_logger:
            session_logger.log_graph_node_exit(
                node_name="check_progress",
                iteration=state.get("iteration", 0),
                output_preview=(
                    f"Progress: {completed}/{len(todos)} done, "
                    f"{failed} failed"
                ),
                duration_ms=0,
                state_changes={
                    "completed_count": completed,
                    "failed_count": failed,
                },
            )

        return {
            "current_step": "progress_checked",
            "metadata": {
                **state.get("metadata", {}),
                "completed_todos": completed,
                "failed_todos": failed,
                "total_todos": len(todos),
            },
        }

    async def _final_review_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Final review of all TODO results (hard path).

        Comprehensively reviews completed work with budget-aware
        result compaction.
        """
        logger.info(
            f"[{self._session_id}] final_review: reviewing all work"
        )
        session_logger = self._get_logger()
        todos = state.get("todos", [])

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="final_review",
                iteration=state.get("iteration", 0),
                state_summary={"total_todos": len(todos)},
            )

        try:
            input_text = state.get("input", "")

            # Budget-aware result compaction
            budget = state.get("context_budget") or {}
            compact_mode = budget.get("status") in (
                "block", "overflow",
            )
            max_result_chars = 500 if compact_mode else 2000

            todo_results = ""
            for todo in todos:
                status = todo.get("status", TodoStatus.PENDING)
                result = todo.get("result", "No result")
                if result and len(result) > max_result_chars:
                    result = (
                        result[:max_result_chars] + "... (truncated)"
                    )
                todo_results += (
                    f"\n### {todo['title']} [{status}]\n{result}\n"
                )

            prompt = AutonomousPrompts.final_review().format(
                input=input_text,
                todo_results=todo_results,
            )
            messages = [HumanMessage(content=prompt)]

            response, fallback_updates = await self._resilient_invoke(
                messages, "final_review", state
            )
            review_feedback = response.content

            logger.info(
                f"[{self._session_id}] final_review: completed"
            )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="final_review",
                    iteration=state.get("iteration", 0),
                    output_preview=(
                        review_feedback[:200]
                        if review_feedback
                        else None
                    ),
                    duration_ms=0,
                    state_changes={"final_review_done": True},
                )

            result: Dict[str, Any] = {
                "review_feedback": review_feedback,
                "messages": [response],
                "last_output": review_feedback,
                "current_step": "final_review_complete",
            }
            result.update(fallback_updates)
            return result

        except Exception as e:
            logger.exception(
                f"[{self._session_id}] final_review: error: {e}"
            )
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="final_review",
                    iteration=state.get("iteration", 0),
                    error_type=type(e).__name__,
                )
            return {
                "review_feedback": f"Review failed: {str(e)}",
                "last_output": f"Review failed: {str(e)}",
                "current_step": "final_review_failed",
            }

    async def _final_answer_node(
        self, state: AutonomousState
    ) -> Dict[str, Any]:
        """Synthesize final answer from all TODO results (hard path).

        Combines completed work and review feedback into a coherent
        final answer. Budget-aware result compaction applied.
        """
        logger.info(
            f"[{self._session_id}] final_answer: synthesizing"
        )
        session_logger = self._get_logger()
        todos = state.get("todos", [])

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="final_answer",
                iteration=state.get("iteration", 0),
                state_summary={"total_todos": len(todos)},
            )

        try:
            input_text = state.get("input", "")
            review_feedback = state.get("review_feedback", "")

            # Budget-aware result compaction
            budget = state.get("context_budget") or {}
            compact_mode = budget.get("status") in (
                "block", "overflow",
            )
            max_result_chars = 500 if compact_mode else 2000

            todo_results = ""
            for todo in todos:
                status = todo.get("status", TodoStatus.PENDING)
                result = todo.get("result", "No result")
                if result and len(result) > max_result_chars:
                    result = (
                        result[:max_result_chars] + "... (truncated)"
                    )
                todo_results += (
                    f"\n### {todo['title']} [{status}]\n{result}\n"
                )

            # Compact review feedback if needed
            review_text = review_feedback
            if review_text and len(review_text) > 2000:
                review_text = review_text[:2000] + "... (truncated)"

            prompt = AutonomousPrompts.final_answer().format(
                input=input_text,
                todo_results=todo_results,
                review_feedback=review_text,
            )
            messages = [HumanMessage(content=prompt)]

            response, fallback_updates = await self._resilient_invoke(
                messages, "final_answer", state
            )
            final_answer = response.content

            logger.info(
                f"[{self._session_id}] final_answer: "
                f"generated ({len(final_answer)} chars)"
            )

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="final_answer",
                    iteration=state.get("iteration", 0),
                    output_preview=(
                        final_answer[:200] if final_answer else None
                    ),
                    duration_ms=0,
                    state_changes={
                        "final_answer_generated": True,
                        "is_complete": True,
                    },
                )

            result: Dict[str, Any] = {
                "final_answer": final_answer,
                "messages": [response],
                "last_output": final_answer,
                "current_step": "complete",
                "is_complete": True,
            }
            result.update(fallback_updates)
            return result

        except Exception as e:
            logger.exception(
                f"[{self._session_id}] final_answer: error: {e}"
            )
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="final_answer",
                    iteration=state.get("iteration", 0),
                    error_type=type(e).__name__,
                )

            # On error, compose answer from TODO results directly
            todo_results = ""
            for todo in todos:
                if todo.get("result"):
                    todo_results += (
                        f"{todo['title']}: {todo['result']}\n"
                    )

            return {
                "final_answer": (
                    f"Task completed with errors.\n\n"
                    f"Results:\n{todo_results}"
                ),
                "last_output": f"Error in final_answer: {str(e)}",
                "error": str(e),
                "is_complete": True,
            }

    # ========================================================================
    # Conditional Edges (Routers)
    # ========================================================================

    def _route_by_difficulty(
        self, state: AutonomousState
    ) -> Literal["easy", "medium", "hard", "end"]:
        """Route based on classified difficulty.

        Also checks for early termination from errors.
        """
        if state.get("error"):
            return "end"

        difficulty = state.get("difficulty")
        if difficulty == Difficulty.EASY:
            return "easy"
        elif difficulty == Difficulty.MEDIUM:
            return "medium"
        return "hard"

    def _route_after_review(
        self, state: AutonomousState
    ) -> Literal["approved", "retry", "end"]:
        """Route based on review result.

        Checks is_complete, error, and completion signal before
        inspecting review_result.
        """
        if state.get("is_complete") or state.get("error"):
            return "end"

        # Completion signal from post_review can override
        signal = state.get("completion_signal")
        if signal in (
            CompletionSignal.COMPLETE.value,
            CompletionSignal.BLOCKED.value,
        ):
            return "approved"

        review_result = state.get("review_result")
        if review_result == ReviewResult.APPROVED:
            return "approved"
        return "retry"

    def _route_after_progress_check(
        self, state: AutonomousState
    ) -> Literal["continue", "complete"]:
        """Route based on TODO progress.

        Checks is_complete, error, and completion signal in addition
        to the todo index vs total count.
        """
        if state.get("is_complete") or state.get("error"):
            return "complete"

        signal = state.get("completion_signal")
        if signal in (
            CompletionSignal.COMPLETE.value,
            CompletionSignal.BLOCKED.value,
        ):
            return "complete"

        current_index = state.get("current_todo_index", 0)
        todos = state.get("todos", [])
        if current_index >= len(todos):
            return "complete"
        return "continue"

    def _route_iteration_gate(
        self, state: AutonomousState
    ) -> Literal["continue", "stop"]:
        """Route based on iteration gate decision.

        Simple binary check — if the gate set is_complete, stop.
        """
        if state.get("is_complete") or state.get("error"):
            return "stop"
        return "continue"

    # ========================================================================
    # Graph Building
    # ========================================================================

    def build(self) -> CompiledStateGraph:
        """Build and compile the resilience-enhanced autonomous graph.

        Creates a StateGraph with 28 nodes organized into:
        - 1 common entry (memory_inject → guard → classify → post)
        - 3 execution paths (easy/medium/hard), each with
          guard → execute → post patterns
        - 2 iteration gates for loop prevention
        - 4 conditional routers for path decisions

        Returns:
            Compiled StateGraph ready for execution.
        """
        logger.info(
            f"[{self._session_id}] Building enhanced AutonomousGraph..."
        )

        # Checkpointer setup
        if self._enable_checkpointing:
            self._checkpointer = create_checkpointer(
                storage_path=self._storage_path,
                persistent=True,
            )

        graph_builder = StateGraph(AutonomousState)

        # ========== Register nodes ==========================================

        # -- Common entry ---------------------------------------------------
        graph_builder.add_node(
            "memory_inject", self._memory_inject_node
        )
        graph_builder.add_node(
            "guard_classify",
            self._make_context_guard_node("classify"),
        )
        graph_builder.add_node(
            "classify_difficulty", self._classify_difficulty_node
        )
        graph_builder.add_node(
            "post_classify",
            self._make_post_model_node(
                "classify", detect_completion=False
            ),
        )

        # -- Easy path ------------------------------------------------------
        graph_builder.add_node(
            "guard_direct",
            self._make_context_guard_node("direct"),
        )
        graph_builder.add_node(
            "direct_answer", self._direct_answer_node
        )
        graph_builder.add_node(
            "post_direct",
            self._make_post_model_node("direct"),
        )

        # -- Medium path ----------------------------------------------------
        graph_builder.add_node(
            "guard_answer",
            self._make_context_guard_node("answer"),
        )
        graph_builder.add_node("answer", self._answer_node)
        graph_builder.add_node(
            "post_answer",
            self._make_post_model_node(
                "answer", detect_completion=False
            ),
        )
        graph_builder.add_node(
            "guard_review",
            self._make_context_guard_node("review"),
        )
        graph_builder.add_node("review", self._review_node)
        graph_builder.add_node(
            "post_review",
            self._make_post_model_node("review"),
        )
        graph_builder.add_node(
            "iter_gate_medium",
            self._make_iteration_gate_node("medium"),
        )

        # -- Hard path ------------------------------------------------------
        graph_builder.add_node(
            "guard_create_todos",
            self._make_context_guard_node("create_todos"),
        )
        graph_builder.add_node(
            "create_todos", self._create_todos_node
        )
        graph_builder.add_node(
            "post_create_todos",
            self._make_post_model_node(
                "create_todos", detect_completion=False
            ),
        )
        graph_builder.add_node(
            "guard_execute",
            self._make_context_guard_node("execute"),
        )
        graph_builder.add_node(
            "execute_todo", self._execute_todo_node
        )
        graph_builder.add_node(
            "post_execute",
            self._make_post_model_node("execute"),
        )
        graph_builder.add_node(
            "check_progress", self._check_progress_node
        )
        graph_builder.add_node(
            "iter_gate_hard",
            self._make_iteration_gate_node("hard"),
        )
        graph_builder.add_node(
            "guard_final_review",
            self._make_context_guard_node("final_review"),
        )
        graph_builder.add_node(
            "final_review", self._final_review_node
        )
        graph_builder.add_node(
            "post_final_review",
            self._make_post_model_node("final_review"),
        )
        graph_builder.add_node(
            "guard_final_answer",
            self._make_context_guard_node("final_answer"),
        )
        graph_builder.add_node(
            "final_answer", self._final_answer_node
        )
        graph_builder.add_node(
            "post_final_answer",
            self._make_post_model_node("final_answer"),
        )

        # ========== Define edges ============================================

        # -- Common entry ---------------------------------------------------
        graph_builder.add_edge(START, "memory_inject")
        graph_builder.add_edge("memory_inject", "guard_classify")
        graph_builder.add_edge("guard_classify", "classify_difficulty")
        graph_builder.add_edge(
            "classify_difficulty", "post_classify"
        )

        # Route by difficulty after post_classify
        graph_builder.add_conditional_edges(
            "post_classify",
            self._route_by_difficulty,
            {
                "easy": "guard_direct",
                "medium": "guard_answer",
                "hard": "guard_create_todos",
                "end": END,
            },
        )

        # -- Easy path: guard → direct_answer → post → END -----------------
        graph_builder.add_edge("guard_direct", "direct_answer")
        graph_builder.add_edge("direct_answer", "post_direct")
        graph_builder.add_edge("post_direct", END)

        # -- Medium path ----------------------------------------------------
        # guard_answer → answer → post_answer → guard_review
        graph_builder.add_edge("guard_answer", "answer")
        graph_builder.add_edge("answer", "post_answer")
        graph_builder.add_edge("post_answer", "guard_review")

        # guard_review → review → post_review → route
        graph_builder.add_edge("guard_review", "review")
        graph_builder.add_edge("review", "post_review")

        graph_builder.add_conditional_edges(
            "post_review",
            self._route_after_review,
            {
                "approved": END,
                "retry": "iter_gate_medium",
                "end": END,
            },
        )

        # Iteration gate for medium retry loop
        graph_builder.add_conditional_edges(
            "iter_gate_medium",
            self._route_iteration_gate,
            {
                "continue": "guard_answer",
                "stop": END,
            },
        )

        # -- Hard path ------------------------------------------------------
        # guard → create_todos → post → guard_execute
        graph_builder.add_edge(
            "guard_create_todos", "create_todos"
        )
        graph_builder.add_edge("create_todos", "post_create_todos")
        graph_builder.add_edge(
            "post_create_todos", "guard_execute"
        )

        # guard_execute → execute_todo → post → check_progress
        graph_builder.add_edge("guard_execute", "execute_todo")
        graph_builder.add_edge("execute_todo", "post_execute")
        graph_builder.add_edge("post_execute", "check_progress")

        # Route after progress check
        graph_builder.add_conditional_edges(
            "check_progress",
            self._route_after_progress_check,
            {
                "continue": "iter_gate_hard",
                "complete": "guard_final_review",
            },
        )

        # Iteration gate for hard TODO loop
        graph_builder.add_conditional_edges(
            "iter_gate_hard",
            self._route_iteration_gate,
            {
                "continue": "guard_execute",
                "stop": "guard_final_review",
            },
        )

        # Final review/answer chain
        graph_builder.add_edge(
            "guard_final_review", "final_review"
        )
        graph_builder.add_edge("final_review", "post_final_review")
        graph_builder.add_edge(
            "post_final_review", "guard_final_answer"
        )
        graph_builder.add_edge("guard_final_answer", "final_answer")
        graph_builder.add_edge("final_answer", "post_final_answer")
        graph_builder.add_edge("post_final_answer", END)

        # ========== Compile =================================================

        if self._checkpointer:
            self._graph = graph_builder.compile(
                checkpointer=self._checkpointer
            )
        else:
            self._graph = graph_builder.compile()

        logger.info(
            f"[{self._session_id}] AutonomousGraph built successfully "
            f"(28 nodes, 4 routers)"
        )
        return self._graph

    def compile(self) -> CompiledStateGraph:
        """Alias for build()."""
        return self.build()

    @property
    def graph(self) -> Optional[CompiledStateGraph]:
        """Return the compiled graph."""
        return self._graph

    def get_initial_state(
        self, input_text: str, **kwargs
    ) -> AutonomousState:
        """Create initial state using the centralized helper.

        Args:
            input_text: User input.
            **kwargs: Additional metadata.

        Returns:
            Initial AutonomousState dictionary.
        """
        return make_initial_autonomous_state(
            input_text,
            max_iterations=self._max_iterations,
            **kwargs,
        )

    def visualize(self) -> Optional[bytes]:
        """Visualize the graph (returns a PNG image).

        Returns:
            PNG image bytes, or None.
        """
        if not self._graph:
            logger.warning(
                f"[{self._session_id}] "
                f"Graph not built yet, building now..."
            )
            self.build()

        try:
            return self._graph.get_graph().draw_mermaid_png()
        except Exception as e:
            logger.warning(
                f"[{self._session_id}] "
                f"Could not visualize graph: {e}"
            )
            return None

    def get_mermaid_diagram(self) -> Optional[str]:
        """Return a Mermaid diagram string.

        Returns:
            Mermaid diagram string, or None.
        """
        if not self._graph:
            logger.warning(
                f"[{self._session_id}] "
                f"Graph not built yet, building now..."
            )
            self.build()

        try:
            return self._graph.get_graph().draw_mermaid()
        except Exception as e:
            logger.warning(
                f"[{self._session_id}] "
                f"Could not generate mermaid diagram: {e}"
            )
            return None
