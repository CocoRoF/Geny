"""
AgentSessionManager — manages AgentSession (geny-executor Pipeline) instances.

Usage example:
    from service.executor import get_agent_session_manager

    manager = get_agent_session_manager()

    agent = await manager.create_agent_session(CreateSessionRequest(
        working_dir="/path/to/project",
        model="claude-sonnet-4-20250514",
    ))

    agent = manager.get_agent(session_id)
    result = await agent.invoke("Hello")
"""

from datetime import datetime
from logging import getLogger
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # quoted-annotation only — no import cycle at runtime
    from service.tick.engine import TickEngine
import asyncio
import os
import time
import uuid

from service.utils.async_fs import rmtree_async
from service.utils.background import spawn_background
from service.sessions.models import (
    CreateSessionRequest,
    MCPConfig,
    SessionInfo,
    SessionRole,
    SessionStatus,
)

from service.logging.session_logger import get_session_logger, remove_session_logger
from service.executor.agent_session import AgentSession
from service.prompt.sections import build_agent_prompt
from service.prompt.context_loader import ContextLoader
from service.prompt.builder import PromptMode

from service.sessions.store import get_session_store

from pathlib import Path as _Path

from service.executor.agent_session import (
    _ADAPTIVE_PROMPT,
    _DEFAULT_VTUBER_PROMPT,
    _DEFAULT_WORKER_PROMPT,
)
from service.persona import CharacterPersonaProvider
from service.lifecycle import LifecycleEvent, SessionLifecycleBus
from service.plugin import PluginRegistry, TamagotchiPlugin


logger = getLogger(__name__)


#: Eviction must stay clear of the IDLE transition (default 600s). A
#: threshold just above it would tear a session down almost the moment it
#: fell asleep, which is not "long-idle" by any reading.
_EVICT_FLOOR_S = 900.0


def _coerce_evict_seconds(raw: object, fallback: float) -> float:
    """Read an evict threshold from anywhere, and keep it sane.

    ``0`` means "never evict" and is preserved exactly. A NEGATIVE value
    is not a quieter way of saying zero — it is invalid input (the field
    declares a minimum of 0, and the settings API saves-then-reports
    rather than rejecting), so it falls back instead of silently turning
    eviction off. Everything else is lifted to the floor.
    """
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if value < 0:
        return fallback
    if value == 0:
        return 0.0
    return max(value, _EVICT_FLOOR_S)


_VTUBER_CHARACTERS_DIR = _Path(__file__).resolve().parent.parent.parent / "prompts" / "vtuber_characters"


# Single source of truth for the VTuber's "you have a Sub-Worker" notice.
# Layered onto VTuber sessions through ``PersonaProvider.append_context``
# (cycle 20260422_6 PR4 — see ``_build_system_prompt``'s long comment).
# ``append_context`` is idempotent on identical text, so re-registering
# this string for an already-paired VTuber is a no-op.
_VTUBER_SUB_WORKER_NOTICE_DEFAULT = (
    "\n\n## Execution layer\n"
    "You have your OWN tools — DO quick work yourself, inline. If a task finishes in "
    "roughly a minute with a handful of tool calls (a status/health check, a quick SSH "
    "command, a short lookup, a small edit), just say a brief \"잠깐만\" and do it — a few "
    "tool turns don't break the conversation.\n"
    "DELEGATE to your sub-worker ONLY genuinely long or heavy multi-step work (a full "
    "audit, a build or deploy, a large migration — anything that would run many minutes "
    "or dozens of steps). To delegate, CALL the `send_direct_message_internal` tool with "
    "the full task description as `content` — saying you will hand it off does NOT "
    "delegate anything; only that tool call does. No target id is needed (it routes to "
    "your paired sub-worker). Its result returns as a `[SUB_WORKER_RESULT]` trigger, "
    "which you summarize in your own words in Korean — don't paste raw output.\n"
    "When unsure, do it yourself — over-delegating a trivial task wastes time and feels evasive."
)


def _load_vtuber_sub_worker_section() -> dict:
    """M.1 (cycle 20260426_3) — best-effort read of
    ``settings.json:vtuber.sub_worker``. Returns ``{}`` when the
    section / sub-block is absent so the caller falls back to defaults.
    """
    try:
        from geny_executor.settings import get_default_loader
    except ImportError:
        return {}
    section = get_default_loader().get_section("vtuber")
    if section is None:
        return {}
    if hasattr(section, "model_dump"):
        section_dict = section.model_dump(exclude_none=True)
    elif isinstance(section, dict):
        section_dict = section
    else:
        return {}
    sub = section_dict.get("sub_worker") or {}
    return sub if isinstance(sub, dict) else {}


def _vtuber_sub_worker_notice() -> str:
    """Settings-driven notice template; falls back to the built-in
    default when ``settings.json:vtuber.sub_worker.notice_template``
    is absent or empty."""
    sub = _load_vtuber_sub_worker_section()
    template = sub.get("notice_template")
    if isinstance(template, str) and template.strip():
        text = template if template.startswith("\n") else "\n\n" + template
        return text
    return _VTUBER_SUB_WORKER_NOTICE_DEFAULT





async def _remove_cloud_agent_space(owner_username: str, session_id: str) -> None:
    """Delete an agent's space inside the cloud, on permanent delete only.

    Best-effort: a session must always finish being deleted, even if its
    cloud directory cannot be removed. Off-loop because it is a tree.
    """
    if not owner_username:
        return
    try:
        from pathlib import Path as _P

        from service.cloud import agent_space
        from service.utils.async_fs import rmtree_async

        space = _P(agent_space(owner_username, session_id))
        if space.is_dir() and not space.is_symlink():
            await rmtree_async(space, ignore_errors=True)
            logger.info("[%s] cloud agent space removed", session_id)
    except Exception:  # noqa: BLE001
        logger.debug(
            "[%s] cloud agent space cleanup skipped", session_id, exc_info=True,
        )


