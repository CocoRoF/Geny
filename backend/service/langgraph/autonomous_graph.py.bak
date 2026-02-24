"""Autonomous Graph — difficulty-based LangGraph StateGraph.

Routes task execution by difficulty classification:
    - Easy:   direct answer → END
    - Medium: answer → review → (approved → END | rejected → retry)
    - Hard:   create TODOs → execute each → progress check → final review → END

Graph topology::

    START → classify_difficulty
              ↓ [easy/medium/hard]

    [easy]  → direct_answer → END

    [medium] → answer → review → [approved/retry]
                                    → approved: END
                                    → retry: answer

    [hard]  → create_todos → execute_todo → check_progress
                                              → [has_more/complete]
                                              → has_more: execute_todo
                                              → complete: final_review → final_answer → END
"""

from logging import getLogger
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
)

from langchain_core.messages import (
    HumanMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from service.langgraph.checkpointer import create_checkpointer
from service.langgraph.claude_cli_model import ClaudeCLIChatModel
from service.langgraph.state import (
    AutonomousState,
    Difficulty,
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
    """Difficulty-based autonomous execution graph.

    Classifies the task difficulty automatically and routes to the
    appropriate execution path (easy / medium / hard).
    """

    # Maximum review retries for the medium path
    MAX_REVIEW_RETRIES = 3

    def __init__(
        self,
        model: ClaudeCLIChatModel,
        session_id: Optional[str] = None,
        enable_checkpointing: bool = False,
        max_review_retries: int = 3,
        storage_path: Optional[str] = None,
    ):
        """Initialize AutonomousGraph.

        Args:
            model: Claude CLI model instance.
            session_id: Session ID for logging.
            enable_checkpointing: Enable LangGraph checkpointing.
            max_review_retries: Maximum review retries for the medium path.
            storage_path: Session storage directory (for persistent checkpointer).
        """
        self._model = model
        self._session_id = session_id or (model.session_id if model else "unknown")
        self._enable_checkpointing = enable_checkpointing
        self._max_review_retries = max_review_retries
        self._storage_path = storage_path
        self._checkpointer: Optional[object] = None
        self._graph: Optional[CompiledStateGraph] = None

        logger.info(f"[{self._session_id}] AutonomousGraph initialized")

    def _get_logger(self) -> Optional[SessionLogger]:
        """Get session logger (lazy)."""
        return get_session_logger(self._session_id, create_if_missing=True)

    # ========================================================================
    # Graph Nodes
    # ========================================================================

    async def _classify_difficulty_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        Difficulty classification node.

        Analyzes the input and classifies it as easy, medium, or hard.
        """
        logger.info(f"[{self._session_id}] classify_difficulty: Classifying input difficulty")
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="classify_difficulty",
                iteration=0,
                state_summary={"input_length": len(state.get("input", ""))}
            )

        try:
            input_text = state.get("input", "")

            # Request difficulty classification
            prompt = AutonomousPrompts.classify_difficulty().format(input=input_text)
            messages = [HumanMessage(content=prompt)]

            response = await self._model.ainvoke(messages)
            response_text = response.content.strip().lower()

            # Extract difficulty from response
            if "easy" in response_text:
                difficulty = Difficulty.EASY
            elif "medium" in response_text:
                difficulty = Difficulty.MEDIUM
            elif "hard" in response_text:
                difficulty = Difficulty.HARD
            else:
                # Default: medium
                logger.warning(f"[{self._session_id}] Could not parse difficulty from: {response_text}, defaulting to medium")
                difficulty = Difficulty.MEDIUM

            logger.info(f"[{self._session_id}] classify_difficulty: Classified as {difficulty.value}")

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="classify_difficulty",
                    iteration=0,
                    output_preview=f"Difficulty: {difficulty.value}",
                    duration_ms=0,
                    state_changes={"difficulty": difficulty.value}
                )

            return {
                "difficulty": difficulty,
                "current_step": "difficulty_classified",
                "messages": [HumanMessage(content=input_text)],
            }

        except Exception as e:
            logger.exception(f"[{self._session_id}] Error in classify_difficulty: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="classify_difficulty",
                    iteration=0,
                    error_type=type(e).__name__
                )

            return {
                "error": str(e),
                "is_complete": True,
            }

    async def _direct_answer_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        Direct answer node (for easy tasks).

        Generates an answer directly without additional review.
        """
        logger.info(f"[{self._session_id}] direct_answer: Generating direct answer")
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="direct_answer",
                iteration=0,
                state_summary={"difficulty": "easy"}
            )

        try:
            input_text = state.get("input", "")

            # Request direct answer
            messages = [HumanMessage(content=input_text)]
            response = await self._model.ainvoke(messages)
            answer = response.content

            logger.info(f"[{self._session_id}] direct_answer: Answer generated ({len(answer)} chars)")

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="direct_answer",
                    iteration=0,
                    output_preview=answer[:200] if answer else None,
                    duration_ms=0,
                    state_changes={"answer_generated": True, "is_complete": True}
                )

            return {
                "answer": answer,
                "final_answer": answer,
                "messages": [response],
                "current_step": "direct_answer_complete",
                "is_complete": True,
            }

        except Exception as e:
            logger.exception(f"[{self._session_id}] Error in direct_answer: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="direct_answer",
                    iteration=0,
                    error_type=type(e).__name__
                )

            return {
                "error": str(e),
                "is_complete": True,
            }

    async def _answer_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        Answer generation node (for medium-difficulty tasks).

        Generates an answer and passes it on for review.
        """
        logger.info(f"[{self._session_id}] answer: Generating answer for review")
        session_logger = self._get_logger()
        review_count = state.get("review_count", 0)

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="answer",
                iteration=review_count,
                state_summary={
                    "difficulty": "medium",
                    "review_count": review_count,
                    "has_previous_feedback": bool(state.get("review_feedback"))
                }
            )

        try:
            input_text = state.get("input", "")
            previous_feedback = state.get("review_feedback")

            # Include feedback if available
            if previous_feedback and review_count > 0:
                prompt = AutonomousPrompts.retry_with_feedback().format(
                    previous_feedback=previous_feedback,
                    input_text=input_text,
                )
            else:
                prompt = input_text

            messages = [HumanMessage(content=prompt)]
            response = await self._model.ainvoke(messages)
            answer = response.content

            logger.info(f"[{self._session_id}] answer: Answer generated ({len(answer)} chars)")

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="answer",
                    iteration=review_count,
                    output_preview=answer[:200] if answer else None,
                    duration_ms=0,
                    state_changes={"answer_generated": True}
                )

            return {
                "answer": answer,
                "messages": [response],
                "current_step": "answer_generated",
            }

        except Exception as e:
            logger.exception(f"[{self._session_id}] Error in answer: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="answer",
                    iteration=review_count,
                    error_type=type(e).__name__
                )

            return {
                "error": str(e),
                "is_complete": True,
            }

    async def _review_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        Review node (for medium-difficulty tasks).

        Reviews the generated answer and decides to approve or reject it.
        """
        logger.info(f"[{self._session_id}] review: Reviewing answer")
        session_logger = self._get_logger()
        review_count = state.get("review_count", 0) + 1

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="review",
                iteration=review_count,
                state_summary={
                    "review_count": review_count,
                    "answer_length": len(state.get("answer", ""))
                }
            )

        try:
            input_text = state.get("input", "")
            answer = state.get("answer", "")

            # Request review
            prompt = AutonomousPrompts.review().format(question=input_text, answer=answer)
            messages = [HumanMessage(content=prompt)]

            response = await self._model.ainvoke(messages)
            review_text = response.content

            # Parse review result
            review_result = ReviewResult.APPROVED
            feedback = ""

            if "VERDICT:" in review_text:
                lines = review_text.split("\n")
                for line in lines:
                    if line.startswith("VERDICT:"):
                        verdict = line.replace("VERDICT:", "").strip().lower()
                        if "rejected" in verdict:
                            review_result = ReviewResult.REJECTED
                    elif line.startswith("FEEDBACK:"):
                        feedback = line.replace("FEEDBACK:", "").strip()
                        # Include remaining lines in feedback
                        idx = lines.index(line)
                        feedback = "\n".join([feedback] + lines[idx + 1:])
                        break
            else:
                # If no VERDICT format found, assume approved
                feedback = review_text

            logger.info(f"[{self._session_id}] review: Result = {review_result.value}")

            # Force approval if max retry count reached
            is_complete = False
            if review_result == ReviewResult.REJECTED and review_count >= self._max_review_retries:
                logger.warning(f"[{self._session_id}] review: Max retries reached, forcing approval")
                review_result = ReviewResult.APPROVED
                is_complete = True
            elif review_result == ReviewResult.APPROVED:
                is_complete = True

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="review",
                    iteration=review_count,
                    output_preview=f"Result: {review_result.value}",
                    duration_ms=0,
                    state_changes={
                        "review_result": review_result.value,
                        "review_count": review_count,
                        "is_complete": is_complete
                    }
                )

            result = {
                "review_result": review_result,
                "review_feedback": feedback,
                "review_count": review_count,
                "messages": [response],
                "current_step": "review_complete",
            }

            if is_complete:
                result["final_answer"] = answer
                result["is_complete"] = True

            return result

        except Exception as e:
            logger.exception(f"[{self._session_id}] Error in review: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="review",
                    iteration=review_count,
                    error_type=type(e).__name__
                )

            return {
                "error": str(e),
                "is_complete": True,
            }

    async def _create_todos_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        TODO creation node (for hard tasks).

        Breaks down a complex task into a TODO list.
        """
        logger.info(f"[{self._session_id}] create_todos: Creating TODO list")
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="create_todos",
                iteration=0,
                state_summary={"difficulty": "hard"}
            )

        try:
            input_text = state.get("input", "")

            # Request TODO creation
            prompt = AutonomousPrompts.create_todos().format(input=input_text)
            messages = [HumanMessage(content=prompt)]

            response = await self._model.ainvoke(messages)
            response_text = response.content.strip()

            # Parse JSON
            import json

            # Remove markdown code block wrappers
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            try:
                todos_raw = json.loads(response_text.strip())
            except json.JSONDecodeError as je:
                logger.warning(f"[{self._session_id}] Failed to parse todos, creating single TODO: {je}")
                todos_raw = [{"id": 1, "title": "Execute task", "description": input_text}]

            # Convert to TodoItem format
            todos: List[TodoItem] = []
            for item in todos_raw:
                todos.append({
                    "id": item.get("id", len(todos) + 1),
                    "title": item.get("title", f"Task {len(todos) + 1}"),
                    "description": item.get("description", ""),
                    "status": TodoStatus.PENDING,
                    "result": None,
                })

            logger.info(f"[{self._session_id}] create_todos: Created {len(todos)} TODO items")

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="create_todos",
                    iteration=0,
                    output_preview=f"Created {len(todos)} TODOs",
                    duration_ms=0,
                    state_changes={"todos_created": len(todos)}
                )

            return {
                "todos": todos,
                "current_todo_index": 0,
                "messages": [response],
                "current_step": "todos_created",
            }

        except Exception as e:
            logger.exception(f"[{self._session_id}] Error in create_todos: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="create_todos",
                    iteration=0,
                    error_type=type(e).__name__
                )

            return {
                "error": str(e),
                "is_complete": True,
            }

    async def _execute_todo_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        TODO execution node (for hard tasks).

        Executes the TODO item at the current index.
        """
        current_index = state.get("current_todo_index", 0)
        todos = state.get("todos", [])

        logger.info(f"[{self._session_id}] execute_todo: Executing TODO {current_index + 1}/{len(todos)}")
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="execute_todo",
                iteration=current_index,
                state_summary={
                    "current_index": current_index,
                    "total_todos": len(todos)
                }
            )

        try:
            if current_index >= len(todos):
                logger.warning(f"[{self._session_id}] execute_todo: Index out of range")
                return {
                    "current_step": "todos_complete",
                }

            input_text = state.get("input", "")
            todo = todos[current_index]

            # Collect previous results
            previous_results = ""
            for i, t in enumerate(todos):
                if i < current_index and t.get("result"):
                    previous_results += f"\n[{t['title']}]: {t['result'][:500]}...\n"

            if not previous_results:
                previous_results = "(No previous items completed)"

            # Request TODO execution
            prompt = AutonomousPrompts.execute_todo().format(
                goal=input_text,
                title=todo["title"],
                description=todo["description"],
                previous_results=previous_results,
            )
            messages = [HumanMessage(content=prompt)]

            response = await self._model.ainvoke(messages)
            result = response.content

            # Update TODO status
            updated_todo: TodoItem = {
                **todo,
                "status": TodoStatus.COMPLETED,
                "result": result,
            }

            logger.info(f"[{self._session_id}] execute_todo: TODO {current_index + 1} completed")

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="execute_todo",
                    iteration=current_index,
                    output_preview=result[:200] if result else None,
                    duration_ms=0,
                    state_changes={
                        "todo_completed": todo["title"],
                        "new_index": current_index + 1
                    }
                )

            return {
                "todos": [updated_todo],
                "current_todo_index": current_index + 1,
                "messages": [response],
                "current_step": f"todo_{current_index + 1}_complete",
            }

        except Exception as e:
            logger.exception(f"[{self._session_id}] Error in execute_todo: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="execute_todo",
                    iteration=current_index,
                    error_type=type(e).__name__
                )

            # Update failed TODO
            if current_index < len(todos):
                failed_todo: TodoItem = {
                    **todos[current_index],
                    "status": TodoStatus.FAILED,
                    "result": f"Error: {str(e)}",
                }
                return {
                    "todos": [failed_todo],
                    "current_todo_index": current_index + 1,
                    "current_step": f"todo_{current_index + 1}_failed",
                }

            return {
                "error": str(e),
                "is_complete": True,
            }

    async def _check_progress_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        Progress check node (for hard tasks).

        Checks whether all TODOs have been completed.
        """
        current_index = state.get("current_todo_index", 0)
        todos = state.get("todos", [])

        logger.info(f"[{self._session_id}] check_progress: {current_index}/{len(todos)} completed")
        session_logger = self._get_logger()

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="check_progress",
                iteration=current_index,
                state_summary={
                    "current_index": current_index,
                    "total_todos": len(todos)
                }
            )

        # Calculate number of completed TODOs
        completed = sum(1 for t in todos if t.get("status") == TodoStatus.COMPLETED)

        if session_logger:
            session_logger.log_graph_node_exit(
                node_name="check_progress",
                iteration=current_index,
                output_preview=f"Progress: {completed}/{len(todos)}",
                duration_ms=0,
                state_changes={"completed_count": completed}
            )

        return {
            "current_step": "progress_checked",
            "metadata": {
                **state.get("metadata", {}),
                "completed_todos": completed,
                "total_todos": len(todos),
            },
        }

    async def _final_review_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        Final review node (for hard tasks).

        Comprehensively reviews all TODO results.
        """
        logger.info(f"[{self._session_id}] final_review: Reviewing all completed work")
        session_logger = self._get_logger()
        todos = state.get("todos", [])

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="final_review",
                iteration=0,
                state_summary={"total_todos": len(todos)}
            )

        try:
            input_text = state.get("input", "")

            # Collect TODO results
            todo_results = ""
            for todo in todos:
                status = todo.get("status", TodoStatus.PENDING)
                result = todo.get("result", "No result")
                todo_results += f"\n### {todo['title']} [{status}]\n{result}\n"

            # Request final review
            prompt = AutonomousPrompts.final_review().format(
                input=input_text,
                todo_results=todo_results,
            )
            messages = [HumanMessage(content=prompt)]

            response = await self._model.ainvoke(messages)
            review_feedback = response.content

            logger.info(f"[{self._session_id}] final_review: Review completed")

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="final_review",
                    iteration=0,
                    output_preview=review_feedback[:200] if review_feedback else None,
                    duration_ms=0,
                    state_changes={"final_review_done": True}
                )

            return {
                "review_feedback": review_feedback,
                "messages": [response],
                "current_step": "final_review_complete",
            }

        except Exception as e:
            logger.exception(f"[{self._session_id}] Error in final_review: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="final_review",
                    iteration=0,
                    error_type=type(e).__name__
                )

            return {
                "review_feedback": f"Review failed: {str(e)}",
                "current_step": "final_review_failed",
            }

    async def _final_answer_node(self, state: AutonomousState) -> Dict[str, Any]:
        """
        Final answer generation node (for hard tasks).

        Synthesizes all task results to generate the final answer.
        """
        logger.info(f"[{self._session_id}] final_answer: Generating final answer")
        session_logger = self._get_logger()
        todos = state.get("todos", [])

        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="final_answer",
                iteration=0,
                state_summary={"total_todos": len(todos)}
            )

        try:
            input_text = state.get("input", "")
            review_feedback = state.get("review_feedback", "")

            # Collect TODO results
            todo_results = ""
            for todo in todos:
                status = todo.get("status", TodoStatus.PENDING)
                result = todo.get("result", "No result")
                todo_results += f"\n### {todo['title']} [{status}]\n{result}\n"

            # Request final answer
            prompt = AutonomousPrompts.final_answer().format(
                input=input_text,
                todo_results=todo_results,
                review_feedback=review_feedback,
            )
            messages = [HumanMessage(content=prompt)]

            response = await self._model.ainvoke(messages)
            final_answer = response.content

            logger.info(f"[{self._session_id}] final_answer: Final answer generated ({len(final_answer)} chars)")

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="final_answer",
                    iteration=0,
                    output_preview=final_answer[:200] if final_answer else None,
                    duration_ms=0,
                    state_changes={"final_answer_generated": True, "is_complete": True}
                )

            return {
                "final_answer": final_answer,
                "messages": [response],
                "current_step": "complete",
                "is_complete": True,
            }

        except Exception as e:
            logger.exception(f"[{self._session_id}] Error in final_answer: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="final_answer",
                    iteration=0,
                    error_type=type(e).__name__
                )

            # On error, compose answer from TODO results only
            todo_results = ""
            for todo in todos:
                if todo.get("result"):
                    todo_results += f"{todo['title']}: {todo['result']}\n"

            return {
                "final_answer": f"Task completed with errors.\n\nResults:\n{todo_results}",
                "error": str(e),
                "is_complete": True,
            }

    # ========================================================================
    # Conditional Edges
    # ========================================================================

    def _route_by_difficulty(self, state: AutonomousState) -> Literal["easy", "medium", "hard"]:
        """Route based on difficulty level."""
        difficulty = state.get("difficulty")

        if difficulty == Difficulty.EASY:
            return "easy"
        elif difficulty == Difficulty.MEDIUM:
            return "medium"
        else:
            return "hard"

    def _route_after_review(self, state: AutonomousState) -> Literal["approved", "retry"]:
        """Route based on review result."""
        review_result = state.get("review_result")

        if review_result == ReviewResult.APPROVED:
            return "approved"
        else:
            return "retry"

    def _route_after_progress_check(self, state: AutonomousState) -> Literal["continue", "complete"]:
        """Route based on progress status."""
        current_index = state.get("current_todo_index", 0)
        todos = state.get("todos", [])

        if current_index >= len(todos):
            return "complete"
        else:
            return "continue"

    # ========================================================================
    # Graph Building
    # ========================================================================

    def build(self) -> CompiledStateGraph:
        """
        Build and compile the graph.

        Returns:
            Compiled StateGraph.
        """
        logger.info(f"[{self._session_id}] Building AutonomousGraph...")

        # Configure checkpointer (persistent when storage_path is available)
        if self._enable_checkpointing:
            self._checkpointer = create_checkpointer(
                storage_path=self._storage_path,
                persistent=True,
            )

        # Create StateGraph
        graph_builder = StateGraph(AutonomousState)

        # ========== Register nodes ==========

        # Common
        graph_builder.add_node("classify_difficulty", self._classify_difficulty_node)

        # Easy path
        graph_builder.add_node("direct_answer", self._direct_answer_node)

        # Medium path
        graph_builder.add_node("answer", self._answer_node)
        graph_builder.add_node("review", self._review_node)

        # Hard path
        graph_builder.add_node("create_todos", self._create_todos_node)
        graph_builder.add_node("execute_todo", self._execute_todo_node)
        graph_builder.add_node("check_progress", self._check_progress_node)
        graph_builder.add_node("final_review", self._final_review_node)
        graph_builder.add_node("final_answer", self._final_answer_node)

        # ========== Define edges ==========

        # START -> classify_difficulty
        graph_builder.add_edge(START, "classify_difficulty")

        # classify_difficulty -> [easy/medium/hard]
        graph_builder.add_conditional_edges(
            "classify_difficulty",
            self._route_by_difficulty,
            {
                "easy": "direct_answer",
                "medium": "answer",
                "hard": "create_todos",
            }
        )

        # Easy path: direct_answer -> END
        graph_builder.add_edge("direct_answer", END)

        # Medium path: answer -> review -> [approved/retry]
        graph_builder.add_edge("answer", "review")
        graph_builder.add_conditional_edges(
            "review",
            self._route_after_review,
            {
                "approved": END,
                "retry": "answer",
            }
        )

        # Hard path: create_todos -> execute_todo -> check_progress -> [continue/complete]
        graph_builder.add_edge("create_todos", "execute_todo")
        graph_builder.add_edge("execute_todo", "check_progress")
        graph_builder.add_conditional_edges(
            "check_progress",
            self._route_after_progress_check,
            {
                "continue": "execute_todo",
                "complete": "final_review",
            }
        )
        graph_builder.add_edge("final_review", "final_answer")
        graph_builder.add_edge("final_answer", END)

        # ========== Compile graph ==========

        if self._checkpointer:
            self._graph = graph_builder.compile(checkpointer=self._checkpointer)
        else:
            self._graph = graph_builder.compile()

        logger.info(f"[{self._session_id}] AutonomousGraph built successfully")
        return self._graph

    def compile(self) -> CompiledStateGraph:
        """Alias for build()."""
        return self.build()

    @property
    def graph(self) -> Optional[CompiledStateGraph]:
        """Return the compiled graph."""
        return self._graph

    def get_initial_state(self, input_text: str, **kwargs) -> AutonomousState:
        """Create the initial state using the centralized helper.

        Args:
            input_text: User input.
            **kwargs: Additional metadata.

        Returns:
            Initial AutonomousState dictionary.
        """
        return make_initial_autonomous_state(input_text, **kwargs)

    def visualize(self) -> Optional[bytes]:
        """
        Visualize the graph (returns a PNG image).

        Returns:
            PNG image bytes, or None.
        """
        if not self._graph:
            logger.warning(f"[{self._session_id}] Graph not built yet, building now...")
            self.build()

        try:
            return self._graph.get_graph().draw_mermaid_png()
        except Exception as e:
            logger.warning(f"[{self._session_id}] Could not visualize graph: {e}")
            return None

    def get_mermaid_diagram(self) -> Optional[str]:
        """
        Return a Mermaid diagram string.

        Returns:
            Mermaid diagram string, or None.
        """
        if not self._graph:
            logger.warning(f"[{self._session_id}] Graph not built yet, building now...")
            self.build()

        try:
            return self._graph.get_graph().draw_mermaid()
        except Exception as e:
            logger.warning(f"[{self._session_id}] Could not generate mermaid diagram: {e}")
            return None
