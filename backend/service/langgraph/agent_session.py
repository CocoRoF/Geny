"""AgentSession — CompiledStateGraph-based session management.

Wraps a CLI session (ClaudeProcess) inside a LangGraph CompiledStateGraph
to provide state-driven execution with resilience (context guard, model
fallback, completion detection) and session memory (long-term / short-term).

Every session is linked to a WorkflowDefinition (either a template or a
user-created workflow). The WorkflowExecutor compiles it into a
CompiledStateGraph. There is ONE graph, ONE execution path — no branching
between "simple" and "autonomous".

Session creation flow:
    1. Create CLI session (ClaudeProcess via ClaudeCLIChatModel)
    2. Load WorkflowDefinition (from workflow_id or default template)
    3. Compile via WorkflowExecutor → CompiledStateGraph
    4. Initialize SessionMemoryManager for the session storage path

Usage::

    from service.langgraph import AgentSession

    agent = await AgentSession.create(
        working_dir="/path/to/project",
        model_name="claude-sonnet-4-20250514",
        session_name="my-agent",
        workflow_id="template-simple",
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
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
)

from langgraph.graph.state import CompiledStateGraph

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
    AutonomousState,
    make_initial_autonomous_state,
)
from service.langgraph.session_freshness import SessionFreshness, FreshnessStatus
from service.logging.session_logger import get_session_logger, SessionLogger
from service.tool_executor.context import set_session_allowed_tools, clear_session_allowed_tools
from service.workflow.workflow_model import WorkflowDefinition
from service.workflow.workflow_executor import WorkflowExecutor
from service.workflow.nodes.base import ExecutionContext

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
        max_iterations: int = 100,
        role: SessionRole = SessionRole.WORKER,
        enable_checkpointing: bool = False,
        workflow_id: Optional[str] = None,
        graph_name: Optional[str] = None,
        tool_preset_id: Optional[str] = None,
        tool_preset_name: Optional[str] = None,
        tool_search_mode: bool = False,
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
            max_iterations: Max graph iterations.
            role: Session role.
            enable_checkpointing: Enable LangGraph MemorySaver checkpointing.
            workflow_id: Optional workflow ID (used to load WorkflowDefinition).
            graph_name: Human-readable graph/workflow name.
            tool_search_mode: Whether tool search mode is active.
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
        self._max_iterations = max_iterations

        # Role
        self._role = role

        # Workflow / Graph
        self._workflow_id = workflow_id
        self._graph_name = graph_name
        self._workflow: Optional[WorkflowDefinition] = None

        # Tool Preset
        self._tool_preset_id = tool_preset_id
        self._tool_preset_name = tool_preset_name

        # Tool Search Mode
        self._tool_search_mode = tool_search_mode

        # Per-session allowed tools (set by agent_session_manager from tool preset / request)
        # None means unrestricted; a list restricts which tools are visible/executable
        self._session_allowed_tools: Optional[List[str]] = None

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
        self._execution_count: int = 0
        self._execution_start_time: Optional[datetime] = None
        self._is_executing: bool = False  # True while invoke/astream is running

        # Session freshness evaluator
        self._freshness = SessionFreshness()

        # Process revival flag (set by _auto_revive when process is dead)
        self._needs_process_restart = False

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
    def from_process(
        cls,
        process: ClaudeProcess,
        enable_checkpointing: bool = False,
        workflow_id: Optional[str] = None,
        graph_name: Optional[str] = None,
    ) -> "AgentSession":
        """Create AgentSession from an existing ClaudeProcess.

        Args:
            process: Initialized ClaudeProcess instance.
            enable_checkpointing: Enable LangGraph checkpointing.
            workflow_id: Optional workflow ID to link.
            graph_name: Human-readable graph name.

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
            role=SessionRole(process.role) if process.role else SessionRole.WORKER,
            enable_checkpointing=enable_checkpointing,
            workflow_id=workflow_id,
            graph_name=graph_name,
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
    def from_model(
        cls,
        model: ClaudeCLIChatModel,
        enable_checkpointing: bool = False,
        workflow_id: Optional[str] = None,
        graph_name: Optional[str] = None,
    ) -> "AgentSession":
        """Create AgentSession from an existing ClaudeCLIChatModel.

        Args:
            model: Initialized ClaudeCLIChatModel instance.
            enable_checkpointing: Enable LangGraph checkpointing.
            workflow_id: Optional workflow ID to link.
            graph_name: Human-readable graph name.

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
            enable_checkpointing=enable_checkpointing,
            workflow_id=workflow_id,
            graph_name=graph_name,
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
        """Whether this session uses an autonomous-type graph (derived from workflow)."""
        if self._workflow:
            return 'autonomous' in (self._workflow.name or '').lower()
        if self._graph_name:
            return 'autonomous' in self._graph_name.lower()
        return False

    @property
    def workflow(self) -> Optional[WorkflowDefinition]:
        """The linked WorkflowDefinition for this session."""
        return self._workflow

    @property
    def max_iterations(self) -> int:
        return self._max_iterations

    @property
    def role(self) -> SessionRole:
        return self._role

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
    def session_allowed_tools(self) -> Optional[List[str]]:
        """Per-session allowed tools filter (None = unrestricted)."""
        return self._session_allowed_tools

    @session_allowed_tools.setter
    def session_allowed_tools(self, tools: Optional[List[str]]) -> None:
        self._session_allowed_tools = tools

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
        """Evaluate session freshness and handle staleness.

        Called at the top of ``invoke()`` and ``astream()`` to detect
        sessions that are too old, idle, or large.

        Design:
            - STALE_IDLE → auto-revive (reset timestamps, restart process
              if needed).  The session continues — the user never sees an
              error.
            - STALE_RESET → truly unrecoverable (extreme age, runaway
              iterations, repeated revival failures).  Mark ERROR.
        """
        result = self._freshness.evaluate(
            created_at=self._created_at,
            last_activity=self._execution_start_time,
            iteration_count=self._current_iteration,
            message_count=0,  # message count resolved inside the graph
        )

        if result.should_revive:
            # Idle session detected — auto-revive instead of killing
            logger.info(
                f"[{self._session_id}] Session idle detected: {result.reason}. "
                f"Auto-reviving..."
            )
            self._auto_revive(result)
            return

        if result.should_reset:
            self._status = SessionStatus.ERROR
            self._error_message = f"Session stale: {result.reason}"
            raise RuntimeError(
                f"Session {self._session_id} is stale and should be recreated: "
                f"{result.reason}"
            )

    def _auto_revive(self, freshness_result=None) -> None:
        """Perform synchronous revival of an idle session.

        Resets timestamps so the session appears fresh.  If the underlying
        CLI process has died during the idle period, the async ``revive()``
        method must be called instead (this is done by invoke/astream when
        they catch the dead-process condition).

        This method is intentionally lightweight and never raises.
        """
        reason = freshness_result.reason if freshness_result else "idle auto-revive"
        logger.info(f"[{self._session_id}] Auto-reviving session from IDLE: {reason}")

        # Reset execution timestamps so freshness evaluates as FRESH
        self._execution_start_time = datetime.now()

        # Ensure status is RUNNING (might be IDLE/ERROR/STOPPED from previous state)
        if self._status in (SessionStatus.IDLE, SessionStatus.ERROR, SessionStatus.STOPPED):
            self._status = SessionStatus.RUNNING
            self._error_message = None

        # Record the revival attempt
        self._freshness.record_revival()

        # Check if the underlying process is still alive
        if self._model and self._model.process and not self._model.process.is_alive():
            logger.warning(
                f"[{self._session_id}] Underlying process died during idle. "
                f"Async revive() needed."
            )
            # Mark that full revival is needed — invoke/astream will handle it
            self._needs_process_restart = True
        else:
            self._needs_process_restart = False

        logger.info(
            f"[{self._session_id}] Auto-revive complete "
            f"(revive_count={self._freshness.revive_count})"
        )

    def mark_idle(self) -> bool:
        """Transition this session to IDLE status.

        Called by the background idle monitor when the session has had
        no activity for ``idle_transition_seconds``.  This does NOT
        destroy anything — the session sleeps and auto-revives on the
        next execution request.

        IMPORTANT: Sessions that are currently executing a command are
        NEVER marked as idle, even if the execution takes longer than
        the idle threshold.  The ``_is_executing`` guard prevents this.

        Returns:
            True if the session was transitioned to IDLE, False if not
            applicable (e.g. already IDLE, STOPPED, ERROR, or executing).
        """
        if self._status != SessionStatus.RUNNING:
            return False

        # Never mark a session as idle while it is actively executing
        if self._is_executing:
            return False

        # Evaluate freshness to confirm the session is actually idle
        result = self._freshness.evaluate(
            created_at=self._created_at,
            last_activity=self._execution_start_time,
            iteration_count=self._current_iteration,
            message_count=0,
        )

        if result.status == FreshnessStatus.STALE_IDLE:
            self._status = SessionStatus.IDLE
            logger.info(
                f"[{self._session_id}] Session transitioned to IDLE "
                f"(idle {result.idle_seconds:.0f}s)"
            )
            return True

        return False

    async def revive(self) -> bool:
        """Full async revival of the session.

        Called when the session was idle and the underlying CLI process
        has died.  Re-initializes the model and rebuilds the graph while
        preserving the session identity (same session_id, same storage).

        Returns:
            True on success, False on failure.
        """
        logger.info(f"[{self._session_id}] Full session revival starting...")

        try:
            # 1. Reset timestamps
            self._execution_start_time = datetime.now()
            self._error_message = None

            # 2. Clean up dead model (if any)
            if self._model:
                try:
                    await self._model.cleanup()
                except Exception:
                    logger.debug(
                        f"[{self._session_id}] Model cleanup during revive (non-critical)",
                        exc_info=True,
                    )

            # 3. Re-create the model (spawns a new ClaudeProcess)
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
            )

            success = await self._model.initialize()
            if not success:
                err = (
                    self._model.process.error_message
                    if self._model.process
                    else "Unknown error"
                )
                self._error_message = f"Revival failed: {err}"
                self._status = SessionStatus.ERROR
                logger.error(
                    f"[{self._session_id}] Revival failed: model init error: {err}"
                )
                return False

            # 4. Re-initialize memory manager
            self._init_memory()

            # 4b. Initialize vector memory layer (async, non-blocking)
            if self._memory_manager:
                try:
                    await self._memory_manager.initialize_vector_memory()
                except Exception as ve:
                    logger.debug(
                        f"[{self._session_id}] Vector memory init skipped on revive: {ve}"
                    )

            # 5. Rebuild the graph
            self._build_graph()

            # 6. Mark as alive
            self._initialized = True
            self._status = SessionStatus.RUNNING
            self._needs_process_restart = False

            # Record revival and log success
            self._freshness.record_revival()

            logger.info(
                f"[{self._session_id}] Session revival successful "
                f"(revive_count={self._freshness.revive_count})"
            )
            return True

        except Exception as e:
            self._error_message = f"Revival failed: {e}"
            self._status = SessionStatus.ERROR
            logger.exception(
                f"[{self._session_id}] Session revival failed: {e}"
            )
            return False

    async def _ensure_alive(self) -> None:
        """Ensure the session is alive before execution.

        Called at the top of invoke() and astream() after freshness check.
        If the process needs restart (flagged by _auto_revive), performs
        full async revival.  If revival fails, raises RuntimeError.
        """
        if getattr(self, '_needs_process_restart', False):
            logger.info(
                f"[{self._session_id}] Process restart needed — "
                f"performing full revival..."
            )
            success = await self.revive()
            if not success:
                raise RuntimeError(
                    f"Session {self._session_id} could not be revived: "
                    f"{self._error_message}"
                )

        # Also check if process died without freshness flagging it
        if self._model and self._model.process and not self._model.process.is_alive():
            logger.warning(
                f"[{self._session_id}] Process found dead — "
                f"attempting revival..."
            )
            success = await self.revive()
            if not success:
                raise RuntimeError(
                    f"Session {self._session_id} process died and could not "
                    f"be revived: {self._error_message}"
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
            )

            # 2. Initialize model (spawns ClaudeProcess)
            success = await self._model.initialize()
            if not success:
                self._error_message = self._model.process.error_message if self._model.process else "Unknown error"
                self._status = SessionStatus.ERROR
                logger.error(f"[{self._session_id}] Failed to initialize model: {self._error_message}")
                return False

            # 3. Initialize memory manager (before graph, so graph can use it)
            self._init_memory()

            # 3b. Initialize vector memory layer (async, non-blocking)
            if self._memory_manager:
                try:
                    await self._memory_manager.initialize_vector_memory()
                except Exception as ve:
                    logger.debug(
                        f"[{self._session_id}] Vector memory init skipped: {ve}"
                    )

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
        """Build the LangGraph StateGraph from the linked WorkflowDefinition.

        Loads the WorkflowDefinition (from workflow_id or default template),
        creates an ExecutionContext, and compiles via WorkflowExecutor.
        All graph types go through this single path.
        """
        # Checkpointer setup (persistent when storage_path is available)
        if self._enable_checkpointing:
            storage = self.storage_path if hasattr(self, 'storage_path') else None
            self._checkpointer = create_checkpointer(
                storage_path=storage,
                persistent=True,
            )

        # Load WorkflowDefinition
        self._workflow = self._load_workflow_definition()
        if not self._workflow:
            raise RuntimeError(
                f"Failed to load WorkflowDefinition for session {self._session_id} "
                f"(workflow_id={self._workflow_id}, graph_name={self._graph_name})"
            )

        # Update graph_name from the workflow if not explicitly set
        if not self._graph_name:
            self._graph_name = self._workflow.name

        # Create ExecutionContext for the WorkflowExecutor
        context = ExecutionContext(
            model=self._model,
            session_id=self._session_id,
            memory_manager=self._memory_manager,
            session_logger=self._get_logger(),
            context_guard=None,  # Context guard nodes are part of the workflow
            max_retries=2,
            model_name=self._model_name,
        )

        # Compile via WorkflowExecutor
        executor = WorkflowExecutor(self._workflow, context)
        self._graph = executor.compile()

        logger.info(
            f"[{self._session_id}] Graph compiled from workflow "
            f"'{self._workflow.name}' ({self._workflow.id})"
        )

    def _load_workflow_definition(self) -> Optional[WorkflowDefinition]:
        """Load the WorkflowDefinition for this session.

        Resolution order:
            1. workflow_id → load from WorkflowStore
            2. graph_name contains 'autonomous' → template-autonomous
            3. Fallback → template-simple
        """
        from service.workflow.workflow_store import get_workflow_store

        store = get_workflow_store()

        # 1. Try explicit workflow_id
        if self._workflow_id:
            wf = store.load(self._workflow_id)
            if wf:
                logger.info(
                    f"[{self._session_id}] Loaded workflow '{wf.name}' "
                    f"from workflow_id={self._workflow_id}"
                )
                return wf
            logger.warning(
                f"[{self._session_id}] workflow_id={self._workflow_id} not found "
                f"in store, falling back to template"
            )

        # 2. Infer from graph_name, with tool_search_mode variants
        is_autonomous = self._graph_name and 'autonomous' in self._graph_name.lower()
        is_tool_search = getattr(self, '_tool_search_mode', False)

        if is_tool_search:
            template_id = "template-tool-search-autonomous" if is_autonomous else "template-tool-search-simple"
        elif is_autonomous:
            template_id = "template-autonomous"
        else:
            template_id = "template-simple"

        wf = store.load(template_id)
        if wf:
            logger.info(
                f"[{self._session_id}] Using template '{wf.name}' ({template_id})"
            )
            return wf

        # 3. If templates are not in store, generate them on the fly
        logger.warning(
            f"[{self._session_id}] Template {template_id} not found in store, "
            f"generating from factory"
        )
        from service.workflow.templates import (
            create_autonomous_template,
            create_simple_template,
            create_tool_search_simple_template,
            create_tool_search_autonomous_template,
        )

        _template_factories = {
            "template-autonomous": create_autonomous_template,
            "template-simple": create_simple_template,
            "template-tool-search-simple": create_tool_search_simple_template,
            "template-tool-search-autonomous": create_tool_search_autonomous_template,
        }
        factory = _template_factories.get(template_id, create_simple_template)
        return factory()

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
        """Execute the linked workflow graph and return the final result.

        All sessions use the same path: create initial AutonomousState,
        invoke the compiled graph, extract the result.

        Args:
            input_text: User input text.
            thread_id: Thread ID for checkpointing.
            max_iterations: Override for max iterations.
            **kwargs: Additional metadata.

        Returns:
            Agent response text.
        """
        start_time = time.time()

        if not self._initialized or not self._graph:
            raise RuntimeError("AgentSession not initialized. Call initialize() first.")

        # Freshness check — auto-revive if idle, raise if hard limit
        self._check_freshness()

        # Ensure underlying process is alive (restart if needed)
        await self._ensure_alive()

        self._status = SessionStatus.RUNNING
        self._is_executing = True          # guard: prevent idle monitor interference
        self._current_iteration = 0
        self._execution_start_time = datetime.now()
        thread_id = thread_id or self._current_thread_id
        effective_max_iterations = max_iterations or self._max_iterations

        session_logger = self._get_logger()

        # Log graph execution start
        if session_logger:
            session_logger.log_graph_execution_start(
                input_text=input_text,
                thread_id=thread_id,
                max_iterations=effective_max_iterations,
                execution_mode="invoke",
            )

        try:
            config = {"configurable": {"thread_id": thread_id}}

            # Unified initial state — all workflows use AutonomousState
            # Always include agent identity for relevance gate (chat mode)
            kwargs.setdefault("agent_name", self._session_name or self._session_id[:8])
            kwargs.setdefault("agent_role", self._role.value if hasattr(self._role, 'value') else str(self._role))
            kwargs.setdefault("tool_search_mode", self._tool_search_mode)
            initial_state = make_initial_autonomous_state(
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

            # Set per-session tool filtering context
            _ctx_token = set_session_allowed_tools(self._session_allowed_tools)
            try:
                # Execute the compiled graph
                result = await self._graph.ainvoke(initial_state, config)
            finally:
                clear_session_allowed_tools(_ctx_token)
            duration_ms = int((time.time() - start_time) * 1000)
            self._is_executing = False       # execution complete
            self._execution_start_time = datetime.now()   # refresh activity timestamp
            self._status = SessionStatus.RUNNING

            # Successful execution — reset revive counter
            self._freshness.reset_revive_counter()

            # Extract results — try various output fields
            final_output = (
                result.get("final_answer", "")
                or result.get("answer", "")
                or result.get("last_output", "")
            )
            has_error = bool(result.get("error"))
            total_iterations = result.get("iteration", 0)

            # Log execution completion
            if session_logger:
                session_logger.log_graph_execution_complete(
                    success=not has_error,
                    total_iterations=total_iterations,
                    final_output=final_output[:500] if final_output else None,
                    total_duration_ms=duration_ms,
                    stop_reason="completed" if not has_error else result.get("error"),
                )

            # Record structured execution entry to long-term memory
            self._execution_count += 1
            if self._memory_manager:
                try:
                    await self._memory_manager.record_execution(
                        input_text=input_text,
                        result_state=result,
                        duration_ms=duration_ms,
                        execution_number=self._execution_count,
                        success=not has_error,
                    )
                except Exception:
                    logger.debug(
                        f"[{self._session_id}] LTM execution record failed (non-critical)",
                        exc_info=True,
                    )

            if has_error:
                self._error_message = result["error"]
                return f"Error: {result['error']}"

            return final_output

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self._is_executing = False       # execution complete (error path)
            self._execution_start_time = datetime.now()
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

    async def astream(
        self,
        input_text: str,
        thread_id: Optional[str] = None,
        max_iterations: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream the linked workflow graph execution.

        All sessions use the same path: create initial AutonomousState,
        stream the compiled graph, yield per-node events.

        Args:
            input_text: User input text.
            thread_id: Thread ID for checkpointing.
            max_iterations: Override for max iterations.

        Yields:
            Per-node execution results.
        """
        if not self._initialized or not self._graph:
            raise RuntimeError("AgentSession not initialized. Call initialize() first.")

        # Freshness check — auto-revive if idle
        self._check_freshness()

        # Ensure underlying process is alive (restart if needed)
        await self._ensure_alive()

        self._status = SessionStatus.RUNNING
        self._is_executing = True              # guard: prevent idle monitor interference
        thread_id = thread_id or self._current_thread_id

        # Initialize logging for graph execution
        session_logger = self._get_logger()
        start_time = time.time()
        self._current_iteration = 0
        self._execution_start_time = datetime.now()  # fixed: was float, must be datetime
        effective_max_iterations = max_iterations or self._max_iterations
        event_count = 0
        last_event = None

        # Log execution start
        if session_logger:
            session_logger.log_graph_execution_start(
                input_text=input_text,
                thread_id=thread_id,
                max_iterations=effective_max_iterations,
                execution_mode="astream",
            )

        try:
            config = {"configurable": {"thread_id": thread_id}}

            # Unified initial state — all workflows use AutonomousState
            # Always include agent identity for relevance gate (chat mode)
            kwargs.setdefault("agent_name", self._session_name or self._session_id[:8])
            kwargs.setdefault("agent_role", self._role.value if hasattr(self._role, 'value') else str(self._role))
            kwargs.setdefault("tool_search_mode", self._tool_search_mode)
            initial_state = make_initial_autonomous_state(
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

            # Accumulate state updates for LTM recording
            accumulated_state: Dict[str, Any] = {}

            # Set per-session tool filtering context
            _ctx_token = set_session_allowed_tools(self._session_allowed_tools)

            # Stream the compiled graph
            async for event in self._graph.astream(initial_state, config):
                event_count += 1
                last_event = event

                # Accumulate state from node outputs for LTM recording
                if isinstance(event, dict):
                    for key, value in event.items():
                        if key == "__end__":
                            continue
                        if isinstance(value, dict):
                            accumulated_state.update(value)

                # Parse per-node event info from the streamed dict.
                # LangGraph astream yields dicts like {node_id: state_update}.
                if session_logger and isinstance(event, dict):
                    node_names = [k for k in event.keys() if k != "__end__"]
                    elapsed_ms = int((time.time() - start_time) * 1000)

                    if node_names:
                        for node_name in node_names:
                            node_result = event[node_name]
                            # Build concise preview of what this node produced
                            preview_parts = []
                            if isinstance(node_result, dict):
                                changed = [k for k, v in node_result.items() if v is not None]
                                if changed:
                                    preview_parts.append(f"updated: {', '.join(changed[:5])}")
                            session_logger.log_graph_event(
                                event_type="node_output",
                                message=f"NODE OUTPUT: {node_name} [{elapsed_ms}ms]"
                                + (f" ({'; '.join(preview_parts)})" if preview_parts else ""),
                                node_name=node_name,
                                data={
                                    "event_number": event_count,
                                    "elapsed_ms": elapsed_ms,
                                },
                            )
                    elif "__end__" in event:
                        session_logger.log_graph_event(
                            event_type="graph_end",
                            message=f"GRAPH END [{elapsed_ms}ms]",
                            data={
                                "event_number": event_count,
                                "elapsed_ms": elapsed_ms,
                            },
                        )

                # Heartbeat: refresh activity timestamp on every streamed event
                # so the idle monitor sees continuous activity during long runs
                self._execution_start_time = datetime.now()

                yield event

            self._is_executing = False             # execution complete
            self._execution_start_time = datetime.now()  # refresh activity timestamp
            self._status = SessionStatus.RUNNING

            # Successful execution — reset revive counter
            self._freshness.reset_revive_counter()

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

            # Record structured execution entry to long-term memory
            self._execution_count += 1
            if self._memory_manager:
                try:
                    # Ensure input is in accumulated state
                    accumulated_state.setdefault("input", input_text)
                    await self._memory_manager.record_execution(
                        input_text=input_text,
                        result_state=accumulated_state,
                        duration_ms=duration_ms,
                        execution_number=self._execution_count,
                        success=True,
                    )
                except Exception:
                    logger.debug(
                        f"[{self._session_id}] LTM execution record failed (non-critical)",
                        exc_info=True,
                    )

        except Exception as e:
            self._is_executing = False             # execution complete (error path)
            self._execution_start_time = datetime.now()
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

        finally:
            clear_session_allowed_tools(_ctx_token)

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
        self._workflow = None
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
            max_iterations=self._max_iterations,
            storage_path=self.storage_path,
            pod_name=pod_name,
            pod_ip=pod_ip,
            role=self._role,
            workflow_id=self._workflow_id,
            graph_name=self._graph_name,
            tool_preset_id=self._tool_preset_id,
            tool_preset_name=self._tool_preset_name,
            system_prompt=self._system_prompt,
            tool_search_mode=self._tool_search_mode,
        )

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def get_state(self, thread_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
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

    def visualize(self) -> Optional[bytes]:
        """Render the compiled graph as a PNG image.

        Returns:
            PNG image bytes or None.
        """
        if not self._graph:
            return None

        try:
            return self._graph.get_graph().draw_mermaid_png()
        except Exception as e:
            logger.warning(f"[{self._session_id}] Could not visualize graph: {e}")
            return None

    def get_mermaid_diagram(self) -> Optional[str]:
        """Return a Mermaid diagram string for the compiled graph.

        Returns:
            Mermaid diagram string or None.
        """
        if not self._graph:
            return None

        try:
            return self._graph.get_graph().draw_mermaid()
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
