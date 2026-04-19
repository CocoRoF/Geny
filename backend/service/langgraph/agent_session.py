"""AgentSession — geny-executor Pipeline-based session management.

Each session runs a geny-executor Pipeline that calls the Anthropic API
directly (no CLI subprocess). Session creation flow:

    1. Determine preset from workflow_id string
    2. Build geny-executor Pipeline via GenyPresets
    3. Initialize SessionMemoryManager for session storage path

Usage::

    agent = await AgentSession.create(
        working_dir="/path/to/project",
        model_name="claude-sonnet-4-20250514",
        session_name="my-agent",
        workflow_id="template-optimized-autonomous",
    )
    result = await agent.invoke("Hello, what can you help me with?")
    await agent.cleanup()
"""

import asyncio
from logging import getLogger
import os
import time
import uuid
from datetime import datetime
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
)

from service.claude_manager.models import (
    MCPConfig,
    SessionInfo,
    SessionRole,
    SessionStatus,
)
from service.langgraph.session_freshness import SessionFreshness, FreshnessStatus
from service.logging.session_logger import get_session_logger, SessionLogger, LogLevel

logger = getLogger(__name__)


# ============================================================================
# AgentSession Class
# ============================================================================


class AgentSession:
    """geny-executor Pipeline-based agent session.

    Key architecture:
        - geny-executor Pipeline: 16-stage execution engine
        - SessionMemoryManager: long-term / short-term memory
        - GenyPresets: pre-configured pipeline templates (worker_adaptive, vtuber, worker_easy)
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
        env_id: Optional[str] = None,
        memory_config: Optional[Dict[str, Any]] = None,
        prebuilt_pipeline: Optional[Any] = None,
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
            workflow_id: Preset identifier (e.g. template-vtuber, template-optimized-autonomous).
            graph_name: Human-readable graph/workflow name.
        """
        # Session identity
        self._session_id = session_id or str(uuid.uuid4())
        self._session_name = session_name
        self._created_at = datetime.now()

        # Execution settings
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

        # Preset (determined during _build_pipeline)
        self._workflow_id = workflow_id  # kept for SessionInfo backward compat
        self._preset_name: str = "default"
        self._tool_preset_id = tool_preset_id
        self._owner_username = owner_username

        # Storage path (set during create())
        self._storage_path: Optional[str] = None

        # Internal components
        self._pipeline: Optional[Any] = None  # geny-executor Pipeline

        # Environment / memory wiring (Phase 3 — env_id pre-builds Pipeline,
        # memory_config is retained for Phase 4 attachment + observability).
        self._env_id: Optional[str] = env_id
        self._memory_config: Optional[Dict[str, Any]] = memory_config
        self._prebuilt_pipeline: Optional[Any] = prebuilt_pipeline

        # geny-executor tool registry (set by AgentSessionManager)
        self._geny_tool_registry = geny_tool_registry

        # Memory manager (initialized lazily once storage_path is available)
        self._memory_manager: Optional["SessionMemoryManager"] = None

        # Execution state
        self._initialized = False
        self._error_message: Optional[str] = None
        self._current_iteration: int = 0
        self._execution_count: int = 0
        self._execution_start_time: Optional[datetime] = None
        self._is_executing: bool = False  # True while invoke/astream is running

        # Session freshness evaluator
        self._freshness = SessionFreshness()

        # Process revival flag (set by _auto_revive when process is dead)

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

        # Set storage path
        from service.claude_manager.platform_utils import DEFAULT_STORAGE_ROOT
        from pathlib import Path
        storage = str(Path(DEFAULT_STORAGE_ROOT) / agent._session_id)
        Path(storage).mkdir(parents=True, exist_ok=True)
        agent._storage_path = storage

        success = await agent.initialize()
        if not success:
            raise RuntimeError(f"Failed to initialize AgentSession: {agent.error_message}")

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
        """Whether this session uses the default (adaptive) preset."""
        return self._preset_name == "default"

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
    def storage_path(self) -> Optional[str]:
        """Session storage directory path."""
        return self._storage_path

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

        Determines preset from workflow_id string, then calls _build_pipeline().
        """
        self._build_pipeline()

    # ========================================================================
    # geny-executor Pipeline Mode
    # ========================================================================

    def _build_pipeline(self):
        """Build a geny-executor Pipeline.

        Three paths:
          - ``prebuilt_pipeline`` was injected (env_id flow) → adopt as-is.
          - ``vtuber``: conversational agent with persona + memory (preset).
          - ``default`` (worker_adaptive): full autonomous agent with binary
            classify (preset).

        No fallback — if this fails, the session is in error state.
        """
        # ── env_id path: the manager already built the Pipeline from a
        # stored EnvironmentManifest. Adopt it and skip the preset branch.
        if self._prebuilt_pipeline is not None:
            self._pipeline = self._prebuilt_pipeline
            self._preset_name = f"env:{self._env_id}" if self._env_id else "env"
            logger.info(
                f"[{self._session_id}] Pipeline adopted from manifest: "
                f"preset={self._preset_name}"
            )
            return

        from geny_executor.memory import GenyPresets
        from geny_executor.tools.registry import ToolRegistry
        from geny_executor.tools.base import ToolContext
        from geny_executor.tools.built_in import (
            ReadTool, WriteTool, EditTool, BashTool, GlobTool, GrepTool,
        )

        # ── API key (required) ──
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
                f"[{self._session_id}] ANTHROPIC_API_KEY is required. "
                f"Set it in environment or config."
            )

        model = self._model_name or "claude-sonnet-4-20250514"
        system_prompt = self._system_prompt or ""
        working_dir = self._working_dir or self.storage_path or ""

        # ── Determine preset: vtuber or default ──
        is_vtuber = self._role == SessionRole.VTUBER
        self._preset_name = "vtuber" if is_vtuber else "default"

        # ── Build tool registry ──
        tools = ToolRegistry()

        # 1. Core built-in tools (file I/O, shell, search)
        tools.register(ReadTool())
        tools.register(WriteTool())
        tools.register(EditTool())
        tools.register(BashTool())
        tools.register(GlobTool())
        tools.register(GrepTool())

        # 2. Geny application tools (via tool_bridge adapter)
        if self._geny_tool_registry:
            for t in self._geny_tool_registry.list_all():
                tools.register(t)

        logger.info(
            f"[{self._session_id}] Tool registry: {len(tools)} tools"
        )

        # ── ToolContext for working_dir propagation ──
        tool_context = ToolContext(
            session_id=self._session_id,
            working_dir=working_dir,
            storage_path=self.storage_path,
        )

        # ── Curated knowledge ──
        curated_km = None
        if self._owner_username:
            try:
                from service.memory.curated_knowledge import get_curated_knowledge_manager
                curated_km = get_curated_knowledge_manager(self._owner_username)
            except Exception:
                pass

        # ── LLM reflection callback ──
        llm_reflect = self._make_llm_reflect_callback(api_key)

        # ── Build pipeline ──
        if is_vtuber:
            self._pipeline = GenyPresets.vtuber(
                api_key=api_key,
                memory_manager=self._memory_manager,
                model=model,
                persona_prompt=system_prompt,
                curated_knowledge_manager=curated_km,
                llm_reflect=llm_reflect,
                tools=tools,
                tool_context=tool_context,
            )
        else:
            max_turns = self._max_iterations or 30
            self._pipeline = GenyPresets.worker_adaptive(
                api_key=api_key,
                memory_manager=self._memory_manager,
                model=model,
                system_prompt=system_prompt,
                tools=tools,
                tool_context=tool_context,
                max_turns=max_turns,
                easy_max_turns=1,
                curated_knowledge_manager=curated_km,
                llm_reflect=llm_reflect,
            )


        logger.info(
            f"[{self._session_id}] Pipeline built: preset={self._preset_name}, "
            f"model={model}, tools={len(tools)}, working_dir={working_dir[:50]}"
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

        # Create PipelineState with session context
        from geny_executor.core.state import PipelineState as _PipelineState
        _state = _PipelineState(session_id=self._session_id)

        async for event in self._pipeline.run_stream(input_text, _state):
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
                        level=LogLevel.TOOL_RESULT,
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
                elif event_type in ("loop.escalate", "loop.error"):
                    signal = event_data.get("signal") or "unknown"
                    session_logger.log_graph_event(
                        event_type="loop_signal",
                        message=f"{event_type}: {signal}",
                        node_name="s13_loop",
                    )

            # Accumulate output + log to session_logger for streaming
            if event_type == "text.delta":
                text = event_data.get("text", "")
                if text:
                    accumulated_output += text
                    if session_logger:
                        session_logger.log(
                            level=LogLevel.STREAM_EVENT,
                            message=text,
                            metadata={"type": "text_delta"},
                        )

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

        # Create PipelineState with session context
        from geny_executor.core.state import PipelineState as _PipelineState
        _state = _PipelineState(session_id=self._session_id)

        async for event in self._pipeline.run_stream(input_text, _state):
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
                        level=LogLevel.TOOL_RESULT,
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
                elif event_type in ("loop.escalate", "loop.error"):
                    signal = event_data.get("signal") or "unknown"
                    session_logger.log_graph_event(
                        event_type="loop_signal",
                        message=f"{event_type}: {signal}",
                        node_name="s13_loop",
                    )

            # ── Yield events to caller ──
            if event_type == "text.delta":
                text = event_data.get("text", "")
                if text:
                    accumulated_output += text
                    if session_logger:
                        session_logger.log(
                            level=LogLevel.STREAM_EVENT,
                            message=text,
                            metadata={"type": "text_delta"},
                        )
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
        thread_id = thread_id or "default"
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
        thread_id = thread_id or "default"

        # Initialize logging for graph execution
        session_logger = self._get_logger()
        start_time = time.time()
        self._current_iteration = 0
        self._execution_start_time = datetime.now()  # fixed: was float, must be datetime
        effective_max_iterations = max_iterations or self._max_iterations

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
        finally:
            self._is_executing = False
            self._execution_start_time = datetime.now()
            self._freshness.reset_revive_counter()

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

        # Resolve effective model name
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
            pid=None,
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
            graph_name=self._preset_name,
            tool_preset_id=self._tool_preset_id,
            system_prompt=self._system_prompt,
            total_cost=_total_cost,
            linked_session_id=self._linked_session_id,
            session_type=self._session_type,
            chat_room_id=self._chat_room_id,
            env_id=self._env_id,
            memory_config=self._memory_config,
        )

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def __repr__(self) -> str:
        return (
            f"AgentSession("
            f"session_id={self._session_id!r}, "
            f"status={self._status.value}, "
            f"initialized={self._initialized})"
        )
