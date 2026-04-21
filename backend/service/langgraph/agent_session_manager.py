"""
AgentSessionManager - AgentSession Manager

Extends the existing SessionManager to manage sessions based on
AgentSession (CompiledStateGraph).

Retains all functionality of the existing SessionManager while
adding methods dedicated to AgentSession management.

Usage example:
    from service.langgraph import get_agent_session_manager

    manager = get_agent_session_manager()

    # Create an AgentSession
    agent = await manager.create_agent_session(CreateSessionRequest(
        working_dir="/path/to/project",
        model="claude-sonnet-4-20250514",
    ))

    # Retrieve an AgentSession
    agent = manager.get_agent(session_id)

    # Execute
    result = await agent.invoke("Hello")

    # Legacy SessionManager compatibility
    process = manager.get_process(session_id)  # Returns ClaudeProcess
    sessions = manager.list_sessions()  # Returns list of SessionInfo
"""

from logging import getLogger
from typing import Any, Dict, List, Optional
import asyncio
import os
import uuid

from service.claude_manager.session_manager import SessionManager, merge_mcp_configs
from service.claude_manager.models import (
    CreateSessionRequest,
    MCPConfig,
    SessionInfo,
    SessionRole,
    SessionStatus,
)

from service.logging.session_logger import get_session_logger, remove_session_logger
from service.langgraph.agent_session import AgentSession
from service.prompt.sections import build_agent_prompt
from service.prompt.context_loader import ContextLoader
from service.prompt.builder import PromptMode

from service.claude_manager.session_store import get_session_store

from pathlib import Path as _Path

from service.langgraph.agent_session import (
    _ADAPTIVE_PROMPT,
    _DEFAULT_VTUBER_PROMPT,
    _DEFAULT_WORKER_PROMPT,
)
from backend.service.persona import CharacterPersonaProvider


logger = getLogger(__name__)


_VTUBER_CHARACTERS_DIR = _Path(__file__).resolve().parent.parent.parent / "prompts" / "vtuber_characters"