class AgentSessionManager:
    """
    AgentSession manager — geny-executor Pipeline sessions.

    Core structure:
    - _local_agents: AgentSession store (local)
    - _global_mcp_config: cluster-wide MCP defaults, injected from main.py
    """

    def __init__(self):
        # Global MCP configuration (applied to every session unless overridden
        # by the per-request mcp_config). Set from main.py via
        # ``set_global_mcp_config`` after MCPLoader.load_all().
        self._global_mcp_config: Optional[MCPConfig] = None

        # AgentSession store (local)
        self._local_agents: Dict[str, AgentSession] = {}

        # Per-session locks guarding lazy re-hydration so two concurrent
        # accesses to a dormant (post-restart) session don't reconstruct
        # it twice. Created on demand, removed once the session is live.
        self._rehydrate_locks: Dict[str, asyncio.Lock] = {}

        # Persistent session metadata store (sessions.json)
        self._store = get_session_store()

        # Database reference (for per-session memory/log DB wiring)
        self._app_db = None

        # Environment service (Phase 3 — enables env_id-driven session creation)
        self._environment_service = None

        # ToolLoader reference (for preset-based tool filtering)
        self._tool_loader = None

        # Background idle monitor (cycle 20260421_8 PR-X2-5: runs on the
        # shared TickEngine rather than a bespoke ``while True`` loop).
        from service.tick import TickEngine
        self._idle_tick_engine: TickEngine = TickEngine()
        self._owns_idle_tick_engine: bool = True
        self._idle_monitor_interval: float = 60.0  # spec cadence (s)
        self._idle_monitor_jitter: float = 3.0     # spec jitter (s)
        self._idle_monitor_running: bool = False

        # Long-idle EVICTION (memory reclaim). Marking a session IDLE keeps
        # its AgentSession — pipeline, MemoryProvider, embedding client —
        # fully resident; ``_local_agents`` is otherwise unbounded, so idle
        # sessions accumulate in memory until explicit delete or a process
        # restart. After this many seconds of inactivity a non-always-on
        # session is torn down (resources released) but its store record +
        # on-disk memory are preserved, so the NEXT access transparently
        # rehydrates it (same id, same conversation) — only restore latency
        # is added. Set ``GENY_IDLE_EVICT_SECONDS=0`` to disable (keep the
        # old always-warm behaviour). Default 30 min; a floor keeps it well
        # clear of the 10-min IDLE transition.
        # Seeded from the environment; the authoritative value is resolved
        # per scan by ``_evict_seconds()`` so a settings change lands within
        # one tick instead of at the next restart.
        self._idle_evict_seconds: float = _coerce_evict_seconds(
            os.environ.get("GENY_IDLE_EVICT_SECONDS", "1800"), 1800.0
        )

        # Plugin registry — cycle 20260422 PR-X5-2/3. Manager-scoped
        # singleton. TamagotchiPlugin owns the four live blocks and the
        # EventSeedPool; future plugins register here the same way.
        # Live blocks drop to empty output when ``creature_state`` isn't
        # hydrated, so classic-mode (no-state) sessions remain
        # byte-identical to pre-X4 prompt output.
        self._plugin_registry = PluginRegistry()
        self._tamagotchi_plugin = TamagotchiPlugin()
        self._plugin_registry.register(self._tamagotchi_plugin)

        # Persona provider — single manager-scoped instance, keys state on
        # session_id. Created eagerly so controllers can inject per-session
        # persona edits without reaching into AgentSession internals.
        self._persona_provider = CharacterPersonaProvider(
            characters_dir=_VTUBER_CHARACTERS_DIR,
            default_vtuber_prompt=_DEFAULT_VTUBER_PROMPT,
            default_worker_prompt=_DEFAULT_WORKER_PROMPT,
            adaptive_prompt=_ADAPTIVE_PROMPT,
            live_blocks=self._plugin_registry.collect_prompt_blocks({}),
            event_seed_pool=self._tamagotchi_plugin.event_seed_pool,
        )

        # Session lifecycle bus — manager-scoped pub/sub rail (cycle
        # 20260421_8 PR-X2-1). Call sites route CREATED/DELETED/PAIRED/
        # RESTORED/IDLE/REVIVED through it; subscribers (not yet any in X2)
        # attach via ``manager.lifecycle_bus.subscribe``.
        self._lifecycle_bus = SessionLifecycleBus()

        # Creature state provider (cycle 20260421_9 PR-X3-5). None until
        # ``set_state_provider`` is called at boot. Gated in ``main.py``
        # by ``GameConfig.enabled`` (Settings UI → Tamagotchi). When
        # the flag is off every session runs in classic (no-state) mode.
        # ``_state_provider_vtuber_only`` decides whether non-VTuber
        # sessions also get the provider (default: VTuber-only, so
        # ordinary Workers don't spawn orphan creature rows).
        self._state_provider = None
        self._state_decay_service = None
        self._state_provider_vtuber_only: bool = True

        logger.info("✅ AgentSessionManager initialized")

    # ========================================================================
    # Global MCP configuration
    # ========================================================================

    def set_global_mcp_config(self, config: MCPConfig) -> None:
        """Set cluster-wide MCP defaults (applied to every new session).

        Called from main.py after MCPLoader.load_all(). The per-request
        ``request.mcp_config`` still overrides these globals at session
        creation via ``build_session_mcp_config``.
        """
        self._global_mcp_config = config
        if config and config.servers:
            logger.info(
                f"✅ Global MCP config registered: {list(config.servers.keys())}"
            )

    @property
    def global_mcp_config(self) -> Optional[MCPConfig]:
        """Currently registered global MCP configuration (or None)."""
        return self._global_mcp_config

    @property
    def persona_provider(self) -> CharacterPersonaProvider:
        """Shared ``CharacterPersonaProvider`` — controllers use it to stage
        per-session persona edits (character / static override / context)."""
        return self._persona_provider

    @property
    def lifecycle_bus(self) -> SessionLifecycleBus:
        """Shared ``SessionLifecycleBus`` — subscribers react to the 7
        canonical session lifecycle events."""
        return self._lifecycle_bus

    def set_app_db(self, app_db) -> None:
        """Store the AppDatabaseManager for per-session DB wiring.

        Called once at startup from main.py lifespan.
        Enables DB-backed memory for newly created sessions.
        """
        self._app_db = app_db
        logger.info("AgentSessionManager: app_db set for per-session memory DB wiring")

    def set_state_provider(
        self,
        state_provider,
        *,
        decay_service=None,
        vtuber_only: bool = True,
    ) -> None:
        """Wire the creature ``CreatureStateProvider`` + its decay service.

        When set, newly created ``AgentSession`` instances receive the
        provider and hydrate/persist ``CreatureState`` around every
        pipeline turn. ``decay_service`` is stored so the manager owns
        the reference — main.py lifespan uses ``state_decay_service``
        for start/stop. Leaving both as ``None`` (the default) keeps
        the session stack in classic mode.

        ``vtuber_only`` (cycle 20260422_5 follow-up): when True, only
        sessions whose role is ``SessionRole.VTUBER`` actually get the
        provider passed to ``AgentSession``. Non-VTuber roles keep
        ``state_provider=None`` so plain workers / sub-workers don't
        spawn orphan creature rows. Toggle off for deployments where a
        non-VTuber role legitimately needs creature state.
        """
        self._state_provider = state_provider
        self._state_decay_service = decay_service
        self._state_provider_vtuber_only = vtuber_only
        logger.info(
            "AgentSessionManager: state_provider set "
            f"({type(state_provider).__name__}; "
            f"decay_service={'yes' if decay_service else 'no'}; "
            f"vtuber_only={vtuber_only})"
        )

    @property
    def state_provider(self):
        """Currently-wired ``CreatureStateProvider`` or ``None``."""
        return self._state_provider

    def _build_manifest_selector(self):
        """Construct the baseline :class:`ManifestSelector` (PR-X4-5).

        One selector per session: selector state (tree snapshots) is
        immutable post-construction, so sharing would work too, but
        per-session instances make test isolation easier and cost is
        negligible. Trees / naming defaults come from
        :mod:`backend.service.progression.trees.default`.
        """
        from service.progression.selector import ManifestSelector
        from service.progression.trees.default import (
            DEFAULT_TREE,
            DEFAULT_TREE_ID,
        )

        return ManifestSelector(trees={DEFAULT_TREE_ID: DEFAULT_TREE})

    @property
    def state_decay_service(self):
        """Decay service paired with the provider (or ``None``)."""
        return self._state_decay_service

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

    # ========================================================================
    # Provider Resolution (Phase E2)
    # ========================================================================

    def _owned_subagent(
        self, session_id: Optional[str], role: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """The persistent companion this session OWNS, or None.

        The session's own choice first, then the default for its role (a
        VTuber owns one; that is what lets the persona hand work off and keep
        talking). It used to be declared by the environment, which meant
        "give this one a companion" required building a whole environment.
        """
        if session_id:
            try:
                rec = self._store.get(session_id) or {}
                val = rec.get("owned_subagent")
                if isinstance(val, dict):
                    return dict(val) if val.get("enabled") is not False else None
                if role is None:
                    role = rec.get("role")
            except Exception:  # noqa: BLE001 — never block a build on the store
                logger.debug("owned sub-agent lookup failed", exc_info=True)
        from service.sessions.attachments import default_owned_subagent

        return default_owned_subagent(role)

    def _subworker_types(
        self, session_id: Optional[str], role: Any = None,
    ) -> List[Dict[str, Any]]:
        """This session's one-shot Sub-Worker roster, or ``[]``.

        Per-type config dicts (``{agent_type, enabled?, description?,
        provider?, model?, system_prompt?, allowed_tools?}``) that
        :class:`SubagentRegistryBuilder` overlays on the seed. The session's
        own list first, then the default for its role — a persona agent gets
        the GAPT sub-worker so it can delegate that work instead of carrying
        nine tool schemas it rarely uses.
        """
        if session_id:
            try:
                rec = self._store.get(session_id) or {}
                val = rec.get("subworker_types")
                if isinstance(val, list):
                    return [c for c in val if isinstance(c, dict)]
                if role is None:
                    role = rec.get("role")
            except Exception:  # noqa: BLE001
                logger.debug("sub-worker roster lookup failed", exc_info=True)
        from service.sessions.attachments import default_subworker_types

        return default_subworker_types(role)

    def _env_sandbox_tool_pack_ids(self, env_id: Optional[str]) -> List[str]:
        """The env's opt-in Sandbox Tool Pack ids, or ``[]``.

        Stored in ``host_selections.extras.sandbox_tool_packs`` — a list of pack
        ids the env editor's pack panel selects. A pack loads only when it is
        BOTH globally enabled AND listed here (decision C: global registry +
        per-env opt-in). Empty → no packs for this session."""
        if not env_id or self._environment_service is None:
            return []
        try:
            manifest = self._environment_service.load_manifest(env_id)
            if manifest is None:
                return []
            extras = getattr(manifest.host_selections, "extras", None) or {}
            val = extras.get("sandbox_tool_packs")
            return [str(p).strip() for p in val if p] if isinstance(val, list) else []
        except Exception:  # noqa: BLE001
            return []

    def _env_computer_use_enabled(self, env_id: Optional[str]) -> bool:
        """Whether this env opted into Local Computer Use (the connector
        capability tools). Stored at ``host_selections.extras.computer_use_enabled``.

        This is the SERVER-side policy gate: when true, the connector capability
        tool names are unioned into ``tools.external`` so the session exposes
        them. The LOCAL execution gate (per-capability consent) is enforced
        independently by the connector; the tools fail-closed ("connector
        offline") when no desktop is attached. Both gates must pass."""
        if not env_id or self._environment_service is None:
            return False
        try:
            manifest = self._environment_service.load_manifest(env_id)
            if manifest is None:
                return False
            extras = getattr(manifest.host_selections, "extras", None) or {}
            return bool(extras.get("computer_use_enabled"))
        except Exception:  # noqa: BLE001
            return False

    def _env_vscode_enabled(self, env_id: Optional[str]) -> bool:
        """Whether this env opted into the VSCode-extension local-development
        tool set (``vscode_*``). Stored at
        ``host_selections.extras.vscode_enabled`` and set ONLY on
        ``template-vscode-env``. Deliberately NOT auto-enabled for any role
        (unlike computer-use for VTuber): the vscode tools drive file writes and
        terminal commands and must never leak into a general session. When true,
        the ``vscode_*`` names are unioned into ``tools.external`` so the session
        exposes them; local execution runs in the VSCode extension (which
        advertises the matching ``vscode.*`` capabilities and enforces
        per-capability consent). Both gates must pass; the tools fail-closed
        ("connector offline") when no extension is attached."""
        if not env_id or self._environment_service is None:
            return False
        try:
            manifest = self._environment_service.load_manifest(env_id)
            if manifest is None:
                return False
            extras = getattr(manifest.host_selections, "extras", None) or {}
            return bool(extras.get("vscode_enabled"))
        except Exception:  # noqa: BLE001
            return False

    def _env_tool_settings(self, env_id: Optional[str]) -> dict:
        """The env's per-tool settings map, or ``{}``.

        Stored at ``host_selections.extras.tool_settings`` (key → field values).
        Used to compute which config-gated tools are satisfied for this env."""
        if not env_id or self._environment_service is None:
            return {}
        try:
            manifest = self._environment_service.load_manifest(env_id)
            if manifest is None:
                return {}
            extras = getattr(manifest.host_selections, "extras", None) or {}
            val = extras.get("tool_settings")
            return val if isinstance(val, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _env_persona_preset_id(self, env_id: Optional[str]) -> Optional[str]:
        """The env's attached Persona Preset id, or ``None``.

        Stored in ``host_selections.extras.persona_preset_id`` — set by the env
        editor's Persona panel. When present, the preset is compiled to a persona
        prompt and prepended to the session's system prompt at build time."""
        if not env_id or self._environment_service is None:
            return None
        try:
            manifest = self._environment_service.load_manifest(env_id)
            if manifest is None:
                return None
            extras = getattr(manifest.host_selections, "extras", None) or {}
            val = extras.get("persona_preset_id")
            return str(val).strip() or None if val else None
        except Exception:  # noqa: BLE001
            return None

    def _env_role_prompt(self, env_id: Optional[str]) -> Optional[str]:
        """The env's stored System-stage prompt (env = single source), or None.

        Seeded from ``prompts/{role}.md`` at env install and editable in the env's
        Stage-3 (System) editor. When present it overrides the on-disk role file at
        session build; absent → the file is the fallback."""
        if not env_id or self._environment_service is None:
            return None
        try:
            manifest = self._environment_service.load_manifest(env_id)
            if manifest is None:
                return None
            for e in manifest.stage_entries():
                if getattr(e, "order", None) == 3:
                    cfg = getattr(e, "config", None) or {}
                    val = cfg.get("prompt")  # StaticPromptBuilder key (Stage-3 editor binds here)
                    return (str(val).strip() or None) if val else None
        except Exception:  # noqa: BLE001
            return None
        return None

    def resolve_persona_preset_id(
        self, session_id: Optional[str], env_id: Optional[str],
    ) -> Tuple[Optional[str], str]:
        """Which persona this session runs, and where it came from.

        Order: the SESSION's own choice, then the environment's. A session
        override exists because a persona used to be a property of the
        environment alone — the only way to give one session a different
        character was to build it another environment, and the only way to
        change one was to edit an environment shared by every session on it.

        Returns ``(preset_id, source)`` with source in
        ``{"session", "role", "none"}`` so callers can SAY which one is in
        force rather than leaving the operator to guess.
        """
        if session_id:
            try:
                rec = self._store.get(session_id) or {}
                own = rec.get("persona_preset_id")
                if isinstance(own, str) and own.strip():
                    return own.strip(), "session"
            except Exception:  # noqa: BLE001 — never block a build on the store
                logger.debug("persona: session override lookup failed", exc_info=True)
        # No session choice: what this ROLE starts with. A VTuber is a
        # persona, so it has one; a worker does not. This used to come from
        # the environment, which is why giving one agent a different persona
        # meant building it a whole environment — sessions carry it now, and
        # `migrate_session_attachments` wrote the environment's choice onto
        # every session that had one before the link was cut.
        from service.sessions.attachments import default_persona_preset_id

        try:
            role = (self._store.get(session_id) or {}).get("role") if session_id else None
        except Exception:  # noqa: BLE001
            role = None
        from_role = default_persona_preset_id(role)
        return (from_role, "role") if from_role else (None, "none")

    def _compile_persona(
        self, session_id: Optional[str], env_id: Optional[str],
    ) -> Optional[str]:
        """Resolve + compile the persona in force for this session, or ``None``.

        Best-effort: a missing/deleted preset or an unwired store never blocks
        session creation."""
        preset_id, source = self.resolve_persona_preset_id(session_id, env_id)
        if not preset_id:
            return None
        try:
            from service.persona_presets import compile_persona, get_persona_preset_store

            defn = get_persona_preset_store().get(preset_id)
            text = compile_persona(defn)
            if text.strip():
                logger.info(
                    "  🎭 persona '%s' (%s) resolved from %s",
                    getattr(defn, "name", preset_id), preset_id, source,
                )
            return text.strip() or None
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "persona preset %s (%s) not applied: %s", preset_id, source, e
            )
            return None

    def _env_host_selection(
        self, env_id: Optional[str], category: str
    ) -> Optional[List[str]]:
        """The env manifest's ``host_selections.<category>`` list, or None.

        Manager-side twin of :meth:`AgentSession._load_host_selection` —
        used for selections resolved *before* the AgentSession exists
        (e.g. the skill registry is built here, in the manager). Returns
        ``None`` on no manifest / unset category / any failure, which the
        caller treats as wildcard (keep all)."""
        if not env_id or self._environment_service is None:
            return None
        try:
            manifest = self._environment_service.load_manifest(env_id)
            if manifest is None:
                return None
            sel = getattr(
                getattr(manifest, "host_selections", None), category, None
            )
            return list(sel) if sel is not None else None
        except Exception:  # noqa: BLE001
            return None

    # ── the session's route ──────────────────────────────────────────
    #
    # A route is which model accounts a session talks to, in order. The
    # pipeline only ever names one provider (``geny_router``); the route is
    # what that provider resolves per call. Because history stays canonical,
    # changing the route mid-conversation continues the SAME conversation
    # with the same tools, memory, hooks and permission policy — which is the
    # whole reason model switching is cheap here.

    async def _resolve_session_route(
        self, session_id: str, request: CreateSessionRequest
    ) -> Dict[str, Any]:
        route = getattr(request, "route", None)
        if isinstance(route, dict) and route.get("primary"):
            return route
        stored = self._stored_route(session_id)
        if stored:
            return stored
        try:
            from service.llm_accounts import get_account_service

            return get_account_service().default_route()
        except Exception as exc:  # noqa: BLE001 — no accounts yet is not a crash
            logger.warning("route: falling back to an empty route (%s)", exc)
            return {"primary": None, "fallbacks": []}

    def _stored_route(self, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            from service.sessions.store import get_session_store

            record = get_session_store().get(session_id) or {}
        except Exception:  # noqa: BLE001
            return None
        route = record.get("route")
        return route if isinstance(route, dict) and route.get("primary") else None

    async def _route_targets(self, route: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            from service.llm_accounts import get_account_service

            return await get_account_service().resolve_route(route or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("route: could not resolve any hop (%s)", exc)
            return []

    def _route_notifier(self, session_id: str):
        """What the router tells the host while a turn runs.

        Three things matter here. ``route`` and ``failover`` are the only
        record of WHICH account answered — without them a user watching a
        subscription burn down has no way to tell which one. ``tokens`` is
        load-bearing: a Codex refresh token is single-use, so a rotation that
        is not persisted logs the account out on the next turn, silently.
        """

        def notify(event: Dict[str, Any]) -> None:
            kind = str(event.get("kind") or "")
            try:
                if kind == "tokens":
                    account_id = str(event.get("accountId") or "")
                    tokens = event.get("tokens")
                    if account_id and isinstance(tokens, dict):
                        from service.llm_accounts import get_secret_store

                        get_secret_store().set(account_id, tokens)
                    return
                if kind in ("route", "failover"):
                    self._record_route_event(session_id, kind, event)
                    return
                if kind in ("rate_limit", "notice"):
                    logger.info("[%s] route %s: %s", session_id, kind,
                                event.get("message") or event.get("info"))
            except Exception:  # noqa: BLE001 — a notification never breaks a turn
                logger.debug("route notify failed", exc_info=True)

        return notify

    def _record_route_event(self, session_id: str, kind: str, event: Dict[str, Any]) -> None:
        agent = self._local_agents.get(session_id)
        summary = {
            "accountId": event.get("accountId"),
            "label": event.get("label") or event.get("from"),
            "kind": event.get("accountKind"),
            "model": event.get("model"),
            "index": event.get("index"),
            "failedOver": kind == "failover",
        }
        if agent is not None:
            setattr(agent, "last_route", summary)
        if kind == "failover":
            logger.warning(
                "[%s] route failover from %s (%s): %s",
                session_id, event.get("from"), event.get("category"), event.get("error"),
            )
        else:
            logger.info("[%s] route → %s (%s)", session_id, summary["label"], summary["model"])
        try:
            from service.sessions.store import get_session_store

            get_session_store().update(session_id, {"last_route": summary})
        except Exception:  # noqa: BLE001
            pass
        # Into the session log too, so the workspace ledger can answer "which
        # account paid for this turn" alongside what the turn did.
        try:
            from service.logging import get_session_logger

            session_logger = get_session_logger(session_id, create_if_missing=False)
            if session_logger is not None:
                label = summary.get("label") or summary.get("accountId") or "?"
                session_logger.log_session_event(kind, {"type": kind, **summary})
                logger.debug("[%s] route event logged (%s)", session_id, label)
        except Exception:  # noqa: BLE001
            pass

    def _extract_primary_provider(self, env_id: str) -> Optional[str]:
        """Return the active Stage 6 provider for ``env_id``.

        Looks first at ``stages[6].config['provider']`` (the v2.0.0
        single source of truth) and falls back to the legacy
        ``strategies['provider']`` location so manifests created before
        the executor 2.0.0 reseeding still resolve. Returns ``None``
        when the manifest is missing or Stage 6 is inactive.

        The manifest is the only source — the legacy
        ``LLMCredentialsConfig.default_provider`` global override was
        removed; the active backend now flows through
        ``install_environment_templates`` baking it into the seeds at
        boot. Environment = single source of truth.
        """
        if self._environment_service is None:
            return None
        manifest = self._environment_service.load_manifest(env_id)
        if manifest is None:
            return None
        for entry in manifest.stage_entries():
            if entry.order != 6 or entry.name != "api":
                continue
            if not entry.active:
                return None
            cfg_provider = (entry.config or {}).get("provider")
            if cfg_provider:
                return str(cfg_provider)
            strat_provider = (entry.strategies or {}).get("provider")
            if strat_provider:
                return str(strat_provider)
            return None
        return None

    #: Provider-agnostic short aliases that resolve to "latest" at the backend —
    #: live discovery returns canonical ids, so don't warn on these.
    _MODEL_ALIASES = frozenset({"sonnet", "opus", "haiku", "default", "latest"})

    async def _warn_if_model_unavailable(
        self, provider: Optional[str], model: Optional[str], credentials, env_id: str
    ) -> None:
        """Best-effort, non-blocking: warn when the configured model isn't in the
        provider's live-discovered list. Silent when discovery is unavailable
        (can't validate) or the model is a short alias. Never raises."""
        if not provider or not model:
            return
        if str(model).strip().lower() in self._MODEL_ALIASES:
            return
        try:
            from geny_executor.llm_client import discover_models

            creds = credentials.get(provider) if hasattr(credentials, "get") else None
            api_key = getattr(creds, "api_key", "") or None
            base_url = getattr(creds, "base_url", "") or None
            disc = await discover_models(provider, api_key=api_key, base_url=base_url)
            if disc.source != "live":
                return  # can't enumerate → no warning; runtime fallback covers it
            ids = {m.id for m in disc.models}
            if model not in ids:
                logger.warning(
                    "[%s] configured model %r is not in %s's %d discovered models — "
                    "it may fail at runtime (model_fallback will retry alternates)",
                    env_id, model, provider, len(ids),
                )
        except Exception:  # noqa: BLE001 — diagnostics only
            logger.debug("model availability warn-check failed", exc_info=True)

    # ========================================================================
    # Prompt Builder
    # ========================================================================

    def _build_system_prompt(
        self,
        request: CreateSessionRequest,
        session_id: Optional[str] = None,
        in_gapt_workspace: bool = False,
        gapt_workspace_id: Optional[str] = None,
        role_protocol_override: Optional[str] = None,
        computer_use_enabled: bool = False,
    ) -> str:
        """Build the system prompt using the modular prompt builder.

        Design: The system prompt tells the agent WHO it is and WHAT to do.
        HOW to use tools and HOW to loop is handled by the Claude API (via
        geny-executor's APIStage) and the Pipeline itself. Tool schemas are
        provided to the model via MCP / function-calling — not repeated in prompts.

        Args:
            request: Session creation request.
            session_id: Pre-generated session ID (for Geny platform awareness).
            in_gapt_workspace: True when the session is bound to a GAPT
                workspace — the agent's cwd is the container's /workspace, so
                the prompt describes that + the gapt_* tools.

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

        # Memory v2 PR 11 — Path A 폐기.
        #
        # Historically this block called
        # ``mgr.build_memory_context(max_chars=4000)`` and appended
        # the result to the system prompt at session-start time.
        # Plan §5.1 / review.md P4-P5 — this caused two issues:
        #
        #   1. The MEMORY.md body was forced into the prompt at
        #      session-start regardless of relevance, contradicting
        #      the progressive-disclosure philosophy (plan §5).
        #   2. The 4 KB cap was tighter than s02's per-turn 8-10 KB
        #      budget, so the same MEMORY.md sometimes appeared once
        #      truncated (path A) and once full (path B) inside the
        #      same prompt.
        #
        # Retrieval now flows entirely through s02 ContextStage's
        # GenyMemoryRetriever which (with PR 10 slim mode flipped on
        # by per-session tuning) injects only recent turns + session
        # summary + vault map. The agent reaches for bodies via the
        # ``memory_search`` / ``memory_read`` ladder (plan §5.3).

        # Determine prompt mode
        mode = PromptMode.FULL

        # Files workspace manifest — same derivation AgentSession uses for its
        # storage_path (DEFAULT_STORAGE_ROOT / session_id), so the short prompt
        # manifest always names the real host path.
        _storage_path: Optional[str] = None
        if session_id:
            from pathlib import Path as _P

            from service.utils.platform import DEFAULT_STORAGE_ROOT

            _storage_path = str(_P(DEFAULT_STORAGE_ROOT) / session_id)

        # Build prompt — when bound to a GAPT workspace the agent's cwd is the
        # container's /workspace, so describe that (not the host path). The
        # binding itself happens in the async create path before this is called.
        prompt = build_agent_prompt(
            agent_name="Great Agent",
            role=role,
            agent_id=None,
            working_dir=("/workspace" if in_gapt_workspace else request.working_dir),
            model=request.model,
            session_id=session_id,
            session_name=request.session_name,
            character_display_name=request.character_display_name,
            mode=mode,
            context_files=context_files if context_files else None,
            extra_system_prompt=request.system_prompt,
            in_gapt_workspace=in_gapt_workspace,
            gapt_workspace_id=gapt_workspace_id,
            role_protocol_override=role_protocol_override,
            storage_path=_storage_path,
            computer_use_enabled=computer_use_enabled,
        )

        # Memory v2 PR 11 — memory_context append removed (see comment
        # above; retrieval flows through s02 + tools).

        # Cycle 20260422_6 PR4 — single-source delegation notices.
        #
        # Earlier code appended `## Sub-Worker Agent` / `## Paired
        # VTuber Agent` blocks here. Both moved out of `_build_system_prompt`:
        #
        #   * VTuber side (`## Sub-Worker Agent`) — owned by
        #     `PersonaProvider.append_context`. The new-pair create
        #     path calls it after the Sub-Worker is spawned; the
        #     warm-restart path calls it from `create_agent_session`
        #     after `set_static_override` (search for `_VTUBER_SUB_WORKER_NOTICE`
        #     in this file). `append_context` is idempotent so
        #     re-registration cannot duplicate the section.
        #   * Sub-Worker side (`## Paired VTuber Agent` /
        #     `## Replying to Your Paired VTuber`) — owned by
        #     `prompts/worker.md`, gated by an explicit
        #     "When you are a paired Sub-Worker..." opener so an
        #     unpaired Worker reading it is told to ignore the section.
        #
        # The result: the invariants in
        # `dev_docs/20260422_6/progress/pr4_strip_worker_persona.md`
        # §4 (table of `vtuber.md` / `worker.md` / pair-block counts)
        # hold structurally instead of by accident.

        logger.debug(f"  PromptBuilder: mode={mode.value}, role={role}, length={len(prompt)} chars")

        return prompt

    # ========================================================================
    # AgentSession Creation
    # ========================================================================

    def _subagent_workspace_ctx(self, session_id: str) -> dict:
        """Workspace context handed to sub-agent factories at delegation time:
        the parent's <storage>/workspace as working_dir (+ path guard) and the
        LIVE GAPT sandbox handle so sub-agents share the exact same
        filesystem — host-side AND container-side."""
        import os as _os
        from pathlib import Path as _Path

        from service.utils.platform import DEFAULT_STORAGE_ROOT

        storage = str(_Path(DEFAULT_STORAGE_ROOT) / session_id)
        workspace = _os.path.join(storage, "workspace")
        try:
            _os.makedirs(workspace, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        agent = self._local_agents.get(session_id)
        return {
            "session_id": session_id,
            "storage_path": storage,
            "working_dir": workspace,
            "sandbox": getattr(agent, "_gapt_sandbox", None) if agent else None,
        }

    async def create_agent_session(
        self,
        request: CreateSessionRequest,
        enable_checkpointing: bool = False,
        session_id: Optional[str] = None,
        owner_username: Optional[str] = None,
        env_id: Optional[str] = None,
        memory_config: Optional[Dict[str, Any]] = None,
        trigger_preset_id: Optional[str] = None,
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

        # Compute allowed MCP servers from preset.
        # NOTE (audit 2026-06-17, C7): the resulting ``merged_mcp_config``
        # is passed to AgentSession.create() but the SDK pipeline never
        # reads it (see AgentSession.__init__ self._mcp_config) — env MCP
        # is resolved from the manifest's tools.mcp_servers. This block is
        # therefore inert for SDK sessions; kept for signature/parity.
        # Configure MCP per environment, not via the tool preset.
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

        # ── GAPT workspace binding ────────────────────────────────────────
        # Every session gets its own persistent GAPT workspace. The executor's
        # attach_runtime(sandbox=) gives tools (forge_tool / SandboxExecTool /
        # gapt_* via the MCP bridge) ``ctx.sandbox`` so they run in the workspace
        # (docker exec) — for EVERY backend, without exception.
        #
        # The sandbox is a TOOL surface only: the LLM is always called from the
        # HOST with the credentials Geny configured. That keeps rotating
        # subscription OAuth (host_mount / in_modal_login) working — nothing
        # authenticates inside a container, so the refreshToken-rotation 401
        # can't happen — while GAPT/forge tools still execute sandboxed. So a
        # setup token is NOT required just to use GAPT tools.
        # See feedback_claude_oauth_no_share + docs/sandboxed-tools/03_*.
        # Default ON; set GENY_GAPT_WORKSPACES=0 to force pure host execution.
        gapt_sandbox = None
        if os.getenv("GENY_GAPT_WORKSPACES", "1").strip().lower() not in (
            "0", "false", "no", "off", ""
        ):
            try:
                from service.gapt import GaptWorkspaceProvider, get_gapt_client

                _gc = get_gapt_client()
                if _gc.configured:
                    # One session = one GAPT workspace = ONE filesystem.
                    # When the deployment exports the sessions volume's HOST
                    # path (GENY_AGENT_SESSIONS_HOST_DIR), the workspace is
                    # created as GAPT kind='bind': its /workspace mounts the
                    # session's own workspace dir, so sandboxed Bash/CLI and
                    # host-side tools (Doc*, uploads, storage tab) see the
                    # SAME files. Without the env we fall back to the legacy
                    # GAPT-owned worktree (split filesystems).
                    from service.utils.platform import DEFAULT_STORAGE_ROOT as _ROOT

                    _host_root = os.getenv(
                        "GENY_AGENT_SESSIONS_HOST_DIR", ""
                    ).strip().rstrip("/")

                    # Bind the agent's space INSIDE THE CLOUD, not the legacy
                    # `<sid>/workspace`. That path is a symlink into the cloud
                    # now, and a bind of a symlink resolves to a target that
                    # does not exist on the host — which is exactly how the
                    # old `workspace/cloud` link dangled inside the sandbox.
                    # Binding the real cloud directory puts the sandbox in the
                    # shared tree with everything else.
                    _backend_ws = os.path.join(str(_ROOT), session_id, "workspace")
                    try:
                        from service.cloud import (
                            adopt_agent_space,
                            sandbox_bind_root,
                        )

                        if owner_username:
                            adopt_agent_space(
                                owner_username,
                                os.path.join(str(_ROOT), session_id),
                                session_id,
                            )
                            # WHAT THE SANDBOX SEES follows the connection, the
                            # same rule the host-side tool roots use: its own
                            # space alone, or the whole shared tree. Connected,
                            # /workspace IS the cloud — the user's linked
                            # folders, the other agents' spaces and the user's
                            # GAPT workspace are all visible and addressable,
                            # which is what makes the cloud shared rather than
                            # a place each agent reaches into blindly.
                            # The executor's path mapping keys off this root,
                            # so the agent's own working_dir lands at
                            # /workspace/agents/<sid> either way.
                            _backend_ws = sandbox_bind_root(
                                owner_username, session_id
                            )
                    except Exception:  # noqa: BLE001 — fall back to the legacy path
                        logger.debug(
                            "[%s] cloud-based bind path unavailable", session_id,
                            exc_info=True,
                        )

                    _bind_host = None
                    if _host_root:
                        # Mirror the backend path under the host root: both
                        # sides see the same volume, only the prefix differs.
                        # That mirroring only holds INSIDE the volume — the
                        # cloud root is configurable, and one pointed outside
                        # it would yield a `../..` relpath and a bind naming
                        # some unrelated host directory. Refuse rather than
                        # mount whatever that resolves to.
                        _rel_to_root = os.path.relpath(_backend_ws, str(_ROOT))
                        if _rel_to_root.startswith(".."):
                            logger.warning(
                                "[%s] cloud root lies outside the bindable volume "
                                "(%s) — sandbox falls back to its own space",
                                session_id, _backend_ws,
                            )
                            _backend_ws = os.path.join(
                                str(_ROOT), session_id, "workspace"
                            )
                            _rel_to_root = os.path.relpath(_backend_ws, str(_ROOT))
                        _bind_host = f"{_host_root}/{_rel_to_root}"
                    if _bind_host:
                        # The dir must exist before GAPT validates/mounts it.
                        os.makedirs(_backend_ws, exist_ok=True)
                    gapt_sandbox = await GaptWorkspaceProvider(_gc).ensure_workspace(
                        project_slug=os.getenv("GENY_GAPT_PROJECT_SLUG", "geny"),
                        workspace_name=session_id,
                        # Never block session creation on container boot:
                        # the handle's ensure() ladder brings the workspace
                        # up lazily on the FIRST sandboxed tool call (the
                        # toolchain-baked image makes that a ~1s docker
                        # run). Session create stays snappy regardless.
                        wait_running=False,
                        bind_host_dir=_bind_host,
                        backend_workspace_dir=(_backend_ws if _bind_host else None),
                    )
                    logger.info(
                        "[%s] bound to GAPT workspace %s (%s; tools sandboxed; CLI on host)",
                        session_id,
                        gapt_sandbox.container_name,
                        "bind: unified session filesystem" if _bind_host else "legacy worktree",
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "[%s] GAPT workspace provisioning failed; using host execution",
                    session_id,
                    exc_info=True,
                )
                gapt_sandbox = None

        # Local Computer Use — decided here (used by the prompt below AND the
        # connector tool exposure further down). VTuber sessions always carry
        # the connector tools; other envs opt in via extras.computer_use_enabled.
        _computer_use_on = (
            request.role == SessionRole.VTUBER
            or self._env_computer_use_enabled(env_id)
        )

        # Prepare system prompt. Every sandboxed session gets the same
        # message — "your file/shell tools operate in /workspace" — because
        # every session's tools really do run there, whichever provider
        # answers. There is no second arrangement to describe.
        system_prompt = self._build_system_prompt(
            request,
            session_id=session_id,
            in_gapt_workspace=gapt_sandbox is not None,
            gapt_workspace_id=(getattr(gapt_sandbox, "workspace_id", None) if gapt_sandbox else None),
            # env = single source: the env's stored Stage-3 prompt overrides the
            # on-disk prompts/{role}.md (which becomes just the seed/fallback).
            role_protocol_override=self._env_role_prompt(env_id),
            computer_use_enabled=_computer_use_on,
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
        # Phase E2 — build the executor's CredentialBundle from Geny's
        # settings (APIConfig + CLI backend configs). The bundle is the
        # single channel; the legacy ``api_key`` kwarg is gone from
        # this code path.
        #
        from service.executor.credentials import CredentialBundleBuilder

        if not session_id:
            session_id = str(uuid.uuid4())
        # The session's route — which model accounts it talks to, in order.
        # Explicit on the request wins; otherwise a restored session keeps the
        # route it had; otherwise every enabled account, arranged as the user
        # arranged them. Resolved here (not at call time) so a turn never waits
        # on a token refresh, and so a route naming a deleted account is
        # noticed at creation rather than mid-conversation.
        route = await self._resolve_session_route(session_id, request)
        route_targets = await self._route_targets(route)

        credentials = CredentialBundleBuilder(
            route_targets=route_targets,
            route_notify=self._route_notifier(session_id),
            session_id=session_id,
            route_timeout_s=request.timeout,
        ).build()

        # Determine the active session's primary provider so we can
        # validate that the matching credentials are actually present —
        # this catches the "user selected Claude Code CLI but never
        # logged in / never set ANTHROPIC_API_KEY" case at session
        # creation time instead of at first LLM call.
        primary_provider = self._extract_primary_provider(env_id)
        if primary_provider == "geny_router" and not route_targets:
            raise ValueError(
                "이 세션이 쓸 모델 계정이 없습니다. 설정 › 모델에서 계정을 추가하고 "
                "켜 두세요 (Claude Code 로그인, ChatGPT·Codex 로그인, API 키 모두 가능합니다)."
            )
        if primary_provider and primary_provider != "geny_router" and not credentials.has(primary_provider):
            raise ValueError(
                f"환경 '{env_id}'의 Stage 6 provider '{primary_provider}'에 사용할 "
                f"자격증명이 설정되지 않았습니다. Settings → LLM Backends에서 해당 provider 카드를 "
                f"열어 API key를 입력하거나, CLI 백엔드라면 binary 설치 + 인증을 완료해 주세요."
            )

        # Warn-only model availability check (non-blocking, best-effort): if the
        # provider supports live discovery and the configured model isn't in the
        # real list, log a warning — never block creation (runtime model_fallback
        # covers genuine failures). Skips aliases and providers that can't be
        # enumerated (e.g. geny_claude_code — the CLI has no model list).
        try:
            spawn_background(
                self._warn_if_model_unavailable(
                    primary_provider, resolved_model, credentials, env_id
                ),
                name=f"model.availability:{session_id}",
            )
        except RuntimeError:
            pass

        # Build the per-session SubagentTypeRegistry once. The Stage 12
        # orchestrator slot is auto-rewired by
        # ``Pipeline.from_manifest_async(subagent_registry=...)``. The env's
        # precise Sub-Worker roster (host_selections.extras.subworker_types) is
        # overlaid on the seed so one-shot sub-workers run with that config.
        from service.agent_types import SubagentRegistryBuilder

        # Progressive disclosure: compute the env's satisfied config-token set once
        # (global config / per-env tool-settings / feature flags incl. Google).
        # Drives BOTH gating layers — GenyToolProvider (Geny tools) AND the
        # executor's from_manifest filter (executor built-ins like google_*) — so
        # an unconfigured tool never reaches the Agent engine.
        from service.executor.tool_config_gate import compute_satisfied_config

        satisfied_config = compute_satisfied_config(self._env_tool_settings(env_id))

        adhoc_providers: list = []
        if self._tool_loader is not None:
            from service.executor.geny_tool_provider import GenyToolProvider

            adhoc_providers.append(
                GenyToolProvider(self._tool_loader, satisfied_config=satisfied_config)
            )

        # Capability bridge (inverse MCP): advertise connector capability tools.
        # Inert unless a manifest's tools.external selects one (e.g. connector_ping).
        from service.executor.connector_bridge import ConnectorToolProvider

        connector_provider = ConnectorToolProvider()
        adhoc_providers.append(connector_provider)

        # VSCode extension local-development tools — a SEPARATE, isolated
        # capability set (vscode_*). Registered always (inert); activated ONLY
        # by the per-env vscode_enabled gate (never auto-on for a role). Its
        # names live only in this provider, so they can't leak into a normal
        # env's tools.external whitelist.
        from service.executor.vscode_bridge import VSCodeToolProvider

        vscode_provider = VSCodeToolProvider()
        adhoc_providers.append(vscode_provider)
        vscode_tools: list = (
            vscode_provider.list_names() if self._env_vscode_enabled(env_id) else []
        )
        if vscode_tools:
            logger.info(
                "  vscode: %d local-development capability tool(s) exposed",
                len(vscode_tools),
            )

        # Local Computer Use — the connector capability tool names, unioned into
        # tools.external so the session AND its delegated sub-agents (companion /
        # sub-worker) expose them. The connector is a conduit bound to a VTuber's
        # overlay session, so VTuber sessions ALWAYS carry these tools; a non-
        # VTuber env can still opt in explicitly (extras.computer_use_enabled).
        # This is NOT the security gate — real execution is gated locally by the
        # connector (per-capability consent) and fails closed when no desktop is
        # attached (connector_bridge.py). The flag is computed once, above the
        # system-prompt build, so the prompt section and the tool exposure agree.
        computer_use_tools: list = (
            connector_provider.list_names() if _computer_use_on else []
        )
        if computer_use_tools:
            logger.info(
                "  computer_use: %d connector capability tool(s) exposed (role=%s)",
                len(computer_use_tools),
                request.role.value if request.role else "worker",
            )

        # G7.3 + G14: skill registry. Always build (bundled skills load
        # without opt-in); only register the SkillToolProvider when at
        # least one skill resolved. Hold the registry on the manager so
        # G14's MCP auto-bridge can re-register prompts post-connect.
        # Phase 10 follow-up — `attach_provider` now auto-wires
        # `make_default_fork_runner()`, so fork-mode skills work out
        # of the box when ANTHROPIC_API_KEY is set. Also builds a
        # SkillRegistryWatcher so operator edits under
        # ~/.geny/skills/ land in the next pipeline scan without a
        # process restart.
        skill_registry = None
        skill_watcher = None
        try:
            from service.skills import (
                attach_provider,
                install_skill_registry,
                install_skill_watcher,
            )

            # Role-aware install: blog-write Skill only resolves for the
            # VTuber role; see service/skills/install.py
            # _SKILL_ROLE_RESTRICTIONS and BLOG_AGENT_DELEGATION_PLAN.md.
            _skill_role = (
                request.role.value if request.role else "worker"
            )
            skill_registry, _skill_list = install_skill_registry(
                role=_skill_role,
                host_selection=self._env_host_selection(env_id, "skills"),
            )
            skill_provider = attach_provider(skill_registry)
            if skill_provider is not None:
                adhoc_providers.append(skill_provider)
            # Hot-reload watcher — only meaningful when we actually
            # have a registry to mutate.
            if skill_registry is not None:
                skill_watcher = install_skill_watcher(
                    skill_registry,
                    on_change=lambda report: logger.info(
                        "skills hot-reload: %d skill(s), %d error(s)",
                        len(report.loaded), len(report.errors),
                    ),
                )
                if skill_watcher is not None:
                    skill_watcher.start()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"  skill registry install skipped: {exc}", exc_info=True)

        # Sandbox Tool Packs (per-env opt-in): load the packs this env selected
        # (and that are globally enabled), surface their tools as a get-style
        # provider, register their skills, and remember the tool names so they
        # get unioned into manifest.tools.external (→ active for the session).
        pack_tool_names: list = []
        try:
            pack_ids = self._env_sandbox_tool_pack_ids(env_id)
            if pack_ids:
                from service.gapt import get_gapt_client
                from service.sandbox_tool_packs import (
                    SandboxToolPackProvider,
                    get_sandbox_tool_pack_store,
                )

                _gc = get_gapt_client()
                if _gc.configured:
                    pack_provider = SandboxToolPackProvider(
                        store=get_sandbox_tool_pack_store(),
                        gapt_client=_gc,
                        pack_ids=pack_ids,
                    )
                    pack_tool_names = pack_provider.list_names()
                    if pack_tool_names:
                        adhoc_providers.append(pack_provider)
                        if skill_registry is not None:
                            for sk in pack_provider.skills():
                                try:
                                    skill_registry.register(sk)
                                except Exception:  # noqa: BLE001
                                    logger.debug(
                                        "  pack skill %s already present",
                                        getattr(sk, "id", "?"),
                                    )
                        logger.info(
                            "  sandbox_tool_packs: %d tool(s) from %d pack(s)",
                            len(pack_tool_names), len(pack_ids),
                        )
                else:
                    logger.warning("  sandbox_tool_packs: GAPT not configured; skipped")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"  sandbox_tool_packs load skipped: {exc}", exc_info=True)

        # Build the sub-worker registry AFTER the adhoc providers so env-declared
        # sub-workers inherit them (GenyToolProvider/Skill/...) and can therefore
        # resolve CUSTOM tools + skills in their allowed_tools — not just
        # framework built-ins. This is what lets e.g. a VTuber delegate GAPT work
        # to a sub-worker carrying the gapt_* tools while the main session stays
        # lean (no gapt_* in its own roster).
        subagent_registry = SubagentRegistryBuilder(
            env_overrides=self._subworker_types(session_id, request.role),
            adhoc_providers=adhoc_providers,
            extra_external_tools=computer_use_tools,
            # Lazy: resolved at DELEGATION time so the sub-agent picks up the
            # live GAPT sandbox handle (bound after registry construction on
            # some paths) and the parent's workspace dir.
            workspace_ctx=lambda sid=session_id: self._subagent_workspace_ctx(sid),
        ).build()

        # Sandbox-tool lifecycle toolset — guarantee EVERY env (incl. lean VTuber
        # personas + already-created envs) can do the full self-service loop:
        #   [create] env(forge_tool)  [save] env(save_pack)  ← env tool: universal
        #   write/test code in /workspace → gapt_run_command
        #   [list] list_tool_packs    [use] use_tool_pack
        # Injected at instantiate-time (unioned into tools.external) so no per-env
        # reseed is needed. Only meaningful when GAPT is configured.
        lifecycle_tools: list = []
        try:
            from service.gapt import get_gapt_client as _ggc

            if _ggc().configured:
                lifecycle_tools = ["gapt_run_command", "list_tool_packs", "use_tool_pack"]
        except Exception:  # noqa: BLE001
            lifecycle_tools = []
        # computer_use_tools + vscode_tools were computed above (before the
        # sub-agent registry).
        _extra_tools = list(
            dict.fromkeys(
                [*lifecycle_tools, *pack_tool_names, *computer_use_tools, *vscode_tools]
            )
        )

        # MCP connectors (config-gated): inject configured connectors' MCP servers
        # so the executor connects them + their tools appear. Only enabled +
        # fully-configured connectors are returned (the gate is omission).
        try:
            from service.mcp_connectors import configured_mcp_servers

            _extra_mcp = configured_mcp_servers()
        except Exception:  # noqa: BLE001 — never block session build on this
            _extra_mcp = []

        prebuilt_pipeline = await self._environment_service.instantiate_pipeline(
            env_id,
            credentials=credentials,
            subagent_registry=subagent_registry,
            adhoc_providers=adhoc_providers,
            extra_external_tools=_extra_tools,
            extra_mcp_servers=_extra_mcp,
            satisfied_config=satisfied_config,
        )
        logger.info(
            f"  env_id: {env_id} → manifest-backed pipeline built "
            f"(adhoc_providers={len(adhoc_providers)})"
        )
        # Diagnostic: the session's resolved active tool set. Confirms the
        # sandbox-tool lifecycle toolset (env, gapt_run_command, list_tool_packs,
        # use_tool_pack) is present for EVERY env (incl. VTuber). Real-app ground
        # truth — out-of-process scripts can't see the wired registry.
        try:
            _envc = getattr(prebuilt_pipeline, "environment", None)
            if _envc is not None:
                _active = _envc.active_tools()
                _life = [t for t in ("env", "gapt_run_command", "list_tool_packs", "use_tool_pack") if t in _active]
                logger.info(
                    "  active tools (%d): lifecycle=%s | all=%s",
                    len(_active), _life, _active,
                )
        except Exception:  # noqa: BLE001
            logger.debug("  active-tools diagnostic skipped", exc_info=True)

        # G14: bridge MCP prompts → skill registry. Runs *after*
        # instantiate_pipeline so the MCPManager has connected to its
        # configured servers; each connected server's prompts get
        # registered as Skills under mcp__<server>__<prompt>. No-op
        # when MCP isn't configured or the registry is None.
        try:
            from service.skills import install as _skill_install

            mcp_manager = getattr(prebuilt_pipeline, "_mcp_manager", None) or getattr(
                prebuilt_pipeline, "mcp_manager", None
            )
            if skill_registry is not None and mcp_manager is not None:
                added = await _skill_install.bridge_mcp_prompts(
                    skill_registry, mcp_manager
                )
                if added:
                    logger.info(
                        f"  MCP prompts → skills bridge: {added} skill(s) added"
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"  MCP prompts bridge failed: {exc}", exc_info=True)

        # Connector local MCP → first-class tools. If the desktop connector is
        # already attached (catalog held on its ConnectorConnection), register
        # mcp_<server>_<tool> into the fresh pipeline's registry now; later
        # catalog updates arrive via the /ws/connector handler.
        try:
            from service.executor.connector_mcp_tools import sync_from_registry

            _mcp_counts = sync_from_registry(
                session_id, registry=getattr(prebuilt_pipeline, "_tool_registry", None)
            )
            if _mcp_counts.get("registered"):
                logger.info(
                    f"  connector local MCP: {_mcp_counts['registered']} first-class tool(s) registered"
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"  connector MCP sync failed: {exc}", exc_info=True)

        # Role-gate the creature-state provider wiring. GameConfig
        # (``vtuber_only=True`` by default) means only ``VTUBER`` role
        # sessions get the provider — plain Worker / sub-Worker keep
        # ``state_provider=None`` (classic mode) so they don't spawn
        # orphan creature rows in the state DB. When ``vtuber_only``
        # is False, every session gets the provider.
        _has_state_provider = self._state_provider is not None
        _role_allows_state = (
            (not self._state_provider_vtuber_only)
            or request.role == SessionRole.VTUBER
        )
        _session_state_provider = (
            self._state_provider if (_has_state_provider and _role_allows_state) else None
        )

        # With CreatureState wired up, prepend the AffectTagEmitter so
        # LLM ``[emotion]`` cues fold into mood/bond mutations on the
        # same turn. Gated on the resolved per-session provider so a
        # classic worker session never has its final_text rewritten.
        if _session_state_provider is not None:
            from service.emit import install_affect_tag_emitter

            install_affect_tag_emitter(prebuilt_pipeline)

        # Persona Preset (Geny persona builder) — if this env has one attached,
        # compile it and prepend so the character identity leads the prompt, ahead
        # of the role/behaviour base. Best-effort; never blocks session creation.
        persona_block = self._compile_persona(session_id, env_id)
        if persona_block:
            system_prompt = (
                f"{persona_block}\n\n---\n\n{system_prompt}" if system_prompt else persona_block
            )
            logger.info(f"  🎭 Persona preset applied (+{len(persona_block)} chars)")

        # Seed the persona provider with the assembled static prompt so the
        # DynamicPersonaSystemBuilder hands back exactly this text on the
        # first turn. Persona mutations (character swap, user-edited
        # system-prompt, sub-worker ctx) then layer on top via the provider.
        self._persona_provider.set_static_override(session_id, system_prompt or None)

        # Cycle 20260422_6 PR4 — warm-restart hookup for the VTuber's
        # "## Sub-Worker Agent" notice. New-pair create handles this
        # later (after the Sub-Worker is actually spawned). Warm
        # restart enters here with ``request.linked_session_id``
        # already set; without this call the persona provider would
        # never learn about the existing pair after a restart.
        # ``append_context`` is idempotent on identical text.
        if (
            request.role == SessionRole.VTUBER
            and request.linked_session_id
        ):
            self._persona_provider.append_context(
                session_id, _vtuber_sub_worker_notice()
            )

        # Create AgentSession (gapt_sandbox was provisioned before the prompt
        # build above so the prompt can describe the /workspace cwd).
        agent = await AgentSession.create(
            working_dir=request.working_dir,
            model_name=resolved_model,
            session_name=request.session_name,
            session_id=session_id,
            gapt_sandbox=gapt_sandbox,
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
            # Carry the owner's resolved credentials/provider so ad-hoc
            # SubAgentSpawn + one-shot Agent sub-workers inherit Stage-6 auth
            # (integrity audit 2026-06-25).
            resolved_credentials=credentials,
            primary_provider=primary_provider,
            persona_provider=self._persona_provider,
            lifecycle_bus=self._lifecycle_bus,
            state_provider=_session_state_provider,
            # MVP: one creature per session — character_id tracks session_id.
            # PR-X4 replaces this with owner-driven multi-character lookup.
            character_id=(session_id if _session_state_provider else None),
            manifest_selector=(
                self._build_manifest_selector()
                if _session_state_provider is not None
                else None
            ),
        )

        session_id = agent.session_id

        # Hand the per-session skill hot-reload watcher to the session so
        # its polling thread is stopped at teardown (audit L1). Before this
        # the watcher was a leaked local — every create/rehydrate started a
        # new daemon thread that nothing ever stopped.
        try:
            agent.attach_skill_watcher(skill_watcher)
        except Exception:  # noqa: BLE001 — never fail create on watcher wiring
            if skill_watcher is not None:
                try:
                    skill_watcher.stop()
                except Exception:  # noqa: BLE001
                    pass

        # Register in local store
        self._local_agents[session_id] = agent

        # The route this session resolved with, so the session screen can show
        # which accounts it will use before a single turn has run.
        agent.route = route

        # Wire DB into session memory manager (if available)
        if self._app_db is not None and agent.memory_manager is not None:
            try:
                agent.memory_manager.set_database(self._app_db, session_id)
                logger.info(f"[{session_id}] Memory DB backend enabled")
            except Exception as e:
                logger.warning(f"[{session_id}] Failed to wire memory DB: {e}")

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
            # Replay every memory event the agent recorded *before* the
            # logger was provisioned (provider init fires inside
            # AgentSession.initialize() — earlier than the logger
            # creation right here). Without this flush the boot-time
            # rows ("MemoryProvider ready: ...") never reach the
            # frontend cache cursor and the VTuber LOGS panel stays
            # silent on the first turn.
            try:
                replayed = agent.flush_pending_memory_events()
                if replayed:
                    logger.info(
                        f"[{session_id}] flushed {replayed} pending memory event(s) into session logger"
                    )
            except Exception as flush_exc:  # noqa: BLE001
                logger.debug(
                    f"[{session_id}] memory event flush skipped: {flush_exc}",
                    exc_info=True,
                )

        # Lifecycle bus emit — SESSION_CREATED. For a sub-worker spawned
        # from a VTuber, ``linked_session_id`` on the request is the
        # VTuber's id (set by the pairing block below) — surface it as
        # ``paired_parent`` so subscribers can reconstruct pairings.
        role_value = request.role.value if request.role else "worker"
        created_meta: Dict[str, Any] = {
            "role": role_value,
            "is_vtuber": request.role == SessionRole.VTUBER,
            "session_type": request.session_type,
            "env_id": env_id,
        }
        if request.linked_session_id:
            created_meta["paired_parent"] = request.linked_session_id
        await self._lifecycle_bus.emit(
            LifecycleEvent.SESSION_CREATED, session_id, **created_meta
        )

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

        # ── Owned persistent sub-agent — ENV-DRIVEN (any role) ────────────
        # Owning a geny-executor persistent sub-agent is now an ENVIRONMENT
        # capability, not a VTuber hardcode: any env that declares
        # A session that owns a companion spawns it here. A VTuber owns one by
        # default — it is what lets the persona hand work off and keep talking
        # — and any session can be given or denied one on its own record.
        # Spawn no-ops when no manager is wired.
        from service.execution.agent_executor import get_app_state as _get_app_state
        _vt_app_state = _get_app_state()
        _owned = self._owned_subagent(session_id, request.role)
        if (
            _owned is not None
            and request.session_type != "sub"
            and not request.linked_session_id
            and getattr(_vt_app_state, "subagent_manager", None) is not None
        ):
            try:
                from service.vtuber.sub_agent_bridge import spawn_owned_subagent
                # One session = one workspace, companion included: hand the
                # OWNER's sandbox handle + workspace paths to the companion
                # so delegated work runs in the same unified filesystem.
                _owner_storage = str(getattr(agent, "storage_path", "") or "")
                sa_id = await spawn_owned_subagent(
                    _vt_app_state, session_id,
                    parent_env_id=env_id,
                    env_service=self._environment_service,
                    system_prompt=(_owned.get("system_prompt") or None),
                    credentials=credentials, parent_provider=primary_provider,
                    adhoc_providers=adhoc_providers,
                    extra_external_tools=computer_use_tools,
                    sandbox=gapt_sandbox,
                    working_dir=_owner_storage,
                    storage_path=_owner_storage,
                )
                agent._executor_sub_agent_id = sa_id
                self._store.update(session_id, {"executor_sub_agent_id": sa_id})
                # The persona "## Sub-Worker Agent" notice only makes sense
                # for an agent that actually owns a delegate.
                self._persona_provider.append_context(
                    session_id, _vtuber_sub_worker_notice()
                )
                logger.info(f"[{session_id}] 🤖 owns executor sub-agent: {sa_id}")
            except Exception as e:  # noqa: BLE001 — never fail create
                logger.error(
                    f"[{session_id}] owned sub-agent setup failed: {e}",
                    exc_info=True,
                )

        # ── VTuber conversational UX — ROLE-DRIVEN (avatar/chat/triggers) ──
        # This is the genuinely VTuber-specific part (a conversational
        # persona surface): mark the session type, create a chat room, and
        # register thinking triggers. Orthogonal to sub-agent ownership above.
        if (
            request.role == SessionRole.VTUBER
            and request.session_type != "sub"
            and not request.linked_session_id
        ):
            agent._session_type = "vtuber"
            self._store.update(session_id, {"session_type": "vtuber"})
            # Through the one rule, never around it. Creating the room here
            # directly is how a session ended up with several: this runs again
            # on every rehydrate, and a listing that came back empty (the chat
            # store's database not attached yet, say) made another one.
            try:
                from service.chat.home_room import resolve_home_room

                room = resolve_home_room(
                    session_id, name_hint=request.session_name or "",
                )
                room_id = (room or {}).get("id")
                if room_id:
                    agent._chat_room_id = room_id
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"[{session_id}] VTuber chat room failed: {e}", exc_info=True
                )
            try:
                from service.vtuber.thinking_trigger import get_thinking_trigger_service
                trigger_svc = get_thinking_trigger_service()
                trigger_svc.record_activity(session_id)
                # The session's own, or none — in which case the runtime uses the
                # designated default ladder. It used to be mapped on an environment.
                effective_trigger = trigger_preset_id
                if effective_trigger:
                    trigger_svc.attach_preset(session_id, effective_trigger)
                    self._store.update(
                        session_id, {"trigger_preset_id": effective_trigger}
                    )
            except Exception:  # noqa: BLE001
                pass

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
    # Lazy session restore (survive redeploy / restart / crash)
    # ========================================================================

    async def ensure_session_live(self, session_id: str) -> Optional[AgentSession]:
        """Return the live ``AgentSession``, lazily re-hydrating a dormant
        (non-deleted, on-disk) session from the persistent store on first
        access.

        This is the heart of lazy session restore. The session LIST is served
        from the store (so sessions survive restarts and reappear in the UI),
        and the heavy ``AgentSession`` — pipeline, memory provider, VTuber
        loops — is reconstructed only when something actually touches the
        session (open / message / WS connect). Returns ``None`` when the id is
        unknown or the session was explicitly deleted.
        """
        agent = self._local_agents.get(session_id)
        if agent is not None:
            # Environment edited while live → rebuild from the fresh manifest.
            # CRITICAL: defer while a turn is in-flight — _reload tears the
            # pipeline down (cleanup → pipeline.aclose() kills MCP / HITL /
            # event taps), which would corrupt a running turn. The flag stays
            # set, so the rebuild lands on the next IDLE access (i.e. the next
            # turn after the current one finishes). A dormant session below
            # already loads the current manifest when _rehydrate runs.
            if getattr(agent, "_needs_manifest_reload", False) and not self._session_busy(session_id, agent):
                lock = self._rehydrate_locks.setdefault(session_id, asyncio.Lock())
                async with lock:
                    cur = self._local_agents.get(session_id)
                    if (
                        cur is not None
                        and getattr(cur, "_needs_manifest_reload", False)
                        and not self._session_busy(session_id, cur)
                    ):
                        try:
                            return await self._reload_session_manifest(session_id)
                        finally:
                            self._rehydrate_locks.pop(session_id, None)
                    return cur
            return agent

        record = self._store.get(session_id)
        if not record or record.get("is_deleted"):
            return None

        lock = self._rehydrate_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            # Re-check inside the lock — a concurrent caller may have won.
            agent = self._local_agents.get(session_id)
            if agent is not None:
                return agent
            try:
                return await self._rehydrate(session_id)
            finally:
                self._rehydrate_locks.pop(session_id, None)

    async def _rehydrate(
        self, session_id: str, *, cascade: bool = True
    ) -> Optional[AgentSession]:
        """Reconstruct an ``AgentSession`` from its stored creation params,
        reusing the SAME ``session_id`` so the on-disk ``storage_path``
        (memory vault, transcripts, checkpoints) reloads and the conversation
        continues. Cascades to the linked VTuber ↔ Sub-Worker peer.

        Shared by :meth:`ensure_session_live` (lazy access) and the
        ``POST /{id}/restore`` endpoint (explicit un-delete + restore), so
        there is one reconstruction implementation. Mirrors the gate in
        ``create_agent_session``: passing ``linked_session_id`` on the request
        suppresses the VTuber auto-sub-worker spawn, so the peer is restored
        explicitly here with its original id instead of a fresh duplicate.
        """
        record = self._store.get(session_id)
        if not record:
            return None
        params = self._store.get_creation_params(session_id)
        if not params:
            return None

        # A wake is the one moment a user is watching a spinner with nothing
        # to read. Time it and say so: the phases land on the session logger,
        # which is the channel the chat panel already renders.
        _wake_started = time.monotonic()
        logger.info("[%s] waking — restoring session", session_id)

        # Defensive: clear any stale teardown gate for this id (a prior evict
        # or delete may have left it set) so the rebuilt session accepts turns.
        try:
            from service.execution.agent_executor import clear_session_closing
            clear_session_closing(session_id)
        except Exception:
            pass

        stored_system_prompt = record.get("system_prompt")
        linked_id = record.get("linked_session_id")

        # `get_creation_params` echoes storage_path back as working_dir. That
        # echo is not a caller's choice, but adoption treats any working_dir as
        # one and steps aside — so a restored agent worked in the session root
        # while the same agent, freshly created, worked in its cloud space.
        # Same agent, different directory either side of a restart.
        _wd = params.get("working_dir")
        if _wd and _wd == record.get("storage_path"):
            _wd = None

        request = CreateSessionRequest(
            session_name=params.get("session_name"),
            working_dir=_wd,
            model=params.get("model"),
            max_turns=params.get("max_turns", 100),
            timeout=params.get("timeout", 21600),
            max_iterations=params.get(
                "max_iterations", params.get("autonomous_max_iterations", 100)
            ),
            role=SessionRole(params["role"]) if params.get("role") else SessionRole.WORKER,
            graph_name=params.get("graph_name"),
            workflow_id=params.get("workflow_id"),
            tool_preset_id=params.get("tool_preset_id"),
            linked_session_id=params.get("linked_session_id"),
            session_type=params.get("session_type"),
        )

        # The owner has to survive the restart. Without it the session is
        # rebuilt with no cloud identity: its space is not adopted, the
        # sandbox binds the legacy path instead of the shared tree, and the
        # quota reads an empty journal. Records written before the owner was
        # carried through hold None, so fall back to the adoption symlink —
        # which already knows, and heals them in place.
        _owner = params.get("owner_username") or ""
        if not _owner:
            try:
                from service.cloud import owner_of_storage

                _owner = owner_of_storage(params.get("working_dir") or "")
                if _owner:
                    self._store.update(session_id, {"owner_username": _owner})
                    logger.info(
                        "[%s] owner recovered from the cloud link: %s",
                        session_id, _owner,
                    )
            except Exception:  # noqa: BLE001 — a restart must not hinge on this
                logger.debug("[%s] owner recovery failed", session_id, exc_info=True)

        agent = await self.create_agent_session(
            request=request,
            session_id=session_id,
            env_id=params.get("env_id"),
            trigger_preset_id=params.get("trigger_preset_id"),
            owner_username=_owner or None,
        )

        # Restore the user's customized system prompt through the persona
        # provider (the new session's DynamicPersonaSystemBuilder reads it on
        # its first turn).
        if stored_system_prompt:
            self._persona_provider.set_static_override(session_id, stored_system_prompt)
            self._store.update(session_id, {"system_prompt": stored_system_prompt})

        # A pin has to survive the thing it protects against. If "keep this
        # session awake" only lived in memory, an eviction (or a restart)
        # would silently drop it and the session would start going to sleep
        # again with the UI still showing it pinned.
        #
        # Read from ``record`` — the store row snapshotted at the top of this
        # method — NOT from ``params``: ``get_creation_params`` maps a fixed
        # set of CreateSessionRequest fields and the pin is not a creation
        # parameter, so reading it there returned None every time and the
        # restore never fired at all. (system_prompt above reads from
        # ``record`` for the same reason.)
        #
        # Written back to the store as well — the create_agent_session call
        # above just REGISTERED the fresh agent's SessionInfo over the
        # stored record, and the fresh agent didn't know about the pin yet,
        # so the record now says None. Healing only the live object would
        # make the pin survive exactly one wake and vanish on the next.
        stored_always_on = record.get("always_on")
        if stored_always_on is not None:
            agent.set_always_on(bool(stored_always_on))
            self._store.update(session_id, {"always_on": bool(stored_always_on)})

        # chat_room_id persists across restart so the messenger thread reattaches.
        stored_chat_room_id = params.get("chat_room_id")
        if stored_chat_room_id:
            agent._chat_room_id = stored_chat_room_id

        # Ensure a VTuber points at its REAL chat room. Reconcile to the
        # session's best existing room (the one with the most messages) — so a
        # stale / missing chat_room_id RECOVERS the conversation instead of
        # stranding it behind a fresh empty room. Only create one when the
        # session has no room at all. (The earlier "always create when missing"
        # version orphaned a 46-message room behind an empty duplicate.)
        is_vtuber = (params.get("role") == SessionRole.VTUBER.value) or (
            params.get("session_type") == "vtuber"
        )
        if is_vtuber:
            try:
                from service.chat.home_room import resolve_home_room

                room = resolve_home_room(
                    session_id, name_hint=params.get("session_name") or "",
                )
                room_id = (room or {}).get("id")
                if room_id and room_id != getattr(agent, "_chat_room_id", None):
                    agent._chat_room_id = room_id
                    logger.info(f"[{session_id}] 💬 Chat room: {room_id}")
            except Exception as e:  # noqa: BLE001 — chat room is best-effort
                logger.warning(f"[{session_id}] Failed to ensure chat room on reload: {e}")

        logger.info(f"♻️ Session re-hydrated: {session_id} (same ID, storage preserved)")

        # Cascade to the linked peer (VTuber ↔ Sub-Worker) with its own id.
        if cascade and linked_id and not self.has_agent(linked_id):
            linked_rec = self._store.get(linked_id)
            if linked_rec and not linked_rec.get("is_deleted"):
                try:
                    await self._rehydrate(linked_id, cascade=False)
                    await self._lifecycle_bus.emit(
                        LifecycleEvent.SESSION_RESTORED,
                        linked_id,
                        cascade="linked_peer",
                        peer=session_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Failed to cascade re-hydrate to linked session {linked_id}: {e}"
                    )

        await self._lifecycle_bus.emit(
            LifecycleEvent.SESSION_RESTORED,
            session_id,
            cascade="main",
            linked_id=linked_id,
        )
        _wake_took = time.monotonic() - _wake_started
        logger.info("[%s] awake in %.2fs", session_id, _wake_took)
        try:
            # The session is live from here; memory may still be warming, and
            # that phase reports itself separately.
            agent.record_memory_event(
                "awake",
                f"에이전트가 깨어났습니다 ({_wake_took:.1f}초)",
                layer="session",
            )
        except Exception:  # noqa: BLE001 — a notice must not fail a wake
            logger.debug("[%s] wake notice skipped", session_id, exc_info=True)
        return agent

    # ========================================================================
    # Environment propagation — apply an edited manifest to live sessions
    # ========================================================================

    def _best_chat_room_for(self, session_id: str) -> Optional[str]:
        """This session's existing chat room id, or None when it has none.

        Delegates to ``service.chat.home_room`` so the manager, the REST door
        and the autonomous-delivery path cannot disagree about which room a
        session's conversation is in.
        """
        try:
            from service.chat.home_room import best_existing_room

            room = best_existing_room(session_id)
        except Exception:  # noqa: BLE001
            return None
        if not room:
            return None
        return room.get("id") or room.get("room_id")

    def _session_busy(self, session_id: str, agent: AgentSession) -> bool:
        """A turn is in-flight on this session, so a manifest reload must wait.

        Checks the agent's own ``_is_executing`` (set across invoke + astream)
        AND the executor-level holder (registered before invoke for every
        command / chat / trigger path) so a concurrent turn — even one between
        resolve and invoke — defers the rebuild instead of tearing its pipeline
        down mid-stream.
        """
        if getattr(agent, "_is_executing", False):
            return True
        try:
            from service.execution.agent_executor import is_executing

            return bool(is_executing(session_id))
        except Exception:  # noqa: BLE001 — be conservative only on real signals
            return False

    async def refresh_all_session_credentials(self) -> List[str]:
        """Flag EVERY live session for rebuild after a global credential change
        (LLM backend API keys in the LLM 백엔드 config).

        The CredentialBundle is snapshotted into each session at build time
        (``CredentialBundleBuilder().build()`` reads the live config), so a key
        change in the config only reaches LIVE sessions when they rebuild. This
        marks them all; the rebuild reconstructs the bundle with the new key on
        the next turn (between-turn, never mid-turn — same path as
        :meth:`propagate_env_update`). Without this, changing the OpenAI key in
        the config left live sessions (and their embedding/Stage-6 clients) on
        the stale key until manual restart.
        """
        affected: List[str] = []
        for sid, agent in list(self._local_agents.items()):
            try:
                agent._needs_manifest_reload = True
                affected.append(sid)
            except Exception:  # noqa: BLE001
                pass
        if affected:
            logger.info(
                "🔑 LLM credentials changed → %d live session(s) flagged for "
                "credential rebuild", len(affected),
            )
        return affected

    async def propagate_env_update(self, env_id: str) -> List[str]:
        """Flag every LIVE session bound to ``env_id`` so it rebuilds its
        pipeline from the freshly-saved manifest on its next access.

        Returns the affected session ids. The rebuild itself is deferred to
        :meth:`ensure_session_live` (which the message / invoke / WS paths all
        funnel through) so it lands BETWEEN turns, never mid-turn. Dormant
        (post-restart) sessions need no flag — :meth:`_rehydrate` already loads
        the current manifest when they next wake.
        """
        affected: List[str] = []
        for sid, agent in list(self._local_agents.items()):
            if getattr(agent, "env_id", None) == env_id:
                agent._needs_manifest_reload = True
                affected.append(sid)
        if affected:
            logger.info(
                f"♻️ env '{env_id}' edited → {len(affected)} live session(s) "
                f"flagged for manifest reload: {affected}"
            )
        return affected

    #: A persona's ``emotion.default_mood`` names where its feelings rest.
    #: The live mood vector is 6 floats; "neutral" is the absence of a
    #: peak, not a seventh axis.
    _PERSONA_BASELINE = 0.5

    async def _reset_mood_to_persona(self, session_id: str, preset_id: Optional[str]) -> bool:
        """Point the live mood at the NEW persona's resting disposition.

        Swapping a persona used to change what the agent was told it is
        while leaving what it currently FEELS untouched. Production:
        a session moved onto an outgoing ESFP preset (extraversion 85,
        enthusiasm 90) kept ``calm: 0.98`` from months under the previous
        character, and every reply still came out calm — the persona had
        applied, and nothing about the agent's manner moved.

        Mood is a running EMA, so a settled value dominates for a long
        time; nudging it is not enough, and it has to be reset at the one
        moment the character legitimately discontinues. Only on an actual
        persona CHANGE — a rebuild for any other reason keeps the
        emotional continuity that makes the agent feel like itself.
        """
        if not preset_id:
            return False
        try:
            from service.persona_presets import get_persona_preset_store

            defn = get_persona_preset_store().get(preset_id)
            mood_name = str(
                getattr(getattr(defn, "emotion", None), "default_mood", "") or ""
            ).strip().lower()
        except Exception:  # noqa: BLE001 — a persona swap must not fail on this
            logger.debug("persona mood reset: preset unreadable", exc_info=True)
            return False

        from service.state.schema.mood import MoodVector

        fresh = {k: 0.0 for k in MoodVector.keys()}
        if mood_name in fresh:
            fresh[mood_name] = self._PERSONA_BASELINE
        # "neutral" (and anything unrecognised) lands as all-zero: no peak,
        # which is what neutral means here.

        try:
            provider = self._state_provider
            if provider is None:
                return False
            await provider.set_absolute(
                session_id, {f"mood.{k}": v for k, v in fresh.items()}
            )
        except Exception:  # noqa: BLE001
            logger.debug("persona mood reset failed", exc_info=True)
            return False
        logger.info(
            "[%s] mood reset to the new persona's resting disposition (%s)",
            session_id, mood_name or "neutral",
        )
        return True

    async def set_session_persona(
        self, session_id: str, preset_id: Optional[str],
    ) -> Dict[str, Any]:
        """Give ONE session its own persona, or hand it back to the env.

        ``preset_id=None`` clears the override, so the session follows its
        environment again — which is what it did before this existed.

        Applied the way every other binding change is: persisted first (so
        it survives eviction and restart), then the live session rebuilds.
        A session that is mid-turn is FLAGGED rather than torn down —
        rebuilding underneath a running answer is how you lose one — and
        picks the persona up between turns.

        Raises ValueError for an unknown session or an unknown preset: a
        persona that silently does not exist is worse than a refusal.
        """
        rec = self._store.get(session_id)
        if not rec:
            raise ValueError(f"session not found: {session_id}")

        before, _ = self.resolve_persona_preset_id(session_id, rec.get("env_id"))
        cleaned = (preset_id or "").strip() or None
        if cleaned:
            from service.persona_presets import get_persona_preset_store
            from service.persona_presets.store import PersonaPresetNotFound

            try:
                get_persona_preset_store().get(cleaned)
            except PersonaPresetNotFound:
                raise ValueError(f"persona preset not found: {cleaned}")

        self._store.update(session_id, {"persona_preset_id": cleaned})

        applied_now = False
        agent = self._local_agents.get(session_id)
        if agent is not None:
            if self._session_busy(session_id, agent):
                # Between turns, not mid-answer.
                agent._needs_manifest_reload = True
            else:
                await self._reload_session_manifest(session_id)
                applied_now = True

        effective, source = self.resolve_persona_preset_id(session_id, rec.get("env_id"))
        # The character discontinues here and only here — so this is the one
        # moment its accumulated feelings should not carry over.
        mood_reset = False
        if effective != before:
            mood_reset = await self._reset_mood_to_persona(session_id, effective)
        logger.info(
            "[%s] persona override -> %s (effective %s from %s, applied_now=%s)",
            session_id, cleaned, effective, source, applied_now,
        )
        return {
            "session_id": session_id,
            "persona_preset_id": cleaned,
            "effective_preset_id": effective,
            "persona_source": source,
            "applied_now": applied_now,
            "mood_reset": mood_reset,
            "live": agent is not None,
        }

    async def restart_session(self, session_id: str) -> Dict[str, Any]:
        """Rebuild this session now, keeping everything it remembers.

        The same in-place rebuild an env edit triggers — storage, memory,
        transcripts and the conversation are on disk and survive; only the
        running pipeline is replaced. Exposed on its own because every
        other way to get one was a side effect of changing something else,
        so "just apply what I already set" had no button.

        Refuses mid-turn rather than tearing down a running answer.
        """
        rec = self._store.get(session_id)
        if not rec:
            raise ValueError(f"session not found: {session_id}")

        agent = self._local_agents.get(session_id)
        if agent is not None and self._session_busy(session_id, agent):
            raise RuntimeError("세션이 실행 중입니다. 끝난 뒤 다시 시도해 주세요.")

        if agent is None:
            # Dormant: it will build from the current state on next access,
            # which is exactly what a restart would have produced.
            return {"session_id": session_id, "restarted": False, "reason": "dormant"}

        rebuilt = await self._reload_session_manifest(session_id)
        return {"session_id": session_id, "restarted": rebuilt is not None}

    async def change_session_env(
        self, session_id: str, env_id: str
    ) -> Dict[str, Any]:
        """Rebind an existing session to a different environment.

        The session keeps its id, storage, memory, transcripts and
        conversation — only the bound manifest changes. The new binding is
        persisted to the store (the top-level ``env_id`` field, which
        :meth:`SessionStore.get_creation_params` now reads), and a live
        session is flagged for a between-turn manifest reload via the same
        proven path env-edit propagation uses (:meth:`propagate_env_update`
        → :meth:`ensure_session_live` → :meth:`_reload_session_manifest`).
        Dormant (post-restart) sessions pick up the new env on their next
        wake through :meth:`_rehydrate`.

        Each session is rebound independently — for a VTuber/Sub-Worker
        pair the caller targets whichever session id it wants (the FE's
        VTuber tab vs Sub-Agent tab), so there is no implicit cascade.

        Raises:
            ValueError — session unknown, env unknown, or the new env's
                Stage 6 provider has no configured credentials (caught here
                so the rebind fails loudly now instead of breaking the
                session on its next turn).
        """
        if self._environment_service is None:
            raise RuntimeError(
                "EnvironmentService is not configured on AgentSessionManager."
            )
        rec = self._store.get(session_id)
        if not rec:
            raise ValueError(f"session not found: {session_id}")

        manifest = self._environment_service.load_manifest(env_id)
        if manifest is None:
            raise ValueError(f"environment not found: {env_id}")

        # Same guard create_agent_session applies — refuse to rebind onto an
        # env whose primary provider can't authenticate, so the deferred
        # reload won't silently break the session.
        primary_provider = self._extract_primary_provider(env_id)
        if primary_provider:
            try:
                from service.executor.credentials import CredentialBundleBuilder

                creds = CredentialBundleBuilder().build()
                if not creds.has(primary_provider):
                    raise ValueError(
                        f"환경 '{env_id}'의 Stage 6 provider '{primary_provider}'에 "
                        f"사용할 자격증명이 없습니다. Settings → LLM Backends에서 먼저 "
                        f"설정해 주세요."
                    )
            except ValueError:
                raise
            except Exception:  # noqa: BLE001 — never block on a creds-probe hiccup
                logger.debug(
                    "change_session_env: credential probe failed; skipping",
                    exc_info=True,
                )

        previous_env_id = rec.get("env_id")
        self._store.update(session_id, {"env_id": env_id})
        agent = self._local_agents.get(session_id)
        live = agent is not None
        if live:
            agent._env_id = env_id
            agent._needs_manifest_reload = True

        logger.info(
            "🔀 session %s env rebind: %s → %s (live=%s, applies between turns)",
            session_id, previous_env_id, env_id, live,
        )
        return {
            "session_id": session_id,
            "env_id": env_id,
            "previous_env_id": previous_env_id,
            "live": live,
            # The pipeline rebuild lands on the next access between turns;
            # the binding itself is already persisted + reflected in the store.
            "applies": "next_turn",
        }

    async def change_session_route(
        self, session_id: str, route: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Point a session at different model accounts — mid-conversation.

        This is the whole reason the pipeline names one provider. The session
        keeps its id, storage, memory, transcripts, tools, hooks, permission
        policy and conversation; only who answers the next turn changes. A
        live session has its Stage 6 credentials swapped in place — no
        pipeline rebuild, because rebuilding is exactly what would cost it
        all of the above.

        A route that resolves to nothing is refused. Leaving a session with
        no way to reach a model, in exchange for a switch the user can simply
        retry, is not a trade worth making.

        Raises:
            ValueError — the session is unknown, or the route named no usable
                account (every hop disabled, deleted, or unknown).
        """
        record = self._store.get(session_id)
        if not record:
            raise ValueError(f"session not found: {session_id}")

        targets = await self._route_targets(route)
        if not targets:
            raise ValueError(
                "그 라우트에는 쓸 수 있는 계정이 없습니다 — 계정이 켜져 있는지 확인하세요. "
                "지금 쓰던 라우트는 그대로 둡니다."
            )

        previous = record.get("route")
        self._store.update(session_id, {"route": route})

        agent = self._local_agents.get(session_id)
        applied = "next_turn"
        if agent is not None:
            agent.route = route
            pipeline = getattr(agent, "_pipeline", None)
            swap = getattr(pipeline, "set_provider_credentials", None)
            if callable(swap):
                from service.executor.credentials import CredentialBundleBuilder

                bundle = CredentialBundleBuilder(
                    route_targets=targets,
                    route_notify=self._route_notifier(session_id),
                    session_id=session_id,
                ).build()
                swap("geny_router", bundle.get("geny_router"))
                applied = "immediately"

        logger.info(
            "🔀 session %s route → %s (%d hop(s), applies %s)",
            session_id,
            ", ".join(f"{t['label']}·{t['model']}" for t in targets),
            len(targets), applied,
        )
        return {
            "session_id": session_id,
            "route": route,
            "previous_route": previous,
            "targets": [
                {k: t.get(k) for k in ("accountId", "label", "kind", "model")}
                for t in targets
            ],
            "live": agent is not None,
            "applies": applied,
        }

    def get_session_route(self, session_id: str) -> Dict[str, Any]:
        """The route a session is on, and who answered its last turn."""
        record = self._store.get(session_id) or {}
        agent = self._local_agents.get(session_id)
        route = (getattr(agent, "route", None) if agent else None) or record.get("route")
        last = (getattr(agent, "last_route", None) if agent else None) or record.get("last_route")
        return {
            "session_id": session_id,
            "route": route if isinstance(route, dict) else None,
            "last_route": last if isinstance(last, dict) else None,
            "live": agent is not None,
        }

    async def _reload_session_manifest(self, session_id: str) -> Optional[AgentSession]:
        """Tear down a live session and re-create it (same id) from the
        current manifest — the in-place equivalent of a restart that reuses the
        proven :meth:`_rehydrate` path (storage / memory / transcripts on disk
        are preserved; the conversation continues). Used by the manifest-reload
        branch of :meth:`ensure_session_live`.
        """
        old = self._local_agents.get(session_id)
        if old is not None:
            try:
                await old.cleanup()
            except Exception as e:  # noqa: BLE001 — best effort; rebuild anyway
                logger.warning(f"[{session_id}] cleanup before manifest reload failed: {e}")
            self._local_agents.pop(session_id, None)
        # cascade=False: each affected session reloads independently; a linked
        # peer on the same env is flagged + reloaded on its own next access.
        agent = await self._rehydrate(session_id, cascade=False)
        if agent is not None:
            logger.info(f"♻️ Session {session_id} pipeline reloaded from edited manifest")
        return agent

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

            # QUIESCE before teardown. cleanup() tears the pipeline down
            # (aclose → cancels HITL futures, closes event taps, disconnects
            # MCP) — doing that UNDER a live turn corrupts the turn and leaks
            # its pipeline/MCP/HITL resources. Block new turns, then wait for
            # any in-flight turn to finish (or gracefully cancel it past a
            # bounded window), so cleanup only runs once the session is idle.
            try:
                from service.execution.agent_executor import close_session_execution
                drained = await close_session_execution(session_id)
                if not drained:
                    logger.warning(
                        f"[{session_id}] delete: in-flight turn did not fully "
                        "drain; proceeding with teardown",
                    )
            except Exception:
                logger.debug(
                    f"[{session_id}] delete drain failed — proceeding with teardown",
                    exc_info=True,
                )

            # Clean up AgentSession (stop process, release resources)
            await agent.cleanup()

            # Clean up storage (only on permanent delete)
            if cleanup_storage and agent.storage_path:
                # The agent's files live in the cloud now, and rmtree of the
                # session root only removes the SYMLINK — leaving
                # `agents/<sid>/` behind forever, keyed by an opaque uuid the
                # user cannot identify, and replicating to every PC. A
                # permanent delete is the user asking for the files to go.
                await _remove_cloud_agent_space(
                    getattr(agent, "_owner_username", "") or "", session_id,
                )
                from pathlib import Path as FilePath
                sp = FilePath(agent.storage_path)
                if sp.is_dir():
                    try:
                        # Off-loop — a session tree is thousands of files.
                        await rmtree_async(sp)
                        logger.info(f"[{session_id}] Storage cleaned up: {agent.storage_path}")
                    except Exception as e:
                        logger.warning(f"[{session_id}] Failed to cleanup storage: {e}")

            # Remove from local store
            del self._local_agents[session_id]

            # Clear persona provider's in-memory state for this session.
            # Restore re-stages static_override/character from sessions.json.
            try:
                self._persona_provider.reset(session_id)
            except Exception:
                pass  # best-effort — provider must not block deletion

            # Drop the session's screen-observation in-memory state
            # (cooldown + caption dedup) so those tables don't grow
            # unbounded across the process lifetime.
            try:
                from service.vtuber.screen_observation import cleanup_session_state
                cleanup_session_state(session_id)
            except Exception:
                pass  # best-effort

            # Same reasoning for the executor's own per-session registries
            # (holder, drain/closing guards, admission lock): keyed by session
            # id, and until now never cleared for a deleted session.
            try:
                from service.execution.agent_executor import forget_session
                forget_session(session_id)
            except Exception:
                pass  # best-effort — must not block deletion

            # Remove session logger
            remove_session_logger(session_id)

            # Soft-delete in persistent store (keeps metadata for restore)
            self._store.soft_delete(session_id)
            # Archive the session's GAPT workspace (resource hygiene + keeps
            # the GAPT view clean). Bind workspaces never delete the session
            # dir, so a restore simply re-provisions under the same name.
            try:
                from service.gapt import GaptWorkspaceProvider, get_gapt_client

                _gc = get_gapt_client()
                if _gc.configured:
                    _prov = GaptWorkspaceProvider(_gc)
                    _proj = await _prov._find_project_by_slug(
                        os.getenv("GENY_GAPT_PROJECT_SLUG", "geny")
                    )
                    if _proj:
                        _ws = await _prov._find_workspace_by_name(
                            _proj.get("id") or "", session_id
                        )
                        if _ws and _ws.get("id"):
                            await _gc.delete_workspace(_ws["id"])
                            logger.info(
                                f"[{session_id}] gapt workspace archived with delete"
                            )
            except Exception:  # noqa: BLE001 — never block session delete
                logger.debug(
                    f"[{session_id}] gapt workspace archive failed", exc_info=True
                )

            # Re-open the teardown gate: the record is soft-deleted so no turn
            # can resolve it now, but a later restore reuses this id and must
            # not inherit a stale "closing" flag (which would reject its turns).
            try:
                from service.execution.agent_executor import clear_session_closing
                clear_session_closing(session_id)
            except Exception:
                pass

            # SESSION_DELETED bus emit — ``hard`` reflects whether the
            # caller asked for storage cleanup (permanent delete flow).
            await self._lifecycle_bus.emit(
                LifecycleEvent.SESSION_DELETED,
                session_id,
                hard=bool(cleanup_storage),
            )

            logger.info(f"[{session_id}] ✅ AgentSession deleted (soft)")
            return True

        # Dormant session (post-restart): not live in memory, but a
        # non-deleted record exists in the store. Without this branch the
        # delete silently no-ops ("AgentSession not found"), leaving the
        # session visible-and-undeletable. Soft-delete the store record
        # directly (store.soft_delete cascades to the linked peer).
        record = self._store.get(session_id)
        if record and not record.get("is_deleted"):
            logger.info(f"[{session_id}] Deleting dormant session (store-only)...")
            try:
                self._persona_provider.reset(session_id)
            except Exception:
                pass  # best-effort
            remove_session_logger(session_id)

            if cleanup_storage:
                storage_path = record.get("storage_path")
                if storage_path:
                    from pathlib import Path as FilePath

                    sp = FilePath(storage_path)
                    if sp.is_dir():
                        try:
                            await rmtree_async(sp)
                            logger.info(f"[{session_id}] Storage cleaned up: {storage_path}")
                        except Exception as e:
                            logger.warning(f"[{session_id}] Failed to cleanup storage: {e}")

            # A dormant session can still own stale executor rows from when it
            # was live earlier in this process lifetime.
            try:
                from service.execution.agent_executor import forget_session
                forget_session(session_id)
            except Exception:
                pass  # best-effort

            self._store.soft_delete(session_id)
            await self._lifecycle_bus.emit(
                LifecycleEvent.SESSION_DELETED,
                session_id,
                hard=bool(cleanup_storage),
            )
            logger.info(f"[{session_id}] ✅ Dormant session deleted (soft)")
            return True

        # Unknown session id — nothing anywhere to delete.
        return False

    async def cleanup_dead_sessions(self):
        """Revive idle AgentSessions; delete the ones that cannot be revived."""
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

            logger.info(f"[{session_id}] Cleaning up unrevivable AgentSession")
            await self.delete_session(session_id)

    # ========================================================================
    # Background Idle Monitor
    # ========================================================================

    def set_tick_engine(self, engine: "TickEngine") -> None:  # type: ignore[name-defined]
        """Inject an externally-owned ``TickEngine``.

        Used in X2-6 when ``main.py`` constructs a single shared engine
        for all services. When injected, the manager won't call
        ``engine.start()`` / ``engine.stop()`` — the owner does.
        Must be called before :meth:`start_idle_monitor`.
        """
        if self._idle_monitor_running:
            raise RuntimeError(
                "set_tick_engine must be called before start_idle_monitor"
            )
        self._idle_tick_engine = engine
        self._owns_idle_tick_engine = False

    async def start_idle_monitor(self) -> None:
        """Start the background idle monitor on the TickEngine.

        Periodically scans all RUNNING sessions and transitions them to
        IDLE if they have had no activity for ``idle_transition_seconds``
        (default 10 minutes / 600 seconds).

        Should be called once during application startup.
        """
        if self._idle_monitor_running:
            logger.debug("Idle monitor already running")
            return

        from service.tick import TickSpec
        self._idle_tick_engine.register(
            TickSpec(
                name="idle_monitor",
                interval=self._idle_monitor_interval,
                handler=self._scan_for_idle_sessions,
                jitter=self._idle_monitor_jitter,
            )
        )
        # Media retention janitor: the screen-observation pipeline's own
        # pruner only fires DURING live uploads, so dormant sessions kept
        # accumulating frames forever (387 MB observed in prod). This sweep
        # covers every session under the storage root — live or dormant —
        # on a 6h cadence (age window + size budget; attachments opt-in).
        async def _media_retention_tick() -> None:
            import asyncio as _aio

            from service.memory.media_retention import sweep_all_sessions

            await _aio.to_thread(sweep_all_sessions)

        self._idle_tick_engine.register(
            TickSpec(
                name="media_retention",
                interval=6 * 3600,
                handler=_media_retention_tick,
                jitter=300,
            )
        )

        # Note retention — the OTHER half of the same problem. Media sweeps
        # frames; this sweeps the notes themselves, which grow at ~757/day
        # from the observation trigger and were never removed by anything.
        #
        # A tick, deliberately, not the session warm-up: the first version
        # ran there and its deletes starved a live turn for 300 seconds.
        # Housekeeping belongs off the path a user is waiting on.
        async def _note_retention_tick() -> None:
            for agent in list(self._local_agents.values()):
                mm = getattr(agent, "_memory_manager", None)
                if mm is None or not hasattr(mm, "prune_expired_notes"):
                    continue
                try:
                    await mm.prune_expired_notes()
                except Exception:  # noqa: BLE001 — one session, not the tick
                    logger.debug("note retention tick failed", exc_info=True)

        self._idle_tick_engine.register(
            TickSpec(
                name="note_retention",
                interval=6 * 3600,
                handler=_note_retention_tick,
                jitter=600,
            )
        )
        if self._owns_idle_tick_engine:
            await self._idle_tick_engine.start()
        self._idle_monitor_running = True
        _now = self._evict_seconds()
        try:
            from service.executor.agent_session import _host_keeps_sessions_awake
            _awake = _host_keeps_sessions_awake()
        except Exception:  # noqa: BLE001 — log line must never fail startup
            _awake = False
        if _now <= 0:
            _evict = "disabled"
        elif _awake:
            # The threshold is live, but the host default pins every
            # session — only ones the user released (always_on=False)
            # are eligible.
            _evict = f"{_now:.0f}s (host keeps sessions awake; applies only to sessions released by the user)"
        else:
            _evict = f"{_now:.0f}s"
        logger.info(
            "✅ Idle monitor started (interval=%ss±%ss, evict=%s, owned=%s)",
            self._idle_monitor_interval,
            self._idle_monitor_jitter,
            _evict,
            self._owns_idle_tick_engine,
        )

    async def stop_idle_monitor(self) -> None:
        """Stop the background idle monitor.

        Called during application shutdown.
        """
        if not self._idle_monitor_running:
            return
        self._idle_monitor_running = False
        self._idle_tick_engine.unregister("idle_monitor")
        if self._owns_idle_tick_engine:
            await self._idle_tick_engine.stop()
        logger.info("Idle monitor stopped")

    async def _scan_for_idle_sessions(self) -> None:
        """Scan all agent sessions: mark idle ones, then EVICT long-idle ones.

        Two passes. (1) RUNNING → IDLE after ``idle_transition_seconds`` —
        lightweight, just flips the flag. (2) IDLE sessions inactive beyond
        ``_idle_evict_seconds`` are torn down to reclaim RAM (their store
        record + on-disk memory are kept, so they rehydrate transparently on
        next access). Eviction is gated (never always-on, never mid-turn)
        and serialised against reconnects via the per-session rehydrate lock.
        """
        transitioned = 0
        evicted = 0
        now = datetime.now()
        # Resolved once per scan (not per session): every session in this
        # pass is judged against the same threshold, and a settings change
        # takes effect on the next tick.
        evict_after = self._evict_seconds()
        # Snapshot items() so a concurrent create/delete does not mutate
        # the dict mid-scan.
        for session_id, agent in list(self._local_agents.items()):
            if agent.status == SessionStatus.RUNNING:
                if agent.mark_idle():
                    transitioned += 1
                    # Update persistent store with IDLE status
                    try:
                        info = agent.get_session_info()
                        self._store.register(session_id, info.model_dump(mode="json"))
                    except Exception:
                        pass  # non-critical
                    await self._lifecycle_bus.emit(
                        LifecycleEvent.SESSION_IDLE,
                        session_id,
                        reason="timeout",
                    )

            # Eviction pass — only when enabled. Cheap pre-checks here; the
            # authoritative re-check + teardown happens under the lock inside.
            if evict_after > 0 and self._is_evict_candidate(agent, now, evict_after):
                if await self._evict_idle_session(session_id, agent):
                    evicted += 1

        if transitioned > 0:
            logger.info(f"Idle monitor: {transitioned} session(s) transitioned to IDLE")
        if evicted > 0:
            logger.info(
                "Idle monitor: evicted %d long-idle session(s) — resources "
                "released; each rehydrates on next access", evicted,
            )

    def _evict_seconds(self) -> float:
        """The evict threshold in force RIGHT NOW — 0 meaning "never".

        Read per scan, not cached at construction: the whole point of
        putting this in settings is that an operator can turn eviction
        off and have quiet sessions stop disappearing, without a
        redeploy. Settings win; the environment is the fallback for
        hosts that never opened the page.

        Deliberately NOT zeroed by ``keep_sessions_awake``. The host
        policy is folded into each session's ``_is_always_on`` (user
        override → role → host), and the candidate filter consults that
        per session — which is what lets a session the user explicitly
        released (``always_on=False``) still be reclaimed while the host
        keeps everything else awake. Zeroing the threshold here would
        switch the whole pass off and quietly break that override, which
        is exactly what shipped first: the field promised it, the scan
        never ran.
        """
        try:
            from service.config import get_config_manager
            from service.config.sub_config.general.session_lifecycle_config import (
                SessionLifecycleConfig,
            )

            cfg = get_config_manager().load_config(SessionLifecycleConfig)
            if cfg is not None:
                return _coerce_evict_seconds(
                    cfg.idle_evict_seconds, self._idle_evict_seconds
                )
        except Exception:  # noqa: BLE001 — settings must never break the tick
            logger.debug("session lifecycle config unavailable", exc_info=True)
        return self._idle_evict_seconds

    def _is_evict_candidate(
        self, agent: AgentSession, now: datetime, evict_after: float,
    ) -> bool:
        """Cheap, lock-free filter for the eviction pass: a sleeping
        (IDLE), non-always-on session that has been inactive past the evict
        threshold and isn't mid-turn. Re-verified under the lock before any
        teardown (see :meth:`_evict_idle_session`)."""
        if agent.status != SessionStatus.IDLE:
            return False
        if getattr(agent, "_is_always_on", False):
            return False  # VTuber, or one the user pinned — always resident
        last = getattr(agent, "_execution_start_time", None) or getattr(agent, "_created_at", None)
        if last is None:
            return False
        if (now - last).total_seconds() < evict_after:
            return False
        return not self._session_busy(agent._session_id, agent)

    async def _evict_idle_session(self, session_id: str, agent: AgentSession) -> bool:
        """Tear down a long-idle session to reclaim memory, preserving its
        store record + on-disk state so it rehydrates on next access.

        Safety: runs under the per-session rehydrate lock (the same one
        :meth:`ensure_session_live` takes to rebuild a dormant session), so a
        concurrent reconnect blocks here, then takes the absent path and
        rehydrates a FRESH agent after we finish — no two providers touch the
        same ``storage_path`` at once. The agent is removed from the registry
        FIRST (under the lock) so no new caller can bind to a torn-down agent,
        and cleanup runs with ``flush=False`` to keep the lock hold short.
        """
        lock = self._rehydrate_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            try:
                # Authoritative re-check under the lock — state may have moved
                # since the cheap pre-filter (a turn started, a reload rebuilt
                # the agent, another scan already evicted it).
                cur = self._local_agents.get(session_id)
                if cur is not agent:
                    return False
                if cur.status != SessionStatus.IDLE:
                    return False
                if getattr(cur, "_is_always_on", False):
                    return False
                if self._session_busy(session_id, cur):
                    return False

                # Remove from the registry FIRST: any concurrent
                # ensure_session_live now misses the fast path and will
                # rehydrate a fresh agent (blocking on this same lock).
                self._local_agents.pop(session_id, None)
                try:
                    await cur.cleanup(flush=False)
                except Exception:  # noqa: BLE001 — reclaim anyway
                    logger.debug(
                        f"[{session_id}] evict cleanup failed — resources may "
                        "partially leak, but the session is unbound", exc_info=True,
                    )
                # Persist the STOPPED status so the UI shows it dormant and
                # the record (with creation params) stays rehydratable.
                try:
                    info = cur.get_session_info()
                    self._store.register(session_id, info.model_dump(mode="json"))
                except Exception:
                    pass  # non-critical
                # Resource efficiency: an evicted (sleeping) session's GAPT
                # workspace container sleeps too. Best-effort — the handle's
                # ensure() ladder revives it on the next tool call after
                # rehydrate.
                _sb = getattr(cur, "_gapt_sandbox", None)
                if _sb is not None and getattr(_sb, "workspace_id", None):
                    try:
                        from service.gapt import get_gapt_client

                        await get_gapt_client().stop_workspace(_sb.workspace_id)
                        logger.info(
                            f"[{session_id}] gapt workspace stopped with evict "
                            f"({_sb.workspace_id})"
                        )
                    except Exception:  # noqa: BLE001 — never block eviction
                        logger.debug(
                            f"[{session_id}] gapt workspace stop failed",
                            exc_info=True,
                        )
                await self._lifecycle_bus.emit(
                    LifecycleEvent.SESSION_IDLE, session_id, reason="evicted",
                )
                return True
            finally:
                self._rehydrate_locks.pop(session_id, None)

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
