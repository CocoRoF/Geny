"""AgentSession — geny-executor Pipeline-based session management.

Each session runs a geny-executor Pipeline that calls the Anthropic API
directly (no CLI subprocess). Session creation flow:

    1. Manager resolves role → env_id → EnvironmentManifest → Pipeline
       (via ``EnvironmentService.instantiate_pipeline``) and hands it
       in as ``prebuilt_pipeline``.
    2. ``AgentSession._build_pipeline`` calls ``Pipeline.attach_runtime``
       to wire the session-scoped runtime objects that a static
       manifest cannot encode: memory retriever/strategy/persistence,
       ``ComposablePromptBuilder`` with persona + datetime + memory
       blocks, and ``ToolContext`` carrying the session's working_dir
       and storage_path.
    3. ``SessionMemoryManager`` is initialized for the session storage
       path.

Usage::

    agent = await AgentSession.create(
        working_dir="/path/to/project",
        model_name="claude-sonnet-4-20250514",
        session_name="my-agent",
        prebuilt_pipeline=<manifest-built pipeline>,
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

from service.sessions.models import (
    MCPConfig,
    SessionInfo,
    SessionRole,
    SessionStatus,
)
from service.executor.session_freshness import SessionFreshness, FreshnessStatus
from service.logging.session_logger import get_session_logger, SessionLogger, LogLevel, STAGE_ORDER

logger = getLogger(__name__)


def _classify_input_role(input_text: str) -> str:
    """Map invoke input to the STM role it should be recorded under.

    Internal auto-triggers and inter-agent DMs must not be recorded as
    ``"user"`` — downstream reasoning (session_summary, keyword/vector
    retrieval) would otherwise conflate system self-prompts and
    counterpart messages with real user input. See
    ``dev_docs/20260420_8/plan/03_turn_memory_continuity.md`` § 4-2.

    Tag coverage mirrors what the rest of the codebase actually emits:

    * ``[THINKING_TRIGGER]`` and ``[ACTIVITY_TRIGGER]`` from
      ``service/vtuber/thinking_trigger.py`` → ``internal_trigger``.
    * ``[SUB_WORKER_RESULT]`` (+ legacy ``[CLI_RESULT]``),
      ``[DELEGATION_REQUEST]``, ``[DELEGATION_RESULT]`` from
      ``service/vtuber/delegation.py`` → ``assistant_dm``.
    * DM prompts emitted by ``_trigger_dm_response`` in
      ``tools/built_in/geny_tools.py`` start with
      ``[SYSTEM] You received a direct message`` — also ``assistant_dm``.
    * ``[SUB_WORKER_PROGRESS]`` / ``[FROM_COUNTERPART]`` are reserved
      forward-compat slots from plan/03 § 4-2; kept here so callers
      that later emit them get routed without another code change.
    * ``[INBOX from {sender}]`` — wrapper emitted by ``_drain_inbox``
      in ``service/execution/agent_executor.py`` when a queued DM
      (e.g. a ``[SUB_WORKER_RESULT]`` that arrived while the target
      was busy) is picked up after the target's execution slot frees.
      Always an inter-agent message, never from the human user →
      ``assistant_dm``. See
      ``dev_docs/20260421_1/analysis/01_dm_continuity_regression.md``
      § 2 for the regression pattern this catches.

    Prefix matches use the open form (``[TAG`` rather than ``[TAG]``)
    so variants like ``[THINKING_TRIGGER:first_idle]`` match.
    """
    head = input_text.lstrip()[:128]
    if head.startswith("[THINKING_TRIGGER") or head.startswith("[ACTIVITY_TRIGGER"):
        return "internal_trigger"
    if (
        head.startswith("[SUB_WORKER_RESULT")
        or head.startswith("[SUB_WORKER_PROGRESS")
        or head.startswith("[CLI_RESULT")
        or head.startswith("[DELEGATION_REQUEST")
        or head.startswith("[DELEGATION_RESULT")
        or head.startswith("[FROM_COUNTERPART")
        or head.startswith("[SYSTEM] You received a direct message")
        or head.startswith("[INBOX from")
    ):
        return "assistant_dm"
    return "user"


# Plan/Phase02 §4 — loneliness drift constants. A single autonomous
# (THINKING_TRIGGER) turn debits affection / familiarity by a fixed
# amount on the active VTuber's bond, modeling "talking to myself
# corrodes the felt closeness". Magnitudes are deliberately small
# (0.10 / 0.05) so the drift is felt over many turns rather than
# punching the bond down on a single trigger. The `Bond` clamp policy
# (0.0–100.0) caps the floor — affection won't go negative.
_LONELINESS_AFFECTION_LOSS = -0.10
_LONELINESS_FAMILIARITY_LOSS = -0.05

# Plan/Phase01 §3.2 — attention recovery constants. Hunger now models
# attention deprivation (see Plan/01); every user-initiated turn
# refunds a chunk of it, while autonomous (TRIGGER) turns do not. The
# user-message familiarity gain is the *only* automatic familiarity
# bump from plain dialogue (game tools / loneliness drift handle the
# other channels). Magnitudes chosen via Plan/01 §7 (~30min/day user
# keeps hunger < 50, idle user reaches >= 80 by 24h).
_USER_MSG_HUNGER_RECOVERY = -3.0
_USER_MSG_FAMILIARITY_GAIN = +0.05


def _apply_loneliness_drift(buf: Any) -> None:
    """Push the trigger-turn loneliness debit onto the current buffer.

    The caller is responsible for the gate (vtuber + trigger turn +
    buffer present); this helper is intentionally thin so it stays
    trivially testable.
    """
    buf.append(
        op="add",
        path="bond.affection",
        value=_LONELINESS_AFFECTION_LOSS,
        source="loneliness:thinking_trigger",
    )
    buf.append(
        op="add",
        path="bond.familiarity",
        value=_LONELINESS_FAMILIARITY_LOSS,
        source="loneliness:thinking_trigger",
    )


def _apply_attention_recovery(buf: Any) -> None:
    """Push the user-message attention recovery onto the current buffer.

    Counterpart to :func:`_apply_loneliness_drift` — runs only on
    user-initiated turns. Caller is responsible for the role / turn
    gate. The hunger refund is large (-3) and the familiarity bump is
    tiny (+0.05) so dialogue feels rewarding for upkeep but the bond
    only meaningfully grows through richer interactions (game tools,
    affect tags).
    """
    buf.append(
        op="add",
        path="vitals.hunger",
        value=_USER_MSG_HUNGER_RECOVERY,
        source="attention:user_message",
    )
    buf.append(
        op="add",
        path="bond.familiarity",
        value=_USER_MSG_FAMILIARITY_GAIN,
        source="attention:user_message",
    )


# ============================================================================
# AgentSession Class
# ============================================================================


_DEFAULT_WORKER_PROMPT = """\
You are an autonomous AI agent. Complete the user's task step by step.

When you have finished the task, end your response with [TASK_COMPLETE].
If you need to continue working, end with [CONTINUE: next action].
If you are blocked and cannot proceed, end with [BLOCKED: reason].

Be thorough, accurate, and concise."""

_ADAPTIVE_PROMPT = """\
## Execution Strategy

Classify the task and act accordingly:

**Easy tasks** (factual Q&A, simple lookups, greetings, short explanations):
Answer directly in one response. Do not use tools unless absolutely necessary.

**Complex tasks** (coding, research, multi-step work, file operations):
1. Plan: Decompose into clear steps
2. Execute: Use tools to complete each step
3. Verify: Check your work
4. Signal [CONTINUE: next step] after each step
5. Signal [TASK_COMPLETE] when all steps are done"""

_DEFAULT_VTUBER_PROMPT = """\
You are a friendly AI VTuber assistant. Engage in natural conversation
while being helpful and knowledgeable.

When the user asks a complex task that requires tools or multi-step work,
indicate that you will delegate it.

Keep responses conversational and natural."""


class _SessionCharacterLike:
    """Minimal :class:`CharacterLike` carrier for the manifest selector.

    Until the Character repo lands (plan/04 §1.1) the selector needs
    *something* with ``species`` / ``growth_tree_id`` /
    ``personality_archetype``. Defaults live on :class:`AgentSession`,
    which constructs this on demand inside ``_build_state_registry``.
    """

    __slots__ = ("species", "growth_tree_id", "personality_archetype")

    def __init__(
        self, *, species: str, growth_tree_id: str, personality_archetype: str,
    ) -> None:
        self.species = species
        self.growth_tree_id = growth_tree_id
        self.personality_archetype = personality_archetype


class AgentSession:
    """geny-executor Pipeline-based agent session.

    Key architecture:
        - geny-executor Pipeline: 16-stage execution engine, built
          from an EnvironmentManifest by the session manager and
          handed in via ``prebuilt_pipeline``.
        - ``Pipeline.attach_runtime``: the sole injection point for
          session-scoped runtime (memory retriever/strategy/persistence,
          composable system prompt builder, tool context).
        - SessionMemoryManager: long-term / short-term memory backing
          the retriever + strategy + persistence triple.
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
        env_id: Optional[str] = None,
        memory_config: Optional[Dict[str, Any]] = None,
        prebuilt_pipeline: Optional[Any] = None,
        persona_provider: Optional[Any] = None,
        lifecycle_bus: Optional[Any] = None,
        state_provider: Optional[Any] = None,
        character_id: Optional[str] = None,
        catchup_policy: Optional[Any] = None,
        manifest_selector: Optional[Any] = None,
        species: Optional[str] = None,
        growth_tree_id: Optional[str] = None,
        personality_archetype: Optional[str] = None,
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
            enable_checkpointing: Enable Pipeline-state checkpointing (legacy flag, currently a no-op for the geny-executor path).
            workflow_id: Preset identifier (e.g. template-vtuber, template-optimized-autonomous).
            graph_name: Human-readable graph/workflow name.
            persona_provider: ``PersonaProvider`` resolved per turn by
                ``DynamicPersonaSystemBuilder``. When omitted, the session
                falls back to the legacy fixed ``ComposablePromptBuilder``
                (kept for tests that construct ``AgentSession`` directly).
            lifecycle_bus: Optional ``SessionLifecycleBus`` the session
                uses to emit ``SESSION_REVIVED`` when ``revive`` /
                ``_auto_revive`` succeed. Tests that construct a session
                directly may leave this ``None``.
            state_provider: Optional ``CreatureStateProvider`` (PR-X3-5).
                When combined with ``character_id``, each turn hydrates
                the creature state into ``PipelineState.shared`` before
                ``pipeline.run_stream`` and persists mutations after. When
                ``None``, the session runs in "classic" mode — no state
                layer involvement. Shadow rollout is driven by
                ``GENY_GAME_FEATURES`` at the manager level.
            character_id: Optional character id for state load/persist.
                Defaults to ``session_id`` when ``state_provider`` is
                set — each session owns one creature. PR-X4 moves
                character identity onto the owner/env surface.
            catchup_policy: Optional ``DecayPolicy`` for the hydrate-side
                catch-up tick. Defaults to ``DEFAULT_DECAY`` when
                unspecified and ``state_provider`` is set.
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
        self._persona_provider = persona_provider
        self._lifecycle_bus = lifecycle_bus
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

        # Dual-agent pairing (VTuber ↔ Sub-Worker)
        self._linked_session_id: Optional[str] = None
        self._session_type: Optional[str] = None  # "vtuber" | "sub" | "solo" | None
        self._chat_room_id: Optional[str] = None

        # Creature state wiring (PR-X3-5). Registry is turn-scoped — a
        # fresh one is built inside ``_invoke_pipeline`` / ``_astream_pipeline``
        # so the snapshot and mutation buffer don't leak across turns. When
        # ``state_provider`` is ``None`` the hydrate/persist path is
        # skipped entirely (classic mode).
        self._state_provider = state_provider
        self._character_id = character_id
        self._catchup_policy = catchup_policy

        # Manifest selector / character identity (PR-X4-5). Selector is
        # consulted inside ``SessionRuntimeRegistry.hydrate`` to stage a
        # transition mutation when the life-stage predicate fires.
        # species / growth_tree_id / personality_archetype are read by
        # the selector through the ``CharacterLike`` protocol; defaults
        # keep classic sessions safe (selector is ``None`` there anyway).
        self._manifest_selector = manifest_selector
        self._species = species or "generic"
        self._growth_tree_id = growth_tree_id or "default"
        self._personality_archetype = personality_archetype or ""

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
            enable_checkpointing: Enable Pipeline-state checkpointing (legacy flag).
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
        from service.utils.platform import DEFAULT_STORAGE_ROOT
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
    def persona_provider(self) -> Optional[Any]:
        """``PersonaProvider`` bound at construction — None for legacy path."""
        return self._persona_provider

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
    def env_id(self) -> Optional[str]:
        """Environment id the session was built from (e.g.
        ``template-worker-env``). ``None`` only on sessions that
        predate manifest-backed construction."""
        return self._env_id

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
        """ID of the paired session (VTuber ↔ Sub-Worker)."""
        return self._linked_session_id

    @property
    def session_type(self) -> Optional[str]:
        """Session type: 'vtuber', 'sub', 'solo', or None."""
        return self._session_type

    @property
    def _is_always_on(self) -> bool:
        """Whether this session should never go idle.

        True for VTuber sessions and their Sub-Worker sessions — these
        form a tightly-coupled unit that must stay warm together.
        """
        if self._role == SessionRole.VTUBER:
            return True
        if self._session_type == "sub" and self._linked_session_id:
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

        # Fire-and-forget bus emit — _auto_revive is sync but runs inside
        # invoke/astream, both async. If no loop is running (very early
        # startup), skip silently; no session state depends on the emit.
        self._schedule_revived_emit(kind="auto_revive")

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

            await self._emit_revived(kind="pipeline_rebuild")

            return True

        except Exception as e:
            self._error_message = f"Revival failed: {e}"
            self._status = SessionStatus.ERROR
            logger.exception(
                f"[{self._session_id}] Session revival failed: {e}"
            )
            return False

    async def _emit_revived(self, *, kind: str) -> None:
        """Emit SESSION_REVIVED on the lifecycle bus (if one is attached).

        ``kind`` distinguishes ``pipeline_rebuild`` (full ``revive()``
        path) from ``auto_revive`` (lightweight timestamp reset) so
        subscribers can choose how thoroughly to react.
        """
        if self._lifecycle_bus is None:
            return
        try:
            from service.lifecycle import LifecycleEvent
            await self._lifecycle_bus.emit(
                LifecycleEvent.SESSION_REVIVED,
                self._session_id,
                revive_count=self._freshness.revive_count,
                kind=kind,
            )
        except Exception:
            logger.debug(
                f"[{self._session_id}] SESSION_REVIVED emit failed (non-critical)",
                exc_info=True,
            )

    def _schedule_revived_emit(self, *, kind: str) -> None:
        """Fire-and-forget SESSION_REVIVED emit from a sync context.

        Used by ``_auto_revive`` which runs inside async ``invoke``/
        ``astream`` but is itself sync. If no loop is running we skip
        silently — the emit is best-effort.
        """
        if self._lifecycle_bus is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop — skip
        loop.create_task(self._emit_revived(kind=kind))

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
        """Adopt the manager-built Pipeline and attach session runtime.

        Every AgentSession is now manifest-backed: the session manager
        resolves ``role → env_id`` via :func:`resolve_env_id`, calls
        :meth:`EnvironmentService.instantiate_pipeline` to build a
        Pipeline from the stored :class:`EnvironmentManifest`, and
        hands it in as ``prebuilt_pipeline``. This method wires the
        session-scoped runtime objects that a static manifest cannot
        encode (memory, composable system prompt, tool context) via
        :meth:`Pipeline.attach_runtime`.

        Raises:
            RuntimeError: If ``prebuilt_pipeline`` is missing
                (direct construction without the manager is no longer
                supported) or ``ANTHROPIC_API_KEY`` is not configured.
        """
        if self._prebuilt_pipeline is None:
            raise RuntimeError(
                f"[{self._session_id}] prebuilt_pipeline is None. "
                f"Every AgentSession must now be constructed through "
                f"AgentSessionManager, which resolves env_id via "
                f"resolve_env_id() and builds the Pipeline from the "
                f"stored EnvironmentManifest before handing it to "
                f"AgentSession."
            )

        from geny_executor.memory import (
            GenyMemoryRetriever,
            GenyMemoryStrategy,
            GenyPersistence,
            ReflectionResolver,
        )
        from geny_executor.tools.base import ToolContext
        from geny_executor.stages.s03_system.artifact.default.builders import (
            ComposablePromptBuilder,
            DateTimeBlock,
            MemoryContextBlock,
            PersonaBlock,
        )
        from geny_executor.core.config import ModelConfig
        from geny_executor.core.mutation import PipelineMutator
        from geny_executor.core.errors import MutationError
        from geny_executor.llm_client import ClientRegistry

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        api_cfg = None
        try:
            from service.config.manager import get_config_manager
            from service.config.sub_config.general.api_config import APIConfig
            api_cfg = get_config_manager().load_config(APIConfig)
            api_key = api_key or api_cfg.anthropic_api_key or ""
        except Exception:
            pass
        if api_cfg is None:
            from service.config.sub_config.general.api_config import APIConfig
            api_cfg = APIConfig()
        if not api_key:
            raise RuntimeError(
                f"[{self._session_id}] ANTHROPIC_API_KEY is required. "
                f"Set it in environment or config."
            )

        working_dir = self._working_dir or self.storage_path or ""
        is_vtuber = self._role == SessionRole.VTUBER

        # Persona text — preserve legacy GenyPresets.* behavior. The
        # adaptive tail teaches the LLM the [TASK_COMPLETE] / [CONTINUE]
        # / [BLOCKED] vocabulary Stage 12's binary_classify evaluator
        # expects. VTuber roles skip it — they use signal_based
        # evaluation and a conversational persona.
        system_prompt = self._system_prompt or ""
        if is_vtuber:
            persona_text = system_prompt or _DEFAULT_VTUBER_PROMPT
            max_inject_chars = 8000
        else:
            persona_text = (
                (system_prompt or _DEFAULT_WORKER_PROMPT)
                + "\n\n"
                + _ADAPTIVE_PROMPT
            )
            max_inject_chars = 10000

        curated_km = None
        if self._owner_username:
            try:
                from service.memory.curated_knowledge import get_curated_knowledge_manager
                curated_km = get_curated_knowledge_manager(self._owner_username)
            except Exception:
                pass

        # ── Memory model routing (cycle 20260421_4) ──
        #
        # Push APIConfig.memory_model down onto s02 (context) and s15
        # (memory) so executor-native paths honour the per-stage override.
        # Empty memory_model falls back to the main model so no surprise
        # LLM calls spin up.
        mem_model_name = (api_cfg.memory_model or "").strip() or api_cfg.anthropic_model
        memory_cfg = ModelConfig(
            model=mem_model_name,
            max_tokens=2048,
            temperature=0.0,
            thinking_enabled=False,
        )
        try:
            mutator = PipelineMutator(self._prebuilt_pipeline)
        except Exception as exc:
            mutator = None
            logger.warning(
                f"[{self._session_id}] cycle-4: PipelineMutator init failed — "
                f"continuing without stage-level overrides: {exc}"
            )
        if mutator is not None:
            try:
                mutator.set_stage_model(2, memory_cfg)
            except MutationError:
                logger.warning(
                    f"[{self._session_id}] cycle-4: s02 context stage absent — "
                    f"skipping memory model override"
                )
            try:
                mutator.set_stage_model(15, memory_cfg)
            except MutationError:
                logger.warning(
                    f"[{self._session_id}] cycle-4: s15 memory stage absent — "
                    f"skipping memory model override"
                )

        # ── Shared LLM client (cycle 20260421_4) ──
        #
        # Build the vendor-selected client once and inject it via
        # attach_runtime. s06_api's _resolve_client prefers state.llm_client,
        # so main-stage and memory-stage LLM calls both run through the
        # same instance — no credential drift by construction.
        provider_name = (getattr(api_cfg, "provider", "") or "anthropic").strip()
        base_url = (getattr(api_cfg, "base_url", "") or "").strip() or None
        try:
            client_cls = ClientRegistry.get(provider_name)
            client_kwargs: Dict[str, Any] = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            llm_client = client_cls(**client_kwargs)
        except Exception as exc:
            logger.exception(
                f"[{self._session_id}] cycle-4: failed to build LLM client "
                f"for provider={provider_name!r}: {exc}"
            )
            raise

        # Sync s06_api's own config so its fallback client (used only if
        # state.llm_client ever becomes None at run time) stays consistent.
        try:
            s06_stage = next(
                (st for st in self._prebuilt_pipeline.stages if getattr(st, "order", None) == 6),
                None,
            )
            if s06_stage is not None and hasattr(s06_stage, "update_config"):
                s06_stage.update_config({
                    "provider": provider_name,
                    "base_url": base_url or "",
                })
        except Exception as exc:
            logger.warning(
                f"[{self._session_id}] cycle-4: failed to sync s06 provider: {exc}"
            )

        # ── Legacy reflection callback (kept behind APIConfig flag) ──
        use_legacy_reflect = bool(getattr(api_cfg, "use_legacy_reflect", False))
        llm_reflect = (
            self._make_llm_reflect_callback(api_key) if use_legacy_reflect else None
        )

        # ── Native reflection resolver ──
        #
        # Consumed by GenyMemoryStrategy when llm_reflect is None. Closes
        # over the s15 stage handle so the resolver reads the live model
        # override at reflect time (not pipeline-build time).
        s15_stage = next(
            (st for st in self._prebuilt_pipeline.stages if getattr(st, "order", None) == 15),
            None,
        )
        if s15_stage is not None:
            reflection_resolver = ReflectionResolver(
                resolve_cfg=lambda state, _stage=s15_stage: _stage.resolve_model_config(state),
                has_override=lambda _stage=s15_stage: getattr(_stage, "_model_override", None) is not None,
                client_getter=lambda state: getattr(state, "llm_client", None),
            )
        else:
            reflection_resolver = None

        # ── Session-scoped runtime objects ──
        #
        # When a PersonaProvider is bound to this session (PR-X1-3 cycle
        # 20260421_7), s03's builder becomes a DynamicPersonaSystemBuilder
        # that re-resolves the persona section on every turn — persona
        # edits (set_character / set_static_override / append_context)
        # take effect on the next pipeline.run without rebuilding stages.
        # When no provider is bound (legacy / direct AgentSession
        # construction in tests), the fixed ComposablePromptBuilder path
        # is preserved.
        if self._persona_provider is not None:
            from service.persona import DynamicPersonaSystemBuilder
            system_builder: Any = DynamicPersonaSystemBuilder(
                self._persona_provider,
                session_meta={
                    "session_id": self._session_id,
                    "is_vtuber": is_vtuber,
                    "role": self._role.value if self._role else "worker",
                    "owner_username": self._owner_username,
                },
                tail_blocks=[DateTimeBlock(), MemoryContextBlock()],
            )
        else:
            system_builder = ComposablePromptBuilder(
                blocks=[
                    PersonaBlock(persona_text),
                    DateTimeBlock(),
                    MemoryContextBlock(),
                ]
            )
        attach_kwargs: Dict[str, Any] = {
            "system_builder": system_builder,
            "tool_context": ToolContext(
                session_id=self._session_id,
                working_dir=working_dir,
                storage_path=self.storage_path,
            ),
            "llm_client": llm_client,
        }

        # G6.3: forward host-side permission rules + mode. Returns an
        # empty dict when no rule files are present (every tool stays
        # allowed) so older executor builds without the kwarg keep
        # working. Mode defaults to "advisory" — G6.4 flips
        # worker_adaptive to "enforce" once the timeline UI shows the
        # permission.* events.
        try:
            from service.permission import install as _perm_install
            attach_kwargs.update(_perm_install.attach_kwargs())
        except Exception:
            logger.debug(
                "_build_pipeline: permission install failed; continuing without rules",
                exc_info=True,
            )

        # G6.5: forward a session-scoped HookRunner when the operator
        # has set GENY_ALLOW_HOOKS=1 and ~/.geny/hooks.yaml declares
        # enabled hooks. Returns {} otherwise — Stage 4 / Stage 10 fall
        # back to no-op hook handling.
        try:
            from service.hooks import attach_kwargs as _hook_attach_kwargs
            attach_kwargs.update(_hook_attach_kwargs())
        except Exception:
            logger.debug(
                "_build_pipeline: hook install failed; continuing without runner",
                exc_info=True,
            )

        if self._memory_manager is not None:
            attach_kwargs["memory_retriever"] = GenyMemoryRetriever(
                self._memory_manager,
                max_inject_chars=max_inject_chars,
                enable_vector_search=True,
                curated_knowledge_manager=curated_km,
                recent_turns=6,
            )
            attach_kwargs["memory_strategy"] = GenyMemoryStrategy(
                self._memory_manager,
                enable_reflection=True,
                llm_reflect=llm_reflect,
                curated_knowledge_manager=curated_km,
                resolver=reflection_resolver,
            )
            attach_kwargs["memory_persistence"] = GenyPersistence(
                self._memory_manager
            )

        self._pipeline = self._prebuilt_pipeline
        self._pipeline.attach_runtime(**attach_kwargs)
        self._preset_name = f"env:{self._env_id}" if self._env_id else "env"

        # G6.4: populate Stage 4's guard chain. The manifest declares the
        # chain order but the executor's reorder_chain only reorders
        # *existing* items; the default GuardStage starts with an empty
        # chain. populate_guard_chain reads the same default order
        # (token_budget + cost_budget + iteration + permission) and adds
        # any missing guards via add_to_chain. Idempotent. No-op when
        # Stage 4 isn't registered (custom manifest dropped it).
        try:
            from service.permission.install import populate_guard_chain

            populate_guard_chain(self._pipeline)
        except Exception as exc:  # noqa: BLE001 — guard wiring must never block run
            logger.warning(
                f"[{self._session_id}] Guard chain population failed: {exc}"
            )

        # G2.3: install a session-scoped FilePersister into Stage 20.
        # Manifest declares the slot active with a no_persist placeholder;
        # this swaps in the real persister rooted at storage_path. No-op
        # when storage_path is empty or Stage 20 isn't registered.
        try:
            from service.persist import install_file_persister

            install_file_persister(self._pipeline, self.storage_path)
        except Exception as exc:  # noqa: BLE001 — never block run on persist wiring
            logger.warning(
                f"[{self._session_id}] FilePersister install failed: {exc}"
            )

        # G2.5: install the PipelineResumeRequester into Stage 15.
        # Manifest declares the HITL slot active with the safe ``null``
        # requester placeholder; this swaps in the real requester
        # bound to the pipeline so an external /api/agents/{id}/hitl/
        # resume endpoint can satisfy paused requests via
        # pipeline.resume(token, decision). No-op when Stage 15 isn't
        # registered.
        try:
            from service.hitl import install_pipeline_resume_requester

            install_pipeline_resume_requester(self._pipeline)
        except Exception as exc:  # noqa: BLE001 — never block run on HITL wiring
            logger.warning(
                f"[{self._session_id}] PipelineResumeRequester install failed: {exc}"
            )

        logger.info(
            f"[{self._session_id}] Pipeline adopted + runtime attached: "
            f"preset={self._preset_name}, role={self._role.value}, "
            f"memory={'yes' if self._memory_manager else 'no'}, "
            f"working_dir={working_dir[:50]}"
        )

    @staticmethod
    def _make_llm_reflect_callback(api_key: str):
        """Create a legacy LLM reflection callback for GenyMemoryStrategy.

        .. deprecated:: cycle 20260421_4
            Since cycle 20260421_4, geny-executor's memory stage (s15)
            runs reflection natively via
            :class:`geny_executor.memory.ReflectionResolver` using
            ``APIConfig.memory_model``. This callback is retained for
            one cycle behind the ``APIConfig.use_legacy_reflect`` flag
            so operators can A/B-test regressions. It is expected to
            be removed in the next cycle.

        Returns an async callable: (input_text, output_text) -> List[Dict].
        Uses the Anthropic SDK directly (lightweight, no LangChain) with
        a hardcoded Haiku model.
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

    def _build_state_registry(self) -> Optional[Any]:
        """Return a fresh ``SessionRuntimeRegistry`` for this turn, or None.

        Turn-scoped by design (plan/02 §4): the snapshot + mutation buffer
        must not leak across turns. When ``state_provider`` is ``None`` the
        session is in classic mode and this returns ``None``; callers
        treat that as "skip hydrate/persist entirely".

        ``character_id`` defaults to ``session_id`` when the caller didn't
        supply one — MVP assumption of one creature per session. PR-X4
        will replace this with an owner-driven lookup once multi-character
        ownership lands.

        When ``manifest_selector`` was wired in, the registry carries a
        synthesized :class:`CharacterLike` (species / growth_tree_id /
        personality_archetype) so it can run the selector at hydrate
        time — the character data source (repo / admin UI) hasn't
        landed yet, so PR-X4-5 uses the session-scoped defaults.
        """
        if self._state_provider is None:
            return None
        from service.state import (
            DEFAULT_DECAY,
            SessionRuntimeRegistry,
        )
        character = None
        if self._manifest_selector is not None:
            character = _SessionCharacterLike(
                species=self._species,
                growth_tree_id=self._growth_tree_id,
                personality_archetype=self._personality_archetype,
            )
        return SessionRuntimeRegistry(
            session_id=self._session_id,
            character_id=self._character_id or self._session_id,
            owner_user_id=self._owner_username or "",
            provider=self._state_provider,
            catchup_policy=self._catchup_policy or DEFAULT_DECAY,
            manifest_selector=self._manifest_selector,
            character=character,
        )

    async def _hydrate_state_safely(
        self, registry: Any, state: Any,
    ) -> bool:
        """Best-effort ``registry.hydrate``. Returns True on success.

        A hydrate failure must not block the turn: stages simply won't
        see ``creature_state`` in ``state.shared``. Per plan/02 §4.3 the
        user response always takes priority over state observability.
        """
        try:
            await registry.hydrate(state)
            return True
        except Exception:
            logger.exception(
                f"[{self._session_id}] creature_state hydrate failed "
                "— running turn without state"
            )
            return False

    async def _pipeline_events_scoped(
        self, input_text: str, state: Any, hydrated: bool,
        *, attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Any]:
        """Yield events from ``pipeline.run_stream`` with the current-turn
        mutation buffer bound as a contextvar.

        Game tools (``feed`` / ``play`` / ``gift`` / ``talk``) retrieve
        the buffer via :func:`~service.state.current_mutation_buffer`;
        the bind must span exactly the ``run_stream`` iteration so the
        reset fires on normal completion, on exception, and on early
        consumer abandonment (``aclose()`` on this generator propagates
        into the ``finally``).

        A ``None`` token is used when hydrate failed or no buffer was
        installed — :func:`~service.state.reset_mutation_buffer` is
        tolerant of ``None``, so we avoid branching here.
        """
        from service.state import (
            CREATURE_STATE_KEY,
            MUTATION_BUFFER_KEY,
            SESSION_META_KEY,
            TURN_KIND_TRIGGER,
            TURN_KIND_USER,
            bind_creature_role,
            bind_mutation_buffer,
            reset_creature_role,
            reset_mutation_buffer,
            role_of,
        )
        # Plan/Phase02 §2.2 — classify the turn kind once per turn so
        # AffectTagEmitter (and the loneliness-drift logic) can branch
        # on user-vs-trigger semantics. Reuses ``_classify_input_role``
        # so we have a single source of truth: "internal_trigger" maps
        # to TURN_KIND_TRIGGER, everything else to TURN_KIND_USER.
        # ``assistant_dm`` (sub-worker / DM follow-ups) also collapse
        # to USER here — those carry user-equivalent affective intent.
        stm_role = _classify_input_role(input_text)
        turn_kind = TURN_KIND_TRIGGER if stm_role == "internal_trigger" else TURN_KIND_USER
        meta = state.shared.get(SESSION_META_KEY)
        if isinstance(meta, dict):
            meta["turn_kind"] = turn_kind
        else:
            # No registry hydrate ran (classic mode). Stash a minimal
            # meta so downstream stages can still read turn_kind without
            # NPE-ing on a missing dict.
            state.shared[SESSION_META_KEY] = {"turn_kind": turn_kind}

        token = None
        role_token = None
        if hydrated:
            buf = state.shared.get(MUTATION_BUFFER_KEY)
            if buf is not None:
                token = bind_mutation_buffer(buf)
            # Plan/Phase04 §4.2 — bind the current-turn creature role
            # alongside the buffer so game tools can read it without
            # touching ``state.shared``. The contextvar default is
            # VTuber, so omitting this bind would silently treat
            # workers as VTubers — pair it with the buffer bind.
            snap = state.shared.get(CREATURE_STATE_KEY)
            role_token = bind_creature_role(role_of(snap))

            # Plan/Phase02 §4 — loneliness drift: a TRIGGER turn on a
            # VTuber session decrements affection / familiarity by a
            # fixed amount, modeling the "talking to myself" tax. Apply
            # via the same mutation buffer the pipeline writes to so it
            # commits in one OCC cycle. Skip when no buffer / no
            # snapshot / non-VTuber / non-trigger turn.
            is_vtuber_creature = (
                buf is not None
                and snap is not None
                and getattr(snap, "character_role", "vtuber") == "vtuber"
            )
            if is_vtuber_creature and turn_kind == TURN_KIND_TRIGGER:
                _apply_loneliness_drift(buf)
            # Plan/Phase01 §3.2 — attention recovery: a USER turn on a
            # VTuber session refunds a chunk of the attention deficit
            # (hunger -= 3) and bumps familiarity by a tiny amount.
            # Mirrors the loneliness-drift gate so the two policies are
            # never both active on the same turn.
            elif is_vtuber_creature and turn_kind == TURN_KIND_USER:
                _apply_attention_recovery(buf)
        try:
            # Build the pipeline input. When attachments are present we
            # promote the bare string to the canonical dict shape that
            # geny-executor's ``MultimodalNormalizer`` consumes
            # (see ``s01_input.MultimodalNormalizer.normalize``). The
            # text branch — ``input_text`` alone — is kept for the
            # text-only fast path so we don't perturb existing
            # contracts when no attachments are sent.
            if attachments:
                pipeline_input: Any = {
                    "text": input_text,
                    "attachments": list(attachments),
                }
            else:
                pipeline_input = input_text
            async for event in self._pipeline.run_stream(pipeline_input, state):
                yield event
        finally:
            reset_mutation_buffer(token)
            reset_creature_role(role_token)

    async def _persist_state_safely(
        self, registry: Any, state: Any,
    ) -> None:
        """Best-effort ``registry.persist``. Swallows everything.

        ``StateConflictError`` falls to ``debug`` — these races are
        routine when the scheduled decay service and the pipeline
        contend for the same row. All other exceptions go to
        ``exception`` so ops still sees them, but the turn result
        (already yielded to the user) is not rewritten into an error.
        """
        from service.state.provider.interface import (
            StateConflictError,
        )
        try:
            await registry.persist(state)
        except StateConflictError as e:
            logger.debug(
                f"[{self._session_id}] creature_state persist conflict "
                f"(non-critical): {e}"
            )
        except Exception:
            logger.exception(
                f"[{self._session_id}] creature_state persist failed"
            )

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
        # Record input to short-term memory with proper role classification.
        # Internal triggers and inter-agent DMs are not "user" — see
        # _classify_input_role for the full rationale.
        if self._memory_manager:
            try:
                self._memory_manager.record_message(
                    _classify_input_role(input_text), input_text,
                )
            except Exception:
                logger.debug("Failed to record input message — non-critical", exc_info=True)

        # Stream pipeline and log events in real time
        accumulated_output = ""
        total_cost = 0.0
        iterations = 0
        success = True
        error_msg = None

        # Create PipelineState with session context
        from geny_executor.core.state import PipelineState as _PipelineState
        _state = _PipelineState(session_id=self._session_id)

        # Creature state hydrate (PR-X3-5). Skipped when no state_provider
        # is wired — classic session mode. A failed hydrate leaves
        # ``state.shared`` without ``creature_state``; stages check
        # presence via the registry key before reading.
        _state_registry = self._build_state_registry()
        _state_hydrated = False
        if _state_registry is not None:
            _state_hydrated = await self._hydrate_state_safely(
                _state_registry, _state,
            )

        # Publish the current-turn mutation buffer to game tools via a
        # contextvar (PR-X3-6). ``_pipeline_events_scoped`` binds the
        # buffer before yielding the first event and resets it when the
        # underlying stream closes — keeps the ``async for`` body and
        # the post-stream accumulation logic at their current
        # indentation while still being exception-safe.
        # ``attachments`` (image/file refs from the chat layer) are
        # forwarded as-is; ``_pipeline_events_scoped`` is responsible
        # for turning them into the canonical multimodal dict before
        # handing off to ``pipeline.run_stream``.
        attachments = kwargs.pop("attachments", None)
        async for event in self._pipeline_events_scoped(
            input_text, _state, _state_hydrated,
            attachments=attachments,
        ):
            event_type = event.type if hasattr(event, "type") else ""
            event_data = event.data if hasattr(event, "data") else {}

            # Log pipeline events to session_logger for WebSocket/SSE streaming
            if session_logger:
                if event_type == "tool.call_start":
                    session_logger.log_tool_use(
                        tool_name=event_data.get("name", "unknown"),
                        tool_input=event_data.get("input") or {},
                        tool_id=event_data.get("tool_use_id"),
                    )
                elif event_type == "tool.call_complete":
                    if event_data.get("is_error"):
                        name = event_data.get("name", "unknown")
                        duration_ms = event_data.get("duration_ms", 0)
                        session_logger.log(
                            level=LogLevel.TOOL_RESULT,
                            message=f"Tool {name} failed ({duration_ms}ms)",
                            metadata={
                                "tool_name": name,
                                "tool_id": event_data.get("tool_use_id"),
                                "is_error": True,
                                "duration_ms": duration_ms,
                            },
                        )
                elif event_type == "tool.execute_start":
                    count = event_data.get("count", 0)
                    tools = event_data.get("tools", [])
                    session_logger.log(
                        level=LogLevel.INFO,
                        message=f"Tool turn starting: {count} call(s)",
                        metadata={"tool_count": count, "tools": tools},
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
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_enter(
                        stage_name=stage_name,
                        stage_order=STAGE_ORDER.get(stage_name),
                        iteration=iteration or 0,
                    )
                elif event_type == "stage.exit":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_exit(
                        stage_name=stage_name,
                        stage_order=STAGE_ORDER.get(stage_name),
                        iteration=iteration or 0,
                    )
                elif event_type == "stage.bypass":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_bypass(
                        stage_name=stage_name,
                        stage_order=STAGE_ORDER.get(stage_name),
                        iteration=iteration or 0,
                        reason=event_data.get("reason"),
                    )
                elif event_type == "stage.error":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_error(
                        stage_name=stage_name,
                        error=event_data.get("error") or "unknown error",
                        stage_order=STAGE_ORDER.get(stage_name),
                        iteration=iteration or 0,
                    )
                elif event_type == "pipeline.start":
                    session_logger.log_stage_execution_start(
                        input_text=input_text,
                        thread_id=getattr(_state, "pipeline_id", None),
                        execution_mode="invoke",
                    )
                elif event_type == "pipeline.error":
                    err = event_data.get("error") or "unknown"
                    session_logger.log(
                        level=LogLevel.ERROR,
                        message=f"Pipeline error: {err}",
                        metadata={"source": "pipeline"},
                    )
                elif event_type in ("loop.escalate", "loop.error"):
                    signal = event_data.get("signal") or "unknown"
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_event(
                        event_type="loop_signal",
                        message=f"{event_type}: {signal}",
                        stage_name="loop",
                        stage_order=STAGE_ORDER.get("loop"),
                        iteration=iteration or 0,
                        data={"signal": signal},
                    )

                # ── G2.4: Tool Review (Stage 11) flag broadcast ──
                # Each reviewer-emitted flag gets its own log entry so
                # WebSocket / SSE consumers can render them inline
                # against the offending tool call. The summary
                # ``tool_review.completed`` lands once per turn for
                # dashboard counts (only when at least one flag fired).
                elif event_type == "tool_review.flag":
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    severity = event_data.get("severity", "info")
                    reviewer = event_data.get("reviewer", "unknown")
                    reason = event_data.get("reason", "")
                    session_logger.log_stage_event(
                        event_type="tool_review_flag",
                        message=f"[{severity}] {reviewer}: {reason}",
                        stage_name="tool_review",
                        stage_order=STAGE_ORDER.get("tool_review"),
                        iteration=iteration or 0,
                        data=dict(event_data),
                    )
                elif event_type == "tool_review.reviewer_error":
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    reviewer = event_data.get("reviewer", "unknown")
                    err = event_data.get("error", "unknown error")
                    session_logger.log_stage_event(
                        event_type="tool_review_error",
                        message=f"reviewer {reviewer} raised: {err}",
                        stage_name="tool_review",
                        stage_order=STAGE_ORDER.get("tool_review"),
                        iteration=iteration or 0,
                        data=dict(event_data),
                    )
                elif event_type == "tool_review.completed":
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    flags = event_data.get("flags", 0)
                    if flags > 0:
                        session_logger.log_stage_event(
                            event_type="tool_review_summary",
                            message=f"tool_review: {flags} flag(s) raised this turn",
                            stage_name="tool_review",
                            stage_order=STAGE_ORDER.get("tool_review"),
                            iteration=iteration or 0,
                            data=dict(event_data),
                        )

                # ── G2.5: HITL (Stage 15) request / decision broadcast ──
                # ``hitl.request`` is the signal the frontend modal listens
                # for: token + reason + severity + payload. ``hitl.decision``
                # closes the loop. ``hitl.timeout`` lands when the timeout
                # policy fires.
                elif event_type == "hitl.request":
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    token = event_data.get("token", "")
                    reason = event_data.get("reason", "")
                    severity = event_data.get("severity", "warn")
                    session_logger.log_stage_event(
                        event_type="hitl_request",
                        message=f"approval requested ({severity}): {reason}",
                        stage_name="hitl",
                        stage_order=STAGE_ORDER.get("hitl"),
                        iteration=iteration or 0,
                        data=dict(event_data),
                    )
                    logger.info(
                        f"[{self._session_id}] HITL request awaiting decision "
                        f"(token={token[:8]}…, severity={severity}, reason={reason})"
                    )
                elif event_type == "hitl.decision":
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    decision = event_data.get("decision", "unknown")
                    session_logger.log_stage_event(
                        event_type="hitl_decision",
                        message=f"approval resolved: {decision}",
                        stage_name="hitl",
                        stage_order=STAGE_ORDER.get("hitl"),
                        iteration=iteration or 0,
                        data=dict(event_data),
                    )
                elif event_type == "hitl.timeout":
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    verdict = event_data.get("verdict", "unknown")
                    session_logger.log_stage_event(
                        event_type="hitl_timeout",
                        message=f"approval timed out (verdict={verdict})",
                        stage_name="hitl",
                        stage_order=STAGE_ORDER.get("hitl"),
                        iteration=iteration or 0,
                        data=dict(event_data),
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
                # `text.delta` events feed `accumulated_output` in real
                # time and are the source of truth. Older executor
                # builds (≤ 0.20.0) sent a 500-char preview as
                # `result`, which would silently truncate long
                # responses if we trusted it blindly. Only accept
                # `result` when it is at least as long as what we
                # already streamed — a safe upgrade once the executor
                # patch (>= 0.20.1) ships full text.
                streamed_result = event_data.get("result") or ""
                if len(streamed_result) >= len(accumulated_output):
                    accumulated_output = streamed_result
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
            session_logger.log_stage_execution_complete(
                success=success,
                total_iterations=iterations,
                final_output=accumulated_output[:500] if accumulated_output else None,
                total_duration_ms=duration_ms,
                stop_reason="pipeline_complete" if success else (error_msg or "error"),
            )

        # Record the assistant's reply into STM before the LTM write.
        # Without this the transcript only contains user-side messages,
        # so retrieval layers (session_summary, keyword, vector) cannot
        # see what the assistant just said — which is exactly what broke
        # trigger-driven continuity in cycle 20260420_8 Bug 2b.
        if self._memory_manager and success and accumulated_output.strip():
            try:
                self._memory_manager.record_message(
                    "assistant",
                    accumulated_output[:10000],
                )
            except Exception:
                logger.debug(
                    "Failed to record assistant message — non-critical",
                    exc_info=True,
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

        # Creature state persist (PR-X3-5). Runs even on pipeline error —
        # some stages may have produced mutations before the failure and
        # dropping them would silently rewind progress. Persist only when
        # hydrate succeeded; otherwise there is no baseline to apply
        # against.
        if _state_registry is not None and _state_hydrated:
            await self._persist_state_safely(_state_registry, _state)

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
        # Record input to short-term memory with proper role classification.
        # See _classify_input_role for why triggers / inter-agent DMs are
        # not "user".
        if self._memory_manager:
            try:
                self._memory_manager.record_message(
                    _classify_input_role(input_text), input_text,
                )
            except Exception:
                logger.debug("Failed to record input message — non-critical", exc_info=True)

        accumulated_output = ""
        total_cost = 0.0
        iterations = 0
        success = True

        # Create PipelineState with session context
        from geny_executor.core.state import PipelineState as _PipelineState
        _state = _PipelineState(session_id=self._session_id)

        # Creature state hydrate (PR-X3-5, mirrors _invoke_pipeline).
        _state_registry = self._build_state_registry()
        _state_hydrated = False
        if _state_registry is not None:
            _state_hydrated = await self._hydrate_state_safely(
                _state_registry, _state,
            )

        # Bind mutation buffer contextvar for game tools — see
        # _pipeline_events_scoped for the rationale.
        async for event in self._pipeline_events_scoped(
            input_text, _state, _state_hydrated,
        ):
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
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_enter(
                        stage_name=stage_name,
                        stage_order=STAGE_ORDER.get(stage_name),
                        iteration=iteration or 0,
                    )
                elif event_type == "stage.exit":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_exit(
                        stage_name=stage_name,
                        stage_order=STAGE_ORDER.get(stage_name),
                        iteration=iteration or 0,
                    )
                elif event_type == "stage.bypass":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_bypass(
                        stage_name=stage_name,
                        stage_order=STAGE_ORDER.get(stage_name),
                        iteration=iteration or 0,
                        reason=event_data.get("reason"),
                    )
                elif event_type == "stage.error":
                    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_error(
                        stage_name=stage_name,
                        error=event_data.get("error") or "unknown error",
                        stage_order=STAGE_ORDER.get(stage_name),
                        iteration=iteration or 0,
                    )
                elif event_type == "pipeline.start":
                    session_logger.log_stage_execution_start(
                        input_text=input_text,
                        thread_id=getattr(_state, "pipeline_id", None),
                        execution_mode="astream",
                    )
                elif event_type == "pipeline.error":
                    err = event_data.get("error") or "unknown"
                    session_logger.log(
                        level=LogLevel.ERROR,
                        message=f"Pipeline error: {err}",
                        metadata={"source": "pipeline"},
                    )
                elif event_type in ("loop.escalate", "loop.error"):
                    signal = event_data.get("signal") or "unknown"
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    session_logger.log_stage_event(
                        event_type="loop_signal",
                        message=f"{event_type}: {signal}",
                        stage_name="loop",
                        stage_order=STAGE_ORDER.get("loop"),
                        iteration=iteration or 0,
                        data={"signal": signal},
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
                # See _invoke_pipeline for the rationale: prefer the
                # streaming accumulation over a possibly preview-
                # truncated `result` field on legacy executor builds.
                streamed_result = event_data.get("result") or ""
                result_text = (
                    streamed_result
                    if len(streamed_result) >= len(accumulated_output)
                    else accumulated_output
                )
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
            session_logger.log_stage_execution_complete(
                success=success,
                total_iterations=iterations,
                final_output=accumulated_output[:500] if accumulated_output else None,
                total_duration_ms=duration_ms,
                stop_reason="pipeline_stream_complete",
            )

        # Record the assistant's streamed reply into STM before the LTM
        # write — see _invoke_pipeline for the full rationale.
        if self._memory_manager and success and accumulated_output.strip():
            try:
                self._memory_manager.record_message(
                    "assistant",
                    accumulated_output[:10000],
                )
            except Exception:
                logger.debug(
                    "Failed to record assistant message — non-critical",
                    exc_info=True,
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

        # Creature state persist (PR-X3-5). Runs after the stream has
        # been fully consumed. If the consumer abandons the generator
        # early, this line is reached only when the generator is
        # ``aclose()``'d — persist of mutations that never got to fire
        # is intentionally lossy here (no baseline guarantee).
        if _state_registry is not None and _state_hydrated:
            await self._persist_state_safely(_state_registry, _state)

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
            session_logger.log_stage_execution_start(
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
                session_logger.log_stage_execution_complete(
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
            session_logger.log_stage_execution_start(
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
                session_logger.log_stage_execution_complete(
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
            from service.sessions.store import get_session_store
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

    async def load_creature_state_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return a JSON-friendly snapshot of the session's CreatureState.

        Reads directly from the attached ``state_provider`` (SQLite /
        in-memory), so the value reflects the most recently *persisted*
        turn. Snapshots are cheap (single-row load on a keyed index)
        and the provider handles concurrent reads safely, so it's fine
        to call this on every UI refresh.

        Returns ``None`` when:
        - The session has no ``state_provider`` (classic / non-Tamagotchi
          session — no creature state exists).
        - The provider's ``load`` raises (swallowed with a debug log).

        Callers must treat ``None`` as "no creature state" rather than
        "error" — the UI path decides whether to hide the panel
        entirely or show a placeholder.

        Cycle 20260422_5 (X7) — see dev_docs/20260422_5/progress/*.
        """
        if self._state_provider is None:
            return None
        try:
            snapshot = await self._state_provider.load(
                self._character_id or self._session_id,
                owner_user_id=self._owner_username or "",
            )
        except Exception:
            logger.debug(
                "[%s] load_creature_state_snapshot: provider load failed; "
                "returning None",
                self._session_id,
                exc_info=True,
            )
            return None

        bond = snapshot.bond
        vitals = snapshot.vitals
        progression = snapshot.progression
        mood_dict = snapshot.mood.as_dict()

        last_interaction_iso: Optional[str] = None
        if snapshot.last_interaction_at is not None:
            try:
                last_interaction_iso = snapshot.last_interaction_at.isoformat()
            except Exception:
                last_interaction_iso = None

        try:
            last_tick_iso = snapshot.last_tick_at.isoformat()
        except Exception:
            last_tick_iso = None

        return {
            "character_id": snapshot.character_id,
            "owner_user_id": snapshot.owner_user_id,
            "mood": mood_dict,
            "mood_dominant": snapshot.mood.dominant(threshold=0.15),
            "bond": {
                "affection": float(bond.affection),
                "trust": float(bond.trust),
                "familiarity": float(bond.familiarity),
                "dependency": float(bond.dependency),
            },
            "vitals": {
                "hunger": float(vitals.hunger),
                "energy": float(vitals.energy),
                "stress": float(vitals.stress),
                "cleanliness": float(vitals.cleanliness),
            },
            "progression": {
                "age_days": int(progression.age_days),
                "life_stage": progression.life_stage,
                "xp": int(progression.xp),
                "milestones": list(progression.milestones),
                "manifest_id": progression.manifest_id,
            },
            "last_interaction_at": last_interaction_iso,
            "last_tick_at": last_tick_iso,
            "recent_events": list(snapshot.recent_events[-10:]),
        }

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
