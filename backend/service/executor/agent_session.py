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
from service.utils.background import spawn_background
import json
from logging import getLogger
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Tuple,
)

if TYPE_CHECKING:  # quoted-annotation only — no import cycle at runtime
    from service.memory.manager import SessionMemoryManager

from service.sessions.models import (
    MCPConfig,
    SessionInfo,
    SessionRole,
    SessionStatus,
)
from service.executor.session_freshness import SessionFreshness, FreshnessStatus
from service.logging.session_logger import get_session_logger, SessionLogger, LogLevel, STAGE_ORDER

logger = getLogger(__name__)

# Memory-hygiene checks run on their OWN 1-wide pool — loop-independent
# (fire-and-forget submit survives run_coro_sync's short-lived loops) and,
# critically, DISTINCT from sync_async_bridge's single-worker side-effect
# pool, whose worker can be the very thing driving the note write that
# triggered the check (circular wait = the 2026-07-25 prod deadlock).
_HYGIENE_POOL = None


def _hygiene_pool():
    global _HYGIENE_POOL
    if _HYGIENE_POOL is None:
        import concurrent.futures
        _HYGIENE_POOL = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mem-hygiene")
    return _HYGIENE_POOL


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

# Hard cap on the best-effort end-of-session memory flush in ``cleanup``.
# The flush runs off the loop on a shared single-worker pool; this bound
# guarantees a saturated pool can never strand the resource-release steps
# that follow (see ``cleanup``). Unflushed STM survives on disk, so a
# timeout is safe.
_CLEANUP_FLUSH_TIMEOUT_S = 20.0


def _host_keeps_sessions_awake() -> bool:
    """The host-wide "leave sessions running" policy, read live.

    Consulted on every idle scan rather than cached, so switching it in
    settings takes effect on the next tick instead of the next restart —
    which is the difference between a setting and a build flag.

    Falls back to the environment (and finally to False) so a host whose
    config store is unavailable behaves exactly as it did before the
    setting existed.
    """
    try:
        from service.config import get_config_manager
        from service.config.sub_config.general.session_lifecycle_config import (
            SessionLifecycleConfig,
        )

        cfg = get_config_manager().load_config(SessionLifecycleConfig)
        if cfg is not None:
            return bool(cfg.keep_sessions_awake)
    except Exception:  # noqa: BLE001 — a policy read must never fail a turn
        pass
    raw = os.environ.get("GENY_KEEP_SESSIONS_AWAKE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")

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


def _extract_executor_error_meta(exc: BaseException) -> Tuple[Optional[str], str]:
    """Pull the structured ``ExecutorErrorCode`` value off an executor
    exception, returning ``(code_str, exception_type_str)``.

    ``code_str`` is ``None`` when the exception isn't a
    :class:`GenyExecutorError` subclass (e.g. raw ``RuntimeError`` /
    ``ValueError`` slipped past). ``exception_type_str`` is the fully
    qualified class name and is always populated.

    Defensive on the import — the executor pin is ``>=2.1.0`` but a
    plain string fallback keeps the catch-block robust against future
    refactors.
    """
    exc_type = f"{type(exc).__module__}.{type(exc).__name__}"
    code_str: Optional[str] = None
    try:
        from geny_executor import GenyExecutorError  # noqa: WPS433 — lazy import

        if isinstance(exc, GenyExecutorError):
            code_attr = getattr(exc, "code", None)
            if code_attr is not None:
                code_str = getattr(code_attr, "value", str(code_attr))
    except Exception:  # noqa: BLE001 — diagnostics must never crash the catch block
        pass
    return code_str, exc_type


# ── provider error-envelope bridge ──────────────────────────────────
#
# A provider failure arrives as a first-class ``api.error`` event
# carrying a code, a category and the vendor's own message. The helper
# below turns it into the sentence the user sees in the session log —
# most importantly the Korean auth-expired message, which names the
# next step instead of printing a 401.


# Human-readable message shown to the end user when the Claude CLI
# reports an authentication failure. Surfaces the actionable next step
# ("re-login in the settings card") instead of the raw error text.
_AUTH_EXPIRED_MESSAGE = (
    "Claude Code 인증이 만료됐어요. "
    "설정 → LLM 백엔드 → Claude Code 카드의 "
    "‘다시 로그인 / Sign in’ 을 눌러 인증을 갱신해주세요."
)

# api.error codes / categories that mean "the CLI's credentials are
# bad" — the case the old assembler patch special-cased in Korean.
_AUTH_ERROR_CODES = frozenset({
    "exec.cli.auth_failed",
    "exec.api.auth.invalid_key",
    "exec.api.auth.expired",
})
_AUTH_ERROR_CATEGORIES = frozenset({"auth", "cli_auth_failed"})


def _friendly_api_error_message(data: Dict[str, Any]) -> str:
    """Turn an ``api.error`` event payload ({code, category, provider,
    message, cli_version?}) into the human-friendly line the old
    ``llm_patches`` assembler patch produced for ``is_error`` result
    envelopes."""
    code = str(data.get("code") or "")
    category = str(data.get("category") or "")
    message = str(data.get("message") or "").strip()
    if code in _AUTH_ERROR_CODES or category in _AUTH_ERROR_CATEGORIES:
        suffix = f" (원본: {message})" if message else ""
        return _AUTH_EXPIRED_MESSAGE + suffix
    provider = str(data.get("provider") or "")
    label = "Claude Code" if provider == "geny_claude_code" else (provider or "LLM")
    return f"{label} API 에러 [{code or category or 'unknown'}]: {message or 'unknown'}"


