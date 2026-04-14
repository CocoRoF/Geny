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
import os
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
        timeout: float = 21600.0,
        system_prompt: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        mcp_config: Optional[MCPConfig] = None,
        max_iterations: int = 100,
        role: SessionRole = SessionRole.WORKER,
        enable_checkpointing: bool = False,
        workflow_id: Optional[str] = None,
        graph_name: Optional[str] = None,
        tool_preset_id: Optional[str] = None,
        owner_username: Optional[str] = None,
        geny_tool_registry: Optional[Any] = None,
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
        self._tool_preset_id = tool_preset_id
        self._owner_username = owner_username
        self._workflow: Optional[WorkflowDefinition] = None

        # Internal components
        self._model: Optional[ClaudeCLIChatModel] = None
        self._graph: Optional[CompiledStateGraph] = None
        self._pipeline: Optional[Any] = None  # geny-executor Pipeline (pipeline mode)
        self._execution_backend: str = "langgraph"  # "langgraph" | "pipeline"
        self._checkpointer: Optional[object] = None  # MemorySaver or SqliteSaver
        self._enable_checkpointing = enable_checkpointing

        # geny-executor tool registry (set by AgentSessionManager)
        self._geny_tool_registry = geny_tool_registry

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

        # Dual-agent pairing (VTuber ↔ CLI)
        self._linked_session_id: Optional[str] = None
        self._session_type: Optional[str] = None  # "vtuber" | "cli" | None
        self._chat_room_id: Optional[str] = None

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
    def owner_username(self) -> Optional[str]:
        return self._owner_username

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
    def memory_manager(self) -> Optional["SessionMemoryManager"]:
        """Session memory manager (available after initialization)."""
        return self._memory_manager

    @property
    def linked_session_id(self) -> Optional[str]:
        """ID of the paired session (VTuber ↔ CLI)."""
        return self._linked_session_id

    @property
    def session_type(self) -> Optional[str]:
        """Session type: 'vtuber', 'cli', or None."""
        return self._session_type

    @property
    def _is_always_on(self) -> bool:
        """Whether this session should never go idle.

        True for VTuber sessions and their linked CLI sessions — these
        form a tightly-coupled unit that must stay warm together.
        """
        if self._role == SessionRole.VTUBER:
            return True
        if self._session_type == "cli" and self._linked_session_id:
            return True
        return False

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
            - STALE_RESET (age limit) → auto-renew: reset session clock
              and flag for full process restart.  The session identity is
              preserved; only the age counter resets.
            - STALE_RESET (runaway iterations / repeated revival failures)
              → truly unrecoverable.  Mark ERROR.
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
            # Distinguish age-based reset (recoverable) from
            # iteration/revival-failure reset (unrecoverable).
            is_age_based = result.session_age_seconds >= self._freshness.config.max_session_age_seconds
            is_iteration_limit = result.iteration_count >= self._freshness.config.max_iterations
            is_revival_exhausted = self._freshness.revive_count >= self._freshness.config.max_revive_attempts

            if is_age_based and not is_iteration_limit and not is_revival_exhausted:
                # Age-based staleness: auto-renew the session clock
                # and flag for a full process restart.  The session
                # remains usable — the user never sees an error.
                logger.info(
                    f"[{self._session_id}] Session age limit reached: "
                    f"{result.reason}. Auto-renewing session clock..."
                )
                self._created_at = datetime.now()
                self._execution_start_time = datetime.now()
                self._current_iteration = 0
                self._freshness.reset_revive_counter()

                if self._status in (SessionStatus.IDLE, SessionStatus.ERROR, SessionStatus.STOPPED):
                    self._status = SessionStatus.RUNNING
                    self._error_message = None

                # Flag for full process restart in _ensure_alive()
                self._needs_process_restart = True
                logger.info(
                    f"[{self._session_id}] Session clock renewed — "
                    f"full process restart will follow."
                )
                return

            # Truly unrecoverable (runaway iterations or repeated
            # revival failures) — hard error.
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

        VTuber sessions are EXEMPT from idle transition because they
        must remain a permanently-bound unit with their CLI subprocess
        (ThinkingTrigger keeps them active).

        Returns:
            True if the session was transitioned to IDLE, False if not
            applicable (e.g. already IDLE, STOPPED, ERROR, executing,
            or VTuber role).
        """
        if self._status != SessionStatus.RUNNING:
            return False

        # Never mark a session as idle while it is actively executing
        if self._is_executing:
            return False

        # VTuber sessions are always-on — never transition to IDLE.
        # They form a tightly-coupled unit with their CLI subprocess;
        # idle timeout would break session ↔ process binding.
        # The linked CLI session is also exempt for the same reason.
        if self._is_always_on:
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
        """Revive the session by rebuilding the pipeline.

        In pipeline mode, there is no subprocess to restart — we just
        rebuild the pipeline and re-initialize memory if needed.

        Returns:
            True on success, False on failure.
        """
        logger.info(f"[{self._session_id}] Session revival starting (pipeline mode)...")

        try:
            # 1. Reset timestamps
            self._execution_start_time = datetime.now()
            self._error_message = None

            # 2. Re-initialize memory manager if needed
            if not self._memory_manager:
                self._init_memory()
                if self._memory_manager:
                    try:
                        await self._memory_manager.initialize_vector_memory()
                    except Exception as ve:
                        logger.debug(
                            f"[{self._session_id}] Vector memory init skipped on revive: {ve}"
                        )

            # 3. Rebuild the pipeline
            self._build_graph()

            # 4. Mark as alive
            self._initialized = True
            self._status = SessionStatus.RUNNING
            self._needs_process_restart = False

            # Record revival
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

        In pipeline mode, the session is always alive as long as the
        pipeline is initialized. If it somehow got cleared, revive.
        """
        if self._pipeline is not None:
            return

        # Pipeline not set but session was initialized — try to rebuild
        if self._initialized:
            logger.warning(
                f"[{self._session_id}] Pipeline is None but session is "
                f"initialized — attempting revival..."
            )
            success = await self.revive()
            if not success:
                raise RuntimeError(
                    f"Session {self._session_id} could not be revived: "
                    f"{self._error_message}"
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
            1. Initialize SessionMemoryManager.
            2. Build geny-executor Pipeline (no CLI subprocess).

        Returns:
            True on success, False on failure.
        """
        if self._initialized:
            logger.info(f"[{self._session_id}] AgentSession already initialized")
            return True

        logger.info(f"[{self._session_id}] Initializing AgentSession (pipeline mode)...")

        try:
            # 1. Initialize memory manager (before pipeline, so pipeline can use it)
            self._init_memory()

            # 1b. Initialize vector memory layer (async, non-blocking)
            if self._memory_manager:
                try:
                    await self._memory_manager.initialize_vector_memory()
                except Exception as ve:
                    logger.debug(
                        f"[{self._session_id}] Vector memory init skipped: {ve}"
                    )

            # 2. Build geny-executor Pipeline (no subprocess)
            self._build_graph()

            self._initialized = True
            self._status = SessionStatus.RUNNING

            logger.info(f"[{self._session_id}] AgentSession initialized successfully (pipeline)")
            return True

        except Exception as e:
            self._error_message = str(e)
            self._status = SessionStatus.ERROR
            logger.exception(f"[{self._session_id}] Exception during initialization: {e}")
            return False

    def _build_graph(self):
        """Build the geny-executor Pipeline execution backend.

        All execution goes through the geny-executor Pipeline — there is
        no LangGraph/CLI fallback. The Pipeline calls the Anthropic API
        directly (no subprocess).
        """
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

        # Always use geny-executor Pipeline
        self._build_pipeline()

    # ========================================================================
    # geny-executor Pipeline Mode
    # ========================================================================

    def _build_pipeline(self):
        """Build a geny-executor Pipeline with built-in tools and MCP.

        Maps the loaded WorkflowDefinition's template to a GenyPresets
        method, wiring in memory_manager, tools (built-in + Geny custom +
        MCP), and LLM callbacks.

        No fallback — if this fails, the session is in error state.
        """
        from geny_executor.memory import GenyPresets
        from geny_executor.tools.registry import ToolRegistry
        from geny_executor.tools.built_in import (
            ReadTool, WriteTool, EditTool, BashTool, GlobTool, GrepTool,
        )

        # Get API key (required — no fallback to CLI)
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        try:
            from service.config.manager import get_config_manager
            from service.config.sub_config.general.api_config import APIConfig
            api_cfg = get_config_manager().load_config(APIConfig)
            api_key = api_key or api_cfg.anthropic_api_key or ""
        except Exception:
            pass

        if not api_key:
            raise RuntimeError(
                f"[{self._session_id}] ANTHROPIC_API_KEY is required for "
                f"geny-executor Pipeline. Set it in environment or config."
            )

        model = self._model_name or "claude-sonnet-4-20250514"
        system_prompt = self._system_prompt or ""
        working_dir = self._working_dir or self.storage_path or ""

        # ── Build unified tool registry ──
        # 1. Core built-in tools (file I/O, shell, search)
        tools = ToolRegistry()
        tools.register(ReadTool())
        tools.register(WriteTool())
        tools.register(EditTool())
        tools.register(BashTool())
        tools.register(GlobTool())
        tools.register(GrepTool())

        # 2. Geny custom tools (via tool_bridge adapter)
        if self._geny_tool_registry:
            for t in self._geny_tool_registry.list_all():
                tools.register(t)

        logger.info(
            f"[{self._session_id}] Tool registry: {tools.list_names()}"
        )

        # Curated knowledge manager
        curated_km = None
        if self._owner_username:
            try:
                from service.memory.curated_knowledge import get_curated_knowledge_manager
                curated_km = get_curated_knowledge_manager(self._owner_username)
            except Exception:
                pass

        # LLM reflect callback (uses Anthropic SDK directly)
        llm_reflect = self._make_llm_reflect_callback(api_key)

        # Determine preset from template
        template_id = getattr(self._workflow, "id", "") or self._workflow_id or ""
        is_vtuber = "vtuber" in template_id.lower()
        is_simple = "simple" in template_id.lower()

        if is_vtuber:
            self._pipeline = GenyPresets.vtuber(
                api_key=api_key,
                memory_manager=self._memory_manager,
                model=model,
                persona_prompt=system_prompt,
                curated_knowledge_manager=curated_km,
                llm_reflect=llm_reflect,
                tools=tools,
            )
        elif is_simple:
            self._pipeline = GenyPresets.worker_easy(
                api_key=api_key,
                memory_manager=self._memory_manager,
                model=model,
                system_prompt=system_prompt,
            )
        else:
            # autonomous, optimized-autonomous, ultra-light → worker_full
            max_turns = self._max_iterations or 50
            if "optimized" in template_id.lower():
                max_turns = min(max_turns, 30)

            self._pipeline = GenyPresets.worker_full(
                api_key=api_key,
                memory_manager=self._memory_manager,
                model=model,
                system_prompt=system_prompt,
                tools=tools,
                max_turns=max_turns,
                curated_knowledge_manager=curated_km,
                llm_reflect=llm_reflect,
            )

        self._execution_backend = "pipeline"
        self._pipeline_working_dir = working_dir

        preset_name = 'vtuber' if is_vtuber else 'worker_easy' if is_simple else 'worker_full'
        logger.info(
            f"[{self._session_id}] Pipeline built: template='{template_id}', "
            f"preset={preset_name}, model={model}, tools={len(tools)}"
        )

    @staticmethod
    def _make_llm_reflect_callback(api_key: str):
        """Create an LLM reflection callback for GenyMemoryStrategy.

        Returns an async callable: (input_text, output_text) -> List[Dict].
        Uses the Anthropic SDK directly (lightweight, no LangChain).
        """
        async def _llm_reflect(input_text: str, output_text: str):
            import json as _json
            try:
                import anthropic
            except ImportError:
                return []

            prompt = (
                "Analyze the following execution and extract any reusable knowledge, "
                "decisions, or insights worth remembering for future tasks.\n\n"
                f"<input>\n{input_text}\n</input>\n\n"
                f"<output>\n{output_text}\n</output>\n\n"
                "Extract concise, reusable insights. Skip trivial/obvious observations.\n\n"
                'Respond with JSON only:\n'
                '{\n'
                '  "learned": [\n'
                '    {\n'
                '      "title": "concise title (3-10 words)",\n'
                '      "content": "what was learned (1-3 sentences)",\n'
                '      "category": "topics|insights|entities|projects",\n'
                '      "tags": ["tag1", "tag2"],\n'
                '      "importance": "low|medium|high"\n'
                '    }\n'
                '  ],\n'
                '  "should_save": true\n'
                '}\n\n'
                'If nothing meaningful was learned, return:\n'
                '{"learned": [], "should_save": false}'
            )

            try:
                client = anthropic.AsyncAnthropic(api_key=api_key)
                response = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text
                data = _json.loads(text)
                if data.get("should_save") and data.get("learned"):
                    return data["learned"]
                return []
            except Exception:
                return []

        return _llm_reflect

    # ========================================================================
    # Pipeline Execution Methods
    # ========================================================================

    async def _invoke_pipeline(
        self,
        input_text: str,
        start_time: float,
        session_logger: Optional[SessionLogger],
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute via geny-executor Pipeline with real-time event logging.

        Uses run_stream() internally so that Pipeline events are logged to
        session_logger in real time. The WebSocket/SSE layer polls
        session_logger.get_cache_entries_since() and streams events to clients.

        Maintains the same return contract: {"output": str, "total_cost": float}
        """
        # Record user input to short-term memory
        if self._memory_manager:
            try:
                self._memory_manager.record_message("user", input_text)
            except Exception:
                logger.debug("Failed to record user message — non-critical", exc_info=True)

        # Stream pipeline and log events in real time
        accumulated_output = ""
        total_cost = 0.0
        iterations = 0
        success = True
        error_msg = None

        async for event in self._pipeline.run_stream(input_text):
            event_type = event.type if hasattr(event, "type") else ""
            event_data = event.data if hasattr(event, "data") else {}

            # Log pipeline events to session_logger for WebSocket/SSE streaming
            if session_logger:
                if event_type == "tool.execute_start":
                    tool_name = event_data.get("tools", ["unknown"])[0] if event_data.get("tools") else "unknown"
                    session_logger.log_tool_use(
                        tool_name=tool_name,
                        tool_input=str(event_data.get("count", "")),
                    )
                elif event_type == "tool.execute_complete":
                    errors = event_data.get("errors", 0)
                    count = event_data.get("count", 0)
                    session_logger.log(
                        level="TOOL_RES",
                        message=f"Tool execution complete: {count} calls, {errors} errors",
                        metadata={"tool_count": count, "error_count": errors},
                    )
                elif event_type == "stage.enter":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    session_logger.log_graph_event(
                        event_type="node_enter",
                        message=f"→ {stage_name}",
                        node_name=stage_name,
                    )
                elif event_type == "stage.exit":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    session_logger.log_graph_event(
                        event_type="node_exit",
                        message=f"✓ {stage_name}",
                        node_name=stage_name,
                    )

            # Accumulate output
            if event_type == "text.delta":
                text = event_data.get("text", "")
                if text:
                    accumulated_output += text

            elif event_type == "pipeline.complete":
                accumulated_output = event_data.get("result", accumulated_output)
                total_cost = event_data.get("total_cost_usd", 0.0) or 0.0
                iterations = event_data.get("iterations", 0)

            elif event_type == "pipeline.error":
                success = False
                error_msg = event_data.get("error", "Unknown error")
                total_cost = event_data.get("total_cost_usd", 0.0) or 0.0

            # Heartbeat
            self._execution_start_time = datetime.now()

        duration_ms = int((time.time() - start_time) * 1000)

        # Log execution completion
        if session_logger:
            session_logger.log_graph_execution_complete(
                success=success,
                total_iterations=iterations,
                final_output=accumulated_output[:500] if accumulated_output else None,
                total_duration_ms=duration_ms,
                stop_reason="pipeline_complete" if success else (error_msg or "error"),
            )

        # Record to long-term memory
        self._execution_count += 1
        if self._memory_manager:
            try:
                await self._memory_manager.record_execution(
                    input_text=input_text,
                    result_state={
                        "final_answer": accumulated_output,
                        "total_cost": total_cost,
                        "iteration": iterations,
                    },
                    duration_ms=duration_ms,
                    execution_number=self._execution_count,
                    success=success,
                )
            except Exception:
                logger.debug(
                    f"[{self._session_id}] LTM execution record failed (non-critical)",
                    exc_info=True,
                )

        if not success:
            self._error_message = error_msg
            return {"output": f"Error: {error_msg}", "total_cost": total_cost}

        return {"output": accumulated_output, "total_cost": total_cost}

    async def _astream_pipeline(
        self,
        input_text: str,
        start_time: float,
        session_logger: Optional[SessionLogger],
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream via geny-executor Pipeline with real-time event logging.

        Converts PipelineEvent objects to the dict format that
        agent_executor.py and the frontend expect, while also logging
        events to session_logger for WebSocket/SSE streaming.
        """
        # Record user input to short-term memory
        if self._memory_manager:
            try:
                self._memory_manager.record_message("user", input_text)
            except Exception:
                logger.debug("Failed to record user message — non-critical", exc_info=True)

        accumulated_output = ""
        total_cost = 0.0
        iterations = 0
        success = True

        async for event in self._pipeline.run_stream(input_text):
            event_type = event.type if hasattr(event, "type") else ""
            event_data = event.data if hasattr(event, "data") else {}

            # ── Log pipeline events to session_logger ──
            if session_logger:
                if event_type == "tool.execute_start":
                    tool_name = event_data.get("tools", ["unknown"])[0] if event_data.get("tools") else "unknown"
                    session_logger.log_tool_use(
                        tool_name=tool_name,
                        tool_input=str(event_data.get("count", "")),
                    )
                elif event_type == "tool.execute_complete":
                    errors = event_data.get("errors", 0)
                    count = event_data.get("count", 0)
                    session_logger.log(
                        level="TOOL_RES",
                        message=f"Tool execution complete: {count} calls, {errors} errors",
                        metadata={"tool_count": count, "error_count": errors},
                    )
                elif event_type == "stage.enter":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    session_logger.log_graph_event(
                        event_type="node_enter",
                        message=f"→ {stage_name}",
                        node_name=stage_name,
                    )
                elif event_type == "stage.exit":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    session_logger.log_graph_event(
                        event_type="node_exit",
                        message=f"✓ {stage_name}",
                        node_name=stage_name,
                    )

            # ── Yield events to caller ──
            if event_type == "text.delta":
                text = event_data.get("text", "")
                if text:
                    accumulated_output += text
                    yield {"text_delta": {"text": text}}

            elif event_type == "stage.enter":
                stage_name = event.stage if hasattr(event, "stage") else "unknown"
                yield {stage_name: {"status": "enter"}}

            elif event_type == "stage.exit":
                stage_name = event.stage if hasattr(event, "stage") else "unknown"
                yield {stage_name: {"status": "exit"}}

            elif event_type == "pipeline.complete":
                result_text = event_data.get("result", accumulated_output)
                total_cost = event_data.get("total_cost_usd", 0.0) or 0.0
                iterations = event_data.get("iterations", 0)
                yield {
                    "__end__": {
                        "final_answer": result_text,
                        "total_cost": total_cost,
                        "iteration": iterations,
                    }
                }

            elif event_type == "pipeline.error":
                success = False
                yield {
                    "__end__": {
                        "error": event_data.get("error", "Unknown error"),
                        "total_cost": total_cost,
                    }
                }

            # Heartbeat: refresh activity timestamp
            self._execution_start_time = datetime.now()

        # Post-stream: log and record
        duration_ms = int((time.time() - start_time) * 1000)

        if session_logger:
            session_logger.log_graph_execution_complete(
                success=success,
                total_iterations=iterations,
                final_output=accumulated_output[:500] if accumulated_output else None,
                total_duration_ms=duration_ms,
                stop_reason="pipeline_stream_complete",
            )

        self._execution_count += 1
        if self._memory_manager:
            try:
                await self._memory_manager.record_execution(
                    input_text=input_text,
                    result_state={
                        "final_answer": accumulated_output,
                        "total_cost": total_cost,
                        "iteration": iterations,
                    },
                    duration_ms=duration_ms,
                    execution_number=self._execution_count,
                    success=success,
                )
            except Exception:
                logger.debug(
                    f"[{self._session_id}] LTM execution record failed (non-critical)",
                    exc_info=True,
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

        # 2. Infer from graph_name
        is_optimized = self._graph_name and 'optimized' in self._graph_name.lower()
        is_autonomous = self._graph_name and 'autonomous' in self._graph_name.lower()

        if is_optimized and is_autonomous:
            template_id = "template-optimized-autonomous"
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
            create_optimized_autonomous_template,
            create_simple_template,
            create_vtuber_template,
        )

        _template_factories = {
            "template-autonomous": create_autonomous_template,
            "template-optimized-autonomous": create_optimized_autonomous_template,
            "template-simple": create_simple_template,
            "template-vtuber": create_vtuber_template,
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
    ) -> Dict[str, Any]:
        """Execute the linked workflow graph and return the result.

        All sessions use the same path: create initial AutonomousState,
        invoke the compiled graph, extract the result.

        Args:
            input_text: User input text.
            thread_id: Thread ID for checkpointing.
            max_iterations: Override for max iterations.
            **kwargs: Additional metadata.

        Returns:
            Dict with keys: output (str), total_cost (float).
        """
        start_time = time.time()

        if not self._initialized or not self._pipeline:
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

        # Log execution start
        if session_logger:
            session_logger.log_graph_execution_start(
                input_text=input_text,
                thread_id=thread_id,
                max_iterations=effective_max_iterations,
                execution_mode="pipeline",
            )

        try:
            if self._pipeline is None:
                raise RuntimeError(
                    f"[{self._session_id}] Pipeline not initialized. "
                    f"Call initialize() before invoke()."
                )
            try:
                return await self._invoke_pipeline(
                    input_text, start_time, session_logger, **kwargs
                )
            finally:
                self._is_executing = False
                self._execution_start_time = datetime.now()
                self._freshness.reset_revive_counter()

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self._is_executing = False
            self._execution_start_time = datetime.now()
            self._status = SessionStatus.RUNNING
            self._error_message = str(e)
            logger.exception(f"[{self._session_id}] Error during invoke: {e}")

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
        if not self._initialized or not self._pipeline:
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
                execution_mode="pipeline_stream",
            )

        if self._pipeline is None:
            raise RuntimeError(
                f"[{self._session_id}] Pipeline not initialized. "
                f"Call initialize() before astream()."
            )

        try:
            async for event in self._astream_pipeline(
                input_text, start_time, session_logger, **kwargs
            ):
                yield event
        except Exception as e:
            self._is_executing = False
            self._execution_start_time = datetime.now()
            self._status = SessionStatus.RUNNING
            self._error_message = str(e)
            logger.exception(f"[{self._session_id}] Error during astream: {e}")

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

        self._pipeline = None
        self._workflow = None
        self._checkpointer = None
        self._initialized = False
        self._status = SessionStatus.STOPPED

        logger.info(f"[{self._session_id}] AgentSession cleaned up")

    async def stop(self):
        """Stop the session (alias for cleanup)."""
        await self.cleanup()

    def is_alive(self) -> bool:
        """Check whether the session is operational.

        In pipeline mode, the session is always alive as long as it's
        initialized (LLM calls go through the Anthropic API directly).
        """
        return self._initialized and self._pipeline is not None

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
        # Read persisted total_cost from session store
        _total_cost = 0.0
        try:
            from service.claude_manager.session_store import get_session_store
            store_data = get_session_store().get(self._session_id)
            if store_data:
                _total_cost = store_data.get("total_cost", 0.0) or 0.0
        except Exception:
            pass

        # Resolve effective model name (same logic as ClaudeProcess.execute)
        effective_model = self._model_name
        if not effective_model:
            effective_model = os.environ.get('ANTHROPIC_MODEL')
        if not effective_model:
            try:
                from service.config.manager import get_config_manager
                from service.config.sub_config.general.api_config import APIConfig
                api_cfg = get_config_manager().load_config(APIConfig)
                # Use VTuber-specific default for VTuber sessions
                if self._role == SessionRole.VTUBER and api_cfg.vtuber_default_model:
                    effective_model = api_cfg.vtuber_default_model
                else:
                    effective_model = api_cfg.anthropic_model or None
            except Exception:
                pass

        return SessionInfo(
            session_id=self._session_id,
            session_name=self._session_name,
            status=self._status,
            created_at=self._created_at,
            pid=self.pid,
            error_message=self._error_message,
            model=effective_model,
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
            system_prompt=self._system_prompt,
            total_cost=_total_cost,
            linked_session_id=self._linked_session_id,
            session_type=self._session_type,
            chat_room_id=self._chat_room_id,
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
