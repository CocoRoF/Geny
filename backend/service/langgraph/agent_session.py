"""AgentSession — CompiledStateGraph-based session management.

Wraps a CLI session (ClaudeProcess) inside a LangGraph CompiledStateGraph
to provide state-driven execution with resilience (context guard, model
fallback, completion detection) and session memory (long-term / short-term).

Session creation flow:
    1. Create CLI session (ClaudeProcess via ClaudeCLIChatModel)
    2. Build CompiledStateGraph (AgentSession)
    3. Initialize SessionMemoryManager for the session storage path

Usage::

    from service.langgraph import AgentSession

    agent = await AgentSession.create(
        working_dir="/path/to/project",
        model_name="claude-sonnet-4-20250514",
        session_name="my-agent",
    )
    result = await agent.invoke("Hello, what can you help me with?")
    async for event in agent.astream("Build a web app"):
        print(event)
    await agent.cleanup()
"""

import asyncio
from logging import getLogger
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import (
    Annotated,
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    TypedDict,
    Union,
)

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field, PrivateAttr

from service.langgraph.checkpointer import create_checkpointer

from service.claude_manager.models import (
    MCPConfig,
    SessionInfo,
    SessionRole,
    SessionStatus,
)
from service.claude_manager.process_manager import ClaudeProcess
from service.langgraph.claude_cli_model import ClaudeCLIChatModel
from service.langgraph.state import (
    AgentState,
    CompletionSignal,
    make_initial_agent_state,
    make_initial_autonomous_state,
)
from service.langgraph.resilience_nodes import (
    completion_detect_node,
    detect_completion_signal,
    make_context_guard_node,
)
from service.langgraph.session_freshness import (
    SessionFreshness,
    FreshnessConfig,
)
from service.logging.session_logger import get_session_logger, SessionLogger

# Lazy import to avoid circular dependency
_autonomous_graph_module = None

def _get_autonomous_graph_class():
    """Lazy import of AutonomousGraph to avoid circular imports."""
    global _autonomous_graph_module
    if _autonomous_graph_module is None:
        from service.langgraph import autonomous_graph as ag
        _autonomous_graph_module = ag
    return _autonomous_graph_module.AutonomousGraph

logger = getLogger(__name__)


# ============================================================================
# AgentSession Class
# ============================================================================