def _tool_result_text(raw_result: Any) -> Optional[str]:
    """Normalise an ``api.tool_result`` ``content`` payload into the
    string shape ``SessionLogger.log_tool_result`` expects. The CLI
    emits both plain strings and ``content_block`` lists here."""
    if raw_result is None:
        return None
    if isinstance(raw_result, str):
        return raw_result
    if isinstance(raw_result, list):
        parts: List[str] = []
        for c in raw_result:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(str(c.get("text", "")))
            elif isinstance(c, dict):
                parts.append(json.dumps(c, ensure_ascii=False))
            else:
                parts.append(str(c))
        return "\n".join(parts) if parts else None
    try:
        return json.dumps(raw_result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(raw_result)


def _bridge_cli_stream_event(
    session_logger: Any,
    event_type: str,
    event_data: Dict[str, Any],
) -> None:
    """Bridge one ``api.error`` envelope to the SessionLogger.

    This used to bridge tool events too — ``api.cli_tool_call`` and
    ``api.tool_result {source: "cli"}`` — because a CLI backend ran its
    own loop and its tool calls never reached Stage 10. No backend does
    that any more (executor 2.68.0): every tool call goes through Stage
    10, which already logs it via ``tool.call_start`` /
    ``tool.call_complete``, so bridging would double-render it.

    What is left is the error envelope, which is provider-shaped and has
    no Stage-10 equivalent: a CLI auth failure has to become a sentence
    the user can act on.

    Best-effort by contract — observability must never break the turn.
    """
    try:
        if event_type == "api.error":
            session_logger.log(
                level=LogLevel.ERROR,
                message=_friendly_api_error_message(event_data),
                metadata={
                    "source": "api",
                    "error_code": event_data.get("code"),
                    "category": event_data.get("category"),
                    "provider": event_data.get("provider"),
                    "cli_version": event_data.get("cli_version"),
                },
            )
    except Exception:  # noqa: BLE001 — observability must never break execution
        logger.debug(
            "API error-envelope bridge failed for %s (continuing)",
            event_type, exc_info=True,
        )


_DEFAULT_WORKER_PROMPT = """\
You are an autonomous AI agent. Complete the user's task.

End your response with [TASK_COMPLETE] when finished, [CONTINUE: next action] if
more work remains, or [BLOCKED: reason] if you cannot proceed."""

# Loop-control signals only — the model already decides when to use tools and how
# to decompose work; we just give it the pipeline's continue/complete vocabulary.
_ADAPTIVE_PROMPT = """\
## Completion Signals

End each turn with [CONTINUE: next step] if more work remains, [TASK_COMPLETE] when
the whole task is done, or [BLOCKED: reason] if you cannot proceed. A simple ask can
be a single response ending in [TASK_COMPLETE]."""

_DEFAULT_VTUBER_PROMPT = """\
You are a friendly AI VTuber assistant. Engage in natural conversation
while being helpful and knowledgeable.

Do quick tasks yourself with your own tools — a status check, a quick
command, a short lookup all finish in a turn or two.

Keep responses conversational and natural."""
# NOTE: delegation guidance ("hand off to your sub-worker") deliberately
# does NOT live here — it is appended per-session via the sub-worker
# notice ONLY after the companion sub-agent actually spawned (see
# agent_session_manager). A session without a companion must never be
# told it has one: models narrate delegation they cannot perform.


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


class _SessionScopedCronStore:
    """Wraps the shared cron store so every cron an agent self-schedules is
    stamped with its owner session id (``_session_id`` in the job payload).

    Crons are per-agent: the executor's ``CronCreate`` tool builds a bare
    ``CronJob`` and never records who created it, so before this a session's
    crons couldn't be found — and weren't deleted with the session (a runaway
    1-minute cron outlived its agent and spun ~29k failed tasks). Stamping the
    owner here makes ``db_delete_crons_by_session`` reliable. Every other store
    method passes straight through to the real store.
    """

    def __init__(self, inner, session_id: str) -> None:
        self._inner = inner
        self._sid = session_id

    async def put(self, job):  # the CronCreate tool's write path
        try:
            payload = getattr(job, "payload", None)
            if isinstance(payload, dict):
                payload.setdefault("_session_id", self._sid)
        except Exception:  # noqa: BLE001 — stamping must never block cron create
            pass
        return await self._inner.put(job)

    def __getattr__(self, name):  # get / list / delete / mark_fired / update_status
        return getattr(self._inner, name)


#: Ceiling on the background memory warm-up. The session is already live and
#: keyword search covers the gap, so this is not "how long a wake takes" — it
#: is how long `memory_ready` may stay unset before every turn starts paying
#: the readiness gate's full timeout instead.
_MEMORY_WARMUP_TIMEOUT_S = 90.0


class AgentSession:
    """geny-executor Pipeline-based agent session.

    Key architecture:
        - geny-executor Pipeline: 21-stage execution engine, built
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
        #: How much context this session's ROUTE can hold, in tokens, or
        #: ``None`` when no hop could say. Sizes proactive compaction and the
        #: Stage-4 headroom guard; ``None`` keeps the library's 200k, which
        #: is an assumption and is logged as one.
        context_window_budget: Optional[int] = None,
        #: Spend ceiling for ONE turn, in USD, or ``None`` for no ceiling.
        #: Enforced by the Stage-16 cost dimension and the Stage-4 guard —
        #: both of which only see spend a backend actually reports, so a
        #: subscription account (which reports none) is never stopped by it.
        cost_budget_usd: Optional[float] = None,
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
        gapt_sandbox: Optional[Any] = None,
        resolved_credentials: Optional[Any] = None,
        primary_provider: Optional[str] = None,
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
        # Optional GAPT workspace sandbox (executor SandboxHandle). When set,
        # _build_pipeline passes it to attach_runtime(sandbox=) so this
        # session's TOOLS execute inside the workspace container.
        self._gapt_sandbox = gapt_sandbox
        # The owner's resolved Stage-6 credential bundle + primary provider, kept
        # so (a) ToolContext.extras can carry them for ad-hoc SubAgentSpawn /
        # one-shot Agent sub-workers, and (b) the SubAgentManager credentials_provider
        # callback can read them off the live agent (integrity audit 2026-06-25).
        self._resolved_credentials = resolved_credentials
        self._primary_provider = primary_provider
        self._model_name = model_name
        self._max_turns = max_turns
        self._timeout = timeout
        self._system_prompt = system_prompt
        self._persona_provider = persona_provider
        self._lifecycle_bus = lifecycle_bus
        self._env_vars = env_vars or {}
        # NOTE (audit 2026-06-17, C7): ``mcp_config`` is stored but the
        # SDK pipeline never reads ``self._mcp_config`` — for env-driven
        # sessions the MCP servers come from the manifest's
        # ``tools.mcp_servers`` (Stage 10), built by
        # ``Pipeline.from_manifest_async``. The legacy
        # ``build_session_mcp_config`` / tool-preset ``mcp_servers`` chain
        # that feeds this kwarg is therefore inert for SDK sessions; the
        # kwarg is kept for create() signature stability. Configure MCP
        # per environment, not via the tool preset.
        self._mcp_config = mcp_config
        self._max_iterations = max_iterations
        self._context_window_budget = context_window_budget
        self._cost_budget_usd = cost_budget_usd

        # Role
        self._role = role

        # Per-session keep-awake choice. None = follow role + host policy;
        # see :attr:`_is_always_on`. Restored from the store record when a
        # session is rehydrated, so a pin survives eviction and restart.
        self._always_on_override: Optional[bool] = None

        # E.1 (cycle 20260426_1) — between-turn runtime refresh queue.
        # Set via :meth:`queue_runtime_refresh` (admin endpoint), drained
        # at the top of :meth:`invoke` / :meth:`astream`. ``None`` = no
        # refresh pending; otherwise one of {permissions, hooks, all}.
        self._pending_runtime_refresh: Optional[str] = None

        # Preset (determined during _build_pipeline)
        self._workflow_id = workflow_id  # kept for SessionInfo backward compat
        self._preset_name: str = "default"
        self._tool_preset_id = tool_preset_id
        self._owner_username = owner_username

        # Storage path (set during create())
        self._storage_path: Optional[str] = None

        # Internal components
        self._pipeline: Optional[Any] = None  # geny-executor Pipeline
        # Per-session skill hot-reload watcher (audit L1). Held so its
        # polling thread is stopped in cleanup() instead of leaking.
        self._skill_watcher: Optional[Any] = None

        # Environment / memory wiring (Phase 3 — env_id pre-builds Pipeline,
        # memory_config is retained for Phase 4 attachment + observability).
        self._env_id: Optional[str] = env_id
        self._memory_config: Optional[Dict[str, Any]] = memory_config
        self._prebuilt_pipeline: Optional[Any] = prebuilt_pipeline
        # Set when the bound environment's manifest is edited while this
        # session is live; the manager rebuilds the pipeline from the fresh
        # manifest on the next access (ensure_session_live) — see
        # AgentSessionManager.propagate_env_update.
        self._needs_manifest_reload: bool = False

        # Memory manager (initialized lazily once storage_path is available)
        self._memory_manager: Optional["SessionMemoryManager"] = None
        # Long-term-memory readiness. Set when the background vector warm-up
        # (which also forces the notes-store / synapse vault load) finishes —
        # or immediately when there is nothing to warm. Consumers:
        #   • ThinkingTrigger defers self-initiated speech until ready (a
        #     just-rehydrated persona greeting its owner like a stranger),
        #   • execute_command bounded-waits + injects a warm-up notice so an
        #     early user turn never asserts "no record" from partial memory.
        self._memory_ready: asyncio.Event = asyncio.Event()
        self._vector_init_task: Optional[asyncio.Task] = None
        # geny-executor MemoryProvider — built from LTMConfig + storage_path.
        # Single source of truth for vault layout and vector indexing
        # going forward. The legacy SessionMemoryManager stays around for
        # the archive / curation business logic; new search/retrieval
        # paths route through this provider's curated/notes/vector
        # handles instead.
        self._memory_provider: Optional[Any] = None
        # The shared MemoryHooks instance (built in `_build_pipeline`)
        # carries every retrieval policy + business callback. The same
        # object is attached to the provider via `set_hooks` and passed
        # into `MemoryAwareRetriever`; `_install_memory_hooks` mutates
        # it in place when the host installs business callbacks.
        self._memory_hooks: Optional[Any] = None
        # Memory subsystem events that fire *before* the session logger
        # is created (provider init is one boot-tier earlier than
        # session_logger creation in agent_session_manager). The list is
        # drained into the logger by `flush_pending_memory_events()`
        # right after the manager wires the logger up — that way the
        # first chat broadcast already sees the boot-time events on the
        # frontend's VTuber LOGS panel.
        self._pending_memory_events: List[Dict[str, Any]] = []
        # SendUserFile delivery channel (workspace-canvas P1). Built with the
        # tool extras at pipeline construction; None until then (or when the
        # session has no storage_path).
        self._user_file_channel = None
        # Per-session cursor for the chat broadcast handler: tracks how
        # many `MEMORY` log entries have already been forwarded to the
        # frontend. The legacy `file_changes` pipe uses
        # `pre_exec_cursor` (cache length captured *just before* the
        # turn runs), but that misses every memory event that landed
        # earlier — most notably the `provider_initialized` row that
        # fires inside `initialize()` before the session ever runs a
        # turn. Tracking the cursor on the session itself lets the
        # broadcast handler advance it from 0 on the first call and
        # from the cached value on every later one.
        self._memory_events_cursor: int = 0

        # Execution state
        self._initialized = False
        self._error_message: Optional[str] = None
        # Last error's structured code (since executor 2.1.0).
        # ``GenyExecutorError.code.value`` (e.g. ``"exec.cli.auth_failed"``)
        # when the surfaced exception was one the executor classified;
        # ``None`` for plain ``RuntimeError`` / ``ValueError``. Surfaces
        # via the SSE error payload and the session-status API so the
        # frontend can render via i18n key (``executor.<code>``) instead
        # of the raw English message.
        self._error_code: Optional[str] = None
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

        # Cycle 20260430_1 P0-1 — turn-scoped flag set by
        # ``SendDirectMessageInternalTool`` when a paired Sub-Worker
        # explicitly delivers a ``[SUB_WORKER_RESULT]`` payload to its
        # VTuber during this invoke. ``_notify_linked_vtuber`` reads it
        # to suppress the auto-fallback notification (which would
        # otherwise clobber the structured payload with a "Task finished
        # with no output." line). Reset at every ``invoke`` / ``astream``
        # entry so the flag never leaks across turns.
        self._explicit_subworker_report_sent: bool = False

        # Cycle 20260501_1 B — share the LLM client + memory model cfg
        # built during ``_build_pipeline`` so out-of-pipeline tool
        # calls (memory_distill, future memory tools, etc.) can reuse
        # the SAME client and the SAME memory_cfg the s18 ReflectionResolver
        # uses. This preserves cycle 20260421_4's "single client, no
        # credential drift" promise across stage and tool surfaces.
        # Both fields are populated by `_build_pipeline` and remain
        # stable for the session's lifetime; consumers must treat them
        # as read-only.
        self._llm_client_handle: Optional[Any] = None
        self._memory_cfg_handle: Optional[Any] = None

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
        # B.1 (cycle 20260426_1): With env-driven pipelines this field is
        # advisory only — "turn" reduces to "one ``invoke`` call" (one
        # chat message), which is governed by the chat layer, not the
        # executor pipeline. The per-invoke iteration cap is
        # ``max_iterations`` and is enforced via
        # ``_apply_session_limits_to_pipeline``.
        return self._max_turns

    @property
    def timeout(self) -> float:
        # B.1 (cycle 20260426_1): enforced at the chat-execution layer
        # via ``asyncio.wait_for(agent.invoke(...), timeout=...)`` —
        # see ``service/execution/agent_executor.py:_execute_core``.
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
    def llm_client(self) -> Optional[Any]:
        """Shared Anthropic SDK fallback client for out-of-pipeline tool
        calls only (``memory_distill`` narrative, future memory tools
        that need a raw SDK handle outside Stage 6).

        Originally — cycle 20260421_4 — this client was *also* injected
        into ``state.llm_client`` via ``Pipeline.attach_runtime``. That
        path pre-empted the per-Environment Stage-6 provider choice:
        the manifest could say ``geny_router`` but every session
        would hit ``api.anthropic.com`` because the executor's
        ``_resolve_llm_client`` honours the attach-time client first.
        The injection was removed (see ``_build_pipeline``); this
        handle is now an *out-of-pipeline* helper only. Stage 6 is
        wired strictly from the manifest's provider + the
        ``CredentialBundle``.

        Returns ``None`` before ``_build_pipeline`` runs, or when the
        session has no Anthropic key configured at all.
        """
        return self._llm_client_handle

    @property
    def memory_model_cfg(self) -> Optional[Any]:
        """Live ``ModelConfig`` used by s18_memory's reflection LLM call.

        Mirrors ``APIConfig.memory_model || anthropic_model`` resolved
        at session-build time. Out-of-pipeline tool calls that want
        to use the *memory* model (rather than the main model) read
        this property — guarantees same cfg as the in-pipeline
        reflection.
        """
        return self._memory_cfg_handle

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
        """Whether this session should never be put to sleep or torn down.

        Three answers, in order of authority:

        1. **The user's own choice for this session** (``always_on``).
           Explicit beats implicit — a session someone pinned stays up
           even if the host default says otherwise, and one they
           un-pinned can still be reclaimed even while the host is
           keeping everything else awake.
        2. **The role rule.** A VTuber is a conversational persona bound
           to its CLI process; an idle timeout would break that binding.
        3. **The host policy** (Session Lifecycle → keep sessions awake).
           Read live so flipping the setting takes effect on the next
           idle tick, not the next restart.
        """
        if self._always_on_override is not None:
            return self._always_on_override
        if self._role == SessionRole.VTUBER:
            return True
        return _host_keeps_sessions_awake()

    @property
    def always_on_override(self) -> Optional[bool]:
        """The user's explicit choice, or None to follow host policy."""
        return self._always_on_override

    def set_always_on(self, value: Optional[bool]) -> None:
        """Pin this session awake (True), release it (False), or hand it
        back to the host policy (None)."""
        self._always_on_override = value

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
        spawn_background(
            self._emit_revived(kind=kind),
            name=f"session.emit_revived:{kind}",
        )

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
            # Cycle 20260503_5 — pass ``session_id`` at construction
            # so the conversation/dm/daily archivers built inside
            # ``initialize()`` get a real id in their slugs. Without
            # it they fell back to "unknown" and every file landed
            # at ``conversations/unknown__*.md`` until (and unless)
            # ``set_database`` was called.
            self._memory_manager = SessionMemoryManager(
                sp, session_id=self._session_id or "",
            )
            self._memory_manager.initialize()
            logger.info(f"[{self._session_id}] SessionMemoryManager initialized at {sp}")
        except Exception as e:
            logger.warning(f"[{self._session_id}] Failed to initialize memory: {e}")
            self._memory_manager = None

    async def _init_memory_provider(self) -> None:
        """Build the executor's `MemoryProvider` for this session.

        Uses :func:`service.memory.provider_bridge.build_memory_provider`
        which derives the composite config from the live `LTMConfig`
        (embedding provider/key/model + curated flags) and the
        session's storage path. Failures land at WARNING — the
        provider stays optional, the legacy `SessionMemoryManager`
        path keeps working.
        """
        sp = self.storage_path
        if not sp:
            return
        try:
            from service.memory.provider_bridge import build_memory_provider

            self._memory_provider = await build_memory_provider(
                session_id=self._session_id or "",
                storage_path=sp,
                username=self._owner_username,
            )
            descriptor = self._memory_provider.descriptor
            # Plug the live provider into the session manager so its
            # inline ``_vector_*`` / ``_stm_*`` / ``_ltm_*`` /
            # ``_notes_*`` / ``_index_*`` helpers can route every
            # operation through the composite's handles. Without this
            # the manager stays in disabled mode and Stage 2 retrieval
            # silently returns nothing.
            if self._memory_manager is not None:
                try:
                    self._memory_manager.set_memory_provider(self._memory_provider)
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "[%s] memory_manager.set_memory_provider failed",
                        self._session_id, exc_info=True,
                    )
                # NOTE: ``_install_memory_hooks`` USED to be called here,
                # but at this point in the bootstrap ``self._memory_hooks``
                # is still ``None`` (the bag is created later inside
                # ``_build_pipeline``). The post-pipeline call there is
                # the load-bearing one; keeping the call here as well
                # would just be a guaranteed no-op.
                # Path-A: ensure stage 18's `_drive_provider` and stage 2
                # context retriever see the same provider the manager and
                # archivers use. Without this attach, `_drive_provider`
                # runs with `provider=None` and `transcripts/session.jsonl`
                # never gets a single user/assistant line.
                try:
                    self._attach_provider_to_pipeline_stages()
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "[%s] direct stage attach failed",
                        self._session_id, exc_info=True,
                    )
            logger.info(
                "[%s] MemoryProvider initialized: %s",
                self._session_id,
                descriptor.name,
            )
            # Surface the same fact on the per-session log channel so
            # the VTuber LOGS panel can show it in real time. Routed
            # through `record_memory_event` so the event is parked on
            # `_pending_memory_events` if the session logger has not
            # been provisioned yet (boot ordering — see
            # agent_session_manager.create_agent which wires the
            # logger *after* AgentSession.initialize() returns).
            layers = sorted(layer.value for layer in descriptor.layers)
            embedding = descriptor.embedding
            self.record_memory_event(
                event_type="provider_initialized",
                message=(
                    f"MemoryProvider ready: {descriptor.name} "
                    f"(layers={','.join(layers)})"
                ),
                source="Memory",
                backend="filesystem",
                extra={
                    "layers": layers,
                    "embedding": (
                        {
                            "provider": embedding.provider,
                            "model": embedding.model,
                            "dimension": embedding.dimension,
                        }
                        if embedding is not None
                        else None
                    ),
                },
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "[%s] MemoryProvider init failed; continuing with legacy memory only",
                self._session_id,
                exc_info=True,
            )
            self._memory_provider = None
            self.record_memory_event(
                event_type="provider_init_failed",
                message="MemoryProvider init failed; running on legacy path",
                source="Memory",
            )

    @property
    def memory_provider(self) -> Optional[Any]:
        """Public accessor for the executor `MemoryProvider`.

        Tools and controllers that need cross-layer memory access
        (curated knowledge search, vector retrieval, scope-aware
        promotion) reach for this. Returns ``None`` until
        ``initialize()`` runs the provider build.
        """
        return self._memory_provider

    def _attach_provider_to_pipeline_stages(self) -> None:
        """Plug the live `MemoryProvider` into every pipeline stage
        that consults it (stage 2 ContextStage + stage 18 MemoryStage
        + session_runtime.memory_provider).

        Path-A makes the provider load-bearing for every turn —
        without this attach, stage 18's `_drive_provider` runs with
        `provider=None` and silently skips `provider.record_turn(turn)`,
        so user/assistant messages never reach STM and
        `transcripts/session.jsonl` stays empty. Failures are surfaced
        loud (ERROR + memory event) so the operator catches the
        regression in real time.
        """
        provider = self._memory_provider
        pipeline = getattr(self, "_pipeline", None)
        if provider is None or pipeline is None:
            return

        attached: List[str] = []
        # Stage 2 — Context (retriever-aware strategies consult provider)
        try:
            context_stage = pipeline.get_stage(2)
            if context_stage is not None and hasattr(context_stage, "provider"):
                context_stage.provider = provider
                attached.append("stage 2 (context)")
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] stage 2 attach skipped", self._session_id, exc_info=True,
            )

        # Stage 18 — Memory (drives record_turn / record_execution)
        try:
            memory_stage = pipeline.get_stage(18)
            if memory_stage is not None and hasattr(memory_stage, "provider"):
                memory_stage.provider = provider
                attached.append("stage 18 (memory)")
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] stage 18 attach skipped", self._session_id, exc_info=True,
            )

        # session_runtime.memory_provider — read by stage 19 Summarize
        try:
            runtime = getattr(pipeline, "_attached_session_runtime", None)
            if runtime is None:
                # Lightweight container so the runtime attribute exists.
                class _SimpleRuntimeContainer:
                    pass
                runtime = _SimpleRuntimeContainer()
                try:
                    pipeline._attached_session_runtime = runtime  # type: ignore[attr-defined]
                except AttributeError:
                    runtime = None
            if runtime is not None:
                try:
                    runtime.memory_provider = provider  # type: ignore[attr-defined]
                    attached.append("session_runtime")
                except AttributeError:
                    pass
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] runtime attach skipped", self._session_id, exc_info=True,
            )

        if attached:
            logger.info(
                "[%s] MemoryProvider attached directly to %s",
                self._session_id, ", ".join(attached),
            )
            try:
                self.record_memory_event(
                    event_type="provider_attached",
                    message=f"MemoryProvider attached to {', '.join(attached)}",
                    source="Memory",
                    extra={"stages": attached},
                )
            except Exception:  # noqa: BLE001
                pass
        else:
            logger.warning(
                "[%s] MemoryProvider attach: no pipeline stages accepted "
                "the provider — STM/archive will not function",
                self._session_id,
            )
            try:
                self.record_memory_event(
                    event_type="provider_attach_failed",
                    message=(
                        "MemoryProvider direct attach found no compatible "
                        "stages — STM will not record user/assistant turns"
                    ),
                    source="Memory",
                    backend="error",
                )
            except Exception:  # noqa: BLE001
                pass

    def _install_memory_hooks(self) -> None:
        """Plug Geny's per-turn business onto the shared `MemoryHooks`
        bag built in `_build_pipeline`.

        ``_build_pipeline`` already created a hooks instance carrying
        the retrieval policy (vault_descriptions, importance_boost,
        layer_budget_ratio, …) and called ``provider.set_hooks(hooks)``
        once. This method *mutates that same instance* by attaching
        the post-write callbacks (``after_record_turn`` etc.) that
        run Geny's bucket router + DM bundle archiver.

        EXEC-5 (executor 1.20.0) means hierarchical sidecar refresh is
        already automatic — Geny no longer needs an after_note_write
        callback for that.
        """
        provider = self._memory_provider
        mgr = self._memory_manager
        hooks = self._memory_hooks
        if provider is None or mgr is None or hooks is None:
            return

        async def _on_record_turn(turn, _receipt) -> None:
            try:
                role = str(turn.role or "")
                content = _turn_text(turn.content)
                metadata = dict(turn.metadata or {}) or None

                # Archiving is a SYNC chain (ConversationArchiver /
                # DmArchiver) that reaches ``run_coro_sync`` for its
                # provider note writes. This hook runs ON the main event
                # loop, so calling it inline would make ``run_coro_sync``
                # take its in-loop branch and BLOCK the loop on a worker
                # future — and if that worker then contends for a memory
                # ``LoopAgnosticLock`` held by another (now unresumable)
                # loop coroutine, the process deadlocks. So run the whole
                # archive side-effect off the loop on the dedicated
                # single-worker pool. See ``sync_async_bridge``.
                def _archive_offloop() -> None:
                    archived = mgr._maybe_archive_conversation(
                        role, content, metadata,
                    )
                    conv_ref = (
                        archived.relative_path if archived is not None else None
                    )
                    mgr._maybe_archive_dm(role, content, metadata, conv_ref)

                from service.memory.sync_async_bridge import offload_blocking
                await offload_blocking(_archive_offloop)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "[%s] memory after_record_turn hook failed",
                    self._session_id, exc_info=True,
                )

        hooks.after_record_turn = _on_record_turn

        async def _on_note_write(meta) -> None:
            # First-write: register the title so a later citation of it in an
            # answer can be detected (the vector engine doesn't store titles).
            # Not a usefulness signal — a brand-new note was never retrieved.
            try:
                tracker = self._get_usage_tracker()
                if tracker is not None:
                    from service.memory.usage_tracker import ref_key
                    key = ref_key(getattr(meta, "ref", None))
                    tracker.register_title(key, str(getattr(meta, "title", "") or ""))
            except Exception:  # noqa: BLE001
                logger.debug("[%s] after_note_write signal failed",
                             self._session_id, exc_info=True)

        async def _on_note_update(meta) -> None:
            # A re-written note is the strongest "this memory was useful" signal
            # for the Synapse learner: the agent read it and chose to develop it.
            # (A brand-new note was never in a search result, so first-writes
            # can't produce a positive even though we register their title.)
            try:
                tracker = self._get_usage_tracker()
                if tracker is not None:
                    from service.memory.usage_tracker import SIGNAL_EDIT, ref_key
                    key = ref_key(getattr(meta, "ref", None))
                    if key:
                        tracker.register_title(
                            key, str(getattr(meta, "title", "") or ""))
                        tracker.mark_useful(key, SIGNAL_EDIT)
                        # Fire-and-forget, NEVER awaited here: this hook is
                        # awaited inside notes.write, and notes.write can be
                        # driven from the single-worker side-effect pool via
                        # run_coro_sync (the archiver path). Awaiting anything
                        # that needs that same worker from inside this hook
                        # closes a circular wait — the exact deadlock that
                        # froze s18 for 720s on 2026-07-25. (A create_task
                        # variant is also wrong: on the archiver path this
                        # hook runs on run_coro_sync's short-lived loop and
                        # the pending task dies with it.)
                        self._schedule_contradiction_check(key)
            except Exception:  # noqa: BLE001
                logger.debug("[%s] after_note_update signal failed",
                             self._session_id, exc_info=True)

        hooks.after_note_write = _on_note_write
        hooks.after_note_update = _on_note_update
        # Re-apply the (mutated) hooks bag so the provider's STM /
        # notes stores observe the new callbacks.
        provider.set_hooks(hooks)

    def _schedule_contradiction_check(self, note_key: str) -> None:
        """Store hygiene: after a note edit, surface memories that likely
        CONFLICT with it. Observability only (session log) — never injected
        into prompts, never auto-deleted; deterministic engine math, no LLM.

        Submitted to a DEDICATED thread pool, fire-and-forget:
        - never the single-worker memory side-effect pool — this hook can be
          reached from a notes.write that that worker is driving through
          run_coro_sync, and queueing onto the same worker is a circular
          wait (prod deadlock, 2026-07-25);
        - never an asyncio task — on the archiver path the hook runs on
          run_coro_sync's short-lived loop, and a pending task dies with it.
        The engine call is CPU-milliseconds (94 ms measured on the largest
        prod vault); the pool is 1-wide so checks queue rather than pile up."""
        provider = self._memory_provider
        if provider is None:
            return
        try:
            handle = provider.vector()
            fn = getattr(handle, "contradictions", None)
            if fn is None:
                return
        except Exception:  # noqa: BLE001
            return

        session_id = self._session_id

        def _check() -> None:
            try:
                conflicts = fn(note_key, top_k=3)
                if conflicts:
                    logger.info(
                        "[%s] memory hygiene: note %s likely conflicts with %s",
                        session_id, note_key,
                        [(c.get("id"), c.get("score")) for c in conflicts])
            except Exception:  # noqa: BLE001
                logger.debug("[%s] contradiction check failed",
                             session_id, exc_info=True)

        _hygiene_pool().submit(_check)

    def _get_usage_tracker(self):
        """The Synapse usage tracker if the synapse engine is active, else None.
        Reached as ``provider.vector().usage_tracker`` (see provider_bridge)."""
        provider = self._memory_provider
        if provider is None:
            return None
        try:
            vec = provider.vector()
        except Exception:  # noqa: BLE001
            return None
        return getattr(vec, "usage_tracker", None)

    def _observe_memory_signal(self, event_type: str, data) -> None:
        """Fold retrieval/promotion events into the usage tracker. Called once
        per pipeline event from both dispatch loops; cheap no-op when the
        synapse engine isn't active."""
        tracker = self._get_usage_tracker()
        if tracker is None or not isinstance(data, dict):
            return
        try:
            if event_type == "context.built":
                for ch in (data.get("chunks") or []):
                    key = ch.get("key") if isinstance(ch, dict) else None
                    if key:
                        # Injected-as-context: promotes to a RETENTION signal
                        # only after surviving several distinct turns.
                        tracker.note_injected(str(key))
            elif event_type == "memory.promoted":
                from service.memory.usage_tracker import SIGNAL_PROMOTE, ref_key
                key = ref_key(data.get("ref"))
                if key:
                    tracker.mark_useful(key, SIGNAL_PROMOTE)
        except Exception:  # noqa: BLE001
            logger.debug("[%s] memory signal observe failed",
                         self._session_id, exc_info=True)

    async def _flush_memory_learning(self, answer_text: str) -> None:
        """End-of-turn: scan the final answer for note citations, then drive
        Synapse learning from all signals collected this turn. Off-loop —
        learning is CPU-ms but must never block the event loop."""
        tracker = self._get_usage_tracker()
        if tracker is None:
            return
        provider = self._memory_provider
        try:
            handle = provider.vector()
        except Exception:  # noqa: BLE001
            return

        def _do() -> None:
            tracker.scan_citations(answer_text or "")
            tracker.flush(handle)
            tracker.begin_turn()

        try:
            from service.memory.sync_async_bridge import offload_blocking
            await offload_blocking(_do)
        except Exception:  # noqa: BLE001 — learning is best-effort
            logger.debug("[%s] memory learning flush failed",
                         self._session_id, exc_info=True)

    def record_memory_event(
        self,
        event_type: str,
        message: str,
        *,
        source: str = "Memory",
        layer: Optional[str] = None,
        backend: Optional[str] = None,
        engine: Optional[str] = None,
        importance: Optional[str] = None,
        category: Optional[str] = None,
        path: Optional[str] = None,
        chars: Optional[int] = None,
        chunks: Optional[int] = None,
        score: Optional[float] = None,
        duration_ms: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Single entry point for every memory subsystem event.

        Routes the event to the live `SessionLogger` when one exists
        — that is the path the chat broadcast cursor reads. Before
        the session logger is provisioned (provider init fires inside
        `AgentSession.initialize()`, the logger is wired *after*
        `agent_session_manager` returns from session creation), the
        event is parked on `_pending_memory_events` and flushed by
        `flush_pending_memory_events()` once the logger appears.
        """
        kwargs: Dict[str, Any] = {
            "event_type": event_type,
            "message": message,
            "source": source,
        }
        for k, v in (
            ("layer", layer), ("backend", backend), ("engine", engine),
            ("importance", importance), ("category", category),
            ("path", path), ("chars", chars), ("chunks", chunks),
            ("score", score), ("duration_ms", duration_ms),
        ):
            if v is not None:
                kwargs[k] = v
        if extra is not None:
            kwargs["extra"] = extra

        slog = get_session_logger(self._session_id, create_if_missing=False)
        if slog is not None:
            try:
                slog.log_memory_event(**kwargs)
                return
            except Exception:  # noqa: BLE001
                logger.debug(
                    "[%s] log_memory_event failed; parking on pending list",
                    self._session_id, exc_info=True,
                )
        # Logger absent — keep the event in memory for replay.
        self._pending_memory_events.append(kwargs)

    def consume_user_file_attachments(self) -> List[Dict[str, Any]]:
        """Drain the ChatAttachment dicts staged by SendUserFile this turn.

        Mirrors :meth:`consume_memory_events`: the execution layer calls this
        once per turn and forwards the result on
        ``ExecutionResult.attachments`` → chat message ``attachments``.
        Empty list when no channel is wired or nothing was sent.
        """
        channel = getattr(self, "_user_file_channel", None)
        if channel is None:
            return []
        try:
            return channel.drain()
        except Exception:  # noqa: BLE001 — delivery must never break a turn
            logger.warning("[%s] user_file_channel drain failed", self._session_id, exc_info=True)
            return []

    def consume_memory_events(self) -> List[Dict[str, Any]]:
        """Drain every memory event recorded since the last consume.

        The chat broadcast handler calls this once per turn. On the
        first call the cursor is 0, so every event the agent has
        recorded so far (including boot-time `provider_initialized`)
        ships to the frontend; subsequent calls only see new rows.

        Returns an empty list if the session logger has not yet been
        provisioned — callers should still attach an empty
        `memory_events` field so the frontend doesn't have to worry
        about None/undefined.
        """
        slog = get_session_logger(self._session_id, create_if_missing=False)
        if slog is None:
            return []
        try:
            events = slog.extract_memory_events_from_cache(self._memory_events_cursor)
            self._memory_events_cursor = slog.get_cache_length()
            return events
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] consume_memory_events failed", self._session_id, exc_info=True,
            )
            return []

    def flush_pending_memory_events(self) -> int:
        """Replay every parked event into the now-live `SessionLogger`.

        Called by `agent_session_manager` immediately after it
        provisions the logger so the boot-time events (provider
        initialised, vector layer ready, ...) are present on the
        frontend's first poll.
        """
        if not self._pending_memory_events:
            return 0
        slog = get_session_logger(self._session_id, create_if_missing=False)
        if slog is None:
            return 0
        replayed = 0
        for kwargs in self._pending_memory_events:
            try:
                slog.log_memory_event(**kwargs)
                replayed += 1
            except Exception:  # noqa: BLE001
                logger.debug(
                    "[%s] memory event replay failed", self._session_id, exc_info=True,
                )
        self._pending_memory_events.clear()
        return replayed

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

            # 1a. Build the geny-executor MemoryProvider (composite with
            # session + optional user-curated delegates). This is the
            # canonical memory surface going forward — note writes,
            # vector indexing, and curated retrieval all route through
            # the provider's handles. See provider_bridge.py for the
            # config shape.
            await self._init_memory_provider()

            # 1b. Vector memory warm-up — genuinely in the background. This
            # was awaited inline, which meant a large vault (observed: 6.2k
            # notes ≈ 19s full scan + re-index) held EVERY resume hostage;
            # combined with the pre-2.64.2 on-loop scan it also froze /health
            # and got the process watchdog-killed mid-start. The session goes
            # live immediately; memory_search serves whatever is indexed so
            # far (keyword fallback covers the gap) until the warm-up lands.
            if self._memory_manager:
                mm = self._memory_manager
                sid = self._session_id
                ready_evt = self._memory_ready

                self.record_memory_event(
                    "waking",
                    "에이전트를 깨우는 중 — 기억을 불러오고 있습니다…",
                    layer="vector",
                )
                _woke_at = time.monotonic()

                async def _vector_warmup() -> None:
                    try:
                        # BOUNDED. A large vault re-indexes in the background
                        # and the session is already live, but an unbounded
                        # wait leaves `memory_ready` unset forever if the
                        # backend is wedged — and every turn then pays the
                        # readiness gate's full timeout before proceeding.
                        ok = await asyncio.wait_for(
                            mm.initialize_vector_memory(),
                            timeout=_MEMORY_WARMUP_TIMEOUT_S,
                        )
                        took = time.monotonic() - _woke_at
                        logger.info(
                            f"[{sid}] vector memory warm-up done "
                            f"(ok={ok}, {took:.1f}s)"
                        )
                        self.record_memory_event(
                            "awake",
                            f"기억 준비 완료 ({took:.1f}초)"
                            if ok else
                            f"기억 준비 완료 — 벡터 검색은 사용할 수 없습니다 ({took:.1f}초)",
                            layer="vector",
                        )
                    except asyncio.CancelledError:
                        raise
                    except asyncio.TimeoutError:
                        took = time.monotonic() - _woke_at
                        logger.warning(
                            f"[{sid}] vector warm-up exceeded "
                            f"{_MEMORY_WARMUP_TIMEOUT_S}s — continuing without it"
                        )
                        self.record_memory_event(
                            "awake",
                            f"기억 준비가 {took:.0f}초를 넘겨 키워드 검색으로 계속합니다",
                            layer="vector",
                        )
                    except Exception as ve:  # noqa: BLE001
                        logger.debug(f"[{sid}] Vector memory init skipped: {ve}")
                        self.record_memory_event(
                            "awake",
                            "기억 준비 완료 — 벡터 검색은 사용할 수 없습니다",
                            layer="vector",
                        )
                    finally:
                        # Ready even on failure/cancel/timeout: "as loaded as
                        # it will get" — waiters must never hang on a dead
                        # warm-up, and a turn must never be blocked by one.
                        ready_evt.set()

                self._vector_init_task = asyncio.create_task(
                    _vector_warmup(), name=f"vector-warmup-{sid}"
                )
            else:
                self._memory_ready.set()

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

    # ── E.1 (cycle 20260426_1) — between-turn live reload ──

    # O.1 (cycle 20260426_3) — extended scope set; "all" still applies
    # every available branch.
    _RUNTIME_REFRESH_SCOPES = (
        "permissions",
        "hooks",
        "memory_tuning",
        "affect",
        "all",
    )

    def queue_runtime_refresh(self, scope: str) -> bool:
        """Queue a between-turn refresh of permission rules / hook
        runner from settings.json. The refresh is applied at the
        start of the next ``invoke`` / ``astream`` — never mid-turn.

        Returns ``True`` when the queue accepts the request, ``False``
        when scope is unknown or the session isn't initialized yet.

        Why between-turn and not mid-turn:
        ``Pipeline.attach_runtime`` raises after the first run because
        executing state holds references to the slot values; swapping
        them mid-turn produces inconsistent behavior. Between turns is
        safe — a fresh ``PipelineState`` is built on the next
        ``run_stream`` and picks up the new slot values via
        ``Pipeline._init_state``.
        """
        if not getattr(self, "_initialized", False) or self._pipeline is None:
            return False
        if scope not in self._RUNTIME_REFRESH_SCOPES:
            return False
        self._pending_runtime_refresh = scope
        logger.info(
            "[%s] runtime refresh queued for next turn (scope=%s)",
            self._session_id, scope,
        )
        return True

    def _apply_pending_runtime_refresh(self) -> None:
        """Drain the refresh queue at the top of ``invoke`` / ``astream``.

        Re-reads fresh permission rules / hook runner from settings.json
        and swaps them on the bound Pipeline via the *public*
        :meth:`Pipeline.refresh_runtime` (geny-executor 2.2.0) — the
        library-owned between-turn variant of ``attach_runtime`` (same
        kwargs, no construction-time gate; raises if a run is in
        flight, which can't happen here because Geny only drains the
        queue at the turn boundary). Replaces the old private-setter
        bypass (``_set_tool_stage_permission_matrix`` /
        ``_set_tool_stage_hook_runner``).

        Each branch logs success / failure independently — a failed
        permissions reload doesn't block the hooks reload (and vice
        versa).
        """
        scope = getattr(self, "_pending_runtime_refresh", None)
        if not scope:
            return
        # One-shot — clear the flag before applying so a refresh failure
        # doesn't leave the queue stuck.
        self._pending_runtime_refresh = None
        pipeline = self._pipeline
        if pipeline is None:
            return

        if scope in ("permissions", "all"):
            try:
                from service.permission.install import (
                    _resolve_effective_executor_mode,
                    install_permission_rules,
                )

                # Phase 9.9.2 — re-apply manifest narrowing on every
                # runtime refresh so settings.json edits + manifest
                # selection both flow into the live session.
                host_perm_selection = self._load_permission_host_selection()
                rules, runner_mode = install_permission_rules(
                    host_selection=host_perm_selection,
                )
                # Phase 9.9.3 — the executor's permission_mode kwarg
                # consumes the PermissionMode enum value, not the
                # runner mode (advisory / enforce). Pass the executor
                # mode resolved through the enforcement gate so
                # runtime refresh applies the same coercion as boot.
                effective_mode = _resolve_effective_executor_mode(runner_mode)
                pipeline.refresh_runtime(
                    permission_rules=rules, permission_mode=effective_mode,
                )
                logger.info(
                    "[%s] runtime refresh applied: permissions reloaded "
                    "(%d rule(s), runner=%s, executor=%s)",
                    self._session_id, len(rules), runner_mode, effective_mode,
                )
            except Exception:
                logger.exception(
                    "[%s] runtime refresh: permissions reload failed",
                    self._session_id,
                )

        if scope in ("hooks", "all"):
            try:
                from service.hooks.install import install_hook_runner

                runner = install_hook_runner(
                    host_selection=self._load_host_selection("hooks"),
                )
                if runner is not None:
                    pipeline.refresh_runtime(hook_runner=runner)
                    logger.info(
                        "[%s] runtime refresh applied: hooks reloaded",
                        self._session_id,
                    )
            except Exception:
                logger.exception(
                    "[%s] runtime refresh: hooks reload failed",
                    self._session_id,
                )

        if scope in ("memory_tuning", "all"):
            try:
                self._reload_memory_tuning(pipeline)
            except Exception:
                logger.exception(
                    "[%s] runtime refresh: memory_tuning reload failed",
                    self._session_id,
                )

        if scope in ("affect", "all"):
            try:
                self._reload_affect_emitter(pipeline)
            except Exception:
                logger.exception(
                    "[%s] runtime refresh: affect reload failed",
                    self._session_id,
                )

    def _reload_memory_tuning(self, pipeline: Any) -> None:
        """O.1 (cycle 20260426_3) — re-read ``settings.json:memory.tuning``
        and mutate the live ``GenyMemoryRetriever`` / ``GenyMemoryStrategy``
        instances on Stage 2 (context) and Stage 18 (memory).

        Mutates instance attrs directly because the executor's
        retriever / strategy classes don't expose a "reset config"
        method. Field names (``_max_inject``, ``_recent_turns``,
        ``_enable_vector``, ``_enable_reflection``) come from
        ``geny_executor.memory.retriever.GenyMemoryRetriever`` and
        ``geny_executor.memory.strategy.GenyMemoryStrategy``. If those
        ever rename, the change is silent (``getattr`` guards) and the
        live session keeps the pre-refresh values.
        """
        from service.memory.tuning import load_memory_tuning

        is_vtuber = getattr(self._role, "value", None) == "vtuber" or (
            isinstance(self._role, str) and self._role == "vtuber"
        )
        tuning = load_memory_tuning(is_vtuber=is_vtuber)

        applied: list[str] = []
        for stage in pipeline._stages.values():
            slots = (
                stage.get_strategy_slots()
                if hasattr(stage, "get_strategy_slots")
                else {}
            )
            if stage.name == "context":
                slot = slots.get("retriever")
                retriever = getattr(slot, "strategy", None) if slot else None
                if retriever is not None:
                    if hasattr(retriever, "_max_inject"):
                        retriever._max_inject = tuning["max_inject_chars"]
                        applied.append("max_inject_chars")
                    if hasattr(retriever, "_recent_turns"):
                        retriever._recent_turns = tuning["recent_turns"]
                        applied.append("recent_turns")
                    if hasattr(retriever, "_enable_vector"):
                        retriever._enable_vector = tuning["enable_vector_search"]
                        applied.append("enable_vector_search")
            elif stage.name == "memory":
                slot = slots.get("strategy")
                strategy = getattr(slot, "strategy", None) if slot else None
                if strategy is not None and hasattr(strategy, "_enable_reflection"):
                    strategy._enable_reflection = tuning["enable_reflection"]
                    applied.append("enable_reflection")

        logger.info(
            "[%s] runtime refresh applied: memory_tuning reloaded (%s)",
            self._session_id,
            ", ".join(applied) if applied else "no slots matched",
        )

    def _reload_affect_emitter(self, pipeline: Any) -> None:
        """O.1 (cycle 20260426_3) — re-read
        ``settings.json:affect.max_tags_per_turn`` and mutate the live
        ``AffectTagEmitter._max_tags_per_turn`` on Stage 17 (emit)."""
        from service.emit.chain_install import _resolve_max_tags
        from service.emit.affect_tag_emitter import (
            DEFAULT_MAX_TAG_MUTATIONS_PER_TURN,
        )

        new_max = _resolve_max_tags(DEFAULT_MAX_TAG_MUTATIONS_PER_TURN)
        mutated = False
        for stage in pipeline._stages.values():
            if stage.name != "emit":
                continue
            chain = getattr(stage, "emitters", None)
            if chain is None or not hasattr(chain, "items"):
                continue
            for emitter in chain.items:
                if getattr(emitter, "name", None) != "affect_tag":
                    continue
                if hasattr(emitter, "_max_tags_per_turn"):
                    emitter._max_tags_per_turn = new_max
                    mutated = True

        if mutated:
            logger.info(
                "[%s] runtime refresh applied: affect max_tags_per_turn=%d",
                self._session_id, new_max,
            )
        else:
            logger.debug(
                "[%s] runtime refresh: no AffectTagEmitter on chain — skipped",
                self._session_id,
            )

    def _load_host_selection(self, category: str) -> Optional[List[str]]:
        """Read the env manifest's ``host_selections.<category>`` list.

        Generic per-env host-selection lookup. Phase 9.9.2 first shipped
        this for ``permissions``; the env-attachments audit (2026-06-17)
        generalised it so ``hooks`` and ``skills`` pickers stop being
        dead UI — each now narrows the host registry the same way
        permissions always have. Returns:

            ``None`` — no manifest available (legacy envs) OR the manifest
                       leaves the category unset; the caller treats this
                       as wildcard (keep all).
            ``["*"]`` — explicit wildcard (forward-compat; keep all plus
                        future host additions).
            ``[]`` — opt out of every item in this category.
            literal list — only items whose id is in the list survive.

        Failures degrade silently to ``None`` — the runtime should never
        fail to boot because the manifest read hiccupped.
        """
        if not self._env_id:
            return None
        try:
            from service.environment import get_environment_service

            svc = get_environment_service()
            manifest = svc.load_manifest(self._env_id) if svc else None
        except Exception:
            logger.debug(
                "_load_host_selection(%s): manifest read failed "
                "for env_id=%s; treating as wildcard",
                category,
                self._env_id,
                exc_info=True,
            )
            return None
        if manifest is None:
            return None
        sel = getattr(
            getattr(manifest, "host_selections", None),
            category,
            None,
        )
        if sel is None:
            return None
        return list(sel)

    def _load_permission_host_selection(self) -> Optional[List[str]]:
        """Back-compat shim — see :meth:`_load_host_selection`."""
        return self._load_host_selection("permissions")

    def _load_tool_settings(self) -> Dict[str, Dict[str, Any]]:
        """Read per-environment tool settings from the manifest.

        Stored under ``host_selections.extras["tool_settings"]`` (e.g.
        ``{"web_search": {"backend": "brave", "brave_api_key": "..."}}``).
        Sanitized (unknown keys / empty fields dropped) so a stray value can
        never reach a tool or shadow a reserved ToolContext.extras key. Returns
        ``{}`` for legacy envs or on any read failure (never blocks boot).
        """
        if not self._env_id:
            return {}
        try:
            from service.environment import get_environment_service
            from service.tool_settings import sanitize_tool_settings

            svc = get_environment_service()
            manifest = svc.load_manifest(self._env_id) if svc else None
            if manifest is None:
                return {}
            extras = getattr(getattr(manifest, "host_selections", None), "extras", None) or {}
            return sanitize_tool_settings(extras.get("tool_settings"))
        except Exception:
            logger.debug(
                "_load_tool_settings: manifest read failed for env_id=%s",
                self._env_id,
                exc_info=True,
            )
            return {}

    def _apply_session_limits_to_pipeline(self) -> None:
        """B.1 (cycle 20260426_1) — bridge UI session limits into the
        bound Pipeline's ``PipelineConfig``.

        The user-supplied ``max_iterations`` from the Sessions UI is the
        cap on graph iterations per ``invoke``. Without this hook,
        ``Pipeline._config`` keeps the value baked in at manifest-load
        time (typically 50), and ``PipelineConfig.apply_to_state`` writes
        that value into every fresh ``PipelineState`` regardless of what
        Geny set on the session — making the Sessions UI control
        cosmetic.

        Each ``AgentSession`` owns its Pipeline (one Pipeline per session
        via ``EnvironmentService.instantiate_pipeline``), so per-session
        mutation of ``Pipeline._config`` is safe — no other caller
        observes it.

        Called once at the end of :meth:`_build_pipeline`. Idempotent —
        re-calling with unchanged values has no extra effect.

        Skipped silently when:
        - ``self._pipeline`` is ``None`` (not yet built / older path).
        - The pipeline lacks ``_config`` (older executor versions).
        - The session value is falsy — leave manifest default in place.

        ``timeout`` is *not* mutated here: it is enforced at the
        chat-execution layer via
        ``asyncio.wait_for(agent.invoke(...), timeout=...)`` —
        see ``service/execution/agent_executor.py:_execute_core``.

        ``max_turns`` is *not* mutated here either: with env-driven
        pipelines, "turn" reduces to "one chat message", which is
        governed by the chat layer, not the executor pipeline.
        """
        pipeline = getattr(self, "_pipeline", None)
        if pipeline is None:
            return
        config = getattr(pipeline, "_config", None)
        if config is None:
            return
        # The route's binding window. Without this the pipeline compacts at a
        # fraction of 200_000 no matter what answers — six times too late for
        # a local server launched at 32k, where the request overflows before
        # compaction ever fires. ``None`` means no hop could say; the library
        # default stands and the log says it is an assumption.
        if hasattr(config, "context_window_budget"):
            window = self._context_window_budget
            if window and int(window) > 0:
                previous = getattr(config, "context_window_budget", None)
                if previous != int(window):
                    config.context_window_budget = int(window)
                    logger.info(
                        "[%s] context window: %s → %s (from the route's smallest hop)",
                        self._session_id, previous, int(window),
                    )
            else:
                logger.info(
                    "[%s] context window: no hop stated one — assuming %s. "
                    "Declare it on the account, or run model discovery.",
                    self._session_id, getattr(config, "context_window_budget", None),
                )

        if hasattr(config, "cost_budget_usd") and self._cost_budget_usd is not None:
            try:
                budget = float(self._cost_budget_usd)
            except (TypeError, ValueError):
                budget = 0.0
            # 0 and below mean "no ceiling", which is what None already says.
            config.cost_budget_usd = budget if budget > 0 else None
            logger.info(
                "[%s] cost ceiling: %s per turn",
                self._session_id, config.cost_budget_usd or "none",
            )

        if hasattr(config, "max_iterations") and self._max_iterations:
            try:
                desired = int(self._max_iterations)
            except (TypeError, ValueError):
                logger.warning(
                    "[%s] _apply_session_limits: invalid max_iterations=%r — "
                    "leaving manifest default",
                    self._session_id, self._max_iterations,
                )
                return
            if desired <= 0:
                return
            previous = getattr(config, "max_iterations", None)
            if previous != desired:
                config.max_iterations = desired
                logger.info(
                    "[%s] session limit applied: max_iterations %s → %s",
                    self._session_id, previous, desired,
                )

    # ========================================================================
    # Self-modifying environment (session-scoped overlay persistence)
    # ========================================================================

    def _env_overlay_path(self) -> Optional[str]:
        """Per-session file holding the saved env overlay, or None when the
        session has no storage dir."""
        sp = self._storage_path
        if not sp:
            return None
        import os

        return os.path.join(sp, "env_overlay.json")

    def _make_env_persistence(self):
        """Build the ``env_persistence`` callback the executor invokes on
        ``env(action="save")`` — writes the overlay JSON to this session's own
        storage (session-scoped). Returns None when there's no storage dir."""
        path = self._env_overlay_path()
        if not path:
            return None
        session_id = self._session_id

        async def _persist(overlay: Dict[str, Any]) -> None:
            import json
            import os

            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(overlay, fh, ensure_ascii=False)
            os.replace(tmp, path)
            logger.info("[%s] env overlay saved", session_id)

        return _persist

    def _make_pack_persistence(self):
        """Build the ``pack_persistence`` callback the executor invokes on
        ``env(action="save_pack")``: snapshot the session's GAPT workspace
        (``tool_save``, artifacts included) and persist a reusable Sandbox Tool
        Pack (disabled by default — the owner enables it for an environment).
        Returns None when GAPT isn't configured."""
        session_id = self._session_id

        async def _persist(payload: Dict[str, Any]) -> Dict[str, Any]:
            from service.gapt import get_gapt_client
            from service.sandbox_tool_packs import builder, get_sandbox_tool_pack_store
            from service.sandbox_tool_packs.models import PackSkill, SandboxToolSpec

            sandbox = payload.get("sandbox")
            wid = getattr(sandbox, "workspace_id", None)
            if not wid:
                raise RuntimeError("the session has no GAPT workspace to snapshot")
            gc = get_gapt_client()
            if not gc.configured:
                raise RuntimeError("GAPT is not configured on this host")
            # Resolve the project the workspace belongs to (for cold reuse).
            ws = await gc.get_workspace(wid)
            project_ref = ""
            if isinstance(ws, dict):
                project_ref = ws.get("project_id") or (ws.get("project") or {}).get("id") or ""
            tools = [SandboxToolSpec(**t) for t in (payload.get("tools") or [])]
            skills = [
                PackSkill(
                    id=s["id"],
                    description=s.get("description", ""),
                    body=s.get("body", ""),
                    allowed_tools=list(s.get("allowed_tools", []) or []),
                )
                for s in (payload.get("skills") or [])
                if isinstance(s, dict) and s.get("id")
            ]
            # Self-service auto-loop (GENY_PACK_AUTOLOAD_OWN, default ON): an agent
            # that BUILDS a pack should be able to keep using it with zero owner
            # steps. So enable it + opt the CREATING env into it — the agent's
            # future sessions auto-load it (forge_tool already made it live THIS
            # session). Security: only auto-enables the agent's OWN pack for its
            # OWN env (sandbox-isolated execution); OTHER envs still need explicit
            # opt-in. Set GENY_PACK_AUTOLOAD_OWN=false to keep the manual gate.
            import os as _os
            autoload = _os.getenv("GENY_PACK_AUTOLOAD_OWN", "true").strip().lower() in (
                "1", "true", "yes", "on",
            )
            store = get_sandbox_tool_pack_store()
            saved = await builder.save_pack(
                store,
                gc,
                name=payload.get("name") or "pack",
                description=payload.get("description") or "",
                project_ref=project_ref,
                workspace_ref=wid,
                tools=tools,
                skills=skills,
                created_by=session_id,
                enabled=autoload,
            )
            opted_in = False
            if autoload and self._env_id:
                opted_in = self._optin_env_to_pack(self._env_id, saved.id)
            logger.info(
                "[%s] saved sandbox tool pack %s (%s) — autoload=%s opted_in=%s",
                session_id, saved.name, saved.id, autoload, opted_in,
            )
            return {
                "pack_id": saved.id,
                "name": saved.name,
                "enabled": saved.enabled,
                "auto_opted_in_env": self._env_id if opted_in else None,
            }

        return _persist

    def _optin_env_to_pack(self, env_id: str, pack_id: str) -> bool:
        """Add ``pack_id`` to the env's ``host_selections.extras.sandbox_tool_packs``
        so future sessions of this env auto-load the pack. Best-effort; the agent's
        current session already has the tool live via forge_tool, so a failure here
        only affects future-session auto-load, never this turn."""
        try:
            # NOTE: get_environment_service is exported from the PACKAGE
            # (service.environment.__init__), NOT service.environment.service —
            # the `.service` path raises ImportError. (3 pre-existing usages at
            # ~1848/1888/2083 use the broken `.service` path inside try/except,
            # so they silently degrade their manifest reads — flagged separately.)
            from service.environment import get_environment_service

            svc = get_environment_service()
            if svc is None:
                return False
            manifest = svc.load_manifest(env_id)
            if manifest is None:
                return False
            hs = getattr(manifest, "host_selections", None)
            if hs is None:
                return False
            extras = getattr(hs, "extras", None)
            if extras is None:
                extras = {}
                hs.extras = extras
            current = extras.get("sandbox_tool_packs")
            ids = [str(p).strip() for p in current if p] if isinstance(current, list) else []
            if pack_id in ids:
                return True  # already opted in
            ids.append(pack_id)
            extras["sandbox_tool_packs"] = ids
            svc.update_manifest(env_id, manifest)
            return True
        except Exception:  # noqa: BLE001 — never break save_pack on opt-in failure
            logger.warning("[%s] auto opt-in env %s → pack %s failed", self._session_id, env_id, pack_id, exc_info=True)
            return False

    def read_env_overlay(self) -> Optional[Dict[str, Any]]:
        """This session's saved env overlay, or ``None``.

        The same file :meth:`_restore_env_overlay` replays at build time.
        Read here so a settings page can say which values the session itself
        chose, as opposed to inherited.
        """
        path = self._env_overlay_path()
        if not path:
            return None
        import json
        import os

        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:  # noqa: BLE001 — an unreadable overlay is "none"
            logger.debug("[%s] env overlay unreadable", self._session_id, exc_info=True)
            return None
        return data if isinstance(data, dict) else None

    def _restore_env_overlay(self) -> None:
        """Re-apply a previously-saved env overlay (prompt / authored skills /
        enabled tools + skills). Best-effort — additive (does not disable tools
        absent from the overlay). Never blocks session start."""
        path = self._env_overlay_path()
        if not path:
            return
        import json
        import os

        if not os.path.isfile(path):
            return
        env = getattr(self._pipeline, "environment", None)
        if env is None:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                overlay = json.load(fh)
        except Exception:  # noqa: BLE001
            logger.warning("[%s] env overlay unreadable; ignoring", self._session_id, exc_info=True)
            return
        try:
            # 1. Authored skills (define before enabling them).
            for sk in overlay.get("authored_skills", []) or []:
                if not isinstance(sk, dict) or not sk.get("id"):
                    continue
                env.create_skill(
                    sk["id"],
                    sk.get("description", ""),
                    sk.get("body", ""),
                    allowed_tools=sk.get("allowed_tools", []) or [],
                    execution_mode=sk.get("execution_mode", "inline") or "inline",
                    enable=False,
                )
            # 2. Edited system prompt.
            prompt = overlay.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                env.set_prompt(prompt)
            # 3. Tool settings (API keys, backends, …) — executor >=2.28.0.
            for group, fields in (overlay.get("tool_settings") or {}).items():
                if not isinstance(fields, dict):
                    continue
                for field, value in fields.items():
                    env.set_setting(str(group), str(field), value)
            # 4. Tunable config (model knobs + pipeline limits) — core stays
            #    locked, so set_config silently refuses any core key.
            cfg = overlay.get("config") or {}
            for section in ("model", "pipeline"):
                for key, value in (cfg.get(section) or {}).items():
                    env.set_config(str(key), value)
            # 5. Reconcile tools/skills to the EXACT saved set so a tool the
            #    user disabled stays disabled (additive-only restore used to let
            #    the manifest re-add it). The env tool is self-protected.
            target_tools = {str(n) for n in (overlay.get("active_tools") or [])}
            target_skills = {str(s) for s in (overlay.get("active_skills") or [])}
            skill_ids = set()
            sreg = getattr(env, "_skill_registry", None)
            if sreg is not None:
                try:
                    skill_ids = set(sreg.list_ids())
                except Exception:  # noqa: BLE001
                    skill_ids = set()
            # Enable the saved set (skills via enable_skill, others via enable_tool).
            for sid in target_skills:
                env.enable_skill(sid)
            for name in target_tools - target_skills:
                env.enable_tool(name)
            # Disable anything currently active but NOT in the saved set.
            for name in list(env.active_tools()):
                if name == "env" or name in target_tools:
                    continue
                if name in skill_ids:
                    env.disable_skill(name)
                else:
                    env.disable_tool(name)
            logger.info("[%s] env overlay restored", self._session_id)
        except Exception:  # noqa: BLE001
            logger.warning("[%s] env overlay restore failed", self._session_id, exc_info=True)

    # ========================================================================
    # geny-executor Pipeline Mode
    # ========================================================================

    async def invalidate_sandbox_binding(self) -> bool:
        """Tear the GAPT sandbox down so the next use rebuilds its bind.

        The bind is chosen when the workspace is created — the agent's own
        space, or the whole cloud when connected. A container mount cannot be
        re-scoped per turn, so a connection toggle would otherwise leave the
        sandbox looking at the OLD tree: a disconnected agent still reading
        the shared space through Bash, or a freshly connected one unable to.

        Best-effort. The sandbox ladder re-creates the workspace lazily on the
        next sandboxed call, so failing here costs a stale bind until the
        session restarts — never the toggle itself.
        """
        sandbox = getattr(self, "_gapt_sandbox", None)
        if sandbox is None:
            return False
        try:
            from service.gapt import get_gapt_client

            wid = getattr(sandbox, "workspace_id", "")
            if wid:
                await get_gapt_client().delete_workspace(wid)
            self._gapt_sandbox = None
            logger.info(
                "[%s] sandbox binding invalidated — rebuilds on next use",
                self._session_id,
            )
            return True
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] sandbox invalidation skipped", self._session_id, exc_info=True,
            )
            return False

    def rebind_tool_roots(self) -> bool:
        """Re-apply filesystem roots to a LIVE pipeline.

        Connecting an agent to GenyCloud changes what its file tools may
        reach. The roots are baked into the tool context when the pipeline
        is attached, so without this a connection would only take effect
        after a restart — and a user who just clicked "connect" would see
        the agent claim it cannot find the folder.
        """
        pipeline = self._pipeline
        if pipeline is None:
            return False
        ctx = getattr(pipeline, "tool_context", None)
        if ctx is None or not getattr(ctx, "working_dir", None):
            return False
        try:
            from service.cloud import cloud_workspace, is_connected

            # Own space always; the whole cloud only while connected. Both
            # roots are inside the cloud tree now, so "connect" is a WIDENING
            # rather than a bridge to somewhere else.
            roots = [ctx.working_dir]
            owner = self._owner_username
            if owner and is_connected(owner, self._session_id):
                roots.append(cloud_workspace(owner))
            ctx.allowed_paths = roots
            return True
        except Exception:  # noqa: BLE001
            return False

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
            MemoryAwareRetriever,
            MemoryHooks,
            ProviderDrivenStrategy,
        )
        from geny_executor.stages.s18_memory.artifact.default.persistence import (
            NullPersistence,
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
            from service.config.sub_config.general.llm_credentials_config import (
                LLMCredentialsConfig,
            )
            cm = get_config_manager()
            api_cfg = cm.load_config(APIConfig)
            creds = cm.load_config(LLMCredentialsConfig)
            api_key = api_key or creds.anthropic_api_key or ""
        except Exception:
            pass
        if api_cfg is None:
            from service.config.sub_config.general.api_config import APIConfig
            api_cfg = APIConfig()
        # Phase H: do NOT hard-require ANTHROPIC_API_KEY here. The
        # per-Environment provider check upstream
        # (``AgentSessionManager._extract_primary_provider`` +
        # ``CredentialBundle.has``) already validates the credentials
        # actually needed by the manifest. Failing here would block
        # Claude Code (CLI) / Copilot (CLI) / OpenAI / Google /
        # vLLM-only environments where the user never set an
        # Anthropic key — even though their session never makes an
        # Anthropic SDK call. The fallback client below becomes
        # optional and the property exposes ``None`` for those envs;
        # no production code path requires it at session-build time.

        # ── The ONE workspace ────────────────────────────────────────
        # The agent's file tools work in <storage>/workspace — the SAME dir
        # the GAPT sandbox bind-mounts at /workspace, where user uploads are
        # staged (workspace/uploads) and outbound files are delivered from
        # (workspace/outputs). Before this scoping, working_dir fell back to
        # the storage ROOT, one level ABOVE the bind: host-side Read/Write/
        # Bash/Doc* resolved next to (and could overwrite) memory/,
        # transcripts/, synapse.db — and a document "saved" by a Doc tool
        # landed outside the container mount, invisible to sandboxed Bash.
        # An explicit CreateSessionRequest.working_dir still wins (power use).
        if self._working_dir:
            working_dir = self._working_dir
        elif self.storage_path:
            working_dir = str(Path(self.storage_path) / "workspace")
            try:
                os.makedirs(working_dir, exist_ok=True)
            except Exception:  # noqa: BLE001 — fall back to the root
                working_dir = self.storage_path
        else:
            working_dir = ""

        # GenyCloud IS the filesystem. This agent's own space lives inside
        # it at `agents/<sid>`, so `working_dir` moves there and the agent
        # stands in the shared tree rather than reaching into it through a
        # link. CONNECTING widens the reach from "my own space" to the whole
        # cloud — the user's linked folders, the other agents' spaces, the
        # GAPT workspaces — which is what makes it shared.
        cloud_dir = ""
        try:
            from service.cloud import adopt_agent_space, cloud_workspace, is_connected

            owner = self._owner_username
            if owner and self.storage_path:
                adopted = adopt_agent_space(
                    owner, self.storage_path, self._session_id,
                )
                # An explicit CreateSessionRequest.working_dir still wins:
                # a caller who named a directory meant that directory, and
                # adoption must not quietly relocate them.
                if not self._working_dir:
                    working_dir = adopted
                if is_connected(owner, self._session_id):
                    cloud_dir = cloud_workspace(owner)
        except Exception as exc:  # noqa: BLE001 — never block a session on the cloud
            logger.debug("[%s] cloud adoption skipped: %s", self._session_id[:8], exc)

        is_vtuber = self._role == SessionRole.VTUBER

        # Persona text — preserve legacy GenyPresets.* behavior. The
        # adaptive tail teaches the LLM the [TASK_COMPLETE] / [CONTINUE]
        # / [BLOCKED] vocabulary Stage 12's binary_classify evaluator
        # expects. VTuber roles skip it — they use signal_based
        # evaluation and a conversational persona.
        system_prompt = self._system_prompt or ""
        if is_vtuber:
            persona_text = system_prompt or _DEFAULT_VTUBER_PROMPT
        else:
            persona_text = (
                (system_prompt or _DEFAULT_WORKER_PROMPT)
                + "\n\n"
                + _ADAPTIVE_PROMPT
            )

        # G.2 (cycle 20260426_2) — per-session memory tuning knobs.
        # Defaults match the historical hardcoded values exactly; an
        # operator setting settings.json:memory.tuning.<field>
        # overrides them without a code change.
        try:
            from service.memory.tuning import load_memory_tuning
            _tuning = load_memory_tuning(is_vtuber=is_vtuber)
        except Exception:
            _tuning = {
                "max_inject_chars": 8000 if is_vtuber else 10000,
                "recent_turns": 6,
                "enable_vector_search": True,
                "enable_reflection": True,
                # Memory v2 PR 10 — slim retriever (recent + summary +
                # vault map only; rest via tools). Flipped here
                # post-PR-13 once Memory Ladder doc reaches every role.
                "slim_mode": False,
                # Memory v2 followup — insights/ category was filling
                # up with behavioural patterns and per-turn tactics
                # ("greet warmly", "delegate file content tasks").
                # Gate at ``high`` so only genuine factual learnings
                # land. ``low`` restores legacy permissive behaviour.
                "min_insight_importance": "high",
            }

        # Q.1 (cycle 20260426_3) — per-session memory tuning override.
        # ``self._memory_config.tuning`` (when present) wins over the
        # global tuning loaded above. Each field is independently
        # overridable; missing fields fall through to the global value.
        # Type-coerced loosely — the fields are read into private slots
        # of GenyMemoryRetriever / Strategy so a wrong type would silent-
        # fail at use time; we surface a warning at session-build time
        # instead so the operator can catch it before the session runs.
        per_session_cfg = self._memory_config or {}
        per_session_tuning = (
            per_session_cfg.get("tuning")
            if isinstance(per_session_cfg, dict)
            else None
        )
        if isinstance(per_session_tuning, dict):
            for key, validator in (
                ("max_inject_chars", lambda v: isinstance(v, int) and v >= 1),
                ("recent_turns", lambda v: isinstance(v, int) and v >= 0),
                ("enable_vector_search", lambda v: isinstance(v, bool)),
                ("enable_reflection", lambda v: isinstance(v, bool)),
                ("slim_mode", lambda v: isinstance(v, bool)),
                ("min_insight_importance", lambda v: isinstance(v, str) and v.lower() in ("low","medium","high","critical")),
            ):
                if key in per_session_tuning:
                    candidate = per_session_tuning[key]
                    if validator(candidate):
                        _tuning[key] = candidate
                    else:
                        logger.warning(
                            "[%s] memory_config.tuning.%s ignored — invalid "
                            "type / value: %r",
                            self._session_id, key, candidate,
                        )
        max_inject_chars = _tuning["max_inject_chars"]

        curated_km = None
        if self._owner_username:
            try:
                from service.memory.curated_knowledge import get_curated_knowledge_manager
                curated_km = get_curated_knowledge_manager(self._owner_username)
            except Exception:
                pass

        # ── Memory model routing (cycle 20260421_4 / 20260501_1 A1) ──
        #
        # Push APIConfig.memory_model down onto s02 (context) and s18
        # (memory) so executor-native paths honour the per-stage override.
        # Empty memory_model falls back to the main model so no surprise
        # LLM calls spin up.
        #
        # Cycle 20260501_1 A1 — the second target was *15* historically
        # (when the pipeline had 18 stages and memory lived at order 15).
        # The pipeline expanded to 21 stages; ``s18_memory.stage.order``
        # is *18*, ``s15_hitl.stage.order`` is *15*. This call now
        # correctly targets the memory stage.
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
                f"[{self._session_id}] memory wiring: PipelineMutator init failed — "
                f"continuing without stage-level overrides: {exc}"
            )
        if mutator is not None:
            try:
                mutator.set_stage_model(2, memory_cfg)
            except MutationError:
                logger.warning(
                    f"[{self._session_id}] memory wiring: s02 context stage absent — "
                    f"skipping memory model override"
                )
            try:
                mutator.set_stage_model(18, memory_cfg)
            except MutationError:
                logger.warning(
                    f"[{self._session_id}] memory wiring: s18 memory stage absent — "
                    f"skipping memory model override"
                )

        # ── Shared LLM client (cycle 20260421_4 / Phase H) ──
        #
        # Build a fallback Anthropic client for out-of-pipeline tool
        # calls (``memory_distill``, etc.) that read
        # ``self._llm_client_handle``. The per-Environment provider
        # selection lives in the manifest at Stage 6, so this handle
        # is *not* the main-path client — it's only consulted by tools
        # that explicitly reach for ``session.llm_client``.
        #
        # Phase H: this is now OPTIONAL. If the user runs a
        # geny_router / openai / google / vllm-only
        # environment without an Anthropic key, we leave the handle as
        # None. The hard ``raise`` here used to block such sessions at
        # build time even though their main path doesn't need an
        # Anthropic SDK at all.
        llm_client: Optional[Any] = None
        if api_key:
            try:
                client_cls = ClientRegistry.get("anthropic")
                llm_client = client_cls(api_key=api_key)
            except Exception as exc:
                logger.warning(
                    f"[{self._session_id}] could not build the optional "
                    f"Anthropic fallback client: {exc}. Out-of-pipeline "
                    f"tools that need ``session.llm_client`` will see None."
                )
                llm_client = None
        else:
            logger.info(
                f"[{self._session_id}] no Anthropic key configured; "
                f"skipping fallback client build. The main session path "
                f"uses the manifest's Stage 6 provider — this only "
                f"affects out-of-pipeline tools that consult "
                f"``session.llm_client``."
            )

        # Cycle 20260501_1 B — publish the (possibly None) shared
        # client + memory cfg to AgentSession's public properties so
        # out-of-pipeline tool calls (memory_distill, etc.) can reuse
        # them. Tools must already null-check ``session.llm_client``
        # since the property has always been ``Optional[Any]``.
        self._llm_client_handle = llm_client
        self._memory_cfg_handle = memory_cfg

        # ── Legacy reflection callback (kept behind APIConfig flag) ──
        use_legacy_reflect = bool(getattr(api_cfg, "use_legacy_reflect", False))
        llm_reflect = (
            self._make_llm_reflect_callback(api_key) if use_legacy_reflect else None
        )

        # ── Native reflection resolver ──
        #
        # Consumed by GenyMemoryStrategy when llm_reflect is None. Closes
        # over the s18 stage handle so the resolver reads the live model
        # override at reflect time (not pipeline-build time).
        #
        # Cycle 20260501_1 A1 — was looking up order=15 (HITL), which
        # gave the resolver the wrong stage's model_override. The
        # memory stage's actual order is 18; the lookup now matches.
        s18_stage = next(
            (st for st in self._prebuilt_pipeline.stages if getattr(st, "order", None) == 18),
            None,
        )

        # ── Memory v2 PR 7 — LLMSummaryCompactor wiring ──
        #
        # Plan §2.1 — once context_window_budget * 0.8 is reached the
        # s02 ContextStage triggers its compactor. The historical
        # default is the placeholder ``SummaryCompactor`` that emits a
        # canned "[summary]" sentence — useful as a no-cost shim but
        # not actually compaction. Wire the real LLM-backed compactor
        # here so the per-stage memory model (already pushed onto s02
        # at line 1477) drives the summarisation prompt. Falls back to
        # the placeholder when no per-stage override is set.
        s02_stage = next(
            (st for st in self._prebuilt_pipeline.stages if getattr(st, "order", None) == 2),
            None,
        )
        if s02_stage is not None:
            try:
                # PR 8 — use the persisting subclass so each compaction
                # also lands in ``memory/compactions/`` + the audit log.
                # When ``self._memory_manager`` is None (rare; tests),
                # the wrapper is harmless — record_compaction inside
                # the wrapper guards on the manager being None.
                from service.memory.persisting_compactor import (
                    PersistingLLMSummaryCompactor,
                )
                compactor = PersistingLLMSummaryCompactor(
                    keep_recent=10,
                    resolve_cfg=lambda state, _stage=s02_stage: _stage.resolve_model_config(state),
                    has_override=lambda _stage=s02_stage: getattr(_stage, "_model_override", None) is not None,
                    client_getter=lambda state: getattr(state, "llm_client", None),
                    memory_manager=self._memory_manager,
                )
                # Direct slot mutation — the LLMSummaryCompactor
                # carries bound callbacks that can't be expressed via
                # the registry-based ``set_strategy(impl_name, config)``
                # path. The slot lives on the stage instance; we own
                # it for the lifetime of this AgentSession.
                if hasattr(s02_stage, "_slots") and "compactor" in s02_stage._slots:
                    s02_stage._slots["compactor"].strategy = compactor
                    logger.debug(
                        f"[{self._session_id}] s02 compactor → LLMSummaryCompactor (PR 7)"
                    )
            except Exception:
                logger.debug(
                    f"[{self._session_id}] LLMSummaryCompactor wire failed — "
                    "falling back to placeholder",
                    exc_info=True,
                )
        # ReflectionResolver was retired upstream (geny-executor 1.20.0,
        # D5). Reflection / promotion now flow through MemoryStage itself
        # via ``MemoryHooks.should_reflect`` / ``should_auto_promote``;
        # the legacy resolver helper is no longer needed.
        reflection_resolver = None
        _ = s18_stage  # silence unused-name linters when the resolver is gone

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
        # J.1 (cycle 20260426_3) — settings-driven tail-block composition.
        # Falls back to the historical [DateTimeBlock, MemoryContextBlock]
        # chain when settings.json:persona.tail_blocks_by_role is silent.
        # Cycle 20260503_7 — append :class:`HostMemoryToolsBlock` after
        # MemoryContextBlock so the agent sees Geny's *concrete* tool
        # catalogue (memory_categories / memory_list / memory_read /
        # memory_search / memory_pin / memory_write / memory_update)
        # right after the Pinned Facts + Relevant Knowledge data
        # blocks. The executor's generic Memory Usage policy lives
        # inside the host block so the agent gets policy + tools in
        # one coherent section without requiring executor-level
        # tool-name knowledge.
        from service.persona.blocks_resolver import resolve_tail_blocks
        from service.memory.host_memory_tools_block import HostMemoryToolsBlock
        _role_key = (
            self._role.value if self._role and hasattr(self._role, "value")
            else "worker"
        )
        _tail_blocks = resolve_tail_blocks(_role_key) or [
            DateTimeBlock(),
            MemoryContextBlock(),
        ]
        # Idempotent append — settings-driven configurations that
        # already declared the host_memory_tools block keep theirs
        # without duplication.
        if not any(
            getattr(b, "name", "") == "host_memory_tools" for b in _tail_blocks
        ):
            _tail_blocks = list(_tail_blocks) + [HostMemoryToolsBlock()]

        # Whiteboard P2b — inject the SpotlightContextBlock so every
        # session sees the user's active spotlight items at prompt
        # build time. Empty-render when no spotlights active, so the
        # block costs nothing for sessions that never use the feature.
        # Idempotent — never appended twice.
        try:
            from service.whiteboard.spotlight_block import SpotlightContextBlock
        except Exception:  # noqa: BLE001
            SpotlightContextBlock = None  # type: ignore[assignment]
        if SpotlightContextBlock is not None and not any(
            getattr(b, "name", "") == "whiteboard_spotlight" for b in _tail_blocks
        ):
            _tail_blocks = list(_tail_blocks) + [SpotlightContextBlock()]

        # TTFT (executor >=2.50.0) — stable-first ordering. The executor
        # splits the system prompt at the FIRST volatile block (clock,
        # retrieved memory) and keeps only what precedes it in the cached
        # prefix. Stable blocks (host memory-tool catalogue, spotlight)
        # ordered after a volatile one would ride the uncached turn
        # context every turn for no reason. Stable partition — relative
        # order within each group is preserved, and on older executor
        # pins (no ``volatile`` attr anywhere) this is a no-op.
        _tail_blocks = [
            b for b in _tail_blocks if not getattr(b, "volatile", False)
        ] + [b for b in _tail_blocks if getattr(b, "volatile", False)]

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
                tail_blocks=_tail_blocks,
            )
        else:
            # MutablePromptBuilder (executor >=2.27.0) instead of a plain
            # ComposablePromptBuilder so the session can edit its OWN persona
            # via the built-in ``env`` tool (self-modifying environment) while
            # the dynamic tail blocks (datetime / memory / spotlight) keep
            # rendering each turn. The editable base = persona_text.
            from geny_executor.stages.s03_system.builders import (
                MutablePromptBuilder,
            )

            system_builder = MutablePromptBuilder(
                prompt=persona_text, blocks=list(_tail_blocks)
            )
        # PR-D.5.1 — seed the executor 1.3.0 WorkspaceStack into
        # ToolContext.extras at session-build time. EnterWorktreeTool /
        # ExitWorktreeTool will push/pop on it; LSPTool reads
        # workspace.cwd through it. Tools that don't know about
        # workspace see no behaviour change because they keep using
        # working_dir directly.
        #
        # Falls back to None when executor 1.3.0 isn't available
        # (older pin); the seed becomes a no-op and tools default to
        # working_dir as they did pre-1.3.0.
        _workspace_stack = None
        try:
            from geny_executor.workspace import Workspace, WorkspaceStack
            from pathlib import Path as _Path
            _workspace_stack = WorkspaceStack(
                initial=Workspace(cwd=_Path(working_dir or ".")),
            )
        except ImportError:
            pass

        _tool_extras: Dict[str, Any] = {}

        # Per-environment tool settings (Settings → Tool Settings): each
        # schema's key IS the ctx.extras key its tool reads (e.g. web_search).
        # Set first so the reserved runtime handles below always win on the
        # (sanitize-prevented) chance of a collision.
        for _ts_key, _ts_val in self._load_tool_settings().items():
            _tool_extras[_ts_key] = _ts_val

        # Google Workspace OAuth token for the native google_* tools — minted
        # fresh per session from the stored refresh token. None when not
        # connected (the tools are gated out anyway via feature:google_connected).
        try:
            from service.google import google_tool_extras

            _g = google_tool_extras()
            if _g:
                _tool_extras["google"] = _g
        except Exception:  # noqa: BLE001 — never block session build on this
            pass

        # SSH servers for the native ssh_* tools — the user's configured server
        # list (host/user/password/key), handed to the executor per session. The
        # executor persists it to <storage_path>/ssh/servers.json and resolves a
        # server by NAME at call time, so the agent never handles a credential.
        # The tools are gated out via feature:ssh_enabled unless a valid server
        # exists (compute_satisfied_config), so injecting here is harmless when
        # SSH is unused.
        try:
            from service.config import get_config_manager
            from service.config.sub_config.tools.ssh_config import SSHConfig

            _ssh_cfg = get_config_manager().load_config(SSHConfig)
            if _ssh_cfg.enabled and _ssh_cfg.servers:
                _tool_extras["ssh"] = {"servers": list(_ssh_cfg.servers)}
        except Exception:  # noqa: BLE001 — never block session build on this
            pass

        # Atlassian credentials for the native jira_* / confluence_* tools —
        # site URL + API token from the global AtlassianConfig. Gated out via
        # feature:atlassian_connected unless the config is complete, so
        # injecting here is harmless when Atlassian is unused.
        try:
            from service.config import get_config_manager
            from service.config.sub_config.tools.atlassian_config import (
                AtlassianConfig,
            )

            _atl_cfg = get_config_manager().load_config(AtlassianConfig)
            if _atl_cfg.is_connected():
                _tool_extras["atlassian"] = _atl_cfg.executor_extras()
        except Exception:  # noqa: BLE001 — never block session build on this
            pass

        # STT provider for the native Audio* tools (executor 2.64.0) — the
        # Whisper endpoint config becomes the serializable provider spec the
        # executor's openai_compatible client consumes. Gated out via
        # feature:stt_enabled unless enabled+configured, so injecting here is
        # harmless when STT is unused.
        try:
            from service.config import get_config_manager as _gcm_stt
            from service.config.sub_config.stt.whisper_config import WhisperConfig

            _stt_cfg = _gcm_stt().load_config(WhisperConfig)
            if getattr(_stt_cfg, "enabled", False) and getattr(_stt_cfg, "api_url", ""):
                _tool_extras["stt"] = {
                    "provider": "openai_compatible",
                    "api_url": _stt_cfg.api_url,
                    "model": _stt_cfg.model,
                    "language": getattr(_stt_cfg, "language", None) or None,
                    "timeout": float(getattr(_stt_cfg, "timeout_seconds", 300) or 300),
                    "temperature": float(getattr(_stt_cfg, "temperature", 0.0) or 0.0),
                }
        except Exception:  # noqa: BLE001 — never block session build on this
            pass

        if _workspace_stack is not None:
            _tool_extras["workspace_stack"] = _workspace_stack

        # SendUserFile delivery channel (workspace-canvas P1) — lets the agent
        # return files to the user as chat attachments. Files are materialised
        # under this session's storage (workspace/outputs/) and drained per turn by
        # consume_user_file_attachments(). Without this the executor's built-in
        # SendUserFile tool errors with NO_CHANNEL.
        if self.storage_path:
            try:
                from service.executor.user_file_channel import SessionUserFileChannel

                self._user_file_channel = SessionUserFileChannel(
                    self._session_id, self.storage_path
                )
                _tool_extras["user_file_channel"] = self._user_file_channel
            except Exception:  # noqa: BLE001 — never block session build on this
                self._user_file_channel = None

        # Audit 2026-06-18 (GAP A/B) — wire the host's task / cron /
        # sub-agent runtime (boot-set on app.state) into ToolContext.extras
        # so the executor's built-in TaskCreate / Task* / Cron* / Agent
        # tools actually function. Without these the tools raise
        # "not configured" at call time. Read-only handles; tools that
        # don't use them are unaffected.
        try:
            from service.execution.agent_executor import get_app_state

            _app_state = get_app_state()
        except Exception:  # noqa: BLE001 — never block session build on this
            _app_state = None
        if _app_state is not None:
            for _rt_key in (
                "task_registry",
                "task_runner",
                "cron_store",
                "cron_runner",
            ):
                _rt_val = getattr(_app_state, _rt_key, None)
                if _rt_val is not None:
                    # Scope the cron store to THIS session so every cron the
                    # agent self-schedules is owned by it (→ deleted with it).
                    if _rt_key == "cron_store":
                        _rt_val = _SessionScopedCronStore(_rt_val, self._session_id)
                    _tool_extras[_rt_key] = _rt_val
            _orchestrator = getattr(_app_state, "subagent_orchestrator", None)
            if _orchestrator is not None:
                # Inline `Agent` tool reads this from extras (the
                # `[DELEGATE]` path uses the pipeline's own registry slot).
                _tool_extras["agent_orchestrator"] = _orchestrator
            _sa_manager = getattr(_app_state, "subagent_manager", None)
            if _sa_manager is not None:
                # SubAgent* tools — persistent sub-agents (executor 2.7.0).
                _tool_extras["subagent_manager"] = _sa_manager
        # Sub-agent credential/provider inheritance (audit 2026-06-25): the
        # one-shot Agent tool (run_subagent) has no PipelineState handle, so it
        # reads these from extras to seed its ephemeral sub-state's Stage-6 auth.
        # (Ad-hoc persistent SubAgentSpawn inherits via the manager's
        # credentials_provider callback, which reads the same fields off the agent.)
        if self._resolved_credentials is not None:
            _tool_extras["subagent_credentials"] = self._resolved_credentials
        if self._primary_provider:
            _tool_extras["subagent_parent_provider"] = self._primary_provider

        attach_kwargs: Dict[str, Any] = {
            "system_builder": system_builder,
            "tool_context": ToolContext(
                session_id=self._session_id,
                working_dir=working_dir,
                storage_path=self.storage_path,
                # Host-side fs/Doc tools are path-guarded INTO the workspace:
                # without this, a relative-or-absolute path could read or
                # overwrite the session's own persistence tree (memory/,
                # transcripts/, synapse.db, checkpoints/) sitting one level
                # up. Sandboxed tools are already confined to /workspace by
                # the GAPT bind; this closes the host-side half. (Host Bash
                # runs a real shell and cannot be path-guarded — its cwd
                # moves into the workspace, and true containment for it is
                # the sandbox.)
                # The cloud is a SEPARATE root, not a subpath: the guard
                # resolves symlinks before checking containment, so
                # `cloud/x` only becomes legal by listing the cloud here.
                allowed_paths=(
                    [p for p in (working_dir, cloud_dir) if p] or None
                ),
                extras=_tool_extras,
            ),
            # Intentionally NOT passing ``llm_client`` here.
            #
            # ``Pipeline._resolve_llm_client`` checks ``attach_runtime``'s
            # llm_client *first* and only falls back to the manifest's
            # Stage-6 provider when that's None. So an Anthropic
            # fallback client passed here pre-empted the per-Environment
            # provider choice for *every* session — the manifest named
            # one provider, state.llm_client said AnthropicClient,
            # Stage 6 hit api.anthropic.com with a stale key, 401.
            #
            # The fallback Anthropic SDK client we build above is only
            # consulted by out-of-pipeline tools that call
            # ``session.llm_client`` directly (e.g. ``memory_distill``);
            # it lives on ``self._llm_client_handle`` for that purpose
            # and must NOT enter the pipeline state.
        }

        # Forward the executor MemoryProvider on `state.session_runtime`
        # so any stage / tool / hook that wants to reach the unified
        # memory surface (curated handle, vector search, scope-aware
        # promotion) can do `getattr(state.session_runtime,
        # "memory_provider", None)`. The legacy retriever / strategy /
        # persistence triple still attaches below — both paths coexist
        # during the cut-over window.
        if self._memory_provider is not None:
            from types import SimpleNamespace
            attach_kwargs["session_runtime"] = SimpleNamespace(
                memory_provider=self._memory_provider,
                session_id=self._session_id,
                username=self._owner_username or "",
            )

        # G6.3: forward host-side permission rules + mode. Returns an
        # empty dict when no rule files are present (every tool stays
        # allowed) so older executor builds without the kwarg keep
        # working. Mode defaults to "advisory" — G6.4 flips
        # worker_adaptive to "enforce" once the timeline UI shows the
        # permission.* events.
        #
        # Phase 9.9.2 — load the manifest's
        # ``host_selections.permissions`` so per-env narrowing actually
        # shrinks the rule set. ``None`` here means "no manifest
        # available" → wildcard / keep all.
        try:
            from service.permission import install as _perm_install
            host_perm_selection = self._load_permission_host_selection()
            attach_kwargs.update(
                _perm_install.attach_kwargs(host_selection=host_perm_selection)
            )
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
            attach_kwargs.update(
                _hook_attach_kwargs(
                    host_selection=self._load_host_selection("hooks"),
                )
            )
        except Exception:
            logger.debug(
                "_build_pipeline: hook install failed; continuing without runner",
                exc_info=True,
            )

        if self._memory_provider is not None:
            # PR-C1 (executor 1.20.0): provider-driven Stage 2 / Stage 18.
            # All retrieval policy is captured in a single ``MemoryHooks``
            # instance; the same instance is attached to the provider via
            # ``set_hooks`` and passed into ``MemoryAwareRetriever`` so
            # every layer (retrieval, record_turn fan-out, reflection
            # gate) sees the same policy view.
            from service.memory.dedupe_strategy import GenyDedupeStrategy
            from service.memory.types import CATEGORY_DESCRIPTIONS as _CATEGORY_DESCRIPTIONS

            # ── 1. Hooks (single bag of policy + business callbacks)
            hooks_kwargs: Dict[str, Any] = dict(
                max_inject_chars=int(max_inject_chars),
                enable_vector_search=bool(_tuning["enable_vector_search"]),
                recent_turns=int(_tuning["recent_turns"]),
                slim_mode=bool(_tuning.get("slim_mode", False)),
                always_render_vault_map=bool(
                    _tuning.get("always_render_vault_map", True)
                ),
                vault_descriptions=dict(_CATEGORY_DESCRIPTIONS),
            )
            # Graph-aware retrieval (geny-executor >= 2.39.0): append
            # graph-connected notes (Personalized PageRank over the knowledge
            # graph) to the direct hits. Additive — never reorders/evicts a
            # direct hit — so it's safe to default on; config-overridable via
            # the memory tuning block. Guarded by a field check so an older
            # executor (without these MemoryHooks fields) can't break init.
            try:
                from dataclasses import fields as _dc_fields
                _hook_fields = {f.name for f in _dc_fields(MemoryHooks)}
            except Exception:  # noqa: BLE001
                _hook_fields = set()
            if "graph_aware" in _hook_fields:
                hooks_kwargs["graph_aware"] = bool(_tuning.get("graph_aware", True))
                hooks_kwargs["graph_top_k"] = int(_tuning.get("graph_top_k", 5))
                hooks_kwargs["graph_alpha"] = float(_tuning.get("graph_alpha", 0.5))
            # Identity card + ambient-noise exclusion (executor >= 2.64.4).
            # The card is the never-dropped 이름/호칭/금기 channel; screen
            # observations stay out of the AUTOMATIC search layers (they were
            # 59% of a real vault and drowned recall in noise).
            if "identity_card_chars" in _hook_fields:
                hooks_kwargs["identity_card_chars"] = int(
                    _tuning.get("identity_card_chars", 600)
                )
            if "search_exclude_categories" in _hook_fields:
                hooks_kwargs["search_exclude_categories"] = tuple(
                    _tuning.get("search_exclude_categories", ("observations",))
                )
            if "category_boosts" in _tuning and isinstance(
                _tuning["category_boosts"], dict
            ):
                hooks_kwargs["category_boosts"] = dict(_tuning["category_boosts"])
            if "pin_budget_ratio" in _tuning:
                # The retriever reads `layer_budget_ratio["pinned"]`.
                # Override only the pinned slot so other layers keep
                # the default ratio.
                from geny_executor.memory.provider import (
                    _DEFAULT_LAYER_BUDGET_RATIO,
                )

                ratio = dict(_DEFAULT_LAYER_BUDGET_RATIO)
                ratio["pinned"] = float(_tuning["pin_budget_ratio"])
                hooks_kwargs["layer_budget_ratio"] = ratio
            hooks = MemoryHooks(**hooks_kwargs)
            self._memory_provider.set_hooks(hooks)
            self._memory_hooks = hooks  # store for _install_memory_hooks

            # Wire the post-write callbacks (after_record_turn driver
            # for ConversationArchiver + DmArchiver). This was
            # previously called from ``_init_memory_provider`` but at
            # that point ``self._memory_hooks`` is still ``None`` and
            # the install short-circuited — every conversation/dm
            # archive was silently dropped. Now that the hooks bag
            # exists we install for real.
            try:
                self._install_memory_hooks()
            except Exception:  # noqa: BLE001
                logger.debug(
                    "[%s] _install_memory_hooks (post-pipeline) failed",
                    self._session_id, exc_info=True,
                )

            # ── 2. Stage 2 retriever (provider + hooks, no host duck-type)
            attach_kwargs["memory_retriever"] = MemoryAwareRetriever(
                self._memory_provider, hooks=hooks,
            )
            # ── 3. Stage 18 strategy (Geny dedupe wraps ProviderDrivenStrategy)
            attach_kwargs["memory_strategy"] = GenyDedupeStrategy(self._memory_provider)
            # ── 4. Persistence is now a no-op — provider owns every write
            attach_kwargs["memory_persistence"] = NullPersistence()
            # `llm_reflect`, `reflection_resolver`, `curated_knowledge_manager`
            # and `max_inject_chars` are now host-supplied via the hooks
            # bag (or — for reflection — through MemoryStage's native path).
            # They remain defined locally only so the older code paths
            # below (e.g. system-prompt builders) compile; nothing
            # downstream of this block consumes the legacy values.

        # GAPT sandbox: when this session is bound to a GAPT workspace, hand
        # the executor the SandboxHandle so tools (forge_tool / SandboxExecTool /
        # gapt_* via the MCP bridge) execute IN the workspace (docker exec).
        #
        # The sandbox is a TOOL surface and nothing else (executor 2.68.0):
        # no provider is ever spawned into it. The LLM — Claude Code, Codex,
        # any of them — is called from the HOST with the credentials Geny
        # configured, which is what keeps rotating subscription OAuth working
        # (a provider running inside the container hit the refreshToken
        # rotation 401; that path is gone).
        if getattr(self, "_gapt_sandbox", None) is not None:
            attach_kwargs["sandbox"] = self._gapt_sandbox
            # save_pack (executor >=2.32.0): let the agent persist
            # [this workspace + the tools it forged + skills it authored] as a
            # reusable Sandbox Tool Pack via env(action="save_pack").
            _pack_persist = self._make_pack_persistence()
            if _pack_persist is not None:
                attach_kwargs["pack_persistence"] = _pack_persist

        # Self-modifying environment (executor >=2.26.0): persist the session's
        # evolved env overlay to its OWN storage so ``env(action="save")`` is
        # session-scoped + survives resume. Restored just below.
        _env_persist = self._make_env_persistence()
        if _env_persist is not None:
            attach_kwargs["env_persistence"] = _env_persist
        # Tool-setting descriptors (executor >=2.28.0) so env get_settings can
        # mask secrets accurately + describe what each tool needs (API keys, …).
        try:
            from service.tool_settings import get_tool_setting_schemas

            attach_kwargs["env_settings_schemas"] = get_tool_setting_schemas()
        except Exception:  # noqa: BLE001
            logger.debug("[%s] tool-setting schemas unavailable", self._session_id)

        self._pipeline = self._prebuilt_pipeline
        self._pipeline.attach_runtime(**attach_kwargs)
        # Re-apply any previously-saved env overlay now that the controller is
        # wired (best-effort; never blocks session start).
        self._restore_env_overlay()
        # B.1 (cycle 20260426_1) — bridge UI session limits into the
        # bound Pipeline's PipelineConfig so user-supplied
        # ``max_iterations`` is enforced by the executor's iteration
        # guards / loop controllers. Without this the manifest default
        # (typically 50) wins and the Sessions UI control is cosmetic.
        self._apply_session_limits_to_pipeline()
        self._preset_name = f"env:{self._env_id}" if self._env_id else "env"

        # G9.x: register optional Phase-7 strategies on stage slot
        # registries so manifest preset overrides can select them by
        # name. Each helper is a no-op when its target stage/slot is
        # missing or the executor pin is older than the strategy.
        try:
            from service.strategies import register_mcp_resource_retriever

            register_mcp_resource_retriever(self._pipeline)
        except Exception:
            logger.debug(
                "_build_pipeline: optional strategy registration failed",
                exc_info=True,
            )

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

        # G10.1: attach a FileCredentialStore to the MCPManager so
        # OAuth-required servers persist tokens across pipeline
        # restarts. No-op when the pipeline has no MCPManager.
        try:
            from service.credentials import install_credential_store

            install_credential_store(self._pipeline)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"[{self._session_id}] credential store install skipped: {exc}",
                exc_info=True,
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

        # TTFT (executor >=2.50.0): pre-warm the LLM backend in the
        # background AFTER all runtime wiring — TLS pool prewarm for SDK
        # providers, ``--version`` handshake for the CLI — so the
        # session's first turn skips the cold start. attach_runtime may
        # have bumped the client generation (sandbox), which drops the
        # executor's build-time warm memo; this post-wiring call warms
        # the client the first turn will actually use. Fire-and-forget;
        # older executor pins without warmup() are a silent no-op.
        try:
            _warm = getattr(self._pipeline, "warmup", None)
            if callable(_warm):
                _warm_task = asyncio.get_running_loop().create_task(_warm())
                _warm_task.add_done_callback(lambda t: t.cancelled() or t.exception())
        except RuntimeError:
            pass  # no running loop (sync construction path)

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
        # Guarded: this runs on every turn, and classification is a hint used
        # to label the turn — not a precondition for running it. An unguarded
        # call here meant a classifier failure took down the whole turn, which
        # is precisely what the metadata-resolution path next to it has always
        # protected against.
        try:
            stm_role = _classify_input_role(input_text)
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] input-role classification failed; treating the turn as "
                "user input", self._session_id, exc_info=True,
            )
            stm_role = ""
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
                # workspace-canvas P2: persist this turn's uploads into the
                # session files-workspace (workspace/uploads/) so they outlive
                # the global upload store and stay tool-reachable in later
                # turns, and REQUIRE the agent to process them this turn
                # (uploaded-file must-use contract). Images stay vision blocks;
                # the note only demands tool-processing for non-image files.
                staged = self._stage_attachments_to_workspace(attachments)
                non_image = [s for s in staged if not s["mime"].startswith("image/")]
                if non_image:
                    office_exts = (".docx", ".xlsx", ".pptx")
                    audio_exts = (".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".flac")
                    # Never promise a gated-out tool (ghost-tool lesson):
                    # the AudioTranscribe hint appears only when the same
                    # condition that satisfies feature:stt_enabled holds.
                    stt_on = False
                    try:
                        from service.config import get_config_manager as _gcm_h
                        from service.config.sub_config.stt.whisper_config import (
                            WhisperConfig as _WC_h,
                        )

                        _c = _gcm_h().load_config(_WC_h)
                        stt_on = bool(getattr(_c, "enabled", False) and getattr(_c, "api_url", ""))
                    except Exception:  # noqa: BLE001
                        stt_on = False

                    def _hint(entry: dict) -> str:
                        # doc_* tools address from the STORAGE ROOT
                        rel = entry.get("rel_path") or entry["abs_path"]
                        # executor built-ins (Audio*) address from working_dir
                        ws_rel = entry.get("ws_rel_path") or rel
                        name_l = str(entry["name"]).lower()
                        if name_l.endswith(office_exts):
                            return (
                                f"- {entry['name']} ({entry['mime']}, {entry['size']} bytes): "
                                f"{rel} — OFFICE DOCUMENT: do NOT Read it (binary). "
                                f"Use doc_analyze('{rel}') to get its addressable outline, "
                                f"then doc_edit for precise changes (the user sees the "
                                f"updated preview in the Canvas tab), doc_convert for "
                                f"pdf/png/text, doc_generate for new documents."
                            )
                        if name_l.endswith(audio_exts) or str(entry["mime"]).startswith("audio/"):
                            if stt_on:
                                return (
                                    f"- {entry['name']} ({entry['mime']}, {entry['size']} bytes): "
                                    f"{ws_rel} — AUDIO FILE: do NOT Read it (binary). "
                                    f"Use AudioTranscribe('{ws_rel}') to get the transcript "
                                    f"(cached as {entry['name']}.transcript.json for later turns)."
                                )
                            return (
                                f"- {entry['name']} ({entry['mime']}, {entry['size']} bytes): "
                                f"{ws_rel} — AUDIO FILE (binary; no STT model is configured, "
                                f"so it cannot be transcribed — tell the user if they ask)."
                            )
                        return (
                            f"- {entry['name']} ({entry['mime']}, {entry['size']} bytes): "
                            f"{entry['abs_path']} — open with Read."
                        )

                    lines = "\n".join(_hint(s) for s in non_image)
                    input_text = (input_text or "") + (
                        "\n\n[attached files — saved to your session workspace]\n"
                        f"{lines}\n"
                        "You MUST process these file(s) in THIS turn with the tools named "
                        "above. The files remain at the same paths for later turns."
                    )
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

    def _stage_attachments_to_workspace(
        self, attachments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Copy this turn's uploaded attachments into the session
        files-workspace (``<storage>/workspace/uploads/``).

        Part of the workspace-canvas P2 contract: the global upload store
        (``/static/uploads``, content-addressed, not volume-backed) is not the
        agent's space — the session keeps its own copy so the file stays
        tool-reachable (Read/Glob) in this and later turns. Returns
        ``[{name, mime, size, abs_path, rel_path}]`` for the staged files.
        Best-effort per file; never raises.
        """
        staged: List[Dict[str, Any]] = []
        if not self.storage_path:
            return staged
        try:
            import base64
            import shutil
            from pathlib import Path as FilePath
            from urllib.parse import unquote, urlparse

            from service.executor.user_file_channel import _safe_filename

            uploads_dir = FilePath(self.storage_path) / "workspace" / "uploads"
            for att in attachments or []:
                try:
                    if not isinstance(att, dict):
                        continue
                    # Ambient screen frames are context, not user content.
                    if att.get("source") == "screen_observation":
                        continue
                    name = _safe_filename(att.get("name") or "attachment")
                    # Audio without a recognizable extension would draw an
                    # AudioTranscribe hint the tool then rejects (suffix-
                    # gated) — backfill from the MIME type.
                    _mime0 = str(att.get("mime_type") or "")
                    if _mime0.startswith(("audio/", "video/webm")):
                        _audio_ext_map = {
                            "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
                            "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
                            "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/m4a": ".m4a",
                            "audio/ogg": ".ogg", "audio/webm": ".webm", "video/webm": ".webm",
                            "audio/flac": ".flac", "audio/x-flac": ".flac",
                        }
                        _known = (".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".flac")
                        if not name.lower().endswith(_known):
                            name += _audio_ext_map.get(_mime0, ".webm")
                    url = att.get("url") or ""
                    src: Optional[FilePath] = None
                    if url.startswith("file://"):
                        src = FilePath(unquote(urlparse(url).path))
                    dest = uploads_dir / name
                    # Same-name handling: reuse ONLY when the bytes match
                    # (upload store's content sha when present, else size);
                    # otherwise pick a unique name — silently serving an
                    # older file (or clobbering an earlier turn's) breaks
                    # the "files remain at the same paths" promise.
                    att_sha = str(att.get("sha256") or att.get("attachment_id") or "")
                    if dest.exists():
                        same = dest.stat().st_size == (
                            src.stat().st_size if (src is not None and src.is_file())
                            else len(base64.b64decode(att["data"], validate=False)) if att.get("data")
                            else -1
                        )
                        if same and len(att_sha) == 64:
                            import hashlib as _hl
                            _h = _hl.sha256()
                            with dest.open("rb") as _fh:
                                for _chunk in iter(lambda: _fh.read(1 << 20), b""):
                                    _h.update(_chunk)
                            same = _h.hexdigest() == att_sha
                        if not same:
                            stem, dot, ext2 = name.partition(".")
                            for _i in range(2, 100):
                                cand = f"{stem} ({_i}){dot}{ext2}" if dot else f"{stem} ({_i})"
                                if not (uploads_dir / cand).exists():
                                    name = cand
                                    dest = uploads_dir / name
                                    break
                    if src is not None and src.is_file():
                        if not (dest.exists() and dest.stat().st_size == src.stat().st_size):
                            uploads_dir.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dest)
                    elif att.get("data"):
                        raw = base64.b64decode(att["data"], validate=False)
                        if not (dest.exists() and dest.stat().st_size == len(raw)):
                            uploads_dir.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(raw)
                    else:
                        continue
                    staged.append({
                        "name": name,
                        "mime": att.get("mime_type") or "application/octet-stream",
                        "size": dest.stat().st_size,
                        "abs_path": str(dest),
                        # TWO bases on purpose — the tool families resolve
                        # relative paths differently:
                        #   * rel_path (storage-root): Geny's doc_* tools
                        #     join against the STORAGE ROOT and document
                        #     'workspace/uploads/…' addressing.
                        #   * ws_rel_path (workspace): the executor's
                        #     built-ins (Audio*, Read) resolve against
                        #     working_dir = <storage>/workspace.
                        # A single string breaks one family or the other.
                        "rel_path": f"workspace/uploads/{name}",
                        "ws_rel_path": f"uploads/{name}",
                    })
                except Exception:  # noqa: BLE001 — one bad attachment ≠ broken turn
                    logger.warning(
                        "[%s] failed to stage attachment %r",
                        self._session_id, att.get("name") if isinstance(att, dict) else att,
                        exc_info=True,
                    )
        except Exception:  # noqa: BLE001
            logger.warning("[%s] attachment staging unavailable", self._session_id, exc_info=True)
        return staged

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

    def _promote_turn_screen_frames(
        self,
        attachments: Optional[List[Dict[str, Any]]],
        final_output: str,
    ) -> Optional[List[str]]:
        """Persist screen frames this turn actually SPOKE about into the
        permanent ``memory/attachments/`` bucket, returning bare names for
        the execution record to embed (``record_execution(media=...)``).
        One generalized gate covers every caller: a ``[SILENT]`` reply
        promotes nothing, so unspoken glances stay in the ambient
        observations buffer and age out with it. Fully guarded."""
        if not attachments:
            return None
        try:
            from service.vtuber.screen_observation import promote_used_frames

            media = promote_used_frames(
                self._session_id, attachments, final_output,
            )
            return media or None
        except Exception:  # noqa: BLE001
            logger.debug(
                f"[{self._session_id}] screen frame promotion skipped",
                exc_info=True,
            )
            return None

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
        # Cycle 20260430_2 A3 — callers that already know what kind of
        # InteractionEvent this invoke represents can pass an explicit
        # `source_metadata=...` (the DM-trigger path does this; the
        # thinking-trigger path will in A5; the chat path in A6). When
        # absent, `infer_input_metadata` parses the well-known prompt
        # prefixes (``[SYSTEM] You received...`` / ``[INBOX from X]``)
        # to fill the gap. The metadata is then applied at the
        # *single* STM write site (s18 via GenyDedupeStrategy) — see
        # cycle 20260501_1 C.
        source_metadata = kwargs.pop("source_metadata", None)

        # Cycle 20260501_1 C — resolve the metadata for the upcoming
        # user / assistant turn here, but DO NOT call record_message.
        # The pending metadata gets stamped on state.metadata below
        # and s18 (GenyDedupeStrategy) records both messages with
        # their full InteractionEvent metadata exactly once.
        stm_role: Optional[str] = None
        pending_metadata: Dict[str, Any] = {}
        if self._memory_manager:
            try:
                from service.memory.interaction_event import (
                    CounterpartRole,
                    Direction,
                    Kind,
                    canonical_user_id,
                    infer_input_metadata,
                    make_event_metadata,
                )
                stm_role = _classify_input_role(input_text)
                event_meta = source_metadata
                if event_meta is None:
                    event_meta = infer_input_metadata(
                        input_text=input_text,
                        recorder_agent=self,
                        role=stm_role,
                    )
                if event_meta:
                    pending_metadata["user"] = event_meta
                # Cycle 20260430_2 A6 — assistant USER_CHAT/OUT
                # metadata can be resolved up front because it
                # mirrors the user's owner_username and is
                # direction-flipped.
                #
                # Cycle 20260501_2 F2 — for *VTuber* sessions, every
                # assistant response is broadcast back to the chat
                # room (or routed via _save_subworker_reply_to_chat_room),
                # so the canonical kind is always USER_CHAT/OUT —
                # regardless of what triggered the turn (user input,
                # internal_trigger, SUB_WORKER_RESULT/assistant_dm).
                # Without this default, session.jsonl line 6 (response
                # to a SUB_WORKER_RESULT) records with metadata=None.
                # Worker / Sub-Worker sessions retain the original
                # narrow trigger because their assistant responses
                # are tool/task results, not chat traffic.
                if stm_role == "user" or self._role == SessionRole.VTUBER:
                    pending_metadata["assistant"] = make_event_metadata(
                        kind=Kind.USER_CHAT,
                        direction=Direction.OUT,
                        counterpart_id=canonical_user_id(self._owner_username),
                        counterpart_role=CounterpartRole.USER,
                    )
            except Exception:
                logger.debug(
                    "Failed to resolve InteractionEvent metadata for the "
                    "upcoming turn — strategy will record without metadata",
                    exc_info=True,
                )
                stm_role = None
                pending_metadata = {}

        # Stream pipeline and log events in real time
        accumulated_output = ""
        total_cost = 0.0
        iterations = 0
        success = True
        error_msg = None
        # Cycle 20260430_1 P0-2 — capture per-turn tool execution log so
        # downstream (`_notify_linked_vtuber`) can synthesise a meaningful
        # `[SUB_WORKER_RESULT]` payload for tool-only turns where the LLM
        # produced no final text. Keyed by `tool_use_id` while in flight,
        # appended to the ordered completion list on `tool.call_complete`.
        tool_calls_in_progress: Dict[str, Dict[str, Any]] = {}
        tool_calls_completed: List[Dict[str, Any]] = []
        # 2.2.0 events tap — CLI-handled tool calls (Bash / Read / Write
        # / Edit / …) keyed by tool_use_id while in flight so the paired
        # ``api.tool_result`` can be timed. Replaces the per-accumulator
        # side table the llm_patches monkey-patch kept.

        # Create PipelineState with session context.
        #
        # R2 (audit 20260425_3): if a checkpoint restore endpoint
        # has stashed a previous PipelineState on ``self._restored_state``,
        # consume it as the starting state for THIS turn instead of
        # the fresh-per-turn default. Cleared after consumption so a
        # second turn doesn't re-apply the same checkpoint. The
        # session_id is rebound because the restored state may have
        # been written under an earlier session id (mid-restart).
        from geny_executor.core.state import PipelineState as _PipelineState

        restored = getattr(self, "_restored_state", None)
        if restored is not None:
            _state = restored
            try:
                _state.session_id = self._session_id
            except Exception:
                logger.warning(
                    f"[{self._session_id}] could not rebind session_id on "
                    "restored state; using fresh state instead"
                )
                _state = _PipelineState(session_id=self._session_id)
            self._restored_state = None  # one-shot
            logger.info(
                f"[{self._session_id}] resumed from checkpoint — "
                f"messages={len(getattr(_state, 'messages', []) or [])}, "
                f"iteration={getattr(_state, 'iteration', 0)}"
            )
        else:
            _state = _PipelineState(session_id=self._session_id)

        # Cycle 20260501_1 C — stamp the pending metadata onto state
        # so GenyDedupeStrategy (s18) applies it when it walks
        # state.messages. We only set the key when we actually
        # resolved metadata for at least one role.
        if pending_metadata:
            _state.metadata["_pending_message_metadata"] = pending_metadata

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

            # Memory learning: fold retrieval/promotion signals into the usage
            # tracker (no-op unless the synapse engine is active).
            self._observe_memory_signal(event_type, event_data)

            # Log pipeline events to session_logger for WebSocket/SSE streaming
            if session_logger:
                if event_type == "tool.call_start":
                    session_logger.log_tool_use(
                        tool_name=event_data.get("name", "unknown"),
                        tool_input=event_data.get("input") or {},
                        tool_id=event_data.get("tool_use_id"),
                    )
                    # Cycle 20260430_1 P0-2 — remember start args so the
                    # paired `tool.call_complete` can fold them into
                    # the per-turn tool_calls log without re-asking the
                    # pipeline.
                    _start_tid = event_data.get("tool_use_id")
                    if _start_tid:
                        tool_calls_in_progress[_start_tid] = {
                            "name": event_data.get("name", "unknown"),
                            "input": event_data.get("input") or {},
                        }
                    # PR-E.4.1 — process-wide tool event ring for the
                    # AdminPanel "Recent Activity" panel.
                    try:
                        from service.telemetry.tool_event_ring import record_event

                        record_event(
                            kind="start",
                            tool_name=str(event_data.get("name", "unknown")),
                            tool_use_id=event_data.get("tool_use_id"),
                            session_id=getattr(self, "session_id", None),
                        )
                    except Exception:  # noqa: BLE001 — telemetry must never break execution
                        pass
                elif event_type == "tool.call_complete":
                    # Cycle 20260430_1 P0-2 — close the per-turn entry
                    # before the existing logging branch runs. Order of
                    # appends matches the order of completion events,
                    # which matches the worker's actual call order.
                    _done_tid = event_data.get("tool_use_id")
                    _started = tool_calls_in_progress.pop(_done_tid, {}) if _done_tid else {}
                    tool_calls_completed.append({
                        "name": (
                            event_data.get("name")
                            or _started.get("name")
                            or "unknown"
                        ),
                        "input": _started.get("input") or {},
                        "is_error": bool(event_data.get("is_error", False)),
                        "duration_ms": int(event_data.get("duration_ms") or 0),
                    })
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
                    # PR-E.4.1 — append complete events too so the panel
                    # can show success/failure + duration.
                    try:
                        from service.telemetry.tool_event_ring import record_event

                        record_event(
                            kind="complete",
                            tool_name=str(event_data.get("name", "unknown")),
                            tool_use_id=event_data.get("tool_use_id"),
                            session_id=getattr(self, "session_id", None),
                            is_error=bool(event_data.get("is_error", False)),
                            duration_ms=int(event_data.get("duration_ms", 0) or 0),
                        )
                    except Exception:  # noqa: BLE001
                        pass
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
                    # PR-E.2.3 — forward full event_data so future executor
                    # versions that emit matched_rule / guard_name details
                    # surface in the timeline detail panel without another
                    # bridge change.
                    session_logger.log_stage_event(
                        event_type="loop_signal",
                        message=f"{event_type}: {signal}",
                        stage_name="loop",
                        stage_order=STAGE_ORDER.get("loop"),
                        iteration=iteration or 0,
                        data={"signal": signal, **dict(event_data)},
                    )

                # PR-E.2.3 — Stage 4 guard outcomes. Today the executor
                # emits guard.check / guard.warn with {passed, guard_name,
                # message}. Surface the failed/warn cases in the timeline
                # so operators can correlate "Denied" loop_signal rows
                # with the guard that produced them.
                elif event_type in ("guard.check", "guard.warn"):
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    passed = bool(event_data.get("passed", True))
                    if not (event_type == "guard.check" and passed):
                        guard_name = event_data.get("guard_name") or "unknown"
                        message = event_data.get("message") or ""
                        session_logger.log_stage_event(
                            event_type="guard_event",
                            message=f"{event_type}: {guard_name} — {message}",
                            stage_name="guard",
                            stage_order=STAGE_ORDER.get("guard"),
                            iteration=iteration or 0,
                            data={
                                "guard_name": guard_name,
                                "message": message,
                                "passed": passed,
                                **dict(event_data),
                            },
                        )
                        # PR-E.4.2 — feed the permission ring when the
                        # rejecting guard is the permission guard.
                        if guard_name == "permission":
                            try:
                                from service.telemetry.permission_ring import record_decision

                                record_decision(
                                    decision="guard_reject",
                                    tool_name=event_data.get("tool_name"),
                                    session_id=getattr(self, "session_id", None),
                                    message=message,
                                )
                            except Exception:  # noqa: BLE001
                                pass

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

                # ── G8.2: MCP FSM state broadcast (Phase 6) ──
                # The executor's MCPManager emits ``mcp.server.state``
                # whenever a server transitions between
                # PENDING / CONNECTED / FAILED / NEEDS_AUTH / DISABLED.
                # Bridge to log_stage_event so the frontend MCP panel
                # (G8.3) can render live status without subscribing
                # directly to the EventBus.
                elif event_type == "mcp.server.state":
                    name = event_data.get("name") or event_data.get("server") or "unknown"
                    state = event_data.get("state") or "unknown"
                    iteration = event.iteration if hasattr(event, "iteration") else 0
                    session_logger.log_stage_event(
                        event_type="mcp_server_state",
                        message=f"MCP {name} → {state}",
                        # Use Stage 3 (System / tool registration) as the
                        # nominal stage anchor for MCP state changes —
                        # that's where MCP tools are exposed to the
                        # registry.
                        stage_name="system",
                        stage_order=STAGE_ORDER.get("system"),
                        iteration=iteration or 0,
                        data=dict(event_data),
                    )

                # Structured provider-error envelopes reach the session
                # log as a sentence the user can act on. Tool events are
                # NOT bridged — Stage 10 logs every dispatch itself.
                elif event_type == "api.error":
                    _bridge_cli_stream_event(
                        session_logger, event_type, event_data,
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

        # Memory learning: end-of-turn flush — scan the final answer for note
        # citations, then reinforce Synapse from this turn's trusted signals.
        await self._flush_memory_learning(accumulated_output)

        # Log execution completion
        if session_logger:
            session_logger.log_stage_execution_complete(
                success=success,
                total_iterations=iterations,
                final_output=accumulated_output[:500] if accumulated_output else None,
                total_duration_ms=duration_ms,
                stop_reason="pipeline_complete" if success else (error_msg or "error"),
            )

        # Cycle 20260501_1 C — assistant STM record is now the
        # responsibility of GenyDedupeStrategy (s18). Pre-cycle this
        # site recorded the assistant message directly with metadata;
        # s18 always re-recorded the same content from state.messages
        # *without* metadata. Result: every turn ended up in STM
        # twice. The dedupe strategy reads
        # state.metadata['_pending_message_metadata'] (stamped at the
        # top of this method) and records the assistant message
        # exactly once, with the correct metadata.

        # Record to long-term memory
        self._execution_count += 1
        if self._memory_manager:
            try:
                _screen_media = self._promote_turn_screen_frames(
                    attachments, accumulated_output,
                )
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
                    media=_screen_media,
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
            # The failure travels WITH the text. Returning only "Error: …" as
            # the output made every caller treat a dead turn as a successful
            # one whose answer happened to begin with the word Error — the
            # session log recorded success, and the chat room stored it as a
            # message from the agent. A user reading the conversation sees the
            # agent calmly announcing "You've hit your session limit".
            return {
                "output": f"Error: {error_msg}",
                "success": False,
                "error": error_msg,
                "total_cost": total_cost,
                "tool_calls": tool_calls_completed,
            }

        return {
            "output": accumulated_output,
            "total_cost": total_cost,
            "tool_calls": tool_calls_completed,
        }

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
        # Cycle 20260430_2 A3 — see ``_invoke_pipeline`` for the rationale
        # on the source_metadata / infer_input_metadata pair.
        source_metadata = kwargs.pop("source_metadata", None)

        # Cycle 20260501_1 C — same path as `_invoke_pipeline`: resolve
        # the InteractionEvent metadata for the upcoming user / assistant
        # turn but defer the actual record_message call to s18
        # (GenyDedupeStrategy). The pending dict is stamped on
        # state.metadata below.
        stm_role: Optional[str] = None
        pending_metadata: Dict[str, Any] = {}
        if self._memory_manager:
            try:
                from service.memory.interaction_event import (
                    CounterpartRole,
                    Direction,
                    Kind,
                    canonical_user_id,
                    infer_input_metadata,
                    make_event_metadata,
                )
                stm_role = _classify_input_role(input_text)
                event_meta = source_metadata
                if event_meta is None:
                    event_meta = infer_input_metadata(
                        input_text=input_text,
                        recorder_agent=self,
                        role=stm_role,
                    )
                if event_meta:
                    pending_metadata["user"] = event_meta
                # Cycle 20260501_2 F2 — VTuber session always defaults
                # the assistant turn to USER_CHAT/OUT (mirror of
                # `_invoke_pipeline`).
                if stm_role == "user" or self._role == SessionRole.VTUBER:
                    pending_metadata["assistant"] = make_event_metadata(
                        kind=Kind.USER_CHAT,
                        direction=Direction.OUT,
                        counterpart_id=canonical_user_id(self._owner_username),
                        counterpart_role=CounterpartRole.USER,
                    )
            except Exception:
                logger.debug(
                    "Failed to resolve InteractionEvent metadata — strategy "
                    "will record without metadata",
                    exc_info=True,
                )
                stm_role = None
                pending_metadata = {}

        accumulated_output = ""
        # 2.2.0 events tap — see _invoke_pipeline (same per-turn table
        # for CLI-handled tool call timing).
        total_cost = 0.0
        iterations = 0
        success = True

        # Create PipelineState with session context.
        #
        # R2 (audit 20260425_3): if a checkpoint restore endpoint
        # has stashed a previous PipelineState on ``self._restored_state``,
        # consume it as the starting state for THIS turn instead of
        # the fresh-per-turn default. Cleared after consumption so a
        # second turn doesn't re-apply the same checkpoint. The
        # session_id is rebound because the restored state may have
        # been written under an earlier session id (mid-restart).
        from geny_executor.core.state import PipelineState as _PipelineState

        restored = getattr(self, "_restored_state", None)
        if restored is not None:
            _state = restored
            try:
                _state.session_id = self._session_id
            except Exception:
                logger.warning(
                    f"[{self._session_id}] could not rebind session_id on "
                    "restored state; using fresh state instead"
                )
                _state = _PipelineState(session_id=self._session_id)
            self._restored_state = None  # one-shot
            logger.info(
                f"[{self._session_id}] resumed from checkpoint — "
                f"messages={len(getattr(_state, 'messages', []) or [])}, "
                f"iteration={getattr(_state, 'iteration', 0)}"
            )
        else:
            _state = _PipelineState(session_id=self._session_id)

        # Cycle 20260501_1 C — stamp the pending metadata for s18.
        if pending_metadata:
            _state.metadata["_pending_message_metadata"] = pending_metadata

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

            # Memory learning: fold retrieval/promotion signals into the usage
            # tracker (no-op unless the synapse engine is active).
            self._observe_memory_signal(event_type, event_data)

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
                    # PR-E.2.3 — forward full event_data so future executor
                    # versions that emit matched_rule / guard_name details
                    # surface in the timeline detail panel without another
                    # bridge change.
                    session_logger.log_stage_event(
                        event_type="loop_signal",
                        message=f"{event_type}: {signal}",
                        stage_name="loop",
                        stage_order=STAGE_ORDER.get("loop"),
                        iteration=iteration or 0,
                        data={"signal": signal, **dict(event_data)},
                    )

                # PR-E.2.3 — Stage 4 guard outcomes. Today the executor
                # emits guard.check / guard.warn with {passed, guard_name,
                # message}. Surface the failed/warn cases in the timeline
                # so operators can correlate "Denied" loop_signal rows
                # with the guard that produced them.
                elif event_type in ("guard.check", "guard.warn"):
                    iteration = event.iteration if hasattr(event, "iteration") else event_data.get("iteration", 0)
                    passed = bool(event_data.get("passed", True))
                    if not (event_type == "guard.check" and passed):
                        guard_name = event_data.get("guard_name") or "unknown"
                        message = event_data.get("message") or ""
                        session_logger.log_stage_event(
                            event_type="guard_event",
                            message=f"{event_type}: {guard_name} — {message}",
                            stage_name="guard",
                            stage_order=STAGE_ORDER.get("guard"),
                            iteration=iteration or 0,
                            data={
                                "guard_name": guard_name,
                                "message": message,
                                "passed": passed,
                                **dict(event_data),
                            },
                        )
                        # PR-E.4.2 — feed the permission ring when the
                        # rejecting guard is the permission guard.
                        if guard_name == "permission":
                            try:
                                from service.telemetry.permission_ring import record_decision

                                record_decision(
                                    decision="guard_reject",
                                    tool_name=event_data.get("tool_name"),
                                    session_id=getattr(self, "session_id", None),
                                    message=message,
                                )
                            except Exception:  # noqa: BLE001
                                pass

                # Mirror of the _invoke_pipeline bridge: structured
                # provider-error envelopes to the SessionLogger.
                elif event_type == "api.error":
                    _bridge_cli_stream_event(
                        session_logger, event_type, event_data,
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

        # Memory learning: end-of-turn flush — scan the final answer for note
        # citations, then reinforce Synapse from this turn's trusted signals.
        await self._flush_memory_learning(accumulated_output)

        if session_logger:
            session_logger.log_stage_execution_complete(
                success=success,
                total_iterations=iterations,
                final_output=accumulated_output[:500] if accumulated_output else None,
                total_duration_ms=duration_ms,
                stop_reason="pipeline_stream_complete",
            )

        # Cycle 20260501_1 C — assistant STM record is owned by s18
        # (GenyDedupeStrategy). See `_invoke_pipeline` for the full
        # rationale.

        self._execution_count += 1
        if self._memory_manager:
            try:
                _screen_media = self._promote_turn_screen_frames(
                    kwargs.get("attachments"), accumulated_output,
                )
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
                    media=_screen_media,
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

        # Mutual-exclusion backstop (audit 2026-06-25): one pipeline per session,
        # so two concurrent turns would corrupt shared STM/per-turn state. The
        # executor's per-session admission lock prevents this for the invoke path;
        # this guard also covers a cross-path race (e.g. astream vs invoke). Reset
        # in the finally below, so a normal sequential turn is never rejected.
        if self._is_executing:
            raise RuntimeError(
                f"[{self._session_id}] a turn is already executing on this session"
            )

        # Freshness check — auto-revive if idle, raise if hard limit
        self._check_freshness()

        # Ensure underlying process is alive (restart if needed)
        await self._ensure_alive()

        self._status = SessionStatus.RUNNING
        self._is_executing = True          # guard: prevent idle monitor interference
        self._current_iteration = 0
        self._execution_start_time = datetime.now()
        # Cycle 20260430_1 P0-1 — clear the per-turn explicit-report flag
        # before `send_direct_message_internal` has a chance to set it.
        self._explicit_subworker_report_sent = False
        thread_id = thread_id or "default"
        effective_max_iterations = max_iterations or self._max_iterations

        # E.1 (cycle 20260426_1) — drain queued runtime refresh at the
        # turn boundary, before pipeline.run_stream sees the state.
        self._apply_pending_runtime_refresh()

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
            err_code, err_type = _extract_executor_error_meta(e)
            self._error_code = err_code
            logger.exception(
                f"[{self._session_id}] Error during invoke: {e} "
                f"(code={err_code or 'n/a'} type={err_type})"
            )

            if session_logger:
                session_logger.log_stage_error(
                    stage_name="invoke",
                    error=str(e),
                    iteration=self._current_iteration,
                    error_code=err_code,
                    exception_type=err_type,
                )
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

        # Mutual-exclusion backstop (audit 2026-06-25) — see invoke(); reset in
        # the finally below, so a normal sequential turn is never rejected.
        if self._is_executing:
            raise RuntimeError(
                f"[{self._session_id}] a turn is already executing on this session"
            )

        # Freshness check — auto-revive if idle
        self._check_freshness()

        # Ensure underlying process is alive (restart if needed)
        await self._ensure_alive()

        self._status = SessionStatus.RUNNING
        self._is_executing = True              # guard: prevent idle monitor interference
        # Cycle 20260430_1 P0-1 — mirror the invoke() reset so streaming
        # turns also get a fresh explicit-report state.
        self._explicit_subworker_report_sent = False
        thread_id = thread_id or "default"

        # E.1 (cycle 20260426_1) — drain queued runtime refresh at the
        # turn boundary, before pipeline.run_stream sees the state.
        self._apply_pending_runtime_refresh()

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

        # See ``invoke()`` for rationale — CLI-handled tools surface as
        # first-class 2.2.0 events, bridged inside ``_astream_pipeline``.
        try:
            async for event in self._astream_pipeline(
                input_text, start_time, session_logger, **kwargs
            ):
                yield event
        except Exception as e:
            self._error_message = str(e)
            err_code, err_type = _extract_executor_error_meta(e)
            self._error_code = err_code
            logger.exception(
                f"[{self._session_id}] Error during astream: {e} "
                f"(code={err_code or 'n/a'} type={err_type})"
            )

            duration_ms = int((time.time() - start_time) * 1000)
            if session_logger:
                session_logger.log_graph_error(
                    error_message=str(e),
                    node_name="astream",
                    iteration=self._current_iteration,
                    error_type=err_type,
                    error_code=err_code,
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

    def attach_skill_watcher(self, watcher: Optional[Any]) -> None:
        """Hold the per-session skill hot-reload watcher so cleanup() can
        stop its polling thread (audit L1). Idempotent — replacing an
        existing watcher stops the old one first."""
        old = getattr(self, "_skill_watcher", None)
        if old is not None and old is not watcher:
            try:
                old.stop()
            except Exception:  # noqa: BLE001
                pass
        self._skill_watcher = watcher

    async def cleanup(self, *, flush: bool = True):
        """Clean up the AgentSession and release all resources.

        Flushes short-term memory to long-term, closes the executor
        ``MemoryProvider`` so vector backends, FAISS handles, and
        embedding-client connections drop their resources, and calls
        ``Pipeline.aclose()`` (geny-executor 2.2.0) so the pipeline's
        own teardown runs — cancels pending HITL futures, closes
        ``events()`` taps, disconnects MCP servers (reaping the stdio
        bridge child Geny used to leak per stopped session), and shuts
        down tool providers.

        ``flush=False`` skips the end-of-session memory compaction — used
        by long-idle EVICTION, where the goal is to reclaim RAM, not to
        shut the session down. Unflushed STM stays on disk and is re-read
        verbatim when the session rehydrates on next access; the LTM fold
        defers to the next real close. Skipping it keeps eviction fast so a
        concurrent reconnect (which serialises on the same rehydrate lock)
        isn't stalled by an up-to-20s compaction.
        """
        logger.info(f"[{self._session_id}] Cleaning up AgentSession (flush=%s)...", flush)

        # Stop a still-running vector warm-up first — it must not keep
        # indexing into a provider we are about to close (or an evicted
        # session's RAM alive).
        warmup = getattr(self, "_vector_init_task", None)
        if warmup is not None:
            if not warmup.done():
                warmup.cancel()
                try:
                    await warmup
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            self._vector_init_task = None
        # Release anyone still blocked on readiness — this session is over.
        self._memory_ready.set()

        # Stop the skill hot-reload watcher's polling thread (audit L1).
        watcher = getattr(self, "_skill_watcher", None)
        if watcher is not None:
            try:
                watcher.stop()
            except Exception:  # noqa: BLE001 — teardown must not raise
                logger.debug("skill watcher stop failed", exc_info=True)
            self._skill_watcher = None

        # Flush memory before shutdown.
        # ``auto_flush`` is SYNC and internally does
        # ``run_coro_sync(compact_now(...))`` — a full end-of-session
        # compaction (LLM summary + note/vector writes). Called inline on
        # this async cleanup path it would BLOCK the event loop for the
        # entire compaction (seconds), freezing every other session, and
        # its provider writes could deadlock on a memory lock held by a
        # now-unresumable loop coroutine. Run it off the loop. See
        # ``service.memory.sync_async_bridge.offload_blocking``.
        #
        # BOUNDED: the flush runs on a shared single-worker pool. If that
        # pool is saturated by other sessions' side-effects, an unbounded
        # await here would STRAND the resource-release steps below
        # (MemoryProvider / Pipeline close → embedding client, MCP stdio
        # child, HITL futures, event taps) and re-leak exactly what this
        # method exists to reclaim. The flush is best-effort (unflushed STM
        # still lives on disk), so cap it and release resources regardless.
        if self._memory_manager:
            if flush:
                try:
                    from service.memory.sync_async_bridge import offload_blocking
                    await asyncio.wait_for(
                        offload_blocking(self._memory_manager.auto_flush),
                        timeout=_CLEANUP_FLUSH_TIMEOUT_S,
                    )
                    logger.debug(f"[{self._session_id}] Memory flushed to long-term storage")
                except asyncio.TimeoutError:
                    logger.warning(
                        "[%s] memory flush exceeded %ss in cleanup — releasing "
                        "resources anyway (unflushed STM remains on disk)",
                        self._session_id, _CLEANUP_FLUSH_TIMEOUT_S,
                    )
                except Exception:
                    logger.debug("Failed to flush memory — non-critical", exc_info=True)
            self._memory_manager = None

        # Release the executor MemoryProvider — pre-audit fix this was
        # never called, leaking FAISS / embedding-client handles per
        # session shutdown.
        if self._memory_provider is not None:
            try:
                await self._memory_provider.close()
            except Exception:
                logger.debug(
                    "MemoryProvider close failed — non-critical",
                    exc_info=True,
                )
            self._memory_provider = None

        # 2.2.0 teardown contract — aggregate close before dropping the
        # reference. Without it the MCP stdio bridge child outlived the
        # session (one leaked process per stopped session).
        if self._pipeline is not None:
            try:
                await self._pipeline.aclose()
            except Exception:
                logger.debug(
                    "Pipeline.aclose failed — non-critical", exc_info=True,
                )

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

    def memory_ready(self) -> bool:
        """Whether the long-term-memory warm-up has finished (see __init__)."""
        return self._memory_ready.is_set()

    async def wait_memory_ready(self, timeout: float = 8.0) -> bool:
        """Bounded wait for the memory warm-up; True when ready in time."""
        if self._memory_ready.is_set():
            return True
        try:
            await asyncio.wait_for(self._memory_ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
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
        # Read persisted total_cost from session store
        _total_cost = 0.0
        try:
            from service.sessions.store import get_session_store
            store_data = get_session_store().get(self._session_id)
            if store_data:
                _total_cost = store_data.get("total_cost", 0.0) or 0.0
        except Exception:
            pass

        # Resolve model + provider + environment name from the session's
        # ENVIRONMENT — the manifest is the single source of truth for what
        # actually runs (stage-6 provider, manifest.model). The old chain fell
        # straight to Anthropic globals, so sessions on other providers were
        # displayed with a claude-* model they never use.
        env_name: Optional[str] = None
        model_provider: Optional[str] = None
        env_model: Optional[str] = None
        if self._env_id:
            try:
                from service.environment import get_environment_service

                env_svc = get_environment_service()
                manifest = env_svc.load_manifest(self._env_id) if env_svc else None
                if manifest is not None:
                    env_name = (manifest.metadata.name or "").strip() or None
                    env_model = ((manifest.model or {}).get("model") or "").strip() or None
                    for entry in manifest.stage_entries():
                        if entry.order != 6 or entry.name != "api":
                            continue
                        if entry.active:
                            model_provider = str(
                                (entry.config or {}).get("provider")
                                or (entry.strategies or {}).get("provider")
                                or ""
                            ).strip() or None
                            # Stage-6 커스텀 model override BEATS the pipeline-
                            # wide model at runtime (PipelineMutator
                            # set_stage_model) — the display must match.
                            override_model = (
                                (entry.model_override or {}).get("model") or ""
                            ).strip() or None
                            if override_model:
                                env_model = override_model
                        break
            except Exception:
                logger.debug(
                    f"[{self._session_id}] env enrichment for get_info failed",
                    exc_info=True,
                )

        # Environment model wins; session override next; global defaults last.
        effective_model = env_model or self._model_name
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

        # Which accounts this session talks to (what the user picked), and who
        # actually answered last turn. They differ exactly when a hop failed
        # over — which is the moment a user wants to see it.
        _record = self._store_record() or {}
        _route = getattr(self, "route", None) or _record.get("route")
        _last_route = getattr(self, "last_route", None) or _record.get("last_route")

        return SessionInfo(
            session_id=self._session_id,
            session_name=self._session_name,
            route=_route if isinstance(_route, dict) else None,
            last_route=_last_route if isinstance(_last_route, dict) else None,
            status=self._status,
            created_at=self._created_at,
            pid=None,
            error_message=self._error_message,
            error_code=self._error_code,
            model=effective_model,
            model_provider=model_provider,
            env_name=env_name,
            max_turns=self._max_turns,
            timeout=self._timeout,
            max_iterations=self._max_iterations,
            storage_path=self.storage_path,
            owner_username=self._owner_username,  # audit S6
            pod_name=pod_name,
            pod_ip=pod_ip,
            role=self._role,
            **self._persona_info(),
            always_on=self._always_on_override,
            workflow_id=self._workflow_id,
            graph_name=self._preset_name,
            tool_preset_id=self._tool_preset_id,
            system_prompt=self._system_prompt,
            memory_ready=self.memory_ready(),
            total_cost=_total_cost,
            linked_session_id=self._linked_session_id,
            session_type=self._session_type,
            chat_room_id=self._chat_room_id,
            env_id=self._env_id,
            memory_config=self._memory_config,
            trigger_preset_id=self._resolve_trigger_preset_id(),
        )

    def _persona_info(self) -> Dict[str, Any]:
        """Which persona this session runs, and where it came from.

        A persona that resolves from the environment is invisible on the
        session screen unless the session says so — and "why is it talking
        like that" is not a question an operator should have to answer by
        reading a manifest.
        """
        out: Dict[str, Any] = {
            "persona_preset_id": None,
            "effective_persona_preset_id": None,
            "persona_source": "none",
            "persona_name": None,
        }
        try:
            from service.executor import get_agent_session_manager

            mgr = get_agent_session_manager()
            own = (self._store_record() or {}).get("persona_preset_id")
            out["persona_preset_id"] = own if isinstance(own, str) and own else None
            effective, source = mgr.resolve_persona_preset_id(
                self._session_id, self._env_id
            )
            out["effective_persona_preset_id"] = effective
            out["persona_source"] = source
            if effective:
                from service.persona_presets import get_persona_preset_store

                out["persona_name"] = getattr(
                    get_persona_preset_store().get(effective), "name", None
                )
        except Exception:  # noqa: BLE001 — session info must never fail on this
            logger.debug("persona info unavailable", exc_info=True)
        return out

    def _store_record(self) -> Optional[Dict[str, Any]]:
        try:
            from service.sessions.store import get_session_store

            return get_session_store().get(self._session_id)
        except Exception:  # noqa: BLE001
            return None

    def _resolve_trigger_preset_id(self) -> Optional[str]:
        """Lookup the trigger preset currently attached to this session.

        Reads directly from the singleton ThinkingTriggerService — keeps
        ``AgentSession`` free of trigger-runtime state while still
        letting ``get_session_info`` surface what's bound. Returns
        ``None`` for non-VTuber sessions or when the trigger service
        is unavailable (e.g. early boot / tests).
        """
        try:
            from service.vtuber.thinking_trigger import (
                get_thinking_trigger_service,
            )

            return get_thinking_trigger_service().get_attached_preset(
                self._session_id
            )
        except Exception:
            return None

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


def _turn_text(content: Any) -> str:
    """Best-effort string projection of `Turn.content`."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        if parts:
            return "\n".join(parts)
    return str(content)