class AgentSessionManager(SessionManager):
    """
    AgentSession manager.

    Inherits from SessionManager to retain all existing functionality while
    adding session management capabilities based on AgentSession (CompiledStateGraph).

    Core structure:
    - _local_agents: AgentSession store (local)

    All sessions use geny-executor Pipeline mode.
    Legacy ClaudeProcess/LangGraph paths have been removed.
    """

    def __init__(self):
        super().__init__()

        # AgentSession store (local)
        self._local_agents: Dict[str, AgentSession] = {}

        # Persistent session metadata store (sessions.json)
        self._store = get_session_store()

        # Shared folder configuration
        self._shared_folder_enabled: bool = False
        self._shared_folder_manager = None  # SharedFolderManager instance
        self._shared_folder_link_name: str = "_shared"

        # Database reference (for per-session memory/log DB wiring)
        self._app_db = None

        # Memory provider registry (Phase 4 attach point; None = legacy path only)
        self._memory_registry = None

        # Environment service (Phase 3 — enables env_id-driven session creation)
        self._environment_service = None

        # ToolLoader reference (for preset-based tool filtering)
        self._tool_loader = None

        # Background idle monitor
        self._idle_monitor_task: Optional[asyncio.Task] = None
        self._idle_monitor_interval: float = 60.0  # check every 60 seconds
        self._idle_monitor_running: bool = False

        # Persona provider — single manager-scoped instance, keys state on
        # session_id. Created eagerly so controllers can inject per-session
        # persona edits without reaching into AgentSession internals.
        self._persona_provider = CharacterPersonaProvider(
            characters_dir=_VTUBER_CHARACTERS_DIR,
            default_vtuber_prompt=_DEFAULT_VTUBER_PROMPT,
            default_worker_prompt=_DEFAULT_WORKER_PROMPT,
            adaptive_prompt=_ADAPTIVE_PROMPT,
        )

        logger.info("✅ AgentSessionManager initialized")

    @property
    def persona_provider(self) -> CharacterPersonaProvider:
        """Shared ``CharacterPersonaProvider`` — controllers use it to stage
        per-session persona edits (character / static override / context)."""
        return self._persona_provider

    def set_app_db(self, app_db) -> None:
        """Store the AppDatabaseManager for per-session DB wiring.

        Called once at startup from main.py lifespan.
        Enables DB-backed memory for newly created sessions.
        """
        self._app_db = app_db
        logger.info("AgentSessionManager: app_db set for per-session memory DB wiring")

    def set_memory_registry(self, memory_registry) -> None:
        """Store the MemorySessionRegistry for per-session MemoryProvider wiring.

        Phase 4 attach point: until populated, sessions run on the legacy
        SessionMemoryManager path only. Once a registry is set, Phase 4 wiring
        will pull a provider per session and attach it to Stage 2 (Context).
        """
        self._memory_registry = memory_registry
        logger.info("AgentSessionManager: memory_registry set for per-session provider wiring")

    def set_environment_service(self, environment_service) -> None:
        """Store the EnvironmentService for env_id-driven session creation.

        When set, ``create_agent_session`` will consult the service for any
        request carrying ``env_id`` and build the Pipeline from the stored
        manifest instead of the GenyPresets path.
        """
        self._environment_service = environment_service
        logger.info("AgentSessionManager: environment_service set for env_id-driven pipelines")

    def set_tool_loader(self, tool_loader) -> None:
        """Store the ToolLoader for preset-based tool filtering.

        Called once at startup from main.py lifespan.
        """
        self._tool_loader = tool_loader
        logger.info("AgentSessionManager: tool_loader set for preset-based tool filtering")

    def set_shared_folder_config(
        self,
        enabled: bool = True,
        shared_folder_manager=None,
        link_name: str = "_shared",
    ) -> None:
        """Configure shared folder for automatic linking on session creation.

        Args:
            enabled: Whether to create shared folder links in new sessions.
            shared_folder_manager: SharedFolderManager instance.
            link_name: Name of the symlink in each session's storage dir.
        """
        self._shared_folder_enabled = enabled
        self._shared_folder_manager = shared_folder_manager
        self._shared_folder_link_name = link_name
        logger.info(
            f"Shared folder config: enabled={enabled}, link_name={link_name}"
        )

    def _link_shared_folder(self, storage_path: str, session_id: str) -> None:
        """Create shared folder link in a session's storage directory."""
        if not self._shared_folder_enabled or self._shared_folder_manager is None:
            return
        try:
            ok = self._shared_folder_manager.link_to_session(
                session_storage_path=storage_path,
                link_name=self._shared_folder_link_name,
            )
            if ok:
                logger.info(f"[{session_id}] Shared folder linked: {self._shared_folder_link_name}")
            else:
                logger.warning(f"[{session_id}] Failed to link shared folder")
        except Exception as e:
            logger.warning(f"[{session_id}] Shared folder link error: {e}")

    def _build_shared_folder_context(self) -> str:
        """Build a concise system-prompt fragment about the shared folder."""
        link = self._shared_folder_link_name or "_shared"
        return (
            f"Shared folder: ./{link}/ (shared across all sessions). "
            f"Use it to exchange files between sessions."
        )

    # ========================================================================
    # Prompt Builder
    # ========================================================================

    def _build_system_prompt(
        self,
        request: CreateSessionRequest,
        session_id: Optional[str] = None,
    ) -> str:
        """Build the system prompt using the modular prompt builder.

        Design: The system prompt tells the agent WHO it is and WHAT to do.
        HOW to use tools and HOW to loop is handled by Claude CLI and LangGraph.
        Tool schemas are provided to Claude CLI via MCP — not repeated in prompts.

        Args:
            request: Session creation request.
            session_id: Pre-generated session ID (for Geny platform awareness).

        Returns:
            Assembled system prompt string.
        """
        # Determine role
        role = request.role.value if request.role else "worker"

        # Load bootstrap context files from working directory
        context_files: dict[str, str] = {}
        if request.working_dir:
            try:
                loader = ContextLoader(
                    working_dir=request.working_dir,
                    include_readme=(role in ("researcher",)),
                )
                context_files = loader.load_context_files()
                if context_files:
                    logger.info(
                        f"  Loaded {len(context_files)} context files: "
                        f"{list(context_files.keys())}"
                    )
            except Exception as e:
                logger.warning(f"  ContextLoader failed: {e}")

        # Load persisted memory if storage_path exists
        memory_context = ""
        storage_path = request.working_dir
        if storage_path:
            try:
                from service.memory.manager import SessionMemoryManager
                mgr = SessionMemoryManager(storage_path)
                mgr.initialize()
                memory_context = mgr.build_memory_context(max_chars=4000)
                if memory_context:
                    logger.info(f"  Injected {len(memory_context)} chars of memory context")
            except Exception:
                pass  # Memory not available yet — fine

        # Determine prompt mode
        mode = PromptMode.FULL

        # Resolve shared folder path for prompt inclusion
        shared_folder_path: str | None = None
        if self._shared_folder_enabled and self._shared_folder_manager:
            shared_folder_path = self._shared_folder_link_name or "_shared"

        # Build prompt
        prompt = build_agent_prompt(
            agent_name="Great Agent",
            role=role,
            agent_id=None,
            working_dir=request.working_dir,
            model=request.model,
            session_id=session_id,
            session_name=request.session_name,
            mode=mode,
            context_files=context_files if context_files else None,
            extra_system_prompt=request.system_prompt,
            shared_folder_path=shared_folder_path,
        )

        # Append memory context if available
        if memory_context:
            prompt = prompt + "\n\n" + memory_context

        # Append VTuber-specific context (Sub-Worker session info).
        # Fires only when the VTuber was reconstituted with a
        # pre-existing linked_session_id (e.g. warm restart). The
        # initial-create path builds the Sub-Worker *after* this
        # method and injects the block directly on the agent.
        if role == "vtuber" and request.linked_session_id:
            vtuber_ctx = (
                "\n\n## Sub-Worker Agent\n"
                "You have a Worker agent bound to you by the runtime. "
                "For complex tasks (coding, file operations, research, "
                "multi-step execution), delegate via the "
                "`send_direct_message_internal` tool — pass only the "
                "`content` argument. The runtime routes the message to "
                "your paired Sub-Worker automatically; you do NOT need "
                "(and must not attempt to create) a target session. "
                "The Worker's reply arrives as a `[SUB_WORKER_RESULT]` "
                "trigger message; summarize it for the user."
            )
            prompt = prompt + vtuber_ctx

        # Append Sub-Worker context (paired VTuber session info)
        if request.session_type == "sub" and request.linked_session_id:
            sub_ctx = (
                "\n\n## Paired VTuber Agent\n"
                "You are the Worker bound to a VTuber persona. "
                "Report results via `send_direct_message_internal` — pass "
                "only the `content` argument; the runtime routes it to "
                "your paired VTuber automatically."
            )
            prompt = prompt + sub_ctx

        logger.debug(f"  PromptBuilder: mode={mode.value}, role={role}, length={len(prompt)} chars")

        return prompt

    # ========================================================================
    # AgentSession Creation
    # ========================================================================

    async def create_agent_session(
        self,
        request: CreateSessionRequest,
        enable_checkpointing: bool = False,
        session_id: Optional[str] = None,
        owner_username: Optional[str] = None,
        env_id: Optional[str] = None,
        memory_config: Optional[Dict[str, Any]] = None,
    ) -> AgentSession:
        """
        Create a new AgentSession.

        1. Build geny-executor Pipeline (via AgentSession.create())
        2. Register in local store

        Args:
            request: Session creation request
            enable_checkpointing: Whether to enable checkpointing
            session_id: Reuse an existing session_id (for restoration)

        Returns:
            The created AgentSession instance
        """
        logger.info(f"Creating new AgentSession...")
        logger.info(f"  session_name: {request.session_name}")
        logger.info(f"  working_dir: {request.working_dir}")
        logger.info(f"  model: {request.model}")
        logger.info(f"  role: {request.role.value if request.role else 'worker'}")

        # ── Enforce unique session name ────────────────────────────────
        if request.session_name:
            existing = self.get_agent_by_name(request.session_name)
            if existing:
                raise ValueError(
                    f"Session name '{request.session_name}' is already in use "
                    f"by session {existing.session_id}. Names must be unique."
                )

        # ── Resolve Tool Preset ────────────────────────────────────────
        # Determines which Python tools and MCP servers are available.
        preset = None
        allowed_mcp_servers: list[str] | None = None

        try:
            from service.tool_preset.store import get_tool_preset_store
            from service.tool_preset.templates import ROLE_DEFAULT_PRESET

            preset_store = get_tool_preset_store()
            preset_id = request.tool_preset_id
            if not preset_id:
                role_key = request.role.value if request.role else "worker"
                preset_id = ROLE_DEFAULT_PRESET.get(role_key, "template-all-tools")

            preset = preset_store.load(preset_id)
            if preset:
                logger.info(f"  tool_preset: {preset.name} ({preset_id})")
            else:
                logger.warning(f"  tool_preset {preset_id} not found, using all tools")
        except Exception as e:
            logger.warning(f"  Tool preset resolution failed: {e}")

        # Log the tool_preset's resolved tool list for operational
        # visibility. After master-plan PR 15 removed
        # ``build_geny_tool_registry``, these values are no longer fed
        # into pipeline construction — tools flow through the manifest
        # (``tools.built_in`` + ``tools.external`` + ``GenyToolProvider``
        # adhoc provider). The log line is retained so operators can
        # still answer "what did this tool_preset resolve to?" at
        # session creation time.
        if self._tool_loader and preset:
            builtin, custom = self._tool_loader.get_allowed_tools_by_category(preset)
            logger.info(
                f"  allowed_tools: {len(builtin)} builtin + {len(custom)} custom"
            )
        elif self._tool_loader:
            total = len(self._tool_loader.get_builtin_names()) + len(
                self._tool_loader.get_custom_names()
            )
            logger.info(f"  allowed_tools: all ({total})")

        # Compute allowed MCP servers from preset
        if preset and preset.mcp_servers:
            allowed_mcp_servers = preset.mcp_servers  # ["*"] = all, or list of names
        else:
            allowed_mcp_servers = ["*"]  # Default: all external MCP servers

        # ── Build Session MCP Config (Dual Proxy MCP Pattern) ────────────
        from service.mcp_loader import build_session_mcp_config
        from service.config.manager import get_config_manager
        from service.config.sub_config.general.api_config import APIConfig

        # Determine backend port via config system
        api_cfg = get_config_manager().load_config(APIConfig)
        backend_port = api_cfg.app_port

        # Resolve model: use VTuber-specific default if role is VTuber and no model specified
        resolved_model = request.model
        if not resolved_model and request.role == SessionRole.VTUBER:
            resolved_model = api_cfg.vtuber_default_model or None

        # Pre-generate session_id so it can be injected into the prompt
        if not session_id:
            session_id = str(uuid.uuid4())

        merged_mcp_config = build_session_mcp_config(
            global_config=self._global_mcp_config,
            allowed_mcp_servers=allowed_mcp_servers,
            extra_mcp=request.mcp_config,
        )

        # Prepare system prompt — using modular prompt builder
        system_prompt = self._build_system_prompt(
            request,
            session_id=session_id,
        )
        logger.info(f"  📋 System prompt built via PromptBuilder ({len(system_prompt)} chars)")

        # Resolve graph_name and workflow_id
        graph_name = getattr(request, 'graph_name', None)
        workflow_id = getattr(request, 'workflow_id', None)

        # Map role to preset workflow_id
        if not workflow_id:
            role_val = request.role.value if request.role else "worker"
            if role_val == "vtuber":
                workflow_id = "template-vtuber"
                if not graph_name:
                    graph_name = "VTuber Conversational"
            elif graph_name and 'optimized' in graph_name.lower() and 'autonomous' in graph_name.lower():
                workflow_id = "template-optimized-autonomous"
            elif graph_name and 'autonomous' in graph_name.lower():
                workflow_id = "template-autonomous"
            else:
                workflow_id = "template-optimized-autonomous"
                if not graph_name:
                    graph_name = "Optimized Autonomous"

        logger.info(f"  workflow_id: {workflow_id}, graph_name: {graph_name}")

        # ── env_id resolution: always through the manifest path ──────────
        # Every session (regardless of role or whether the caller supplied
        # env_id explicitly) resolves to a seed environment id via
        # ``resolve_env_id`` and gets a manifest-backed Pipeline from
        # ``EnvironmentService.instantiate_pipeline``. The GenyPresets
        # branch inside ``AgentSession._build_pipeline`` is reached only
        # if the prebuild fails — master-plan PR 17 deletes that fallback.
        from service.environment.role_defaults import resolve_env_id

        env_id = resolve_env_id(request.role, env_id)
        if self._environment_service is None:
            raise RuntimeError(
                "EnvironmentService is not configured on AgentSessionManager. "
                "Wire it via set_environment_service(...) at app boot — "
                "every session now resolves through the manifest path."
            )
        try:
            from service.config.manager import get_config_manager
            from service.config.sub_config.general.api_config import APIConfig
            api_key = os.environ.get("ANTHROPIC_API_KEY") or (
                get_config_manager().load_config(APIConfig).anthropic_api_key or ""
            )
        except Exception:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for manifest-backed sessions")
        adhoc_providers: list = []
        if self._tool_loader is not None:
            from service.langgraph.geny_tool_provider import GenyToolProvider

            adhoc_providers.append(GenyToolProvider(self._tool_loader))
        prebuilt_pipeline = await self._environment_service.instantiate_pipeline(
            env_id, api_key=api_key, adhoc_providers=adhoc_providers,
        )
        logger.info(
            f"  env_id: {env_id} → manifest-backed pipeline built "
            f"(adhoc_providers={len(adhoc_providers)})"
        )

        # Seed the persona provider with the assembled static prompt so the
        # DynamicPersonaSystemBuilder hands back exactly this text on the
        # first turn. Persona mutations (character swap, user-edited
        # system-prompt, sub-worker ctx) then layer on top via the provider.
        self._persona_provider.set_static_override(session_id, system_prompt or None)

        # Create AgentSession
        agent = await AgentSession.create(
            working_dir=request.working_dir,
            model_name=resolved_model,
            session_name=request.session_name,
            session_id=session_id,
            system_prompt=system_prompt,
            env_vars=request.env_vars,
            mcp_config=merged_mcp_config,
            max_turns=request.max_turns or 50,
            timeout=request.timeout or 21600.0,
            max_iterations=request.max_iterations or 50,
            role=request.role or SessionRole.WORKER,
            enable_checkpointing=enable_checkpointing,
            workflow_id=workflow_id,
            graph_name=graph_name,
            tool_preset_id=preset_id,
            owner_username=owner_username,
            env_id=env_id,
            memory_config=memory_config,
            prebuilt_pipeline=prebuilt_pipeline,
            persona_provider=self._persona_provider,
        )

        session_id = agent.session_id

        # Register in local store
        self._local_agents[session_id] = agent

        # ── Provision + optionally attach MemoryProvider (Phase 4) ───────────
        # If a memory_config override is supplied, or a process-wide default
        # exists (MEMORY_PROVIDER=ephemeral/file/sql), spin up a provider now.
        # When MEMORY_PROVIDER_ATTACH=true is set, the provider is also
        # wired into Pipeline Stage 2 (ContextStage.provider). Default is
        # off so the legacy SessionMemoryManager keeps ownership until each
        # layer is migrated (Phase 5a-5e).
        if self._memory_registry is not None:
            try:
                provider = self._memory_registry.provision(
                    session_id, override=memory_config
                )
                if provider is not None:
                    logger.info(
                        f"[{session_id}] MemoryProvider provisioned "
                        f"(capabilities={[c.name for c in provider.descriptor.capabilities]})"
                    )
                    from service.memory_provider.config import is_attach_enabled
                    if is_attach_enabled() and agent._pipeline is not None:
                        try:
                            self._memory_registry.attach_to_pipeline(
                                agent._pipeline, provider
                            )
                            logger.info(
                                f"[{session_id}] MemoryProvider attached to Stage 2"
                            )
                        except Exception as attach_exc:
                            logger.warning(
                                f"[{session_id}] MemoryProvider attach failed: {attach_exc}"
                            )
            except Exception as e:
                logger.warning(f"[{session_id}] MemoryProvider provisioning skipped: {e}")

        # Wire DB into session memory manager (if available)
        if self._app_db is not None and agent.memory_manager is not None:
            try:
                agent.memory_manager.set_database(self._app_db, session_id)
                logger.info(f"[{session_id}] Memory DB backend enabled")
            except Exception as e:
                logger.warning(f"[{session_id}] Failed to wire memory DB: {e}")

        # Link shared folder into session's storage directory
        storage = agent.storage_path if hasattr(agent, 'storage_path') else None
        if storage:
            self._link_shared_folder(storage, session_id)

        # Create SessionInfo
        session_info = agent.get_session_info()

        # Create session logger
        session_logger = get_session_logger(session_id, request.session_name, create_if_missing=True)
        if session_logger:
            session_logger.log_session_event("created", {
                "model": request.model,
                "working_dir": request.working_dir,
                "max_turns": request.max_turns,
                "type": "agent_session",
                "env_id": env_id,
                "role": request.role.value if request.role else "worker",
                "session_type": request.session_type,
                "linked_session_id": request.linked_session_id,
            })
            logger.info(f"[{session_id}] 📝 Session logger created")

        # Persist session metadata to sessions.json
        self._store.register(session_id, session_info.model_dump(mode="json"))

        # Apply linked session attributes from request (e.g. CLI paired with VTuber)
        if request.linked_session_id:
            agent._linked_session_id = request.linked_session_id
        if request.session_type:
            agent._session_type = request.session_type

        # Persist linked session attributes to the store (they were not in the
        # initial get_session_info() snapshot because they are set after register)
        if request.linked_session_id or request.session_type:
            self._store.update(session_id, {
                k: v for k, v in {
                    "linked_session_id": request.linked_session_id,
                    "session_type": request.session_type,
                }.items() if v is not None
            })

        logger.info(f"[{session_id}] ✅ AgentSession created successfully")

        # ── Auto-create Sub-Worker for VTuber agents ───────────────────
        # Recursion guard: a VTuber request with session_type="sub"
        # is a caller bug (sub sessions are always workers). The
        # implicit guard was `not request.linked_session_id` — that
        # worked because spawned requests carry linked_session_id, but
        # the invariant we actually want is "don't double-spawn." Make
        # it explicit on session_type.
        if (
            request.role == SessionRole.VTUBER
            and request.session_type != "sub"
            and not request.linked_session_id
        ):
            worker_session_id: Optional[str] = None
            try:
                worker_name = f"{request.session_name or 'vtuber'}_worker"
                # Share the VTuber's actual storage path so memory is shared
                shared_dir = (
                    request.working_dir
                    or (agent.storage_path if hasattr(agent, 'storage_path') else None)
                )
                # Let resolve_env_id(role=WORKER, explicit=sub_worker_env_id)
                # pick template-worker-env by default, or honor an
                # explicit override. workflow_id/graph_name/tool_preset_id
                # are left as Pydantic defaults — the manifest path (PR 15)
                # owns stage layout and tool registration now.
                worker_request = CreateSessionRequest(
                    session_name=worker_name,
                    working_dir=shared_dir,
                    model=request.sub_worker_model or None,
                    max_turns=request.max_turns or 50,
                    timeout=request.timeout or 1800.0,
                    max_iterations=request.max_iterations or 50,
                    role=SessionRole.WORKER,
                    system_prompt=request.sub_worker_system_prompt,
                    env_id=request.sub_worker_env_id,
                    linked_session_id=session_id,
                    session_type="sub",
                    env_vars=request.env_vars,
                )
                worker_agent = await self.create_agent_session(worker_request)
                worker_session_id = worker_agent.session_id

                # Back-link: update VTuber session with Sub-Worker ID
                self._store.update(session_id, {
                    "linked_session_id": worker_session_id,
                    "session_type": "vtuber",
                })

                agent._linked_session_id = worker_session_id
                agent._session_type = "vtuber"

                # Inject the Sub-Worker delegation block into the
                # VTuber's system prompt. The runtime pairs this
                # VTuber with the freshly-created Sub-Worker via
                # _linked_session_id; the tool layer resolves the
                # target itself, so we do not expose the Sub-Worker's
                # session_id to the LLM (it doesn't need to copy a
                # UUID and we don't want it to treat the header as a
                # name to recreate).
                vtuber_ctx = (
                    "\n\n## Sub-Worker Agent\n"
                    "You have a Worker agent bound to you by the "
                    "runtime. For complex tasks (coding, file "
                    "operations, research, multi-step execution), "
                    "delegate via the `send_direct_message_internal` "
                    "tool — pass only the `content` argument. The "
                    "runtime routes the message to your paired "
                    "Sub-Worker automatically; you do NOT need (and "
                    "must not attempt to create) a target session. "
                    "The Worker's reply arrives as a "
                    "`[SUB_WORKER_RESULT]` trigger message; "
                    "summarize it for the user."
                )
                # Stage the sub-worker delegation block through the
                # PersonaProvider instead of mutating ``agent._system_prompt``
                # directly. ``append_context`` is idempotent on identical
                # text, so re-registration of an already-paired VTuber is
                # safe.
                self._persona_provider.append_context(session_id, vtuber_ctx)

                logger.info(
                    f"[{session_id}] 🔗 Sub-Worker created: "
                    f"{worker_session_id} ({worker_name})"
                )

                # ── Auto-create chat room for VTuber session ───────────
                try:
                    from service.chat.conversation_store import get_chat_store
                    chat_store = get_chat_store()
                    room_name = f"{request.session_name or 'VTuber'} Chat"
                    room = chat_store.create_room(room_name, [session_id])
                    room_id = room.get("id") or room.get("room_id")
                    if room_id:
                        agent._chat_room_id = room_id
                        self._store.update(session_id, {"chat_room_id": room_id})
                        logger.info(f"[{session_id}] 💬 Chat room created: {room_id}")
                except Exception as e:
                    logger.error(f"[{session_id}] Failed to create chat room: {e}", exc_info=True)

                # Register VTuber session with ThinkingTriggerService immediately
                try:
                    from service.vtuber.thinking_trigger import get_thinking_trigger_service
                    get_thinking_trigger_service().record_activity(session_id)
                except Exception:
                    pass  # best-effort

            except Exception as e:
                logger.error(
                    f"[{session_id}] Failed to create Sub-Worker: {e} — "
                    f"rolling back VTuber to avoid an orphaned half-pair",
                    exc_info=True,
                )
                # Roll back any Sub-Worker that did register before the
                # failure, then the VTuber itself. Each cleanup is
                # independently guarded so a secondary failure can't
                # swallow the primary one — we still re-raise.
                if worker_session_id is not None:
                    try:
                        await self.delete_session(worker_session_id)
                    except Exception:
                        logger.exception(
                            f"[{session_id}] Rollback of partial Sub-Worker "
                            f"{worker_session_id} also failed"
                        )
                try:
                    await self.delete_session(session_id)
                except Exception:
                    logger.exception(
                        f"[{session_id}] Rollback of partial VTuber also failed"
                    )
                raise

        return agent

    # ========================================================================
    # AgentSession Access
    # ========================================================================

    def get_agent(self, session_id: str) -> Optional[AgentSession]:
        """
        Retrieve an AgentSession.

        Args:
            session_id: Session ID

        Returns:
            AgentSession instance or None
        """
        return self._local_agents.get(session_id)

    def has_agent(self, session_id: str) -> bool:
        """
        Check whether an AgentSession exists.

        Args:
            session_id: Session ID

        Returns:
            Whether it exists
        """
        return session_id in self._local_agents

    def list_agents(self) -> List[AgentSession]:
        """
        Return a list of all AgentSessions.

        Returns:
            List of AgentSession instances
        """
        return list(self._local_agents.values())

    def get_agent_by_name(self, name: str) -> Optional[AgentSession]:
        """
        Look up an AgentSession by session name.

        Args:
            name: Session name (case-insensitive match)

        Returns:
            Matching AgentSession or None
        """
        name_lower = name.strip().lower()
        for agent in self._local_agents.values():
            if agent.session_name and agent.session_name.strip().lower() == name_lower:
                return agent
        return None

    def resolve_session(self, name_or_id: str) -> Optional[AgentSession]:
        """
        Look up a session by name or ID. Checks ID first, falls back to name.

        Args:
            name_or_id: Session ID or session name

        Returns:
            Matching AgentSession or None
        """
        # Try exact ID match first
        agent = self.get_agent(name_or_id)
        if agent:
            return agent
        # Fallback to name match
        return self.get_agent_by_name(name_or_id)

    # ========================================================================
    # Session Management (Override for AgentSession support)
    # ========================================================================

    async def delete_session(self, session_id: str, cleanup_storage: bool = False) -> bool:
        """
        Delete a session (supports both AgentSession and legacy approach).

        Args:
            session_id: Session ID
            cleanup_storage: Whether to clean up storage (default False — preserve on soft-delete)

        Returns:
            Whether deletion succeeded
        """
        # If it's an AgentSession
        agent = self._local_agents.get(session_id)
        if agent:
            logger.info(f"[{session_id}] Deleting AgentSession...")

            # Session logger event
            session_logger = get_session_logger(session_id, create_if_missing=False)
            if session_logger:
                session_logger.log_session_event("deleted")

            # Clean up AgentSession (stop process, release resources)
            await agent.cleanup()

            # Clean up storage (only on permanent delete)
            if cleanup_storage and agent.storage_path:
                import shutil
                from pathlib import Path as FilePath
                sp = FilePath(agent.storage_path)
                if sp.is_dir():
                    try:
                        shutil.rmtree(sp)
                        logger.info(f"[{session_id}] Storage cleaned up: {agent.storage_path}")
                    except Exception as e:
                        logger.warning(f"[{session_id}] Failed to cleanup storage: {e}")

            # Remove from local store
            del self._local_agents[session_id]

            # Also remove from _local_processes (for compatibility)
            if session_id in self._local_processes:
                del self._local_processes[session_id]

            # Clear persona provider's in-memory state for this session.
            # Restore re-stages static_override/character from sessions.json.
            try:
                self._persona_provider.reset(session_id)
            except Exception:
                pass  # best-effort — provider must not block deletion

            # Remove session logger
            remove_session_logger(session_id)

            # Soft-delete in persistent store (keeps metadata for restore)
            self._store.soft_delete(session_id)

            logger.info(f"[{session_id}] ✅ AgentSession deleted (soft)")
            return True

        # Legacy approach (direct ClaudeProcess)
        return await super().delete_session(session_id, cleanup_storage)

    async def cleanup_dead_sessions(self):
        """
        Clean up dead sessions (both AgentSession and legacy approach).

        Philosophy: Try to REVIVE idle/dead agent sessions before deleting
        them.  Only sessions that fail revival are removed.
        """
        # Clean up AgentSessions — try revival first
        dead_agents = [
            session_id
            for session_id, agent in self._local_agents.items()
            if not agent.is_alive()
        ]

        for session_id in dead_agents:
            agent = self._local_agents[session_id]
            logger.info(f"[{session_id}] Dead AgentSession detected — attempting revival")

            try:
                success = await agent.revive()
                if success:
                    logger.info(f"[{session_id}] ✅ AgentSession revived successfully")
                    continue
            except Exception as e:
                logger.warning(f"[{session_id}] Revival failed: {e}")

            # Revival failed — clean up
            logger.info(f"[{session_id}] Cleaning up unrevivable AgentSession")
            await self.delete_session(session_id)

        # Clean up legacy processes (only those that are not AgentSessions)
        dead_processes = [
            session_id
            for session_id, process in self._local_processes.items()
            if session_id not in self._local_agents and not process.is_alive()
        ]

        for session_id in dead_processes:
            logger.info(f"[{session_id}] Cleaning up dead session")
            await super().delete_session(session_id)

    # ========================================================================
    # Background Idle Monitor
    # ========================================================================

    def start_idle_monitor(self) -> None:
        """Start the background idle monitor task.

        Periodically scans all RUNNING sessions and transitions them to
        IDLE if they have had no activity for ``idle_transition_seconds``
        (default 10 minutes / 600 seconds).

        Should be called once during application startup.
        """
        if self._idle_monitor_running:
            logger.debug("Idle monitor already running")
            return

        self._idle_monitor_running = True
        self._idle_monitor_task = asyncio.ensure_future(self._idle_monitor_loop())
        logger.info(
            f"✅ Idle monitor started (interval={self._idle_monitor_interval}s)"
        )

    async def stop_idle_monitor(self) -> None:
        """Stop the background idle monitor task.

        Called during application shutdown.
        """
        self._idle_monitor_running = False
        if self._idle_monitor_task and not self._idle_monitor_task.done():
            self._idle_monitor_task.cancel()
            try:
                await self._idle_monitor_task
            except asyncio.CancelledError:
                pass
        self._idle_monitor_task = None
        logger.info("Idle monitor stopped")

    async def _idle_monitor_loop(self) -> None:
        """Background loop that checks for idle sessions.

        Runs every ``_idle_monitor_interval`` seconds and calls
        ``mark_idle()`` on sessions whose freshness evaluates as
        STALE_IDLE.  This causes their status to change from RUNNING
        to IDLE, which is visible in the frontend.

        When the user later sends a command, the session auto-revives
        transparently.
        """
        logger.info("Idle monitor loop started")
        while self._idle_monitor_running:
            try:
                await asyncio.sleep(self._idle_monitor_interval)
                if not self._idle_monitor_running:
                    break
                self._scan_for_idle_sessions()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Idle monitor tick error (non-critical)", exc_info=True)

    def _scan_for_idle_sessions(self) -> None:
        """Scan all agent sessions and mark idle ones.

        This is a lightweight synchronous scan — no I/O, no process
        restarts.  It only flips the status flag.
        """
        transitioned = 0
        for session_id, agent in self._local_agents.items():
            if agent.status == SessionStatus.RUNNING:
                if agent.mark_idle():
                    transitioned += 1
                    # Update persistent store with IDLE status
                    try:
                        info = agent.get_session_info()
                        self._store.register(session_id, info.model_dump(mode="json"))
                    except Exception:
                        pass  # non-critical

        if transitioned > 0:
            logger.info(f"Idle monitor: {transitioned} session(s) transitioned to IDLE")

# ============================================================================
# Singleton
# ============================================================================

_agent_session_manager: Optional[AgentSessionManager] = None


def get_agent_session_manager() -> AgentSessionManager:
    """
    Return the singleton AgentSessionManager instance.

    Returns:
        AgentSessionManager instance
    """
    global _agent_session_manager
    if _agent_session_manager is None:
        _agent_session_manager = AgentSessionManager()
    return _agent_session_manager


def reset_agent_session_manager():
    """
    Reset the AgentSessionManager singleton (for testing).
    """
    global _agent_session_manager
    _agent_session_manager = None