class AgentSession:
    """CompiledStateGraph-based agent session.

    Owns a ClaudeProcess (CLI subprocess) wrapped as a LangChain model
    and orchestrated via a LangGraph state graph with resilience nodes
    (context guard, completion detection) and session memory.

    Key architecture:
        - ClaudeCLIChatModel: wraps ClaudeProcess as a LangChain model
        - CompiledStateGraph: LangGraph graph executing agent + guard nodes
        - SessionMemoryManager: long-term / short-term memory in session dir
        - Checkpointer: persistent (SqliteSaver) or in-memory (MemorySaver)
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        session_name: Optional[str] = None,
        working_dir: Optional[str] = None,
        model_name: Optional[str] = None,
        max_turns: int = 100,
        timeout: float = 1800.0,
        system_prompt: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        mcp_config: Optional[MCPConfig] = None,
        autonomous: bool = True,
        autonomous_max_iterations: int = 100,
        role: SessionRole = SessionRole.WORKER,
        manager_id: Optional[str] = None,
        enable_checkpointing: bool = False,
        workflow_id: Optional[str] = None,
    ):
        """Initialize AgentSession.

        Args:
            session_id: Unique session identifier (auto-generated if omitted).
            session_name: Human-readable session label.
            working_dir: CLI working directory (falls back to storage_path).
            model_name: Claude model name.
            max_turns: Maximum turns per CLI invocation.
            timeout: Execution timeout in seconds.
            system_prompt: System prompt override.
            env_vars: Extra environment variables.
            mcp_config: MCP server configuration.
            autonomous: Whether to use autonomous (difficulty-based) execution.
            autonomous_max_iterations: Max graph iterations for autonomous mode.
            role: Session role (MANAGER / WORKER).
            manager_id: Parent manager session ID (for workers).
            enable_checkpointing: Enable LangGraph MemorySaver checkpointing.
        """
        # Session identity
        self._session_id = session_id or str(uuid.uuid4())
        self._session_name = session_name
        self._created_at = datetime.now()

        # Execution settings (working_dir=None → ClaudeProcess uses storage_path)
        self._working_dir = working_dir
        self._model_name = model_name
        self._max_turns = max_turns
        self._timeout = timeout
        self._system_prompt = system_prompt
        self._env_vars = env_vars or {}
        self._mcp_config = mcp_config
        self._autonomous = autonomous
        self._autonomous_max_iterations = autonomous_max_iterations

        # Role
        self._role = role
        self._manager_id = manager_id

        # Workflow / Graph
        self._workflow_id = workflow_id

        # Internal components
        self._model: Optional[ClaudeCLIChatModel] = None
        self._graph: Optional[CompiledStateGraph] = None
        self._checkpointer: Optional[object] = None  # MemorySaver or SqliteSaver
        self._enable_checkpointing = enable_checkpointing

        # Memory manager (initialized lazily once storage_path is available)
        self._memory_manager: Optional["SessionMemoryManager"] = None

        # Execution state
        self._initialized = False
        self._error_message: Optional[str] = None
        self._current_thread_id: str = "default"
        self._current_iteration: int = 0
        self._execution_start_time: Optional[datetime] = None

        # Autonomous graph (used when autonomous=True)
        self._autonomous_graph: Optional[CompiledStateGraph] = None

        # Session freshness evaluator
        self._freshness = SessionFreshness()

        # Initial status
        self._status = SessionStatus.STARTING

    # ========================================================================
    # Factory Methods
    # ========================================================================

    @classmethod
    async def create(
        cls,
        working_dir: Optional[str] = None,
        model_name: Optional[str] = None,
        session_name: Optional[str] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        mcp_config: Optional[MCPConfig] = None,
        role: SessionRole = SessionRole.WORKER,
        enable_checkpointing: bool = False,
        **kwargs,
    ) -> "AgentSession":
        """Create and initialize a new AgentSession.

        Args:
            working_dir: Working directory for the CLI session.
            model_name: Claude model name.
            session_name: Human-readable session label.
            session_id: Unique session ID.
            system_prompt: System prompt override.
            mcp_config: MCP configuration.
            role: Session role.
            enable_checkpointing: Enable LangGraph checkpointing.
            **kwargs: Additional settings forwarded to __init__.

        Returns:
            Fully initialized AgentSession instance.
        """
        agent = cls(
            session_id=session_id,
            session_name=session_name,
            working_dir=working_dir,
            model_name=model_name,
            system_prompt=system_prompt,
            mcp_config=mcp_config,
            role=role,
            enable_checkpointing=enable_checkpointing,
            **kwargs,
        )

        success = await agent.initialize()
        if not success:
            raise RuntimeError(f"Failed to initialize AgentSession: {agent.error_message}")

        return agent

    @classmethod
    def from_process(cls, process: ClaudeProcess, enable_checkpointing: bool = False) -> "AgentSession":
        """Create AgentSession from an existing ClaudeProcess.

        Args:
            process: Initialized ClaudeProcess instance.
            enable_checkpointing: Enable LangGraph checkpointing.

        Returns:
            AgentSession instance.
        """
        agent = cls(
            session_id=process.session_id,
            session_name=process.session_name,
            working_dir=process.working_dir,
            model_name=process.model,
            max_turns=process.max_turns,
            timeout=process.timeout,
            system_prompt=process.system_prompt,
            env_vars=process.env_vars or {},
            mcp_config=process.mcp_config,
            autonomous=process.autonomous,
            autonomous_max_iterations=process.autonomous_max_iterations,
            role=SessionRole(process.role) if process.role else SessionRole.WORKER,
            manager_id=process.manager_id,
            enable_checkpointing=enable_checkpointing,
        )

        # Wire model, build graph, initialize memory
        agent._model = ClaudeCLIChatModel.from_process(process)
        agent._build_graph()
        agent._init_memory()
        agent._initialized = True
        agent._status = SessionStatus.RUNNING

        logger.info(f"[{agent.session_id}] AgentSession created from existing process")
        return agent

    @classmethod
    def from_model(cls, model: ClaudeCLIChatModel, enable_checkpointing: bool = False) -> "AgentSession":
        """Create AgentSession from an existing ClaudeCLIChatModel.

        Args:
            model: Initialized ClaudeCLIChatModel instance.
            enable_checkpointing: Enable LangGraph checkpointing.

        Returns:
            AgentSession instance.
        """
        if not model.is_initialized:
            raise ValueError("ClaudeCLIChatModel must be initialized before creating AgentSession")

        agent = cls(
            session_id=model.session_id,
            session_name=model.session_name,
            working_dir=model.working_dir,
            model_name=model.model_name,
            max_turns=model.max_turns,
            timeout=model.timeout,
            system_prompt=model.system_prompt,
            env_vars=model.env_vars,
            mcp_config=model.mcp_config,
            autonomous=model.autonomous,
            enable_checkpointing=enable_checkpointing,
        )

        agent._model = model
        agent._build_graph()
        agent._init_memory()
        agent._initialized = True
        agent._status = SessionStatus.RUNNING

        logger.info(f"[{agent.session_id}] AgentSession created from existing model")
        return agent

    # ========================================================================
    # Properties (SessionInfo compatible)
    # ========================================================================

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_name(self) -> Optional[str]:
        return self._session_name

    @property
    def status(self) -> SessionStatus:
        return self._status

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def pid(self) -> Optional[int]:
        """Process ID from the underlying ClaudeProcess."""
        if self._model and self._model.process:
            return self._model.process.pid
        return None

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    @property
    def max_turns(self) -> int:
        return self._max_turns

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def autonomous(self) -> bool:
        return self._autonomous

    @property
    def autonomous_max_iterations(self) -> int:
        return self._autonomous_max_iterations

    @property
    def role(self) -> SessionRole:
        return self._role

    @property
    def manager_id(self) -> Optional[str]:
        return self._manager_id

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def graph(self) -> Optional[CompiledStateGraph]:
        """Internal CompiledStateGraph."""
        return self._graph

    @property
    def model(self) -> Optional[ClaudeCLIChatModel]:
        """Internal ClaudeCLIChatModel."""
        return self._model

    @property
    def process(self) -> Optional[ClaudeProcess]:
        """Internal ClaudeProcess."""
        if self._model:
            return self._model.process
        return None

    @property
    def storage_path(self) -> Optional[str]:
        """Session storage directory path."""
        if self._model and self._model.process:
            return self._model.process.storage_path
        return None

    @property
    def memory_manager(self) -> Optional["SessionMemoryManager"]:
        """Session memory manager (available after initialization)."""
        return self._memory_manager

    def _get_logger(self) -> Optional[SessionLogger]:
        """Get session logger (lazy)."""
        return get_session_logger(self._session_id, create_if_missing=True)

    def _get_state_summary(self, state: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Build a compact state summary for logging."""
        if not state:
            return None
        ctx = state.get("context_budget")
        return {
            "messages_count": len(state.get("messages", [])),
            "current_step": state.get("current_step"),
            "is_complete": state.get("is_complete", False),
            "has_error": bool(state.get("error")),
            "iteration": state.get("iteration", 0),
            "completion_signal": state.get("completion_signal"),
            "context_usage": f"{ctx['usage_ratio']:.0%}" if ctx else None,
            "memory_refs_count": len(state.get("memory_refs", [])),
        }
    # ========================================================================
    # Core Methods
    # ========================================================================

    def _check_freshness(self) -> None:
        """Evaluate session freshness and log or raise on staleness.

        Called at the top of ``invoke()`` and ``astream()`` to detect
        sessions that are too old, idle, or large.  On STALE_RESET the
        session is marked as ERROR to prevent further use.
        """
        result = self._freshness.evaluate(
            created_at=self._created_at,
            last_activity=self._execution_start_time,
            iteration_count=self._current_iteration,
            message_count=0,  # message count resolved inside the graph
        )
        if result.should_reset:
            self._status = SessionStatus.ERROR
            self._error_message = f"Session stale: {result.reason}"
            raise RuntimeError(
                f"Session {self._session_id} is stale and should be recreated: "
                f"{result.reason}"
            )

    def _init_memory(self):
        """Initialize the session memory manager if storage_path is available."""
        sp = self.storage_path
        if not sp:
            logger.debug(f"[{self._session_id}] No storage_path — memory manager skipped")
            return
        try:
            from service.memory.manager import SessionMemoryManager
            self._memory_manager = SessionMemoryManager(sp)
            self._memory_manager.initialize()
            logger.info(f"[{self._session_id}] SessionMemoryManager initialized at {sp}")
        except Exception as e:
            logger.warning(f"[{self._session_id}] Failed to initialize memory: {e}")
            self._memory_manager = None

    async def initialize(self) -> bool:
        """Initialize the AgentSession.

        Steps:
            1. Create and initialize ClaudeCLIChatModel (spawns ClaudeProcess).
            2. Build LangGraph StateGraph with resilience nodes.
            3. Initialize SessionMemoryManager.

        Returns:
            True on success, False on failure.
        """
        if self._initialized:
            logger.info(f"[{self._session_id}] AgentSession already initialized")
            return True

        logger.info(f"[{self._session_id}] Initializing AgentSession...")

        try:
            # 1. Create ClaudeCLIChatModel
            self._model = ClaudeCLIChatModel(
                session_id=self._session_id,
                session_name=self._session_name,
                working_dir=self._working_dir,
                model_name=self._model_name,
                max_turns=self._max_turns,
                timeout=self._timeout,
                system_prompt=self._system_prompt,
                env_vars=self._env_vars,
                mcp_config=self._mcp_config,
                autonomous=self._autonomous,
            )

            # 2. Initialize model (spawns ClaudeProcess)
            success = await self._model.initialize()
            if not success:
                self._error_message = self._model.process.error_message if self._model.process else "Unknown error"
                self._status = SessionStatus.ERROR
                logger.error(f"[{self._session_id}] Failed to initialize model: {self._error_message}")
                return False

            # 3. Initialize memory manager (before graph, so autonomous graph can use it)
            self._init_memory()

            # 4. Build StateGraph
            self._build_graph()

            self._initialized = True
            self._status = SessionStatus.RUNNING
            logger.info(f"[{self._session_id}] AgentSession initialized successfully")
            return True

        except Exception as e:
            self._error_message = str(e)
            self._status = SessionStatus.ERROR
            logger.exception(f"[{self._session_id}] Exception during initialization: {e}")
            return False

    def _build_graph(self):
        """Build the LangGraph StateGraph.

        If autonomous mode: uses difficulty-based AutonomousGraph.
        Otherwise: builds a simple agent -> process_output loop with
        context guard and completion detection nodes.
        """
        # Checkpointer setup (persistent when storage_path is available)
        if self._enable_checkpointing:
            storage = self.storage_path if hasattr(self, 'storage_path') else None
            self._checkpointer = create_checkpointer(
                storage_path=storage,
                persistent=True,
            )

        # Autonomous mode: AutonomousGraph
        if self._autonomous:
            self._build_autonomous_graph()
        else:
            self._build_simple_graph()

        logger.debug(f"[{self._session_id}] StateGraph built (autonomous={self._autonomous})")

    def _build_autonomous_graph(self):
        """Build difficulty-based AutonomousGraph with full resilience.

        Passes memory_manager and max_iterations so the autonomous graph
        can use memory injection and enforce global iteration caps.

        Routes:
            - Easy: direct answer
            - Medium: answer + review loop
            - Hard: TODO planning -> execute -> review -> final
        """
        AutonomousGraph = _get_autonomous_graph_class()

        autonomous_graph_builder = AutonomousGraph(
            model=self._model,
            session_id=self._session_id,
            enable_checkpointing=self._enable_checkpointing,
            max_review_retries=3,
            storage_path=self.storage_path if hasattr(self, 'storage_path') else None,
            memory_manager=self._memory_manager,
            max_iterations=self._autonomous_max_iterations,
            model_name=self._model_name,
        )

        self._autonomous_graph = autonomous_graph_builder.build()

        # Also build the simple graph for backward compatibility
        self._build_simple_graph()

        logger.info(f"[{self._session_id}] AutonomousGraph built for autonomous execution")

    def _build_simple_graph(self):
        """Build the simple (non-autonomous) state graph.

        Graph topology::

            START -> context_guard -> agent -> process_output
                         ^                        |
                         |--- continue -----------+
                                                  |
                                           end -> END

        Nodes:
            context_guard  — check context budget, auto-compact if needed
            agent          — invoke Claude CLI, record transcript
            process_output — increment iteration, detect completion signal
        """
        graph_builder = StateGraph(AgentState)

        # -- Register nodes --
        # Context guard (factory creates a closure with model-specific limits)
        graph_builder.add_node(
            "context_guard",
            make_context_guard_node(model=self._model_name),
        )
        graph_builder.add_node("agent", self._agent_node)
        graph_builder.add_node("process_output", self._process_output_node)

        # -- Edges --
        graph_builder.add_edge(START, "context_guard")
        graph_builder.add_edge("context_guard", "agent")
        graph_builder.add_edge("agent", "process_output")
        graph_builder.add_conditional_edges(
            "process_output",
            self._should_continue,
            {
                "continue": "context_guard",
                "end": END,
            },
        )

        # Compile
        if self._checkpointer:
            self._graph = graph_builder.compile(checkpointer=self._checkpointer)
        else:
            self._graph = graph_builder.compile()

    async def _agent_node(self, state: AgentState) -> Dict[str, Any]:
        """Agent node: invoke Claude CLI and update state.

        Reads messages from state, calls the model, writes the response
        back. Also records the turn to short-term memory if available.
        """
        import time
        start_time = time.time()
        iteration = state.get("iteration", 0)

        session_logger = self._get_logger()
        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="agent",
                iteration=iteration,
                state_summary=self._get_state_summary(state),
            )

        try:
            messages = state.get("messages", [])
            if not messages:
                error_result = {
                    "error": "No messages in state",
                    "is_complete": True,
                }
                if session_logger:
                    session_logger.log_graph_error(
                        error_message="No messages in state",
                        node_name="agent",
                        iteration=iteration,
                    )
                return error_result

            # Invoke Claude CLI
            response = await self._model.ainvoke(messages)
            duration_ms = int((time.time() - start_time) * 1000)

            output_content = response.content if hasattr(response, "content") else str(response)

            # Record turn to short-term memory
            if self._memory_manager:
                try:
                    self._memory_manager.record_message("assistant", output_content)
                    # Record user input on first iteration
                    if iteration == 0:
                        for msg in messages:
                            if hasattr(msg, "type") and msg.type == "human":
                                self._memory_manager.record_message("user", msg.content)
                                break
                except Exception:
                    logger.debug("Failed to record transcript — non-critical", exc_info=True)

            if session_logger:
                session_logger.log_graph_node_exit(
                    node_name="agent",
                    iteration=iteration,
                    output_preview=output_content,
                    duration_ms=duration_ms,
                    state_changes={"messages_added": 1, "last_output_updated": True},
                )

            return {
                "messages": [response],
                "last_output": output_content,
                "current_step": "agent_responded",
                "error": None,
            }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.exception(f"[{self._session_id}] Error in agent node: {e}")

            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="agent",
                    iteration=iteration,
                    error_type=type(e).__name__,
                )

            return {
                "error": str(e),
                "is_complete": True,
            }

    async def _process_output_node(self, state: AgentState) -> Dict[str, Any]:
        """Process output node: increment iteration & detect completion.

        Reads ``last_output`` from state, runs structured signal detection,
        and writes ``iteration``, ``completion_signal``, ``completion_detail``
        back to state. The edge function then reads these to decide routing.
        """
        iteration = state.get("iteration", 0) + 1
        max_iterations = state.get("max_iterations", self._autonomous_max_iterations)

        # Track instance-level iteration counter
        self._current_iteration = iteration

        session_logger = self._get_logger()
        if session_logger:
            session_logger.log_graph_node_enter(
                node_name="process_output",
                iteration=iteration,
                state_summary=self._get_state_summary(state),
            )
            session_logger.log_graph_state_update(
                update_type="iteration_increment",
                changes={"iteration": iteration, "max_iterations": max_iterations},
                iteration=iteration,
            )

        # Detect structured completion signal from last output
        last_output = state.get("last_output", "")
        signal, detail = detect_completion_signal(last_output)

        updates: Dict[str, Any] = {
            "iteration": iteration,
            "current_step": "output_processed",
            "completion_signal": signal.value,
            "completion_detail": detail,
        }

        # Mark is_complete if signal says task is done/blocked/error
        if signal in (CompletionSignal.COMPLETE, CompletionSignal.BLOCKED, CompletionSignal.ERROR):
            updates["is_complete"] = True

        return updates

    def _should_continue(self, state: AgentState) -> Literal["continue", "end"]:
        """Conditional edge: decide whether to loop or stop.

        Reads state fields written by process_output_node:
            - is_complete, error          → immediate stop
            - completion_signal           → structured stop / continue
            - iteration / max_iterations  → iteration cap

        Returns:
            "continue" to loop back to context_guard, "end" to finish.
        """
        iteration = state.get("iteration", 0)
        max_iterations = state.get("max_iterations", self._autonomous_max_iterations)
        session_logger = self._get_logger()

        decision = "continue"
        reason = None

        if state.get("is_complete", False):
            decision = "end"
            reason = "is_complete flag set"
        elif state.get("error"):
            decision = "end"
            reason = f"error: {str(state.get('error'))[:50]}"
        elif not self._autonomous or max_iterations <= 1:
            # Single execution mode (no looping)
            decision = "end"
            reason = "single execution mode"
        elif iteration >= max_iterations:
            decision = "end"
            reason = f"max_iterations reached ({iteration}/{max_iterations})"
        else:
            # Read the structured completion signal from state
            raw_signal = state.get("completion_signal")
            if raw_signal:
                try:
                    signal = CompletionSignal(raw_signal)
                except ValueError:
                    signal = CompletionSignal.NONE
            else:
                signal = CompletionSignal.NONE

            if signal == CompletionSignal.COMPLETE:
                decision = "end"
                reason = "[TASK_COMPLETE] signal"
            elif signal == CompletionSignal.BLOCKED:
                decision = "end"
                reason = f"[BLOCKED] {state.get('completion_detail', '')}"
            elif signal == CompletionSignal.ERROR:
                decision = "end"
                reason = f"[ERROR] {state.get('completion_detail', '')}"
            # CONTINUE / NONE → keep going

        if session_logger:
            session_logger.log_graph_edge_decision(
                from_node="process_output",
                decision=decision,
                reason=reason,
                iteration=iteration,
            )

        return decision

    def _is_task_complete(self, output: str) -> bool:
        """Check whether the output indicates task completion.

        Thin wrapper around the centralized ``detect_completion_signal``
        from resilience_nodes.
        """
        signal, _ = detect_completion_signal(output)
        return signal in (
            CompletionSignal.COMPLETE,
            CompletionSignal.BLOCKED,
            CompletionSignal.ERROR,
        )

    # ========================================================================
    # Execution Methods
    # ========================================================================

    async def invoke(
        self,
        input_text: str,
        thread_id: Optional[str] = None,
        max_iterations: Optional[int] = None,
        **kwargs,
    ) -> str:
        """Synchronous-style execution (returns final result).

        In autonomous mode uses the difficulty-based AutonomousGraph.
        Otherwise runs the simple context_guard -> agent -> process_output loop.

        Args:
            input_text: User input text.
            thread_id: Thread ID for checkpointing.
            max_iterations: Override for max iterations.
            **kwargs: Additional metadata.

        Returns:
            Agent response text.
        """
        import time
        start_time = time.time()

        if not self._initialized or not self._graph:
            raise RuntimeError("AgentSession not initialized. Call initialize() first.")

        # Freshness check — log warning or raise if stale
        self._check_freshness()

        self._status = SessionStatus.RUNNING
        self._current_iteration = 0
        self._execution_start_time = datetime.now()
        thread_id = thread_id or self._current_thread_id
        effective_max_iterations = max_iterations or self._autonomous_max_iterations

        session_logger = self._get_logger()

        # Log graph execution start
        if session_logger:
            session_logger.log_graph_execution_start(
                input_text=input_text,
                thread_id=thread_id,
                max_iterations=effective_max_iterations,
                execution_mode="invoke_autonomous" if self._autonomous else "invoke",
            )

        try:
            config = {"configurable": {"thread_id": thread_id}}

            # Autonomous mode: difficulty-based AutonomousGraph
            if self._autonomous and self._autonomous_graph:
                result = await self._invoke_autonomous(input_text, config, **kwargs)
                duration_ms = int((time.time() - start_time) * 1000)

                final_output = result.get("final_answer", "") or result.get("answer", "")
                has_error = bool(result.get("error"))

                # Log autonomous execution completion
                if session_logger:
                    session_logger.log_graph_execution_complete(
                        success=not has_error,
                        total_iterations=result.get("metadata", {}).get("completed_todos", 0),
                        final_output=final_output[:500] if final_output else None,
                        total_duration_ms=duration_ms,
                        stop_reason="completed" if not has_error else result.get("error"),
                    )

                if has_error:
                    self._error_message = result["error"]
                    return f"Error: {result['error']}"

                return final_output

            # Non-autonomous mode: simple graph
            initial_state = make_initial_agent_state(
                input_text,
                max_iterations=effective_max_iterations,
                **kwargs,
            )

            # Record user input to short-term memory
            if self._memory_manager:
                try:
                    self._memory_manager.record_message("user", input_text)
                except Exception:
                    logger.debug("Failed to record user message — non-critical", exc_info=True)

            result = await self._graph.ainvoke(initial_state, config)
            duration_ms = int((time.time() - start_time) * 1000)
            self._status = SessionStatus.RUNNING

            # Extract results from final state
            final_output = result.get("last_output", "")
            has_error = bool(result.get("error"))
            total_iterations = result.get("iteration", 0)

            # Log execution completion
            if session_logger:
                session_logger.log_graph_execution_complete(
                    success=not has_error,
                    total_iterations=total_iterations,
                    final_output=final_output,
                    total_duration_ms=duration_ms,
                    stop_reason="completed" if not has_error else result.get("error")
                )

            if has_error:
                self._error_message = result["error"]
                return f"Error: {result['error']}"

            return final_output

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self._status = SessionStatus.RUNNING
            self._error_message = str(e)
            logger.exception(f"[{self._session_id}] Error during invoke: {e}")

            # Log error
            if session_logger:
                session_logger.log_graph_execution_complete(
                    success=False,
                    total_iterations=self._current_iteration,
                    final_output=None,
                    total_duration_ms=duration_ms,
                    stop_reason=f"exception: {type(e).__name__}",
                )

            raise

    async def _invoke_autonomous(
        self,
        input_text: str,
        config: Dict[str, Any],
        **kwargs,
    ) -> Dict[str, Any]:
        """Run the autonomous (difficulty-based) graph.

        Args:
            input_text: User input.
            config: LangGraph execution config.
            **kwargs: Extra metadata.

        Returns:
            Final state dict with answer/final_answer.
        """
        if not self._autonomous_graph:
            raise RuntimeError("AutonomousGraph not built")

        # Create initial state using centralized helper
        initial_state = make_initial_autonomous_state(
            input_text,
            max_iterations=self._autonomous_max_iterations,
            **kwargs,
        )

        # Execute graph
        result = await self._autonomous_graph.ainvoke(initial_state, config)

        self._status = SessionStatus.RUNNING

        return result

    async def _astream_autonomous(
        self,
        input_text: str,
        config: Dict[str, Any],
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream the autonomous (difficulty-based) graph execution.

        Args:
            input_text: User input.
            config: LangGraph execution config.
            **kwargs: Extra metadata.

        Yields:
            Per-node execution results.
        """
        if not self._autonomous_graph:
            raise RuntimeError("AutonomousGraph not built")

        # Create initial state using centralized helper
        initial_state = make_initial_autonomous_state(
            input_text,
            max_iterations=self._autonomous_max_iterations,
            **kwargs,
        )

        # Stream graph execution
        async for event in self._autonomous_graph.astream(initial_state, config):
            yield event

    async def astream(
        self,
        input_text: str,
        thread_id: Optional[str] = None,
        max_iterations: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming execution.

        In autonomous mode uses the difficulty-based AutonomousGraph.

        Args:
            input_text: User input text.
            thread_id: Thread ID for checkpointing.
            max_iterations: Override for max iterations.

        Yields:
            Per-node execution results.
        """
        if not self._initialized or not self._graph:
            raise RuntimeError("AgentSession not initialized. Call initialize() first.")

        # Freshness check
        self._check_freshness()

        self._status = SessionStatus.RUNNING
        thread_id = thread_id or self._current_thread_id

        # Initialize logging for graph execution
        session_logger = self._get_logger()
        start_time = time.time()
        self._current_iteration = 0
        self._execution_start_time = start_time
        effective_max_iterations = max_iterations or self._autonomous_max_iterations
        event_count = 0
        last_event = None

        # Log execution start
        if session_logger:
            session_logger.log_graph_execution_start(
                input_text=input_text,
                thread_id=thread_id,
                max_iterations=effective_max_iterations,
                execution_mode="astream_autonomous" if self._autonomous else "astream",
            )

        try:
            config = {"configurable": {"thread_id": thread_id}}

            # Autonomous mode: AutonomousGraph
            if self._autonomous and self._autonomous_graph:
                async for event in self._astream_autonomous(input_text, config, **kwargs):
                    event_count += 1
                    last_event = event

                    # Log stream event
                    if session_logger:
                        event_keys = list(event.keys()) if isinstance(event, dict) else []
                        session_logger.log_graph_event(
                            event_type="stream_event",
                            message=f"AUTONOMOUS_STREAM event_{event_count}",
                            data={
                                "event_number": event_count,
                                "event_keys": event_keys,
                                "elapsed_ms": int((time.time() - start_time) * 1000),
                            },
                        )

                    yield event
            else:
                # Non-autonomous mode: simple graph
                initial_state = make_initial_agent_state(
                    input_text,
                    max_iterations=effective_max_iterations,
                    **kwargs,
                )

                # Record user input to short-term memory
                if self._memory_manager:
                    try:
                        self._memory_manager.record_message("user", input_text)
                    except Exception:
                        logger.debug("Failed to record user message — non-critical", exc_info=True)

                async for event in self._graph.astream(initial_state, config):
                    event_count += 1
                    last_event = event

                    # Log stream event
                    if session_logger:
                        event_keys = list(event.keys()) if isinstance(event, dict) else []
                        session_logger.log_graph_event(
                            event_type="stream_event",
                            message=f"STREAM event_{event_count}",
                            data={
                                "event_number": event_count,
                                "event_keys": event_keys,
                                "elapsed_ms": int((time.time() - start_time) * 1000),
                            },
                        )

                    yield event

            self._status = SessionStatus.RUNNING

            # Log streaming completion
            duration_ms = int((time.time() - start_time) * 1000)
            if session_logger:
                # Try to extract final output from last event
                final_output = None
                if last_event and isinstance(last_event, dict):
                    for key in ["final_answer", "direct_answer", "answer", "process_output", "agent", "__end__"]:
                        if key in last_event:
                            node_result = last_event[key]
                            if isinstance(node_result, dict):
                                final_output = node_result.get("final_answer") or node_result.get("answer") or node_result.get("last_output")
                                if final_output:
                                    break

                session_logger.log_graph_execution_complete(
                    success=True,
                    total_iterations=self._current_iteration,
                    final_output=final_output[:500] if final_output else None,
                    total_duration_ms=duration_ms,
                    stop_reason="stream_complete",
                )

        except Exception as e:
            self._status = SessionStatus.RUNNING
            self._error_message = str(e)
            logger.exception(f"[{self._session_id}] Error during astream: {e}")

            # Log error
            duration_ms = int((time.time() - start_time) * 1000)
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="astream",
                    iteration=self._current_iteration,
                    error_type=type(e).__name__,
                )
                session_logger.log_graph_execution_complete(
                    success=False,
                    total_iterations=self._current_iteration,
                    final_output=None,
                    total_duration_ms=duration_ms,
                    stop_reason=f"exception: {type(e).__name__}",
                )

            raise

    async def execute(
        self,
        prompt: str,
        timeout: Optional[float] = None,
        skip_permissions: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute via the legacy ClaudeProcess.execute() interface.

        Provides backward compatibility with controllers that call
        process.execute() directly.

        Args:
            prompt: Prompt text to execute.
            timeout: Override timeout in seconds.
            skip_permissions: Skip permission prompts.
            **kwargs: Additional settings.

        Returns:
            Result dict with output, cost_usd, duration_ms, etc.
        """
        if not self._initialized or not self._model or not self._model.process:
            raise RuntimeError("AgentSession not initialized")

        self._status = SessionStatus.RUNNING

        try:
            # Delegate to ClaudeProcess.execute() for backward compatibility
            result = await self._model.process.execute(
                prompt=prompt,
                timeout=timeout or self._timeout,
                skip_permissions=skip_permissions,
                **kwargs,
            )

            self._status = SessionStatus.RUNNING
            return result

        except Exception as e:
            self._status = SessionStatus.RUNNING
            self._error_message = str(e)
            logger.exception(f"[{self._session_id}] Error during execute: {e}")
            raise

    # ========================================================================
    # Lifecycle Methods
    # ========================================================================

    async def cleanup(self):
        """Clean up the AgentSession and release all resources.

        Flushes short-term memory to long-term before shutting down.
        """
        logger.info(f"[{self._session_id}] Cleaning up AgentSession...")

        # Flush memory before shutdown
        if self._memory_manager:
            try:
                self._memory_manager.auto_flush()
                logger.debug(f"[{self._session_id}] Memory flushed to long-term storage")
            except Exception:
                logger.debug("Failed to flush memory — non-critical", exc_info=True)
            self._memory_manager = None

        if self._model:
            await self._model.cleanup()
            self._model = None

        self._graph = None
        self._checkpointer = None
        self._initialized = False
        self._status = SessionStatus.STOPPED

        logger.info(f"[{self._session_id}] AgentSession cleaned up")

    async def stop(self):
        """Stop the session (alias for cleanup)."""
        await self.cleanup()

    def is_alive(self) -> bool:
        """Check whether the underlying process is still running."""
        if self._model and self._model.process:
            return self._model.process.is_alive()
        return False

    # ========================================================================
    # SessionInfo Compatibility
    # ========================================================================

    def get_session_info(self, pod_name: Optional[str] = None, pod_ip: Optional[str] = None) -> SessionInfo:
        """Return a SessionInfo for backward compatibility with SessionManager.

        Args:
            pod_name: Optional pod name.
            pod_ip: Optional pod IP.

        Returns:
            SessionInfo instance.
        """
        return SessionInfo(
            session_id=self._session_id,
            session_name=self._session_name,
            status=self._status,
            created_at=self._created_at,
            pid=self.pid,
            error_message=self._error_message,
            model=self._model_name,
            max_turns=self._max_turns,
            timeout=self._timeout,
            autonomous=self._autonomous,
            autonomous_max_iterations=self._autonomous_max_iterations,
            storage_path=self.storage_path,
            pod_name=pod_name,
            pod_ip=pod_ip,
            role=self._role,
            manager_id=self._manager_id,
            workflow_id=self._workflow_id,
        )

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def get_state(self, thread_id: Optional[str] = None) -> Optional[AgentState]:
        """Get current graph state (requires checkpointing).

        Args:
            thread_id: Thread ID.

        Returns:
            Current state or None.
        """
        if not self._enable_checkpointing or not self._graph:
            return None

        config = {"configurable": {"thread_id": thread_id or self._current_thread_id}}
        try:
            state_snapshot = self._graph.get_state(config)
            return state_snapshot.values if state_snapshot else None
        except Exception as e:
            logger.warning(f"[{self._session_id}] Could not get state: {e}")
            return None

    def get_history(self, thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get execution history (requires checkpointing).

        Args:
            thread_id: Thread ID.

        Returns:
            List of state snapshots.
        """
        if not self._enable_checkpointing or not self._graph:
            return []

        config = {"configurable": {"thread_id": thread_id or self._current_thread_id}}
        try:
            history = list(self._graph.get_state_history(config))
            return [{"config": h.config, "values": h.values} for h in history]
        except Exception as e:
            logger.warning(f"[{self._session_id}] Could not get history: {e}")
            return []

    def visualize(self, autonomous: bool = True) -> Optional[bytes]:
        """Render the graph as a PNG image.

        Args:
            autonomous: If True, visualize AutonomousGraph; else simple graph.

        Returns:
            PNG image bytes or None.
        """
        graph_to_visualize = None

        if autonomous and self._autonomous_graph:
            graph_to_visualize = self._autonomous_graph
        elif self._graph:
            graph_to_visualize = self._graph

        if not graph_to_visualize:
            return None

        try:
            return graph_to_visualize.get_graph().draw_mermaid_png()
        except Exception as e:
            logger.warning(f"[{self._session_id}] Could not visualize graph: {e}")
            return None

    def get_mermaid_diagram(self, autonomous: bool = True) -> Optional[str]:
        """Return a Mermaid diagram string for the graph.

        Args:
            autonomous: If True, render AutonomousGraph; else simple graph.

        Returns:
            Mermaid diagram string or None.
        """
        graph_to_visualize = None

        if autonomous and self._autonomous_graph:
            graph_to_visualize = self._autonomous_graph
        elif self._graph:
            graph_to_visualize = self._graph

        if not graph_to_visualize:
            return None

        try:
            return graph_to_visualize.get_graph().draw_mermaid()
        except Exception as e:
            logger.warning(f"[{self._session_id}] Could not generate mermaid diagram: {e}")
            return None

    def __repr__(self) -> str:
        return (
            f"AgentSession("
            f"session_id={self._session_id!r}, "
            f"status={self._status.value}, "
            f"initialized={self._initialized})"
        )
