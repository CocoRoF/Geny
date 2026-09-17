import os

# BLAS threading — MUST be set before numpy is imported anywhere.
#
# OpenBLAS starts a worker pool sized to the host's cores. This process forks
# constantly (the Claude Code CLI, docker exec, every subprocess tool), and a
# fork does not carry the pool's threads into the child while the parent's
# bookkeeping still says they exist. The next BLAS call then spin-waits on
# workers that are never coming — one core pinned at 100%, inside a matmul,
# forever, holding whatever lock the caller took.
#
# That is not hypothetical: it wedged the memory engine's global lock for 27
# hours in production. A (4096 x 256) @ (256,) product — microseconds of real
# work — never returned, 13 threads queued behind it, and every agent turn
# timed out at 1800s while /health kept answering "healthy".
#
# Single-threaded BLAS removes the pool, and with it the whole failure class.
# It costs nothing here: these matrices are far too small for threaded BLAS to
# beat its own dispatch overhead.
for _blas_var in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ.setdefault(_blas_var, "1")

import sys
import asyncio
from logging import basicConfig, getLogger, INFO
from pathlib import Path
from contextlib import asynccontextmanager

# Hang diagnostics: dump every thread's stack on SIGUSR1 (→ container logs)
# so a frozen event loop can be root-caused without ptrace/py-spy (which the
# container lacks the capability for). Trigger with:
#   docker exec <backend> kill -USR1 1   (or the python pid)
try:
    import faulthandler
    import signal

    faulthandler.enable()
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
except Exception:  # noqa: BLE001
    pass

# Load .env BEFORE any other imports so that modules reading os.getenv()
# at import time (e.g. database_config → POSTGRES_PORT) pick up the
# correct values.
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
        print(f"[OK] Loaded environment from {_env_path}")
    else:
        _example_path = Path(__file__).parent / ".env.example"
        if _example_path.exists():
            print("[INFO] No .env file found. Copy .env.example to .env and configure it.")
except ImportError:
    print("[WARN] python-dotenv not installed. Environment variables must be set manually.")

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from controller.command_controller import router as command_router, get_prompts_list
from controller.agent_controller import router as agent_router, agent_manager
from controller.agent_tasks_controller import router as agent_tasks_router
from controller.hook_automation_controller import router as hooks_router
from controller.slash_commands_controller import router as slash_router
from controller.config_controller import router as config_router
from controller.ssh_controller import router as ssh_router  # SSH connection test
from controller.tool_settings_controller import router as tool_settings_router
from controller.gapt_controller import router as gapt_router  # GAPT integration status
from controller.gapt_settings_controller import router as gapt_settings_router  # GAPT settings proxy
from controller.sync_controller import router as sync_router  # cross-service settings sync
from controller.avatar_controller import router as avatar_router  # geny-avatar integration
from controller.llm_backends_controller import router as llm_backends_router
from controller.llm_accounts_controller import router as llm_accounts_router
from controller.mcp_bridge_controller import router as mcp_bridge_router
from controller.chat_controller import router as chat_router
from controller.upload_controller import router as upload_router
from controller.tool_preset_controller import router as tool_preset_router
from controller.tool_controller import router as tool_catalog_router
from controller.custom_tools_controller import router as custom_tools_router  # Phase B — DB-backed user tools
from controller.sandbox_tool_packs_controller import router as sandbox_tool_packs_router  # Sandbox Tool Packs
from controller.persona_presets_controller import router as persona_presets_router  # Persona Presets
from controller.google_controller import router as google_router  # Google Workspace OAuth
from controller.connectors_controller import router as connectors_router  # MCP connectors
from controller.sandbox_observability_controller import router as sandbox_observability_router  # Sandbox Logs
from controller.skills_controller import router as skills_router
from controller.admin_controller import router as admin_router
from controller.permission_controller import router as permission_router  # PR-E.2.1
from controller.hook_controller import router as hook_router  # PR-E.3.1 (env lifecycle hooks — removal pending)
from controller.agent_workspace_controller import router as agent_workspace_router  # workspace state + activity ledger
from controller.framework_settings_controller import router as framework_settings_router  # PR-F.1.x
from controller.subagent_type_controller import router as subagent_type_router  # PR-F.3.1
from controller.mcp_custom_controller import router as mcp_custom_router  # Cycle G — MCP UI
from controller.notifications_controller import router as notifications_router  # Cycle G
from controller.env_defaults_controller import router as env_defaults_router  # 1.0.2 — env-defaults host config
from controller.mcp_oauth_controller import (
    agent_oauth_router,
    mcp_resource_router,
)
from controller.docs_controller import router as docs_router
from controller.memory_controller import router as memory_router
from controller.memory_controller import global_router as global_memory_router
from controller.transcripts_controller import router as transcripts_router
from controller.environment_controller import router as environment_router
from controller.trigger_preset_controller import router as trigger_preset_router
from controller.catalog_controller import router as catalog_router
from controller.vtuber_controller import router as vtuber_router
from controller.vtuber_baked_imports_controller import (
    router as vtuber_baked_imports_router,
    library_router as vtuber_library_router,
)  # geny-avatar integration (Phase C + library auto-sync)
from controller.tts_controller import router as tts_router
from controller.voice_studio import router as voice_studio_router
from controller.auth_controller import router as auth_router
from controller.user_opsidian_controller import router as user_opsidian_router
from controller.knowledge_controller import router as knowledge_router
from controller.curated_knowledge_controller import router as curated_knowledge_router
from controller.whiteboard_controller import router as whiteboard_router  # whiteboard P0
from controller.stt_controller import router as stt_router  # voice-notes W1
from controller.vtuber_screen_observation_controller import (  # V3 screen observation
    router as vtuber_screen_observation_router,
)
from routers.playground2d import router as playground2d_router
from ws.execute_stream import router as ws_execute_router
from ws.chat_stream import router as ws_chat_router
from ws.avatar_stream import router as ws_avatar_router
from ws.connector_stream import router as ws_connector_router
from ws.workspace_stream import router as ws_workspace_router
from ws.voice_realtime_stream import router as ws_voice_realtime_router
from service.config import get_config_manager
from service.mcp_loader import MCPLoader, get_global_mcp_config
import uvicorn

# (.env already loaded at top of file, before controller imports)

# Configure GitHub CLI authentication from GITHUB_TOKEN
# This allows gh CLI to work without interactive login
github_token = os.environ.get('GITHUB_TOKEN')
if github_token:
    os.environ['GH_TOKEN'] = github_token
    print("✅ GitHub CLI configured with GITHUB_TOKEN")

# Logging configuration
basicConfig(
    level=INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = getLogger(__name__)


def print_geny_agent_logo():
    """Print Geny Agent logo"""
    logo = """
     ██████╗ ███████╗███╗   ██╗██╗   ██╗     █████╗  ██████╗ ███████╗███╗   ██╗████████╗
    ██╔════╝ ██╔════╝████╗  ██║╚██╗ ██╔╝    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
    ██║  ███╗█████╗  ██╔██╗ ██║ ╚████╔╝     ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
    ██║   ██║██╔══╝  ██║╚██╗██║  ╚██╔╝      ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
    ╚██████╔╝███████╗██║ ╚████║   ██║       ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
     ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝       ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝

    GenY Agent - Multi-Session Management System
    """
    logger.info(logo)


def print_step_banner(step: str, title: str, description: str = ""):
    """Print step banner"""
    banner = f"""
    ┌{'─' * 60}┐
    │  {step}: {title:<52}│
    {f'│  {description:<58}│' if description else ''}
    └{'─' * 60}┘
    """
    logger.info(banner)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    print_geny_agent_logo()
    print_step_banner("START", "GENY AGENT STARTUP", "Initializing agent session management system")
    logger.info("Starting Geny Agent")

    # Event-loop watchdog: a silent loop block (3 separate prod incidents)
    # now self-diagnoses — after ~10s of unresponsiveness it CRITICAL-logs
    # every thread's stack, including the exact synchronous call squatting
    # on the loop. Read-only diagnostics; one daemon thread.
    try:
        import asyncio as _asyncio

        from service.observability.loop_watchdog import install_loop_watchdog

        install_loop_watchdog(_asyncio.get_running_loop())
    except Exception:  # noqa: BLE001 — never block startup on diagnostics
        logger.warning("loop watchdog install failed", exc_info=True)

    # Make asyncio-level failures audible. Anything that escapes a task —
    # ours or a library's — otherwise reaches only asyncio's own default
    # handler, which writes to stderr with no logger name and no level, so
    # it is invisible to log filters and easily lost in framework noise.
    # A background job can be dead for weeks that way; one was.
    try:
        import asyncio as _asyncio

        install_asyncio_exception_handler(_asyncio.get_running_loop())
    except Exception:  # noqa: BLE001 — never block startup on diagnostics
        logger.warning("asyncio exception handler install failed", exc_info=True)

    # (Step 0 removed — geny-executor 2.2.0 absorbed the llm_patches
    # compensation layer: CLI tool-call observability and structured
    # error envelopes are first-class ``api.*`` pipeline events now,
    # bridged in ``service.executor.agent_session``.)

    # Apply the persisted Timezone config to the environment at boot, so every
    # time helper (now_kst / prompt datetime / think-trigger time-of-day) agrees
    # with the user's configured timezone even before the config is first read.
    try:
        from service.config import get_config_manager
        from service.config.sub_config.general.timezone_config import TimezoneConfig
        from service.config.sub_config.tools.web_search_config import WebSearchConfig

        _cm = get_config_manager()
        # _sync_env_on_load fires each config's env_sync apply_change callbacks,
        # so the persisted values reach os.environ before anything reads them.
        _cm.load_config(TimezoneConfig)  # → GENY_TIMEZONE
        _cm.load_config(WebSearchConfig)  # → GENY_WEBSEARCH_BACKEND / *_API_KEY / SEARXNG_URL
        import os as _os

        logger.info(
            "Boot config sync: GENY_TIMEZONE=%s GENY_WEBSEARCH_BACKEND=%s",
            _os.environ.get("GENY_TIMEZONE"),
            _os.environ.get("GENY_WEBSEARCH_BACKEND"),
        )
    except Exception:  # noqa: BLE001 — never block startup on this
        logger.warning("Boot config env-sync failed; using defaults", exc_info=True)

    # ── Step 1: Initialize PostgreSQL Database ─────────────────────────
    app_db = None
    try:
        print_step_banner("DATABASE", "POSTGRESQL DATABASE", "Connecting to PostgreSQL...")
        from service.database import AppDatabaseManager, database_config, APPLICATION_MODELS
        from service.database.migrations import run_cleanup_migration

        app_db = AppDatabaseManager()

        # Register models first
        app_db.register_models(APPLICATION_MODELS)
        logger.info(f"   - Registered models: {len(APPLICATION_MODELS)}")
        for model_cls in APPLICATION_MODELS:
            inst = model_cls()
            logger.info(f"     - {model_cls.__name__} -> {inst.get_table_name()}")

        # Initialize database (connect + create tables + auto-migration)
        connected = app_db.initialize_database()
        if connected:
            logger.info(f"   - Host: {database_config.POSTGRES_HOST.value}:{database_config.POSTGRES_PORT.value}")
            logger.info(f"   - Database: {database_config.POSTGRES_DB.value}")
            logger.info(f"   - Auto-migration: {database_config.AUTO_MIGRATION.value}")
            logger.info("   - Database tables initialized")

            # Run data migrations (cleanup escaped configs, etc.)
            run_cleanup_migration(app_db)
            logger.info("   - Data migrations complete")

            app.state.app_db = app_db
        else:
            logger.warning("   - Database connection failed, running in file-only mode")
            app_db = None
    except Exception as e:
        logger.warning(f"   - Database initialization failed: {e}")
        logger.warning("   - Running in file-only mode (configs stored in JSON files)")
        app_db = None

    # ── Step 2: Initialize Config Manager (with DB backend) ────────────
    print_step_banner("CONFIG", "CONFIG MANAGER", "Loading configurations...")

    # Initialize Auth Service (requires DB)
    if app_db is not None:
        from service.auth import init_auth_service
        auth_svc = init_auth_service(app_db)
        app.state.auth_service = auth_svc
        has_admin = auth_svc.has_users()
        logger.info(f"   - Auth service: initialized (admin exists: {has_admin})")
        from service.auth.app_password_service import init_app_password_service
        init_app_password_service(app_db)
        logger.info("   - App password service: initialized")
    else:
        app.state.auth_service = None
        logger.info("   - Auth service: disabled (no database)")

    config_manager = get_config_manager()

    # Register MCP connector configs (one hidden BaseConfig per connector, built
    # from the catalog) so they persist + appear in compute_satisfied_config + the
    # /api/config endpoints. Must run before set_database so the tables include them.
    try:
        from service.mcp_connectors import ensure_registered as _register_connectors
        _register_connectors()
        logger.info("   - MCP connectors: catalog registered")
    except Exception as _e:  # noqa: BLE001
        logger.warning(f"   - MCP connectors registration skipped: {_e}")

    # Connect database to config manager if available
    if app_db is not None:
        config_manager.set_database(app_db)
        logger.info("   - Config storage: PostgreSQL (primary) + JSON (backup)")

        # Migrate existing JSON configs to database
        migration_results = config_manager.migrate_all_to_db()
        migrated = sum(1 for v in migration_results.values() if v)
        logger.info(f"   - Config migration: {migrated}/{len(migration_results)} configs in DB")
    else:
        logger.info("   - Config storage: JSON files (database unavailable)")

    app.state.config_manager = config_manager
    registered_configs = config_manager.get_registered_config_classes()
    logger.info(f"   - Registered Configs: {len(registered_configs)}")
    for config_name, config_class in registered_configs.items():
        # Load (and create if missing) each config
        config_manager.load_config(config_class)
        logger.info(f"     - {config_name}")

    # ── Step 3: Connect SessionStore & ChatStore to DB ─────────────────
    print_step_banner("SESSIONS", "SESSION STORE", "Connecting session stores to database...")
    from service.sessions.store import get_session_store
    from service.chat.conversation_store import get_chat_store

    session_store = get_session_store()
    chat_store = get_chat_store()

    if app_db is not None:
        session_store.set_database(app_db)
        logger.info("   - SessionStore: PostgreSQL (primary) + JSON (backup)")

        chat_store.set_database(app_db)
        logger.info("   - ChatStore: PostgreSQL (primary) + JSON (backup)")
    else:
        logger.info("   - SessionStore: JSON files (database unavailable)")
        logger.info("   - ChatStore: JSON files (database unavailable)")

    # ── Step 4: Connect Logging & Memory to DB ─────────────────────────
    print_step_banner("LOGGING", "SESSION LOGGING & MEMORY", "Connecting logging and memory to database...")
    from service.logging.session_logger import set_log_database

    if app_db is not None:
        set_log_database(app_db)
        logger.info("   - SessionLogger: PostgreSQL (primary) + file (backup)")

        agent_manager.set_app_db(app_db)
        logger.info("   - AgentSession memory: PostgreSQL (primary) + file (backup)")
    else:
        logger.info("   - SessionLogger: file only (database unavailable)")
        logger.info("   - AgentSession memory: file only (database unavailable)")

    # Load Python tools via ToolLoader
    print_step_banner("TOOLS", "TOOL LOADER", "Loading Python tools...")
    from service.tool_loader import get_tool_loader
    tool_loader = get_tool_loader()
    tool_loader.load_all()
    app.state.tool_loader = tool_loader
    logger.info(f"   - Built-in tools: {len(tool_loader.get_builtin_names())}")
    logger.info(f"   - Custom tools: {len(tool_loader.get_custom_names())}")

    # Auto-load external MCP configs
    print_step_banner("MCP", "MCP LOADER", "Loading external MCP configs...")
    mcp_loader = MCPLoader()
    mcp_config = mcp_loader.load_all()
    app.state.mcp_loader = mcp_loader
    app.state.global_mcp_config = mcp_config

    # Inject global MCP config into AgentSessionManager
    agent_manager.set_global_mcp_config(mcp_config)
    logger.info(f"   - External MCP Servers: {mcp_loader.get_server_count()}")

    # Inject ToolLoader into AgentSessionManager
    agent_manager.set_tool_loader(tool_loader)

    # Install Tool Preset templates (all-tools only)
    from service.tool_preset.store import get_tool_preset_store
    from service.tool_preset.templates import install_templates as install_tool_preset_templates
    tool_preset_store = get_tool_preset_store()
    # Phase 2A — wire Postgres as the SOT before templates are
    # installed so the seed rows land in the DB. ``set_database``
    # also runs a DB↔file reconcile so any presets created during a
    # previous DB outage are pushed up.
    if app_db is not None:
        tool_preset_store.set_database(app_db)
        logger.info("   - Tool preset storage: PostgreSQL (primary) + JSON (backup)")
    else:
        logger.info("   - Tool preset storage: JSON files (database unavailable)")
    tool_preset_templates_installed = install_tool_preset_templates(tool_preset_store)
    logger.info(f"   - Tool preset templates installed: {tool_preset_templates_installed}")
    logger.info(f"   - Total tool presets: {len(tool_preset_store.list_all())}")

    # ── Custom Tools store (Phase B — DB-backed user tools) ─────────
    # Mirrors the tool-preset store wiring. Must run *after* the
    # filesystem ToolLoader so the boot-time merge can resolve
    # builtin_alias rows. The loader's ``reload_custom_tools_db``
    # path is the runtime hot-reload entry used by the CRUD controller.
    from service.custom_tools import get_custom_tool_store
    from service.custom_tools.samples import seed_samples
    custom_tool_store = get_custom_tool_store()
    if app_db is not None:
        custom_tool_store.set_database(app_db)
        # Phase D — seed the Geny-shipped sample rows (blog_agent_*
        # as builtin_alias). Idempotent: existing rows are skipped.
        seeded = seed_samples(custom_tool_store)
        # Overlay DB-backed custom tools onto the filesystem roster.
        added = tool_loader.load_custom_tools_from_db()
        logger.info(f"   - Custom tools (DB): {added} loaded (seeded {seeded} new sample)")
    else:
        logger.info("   - Custom tools (DB): skipped — database unavailable")

    # Sandbox Tool Packs — [GAPT env + tools + skills] bundles. The store is
    # DB-backed; the table auto-creates via APPLICATION_MODELS. Loading enabled
    # packs into a session happens at session build (env opt-in, later phase).
    from service.sandbox_tool_packs import get_sandbox_tool_pack_store
    if app_db is not None:
        get_sandbox_tool_pack_store().set_database(app_db)
        logger.info("   - Sandbox Tool Packs: store wired")
    else:
        logger.info("   - Sandbox Tool Packs: skipped — database unavailable")

    # Persona Presets — structured persona definitions (Geny-only persona builder).
    # DB-backed (table auto-creates via APPLICATION_MODELS); seed the starter
    # presets after the store has its DB so the rows land in the table.
    from service.persona_presets import (
        get_persona_preset_store,
        install_persona_templates,
    )
    if app_db is not None:
        get_persona_preset_store().set_database(app_db)
        seeded = install_persona_templates(get_persona_preset_store())
        logger.info(f"   - Persona Presets: store wired, {seeded} starter preset(s) installed")
    else:
        logger.info("   - Persona Presets: skipped — database unavailable")

    # (Shared folder removed — sessions now use isolated GAPT workspaces.)

    # Start background idle monitor (transitions idle sessions to IDLE status)
    await agent_manager.start_idle_monitor()
    logger.info("   - Session idle monitor: started (10min threshold)")

    # Cycle 20260421_8 PR-X2-6 — WS abandoned detector. WS handlers call
    # ``detector.connect/disconnect``; a TickEngine spec polls every 60s
    # and emits SESSION_ABANDONED for sessions whose WS has been closed
    # for longer than the threshold (default 120s).
    from service.lifecycle import WSAbandonedDetector
    from service.tick import TickEngine as _WSDetectorEngine
    from service.tick import TickSpec as _WSDetectorSpec

    ws_abandoned_detector = WSAbandonedDetector(
        bus=agent_manager.lifecycle_bus,
        threshold_seconds=120.0,
    )
    _ws_detector_engine = _WSDetectorEngine()
    _ws_detector_engine.register(
        _WSDetectorSpec(
            name="ws_abandoned_detector",
            interval=60.0,
            handler=ws_abandoned_detector.scan,
            jitter=5.0,
        )
    )
    await _ws_detector_engine.start()
    app.state.ws_abandoned_detector = ws_abandoned_detector
    app.state.ws_detector_engine = _ws_detector_engine
    logger.info("   - WS abandoned detector: started (120s threshold, 60s±5s tick)")

    # ── EnvironmentService (Phase 3) ───────────────────────────────────
    # Persists EnvironmentManifest templates to ./data/environments/*.json
    # (or ENVIRONMENT_STORAGE_PATH). Routers are wired in the follow-up PRs
    # (#6 environment_controller, #7 catalog_controller); until then the
    # service sits on app.state ready for use.
    from service.environment import (
        EnvironmentService,
        set_environment_service,
    )
    environment_service = EnvironmentService()
    # Phase 2B — wire Postgres as the SOT before the default
    # manifest seeds run so they land in the DB on first boot.
    # ``set_database`` also reconciles file-only envs (created
    # during a previous DB outage) back into the DB.
    if app_db is not None:
        environment_service.set_database(app_db)
        logger.info("   - Environment storage: PostgreSQL (primary) + JSON (backup)")
    else:
        logger.info("   - Environment storage: JSON files (database unavailable)")
    app.state.environment_service = environment_service
    agent_manager.set_environment_service(environment_service)
    # Phase 9.9.2 — module-level accessor so service-layer code (e.g.
    # ``AgentSession._load_permission_host_selection``) can reach the
    # same instance without a FastAPI ``Request``.
    set_environment_service(environment_service)
    logger.info(f"   - EnvironmentService: storage={environment_service.storage_path}")

    # Seed default environment manifests (WORKER + VTUBER). The two
    # template seed ids are rewritten every boot from the canonical
    # geny_executor.build_manifest output — custom envs (any other id) are
    # untouched. Keeps seeds in lockstep with manifest-builder changes
    # without a migration framework. The worker env binds to every
    # tool the loader knows about — both platform builtins (``geny_*``,
    # ``memory_*``, ``knowledge_*``) and custom tools — so its "All
    # Tools" sensibility tracks what the user actually has. The
    # executor's ``_register_external_tools`` path only consumes
    # ``manifest.tools.external``, so passing the union here is what
    # gets the platform tools into ``pipeline.tool_registry``.
    from service.environment.templates import install_environment_templates
    env_templates_installed = install_environment_templates(
        environment_service,
        external_tool_names=tool_loader.get_all_names(),
        tool_loader=tool_loader,
    )
    logger.info(f"   - Environment templates installed: {env_templates_installed}")

    # An install that predates accounts reaches its model through the legacy
    # per-provider credentials. Environments now name ``geny_router``, so
    # without this an upgrade leaves the server unable to start a session —
    # telling a user to add the account they added years ago. Runs once: the
    # moment one account exists it does nothing.
    from service.llm_accounts import adopt_legacy_credentials

    adopted = adopt_legacy_credentials()
    if adopted:
        logger.info(f"   - Legacy credentials adopted as accounts: {adopted}")
    logger.info(f"   - Total environments: {len(environment_service.list_all())}")

    # ── CreatureState (cycle 20260421_9 PR-X3-5, toggled by GameConfig) ──
    # Controlled via ``GameConfig`` (Settings UI → Tamagotchi).
    # When ``enabled`` we:
    #   1. Build a process-wide ``SqliteCreatureStateProvider``.
    #   2. Launch ``CreatureStateDecayService`` on its own TickEngine.
    #   3. Wire the provider into ``agent_manager`` so new sessions
    #      hydrate/persist around every pipeline turn. Role gating
    #      (``vtuber_only``) is applied per-session inside the manager.
    # Legacy ``GENY_GAME_FEATURES`` / ``GENY_STATE_DB`` env vars are
    # still honored by ``GameConfig.get_default_instance`` on first
    # boot (one-cycle back-compat); after the first save to the config
    # store the persisted value wins.
    # Shutdown mirrors: stop the decay service, close the provider.
    from service.config.sub_config.general.game_config import GameConfig
    game_cfg = config_manager.load_config(GameConfig)
    app.state.state_provider = None
    app.state.state_decay_service = None
    if game_cfg.enabled:
        from service.state import (
            CreatureStateDecayService,
            SqliteCreatureStateProvider,
        )

        # Resolve creature SQLite path. The legacy default
        # ``backend/data/geny_state.sqlite3`` is on the container
        # writable layer (wiped on rebuild). docker-compose now sets
        # ``GENY_GAME_STATE_DB`` to a named-volume path so creature
        # state survives ``docker compose up --build backend``.
        _state_default = os.environ.get("GENY_GAME_STATE_DB", "").strip() or str(
            Path(__file__).parent / "data" / "geny_state.sqlite3"
        )
        resolved_db_path = (
            game_cfg.state_db_path.strip()
            if game_cfg.state_db_path
            else _state_default
        )
        Path(resolved_db_path).parent.mkdir(parents=True, exist_ok=True)
        state_provider = SqliteCreatureStateProvider(db_path=resolved_db_path)
        decay_service = CreatureStateDecayService(provider=state_provider)
        await decay_service.start()
        agent_manager.set_state_provider(
            state_provider,
            decay_service=decay_service,
            vtuber_only=game_cfg.vtuber_only,
        )
        app.state.state_provider = state_provider
        app.state.state_decay_service = decay_service
        logger.info(
            f"   - CreatureState: enabled (sqlite={resolved_db_path}, "
            f"decay interval=15m, vtuber_only={game_cfg.vtuber_only})"
        )
    else:
        logger.info("   - CreatureState: disabled (GameConfig.enabled=False)")

    # ── ArtifactService (Phase 3) ───────────────────────────────────────
    # Session-less catalog of executor stage/artifact introspection.
    # Caches are lazy + process-wide; first call warms them.
    from service.artifact import ArtifactService
    app.state.artifact_service = ArtifactService()
    logger.info("   - ArtifactService: ready (lazy catalog)")

    # ── VTuber Service: Live2D model management + avatar state ─────────
    print_step_banner("VTUBER", "VTUBER SERVICE", "Initializing Live2D model management...")
    from service.vtuber import Live2dModelManager, AvatarStateManager

    live2d_models_dir = str(Path(__file__).parent / "static" / "live2d-models")
    live2d_model_manager = Live2dModelManager(live2d_models_dir)
    avatar_state_manager = AvatarStateManager()
    app.state.live2d_model_manager = live2d_model_manager
    app.state.avatar_state_manager = avatar_state_manager
    # Capability-bridge registry — same singleton the executor capability Tool reads.
    from service.executor.connector_registry import get_connector_registry
    app.state.connector_registry = get_connector_registry()
    logger.info(f"   - Live2D models: {len(live2d_model_manager.models)}")
    logger.info(f"   - Default model: {live2d_model_manager.default_model_name}")

    # Start the auto-publish library watcher. It mirrors the shared
    # docker volume (avatar-editor writes baked zips here whenever a
    # library row changes) into the model registry. The task is
    # cancelled in the shutdown branch below.
    from service.vtuber.library_watcher import start_library_watcher

    app.state.library_watcher_task = start_library_watcher(app)

    # ── Audio Backfill Loop ───────────────────────────────────────────
    # Idle background loop that catches inbox audio notes the W2
    # PostCaptureHook couldn't transcribe at capture time (whisper-stt
    # was down, or the capture pre-dates the hook). Runs at most one
    # transcription per cycle so the live capture path always wins
    # the GPU race. Cancelled cleanly in the shutdown branch below.
    from service.whiteboard.audio_backfill import start_audio_backfill_loop

    app.state.audio_backfill_task = start_audio_backfill_loop()
    logger.info("   ✅ audio_backfill_loop: started")

    # Give agent_executor access to app.state for avatar state emission
    from service.execution.agent_executor import set_app_state
    set_app_state(app.state)

    # ── Trigger Preset Service ────────────────────────────────────────
    # Persists user-defined trigger bundles under ./data/trigger_presets/*.json.
    # Created before ``thinking_trigger`` so the runtime can resolve
    # preset records on the very first tick after boot.
    from service.trigger_preset import (
        TriggerPresetService,
        set_trigger_preset_service,
    )
    trigger_preset_service = TriggerPresetService()
    # Phase 2C — wire Postgres as the SOT. ``set_database`` also
    # reconciles file-only presets back into the DB so a preset
    # created during a DB outage gets picked up on next boot.
    if app_db is not None:
        trigger_preset_service.set_database(app_db)
        logger.info("   - Trigger preset storage: PostgreSQL (primary) + JSON (backup)")
    else:
        logger.info("   - Trigger preset storage: JSON files (database unavailable)")
    app.state.trigger_preset_service = trigger_preset_service
    set_trigger_preset_service(trigger_preset_service)
    logger.info(
        f"   - TriggerPresetService: storage={trigger_preset_service.storage_path}"
    )

    # ── VTuber Thinking Trigger Service ────────────────────────────────
    from service.vtuber.thinking_trigger import get_thinking_trigger_service
    thinking_trigger = get_thinking_trigger_service()
    await thinking_trigger.start()
    app.state.thinking_trigger = thinking_trigger

    # ── Curation Scheduler Service ────────────────────────────────────
    from service.memory.curation_scheduler import get_curation_scheduler
    curation_scheduler = get_curation_scheduler()
    curation_scheduler.start()
    app.state.curation_scheduler = curation_scheduler

    # ── Knowledge Collection Scheduler ─────────────────────────────────
    # Fires due api/web/db knowledge sources (cron) into the user vault.
    from service.knowledge.connectors import get_knowledge_scheduler
    knowledge_scheduler = get_knowledge_scheduler()
    knowledge_scheduler.start()
    app.state.knowledge_scheduler = knowledge_scheduler

    # ── Background Task Runtime ────────────────────────────────────────
    # geny-executor 1.1.0 ships TaskRegistry + BackgroundTaskRunner
    # primitives. Wire them with the in-memory store as the default
    # backend; operators that need durable persistence swap in
    # FileBackedRegistry (or a custom Postgres backend) via env.
    from service.tasks import install_task_runtime
    try:
        task_runtime = install_task_runtime(app.state)
        app.state.task_registry = task_runtime["registry"]
        app.state.task_runner = task_runtime["runner"]
        logger.info("   ✅ task_runtime: BackgroundTaskRunner started")
    except Exception as e:
        logger.warning(f"   ⚠️  task_runtime: skipped ({e})")
        app.state.task_registry = None
        app.state.task_runner = None

    # ── Sub-agent orchestrator ─────────────────────────────────────────
    # GAP B fix (audit 2026-06-18): the local_agent task executor's
    # factory resolves ``app.state.subagent_orchestrator`` at run time and
    # the inline Agent tool reads it from ToolContext.extras — but it was
    # never set, so background sub-agent tasks + the Agent tool failed.
    # Build one global orchestrator from the shared agent-type registry.
    # Per-session role scoping still applies via the pipeline's own
    # subagent_registry; this global instance backs background local_agent
    # tasks and the inline Agent-tool fallback.
    try:
        from service.agent_types import SubagentRegistryBuilder
        from geny_executor.stages.s12_agent.subagent_type import (
            SubagentTypeOrchestrator,
        )
        _sub_registry = SubagentRegistryBuilder().build()
        app.state.subagent_orchestrator = (
            SubagentTypeOrchestrator(_sub_registry)
            if _sub_registry is not None else None
        )
        logger.info(
            "   ✅ subagent_orchestrator wired (%d agent type(s))",
            len(_sub_registry) if _sub_registry is not None else 0,
        )
        # Persistent sub-agents (executor 2.7.0): owned, autonomous,
        # notify-on-completion. Shares the registry; on_event mirrors
        # assignments into the task registry so they appear in 작업.
        from service.subagents import install_subagent_manager
        app.state.subagent_manager = install_subagent_manager(
            app.state, registry=_sub_registry
        )
    except Exception as e:
        logger.warning(f"   ⚠️  subagent_orchestrator: skipped ({e})")
        app.state.subagent_orchestrator = None
        app.state.subagent_manager = None

    # ── Notification + Messaging Channels ──────────────────────────────
    try:
        from service.notifications import (
            install_notification_endpoints,
            install_send_message_channels,
        )
        app.state.notification_endpoints = install_notification_endpoints()
        app.state.send_message_channels = install_send_message_channels()
        logger.info("   ✅ notifications + messaging channels wired")
    except Exception as e:
        logger.warning(f"   ⚠️  notifications/channels: skipped ({e})")
        app.state.notification_endpoints = None
        app.state.send_message_channels = None

    # ── Slash Commands ────────────────────────────────────────────────
    # Imports built_in/__init__.py which auto-installs the 12 framework
    # commands. install_geny_slash_commands then registers Geny-domain
    # commands and discovery paths under ~/.geny/commands/.
    try:
        from service.slash_commands import install_geny_slash_commands
        slash_count = install_geny_slash_commands()
        logger.info("   ✅ slash_commands: %d available", slash_count)
    except Exception as e:
        logger.warning(f"   ⚠️  slash_commands: skipped ({e})")

    # ── Cron Runtime ──────────────────────────────────────────────────
    # Depends on task_runtime above (cron fires submit TaskRecord
    # through the BackgroundTaskRunner). When task_runner is null,
    # skip cron — operators see a clean log line instead of a crash.
    if app.state.task_runner is not None:
        from service.cron import install_cron_runtime
        try:
            cron_runtime = install_cron_runtime(app.state)
            app.state.cron_store = cron_runtime["store"]
            app.state.cron_runner = cron_runtime["runner"]
            logger.info("   ✅ cron_runtime: CronRunner started")
        except Exception as e:
            logger.warning(f"   ⚠️  cron_runtime: skipped ({e})")
            app.state.cron_store = None
            app.state.cron_runner = None
    else:
        app.state.cron_store = None
        app.state.cron_runner = None

    # ── Inbound Gateway (geny-executor ≥2.11.0) ───────────────────────
    # Telegram (etc) DM → run one VTuber turn → reply. Starts only when a
    # platform is configured (GATEWAY_TELEGRAM_BOT_TOKEN env, or the
    # settings.json ``gateway.platforms`` section). The transport + loop live
    # in the executor; Geny supplies the per-chat session handler.
    try:
        from service.gateway import install_gateway
        app.state.gateway_runner = await install_gateway()
        if app.state.gateway_runner is not None:
            logger.info("   ✅ gateway: inbound chat gateway started")
        else:
            logger.info("   ⏭️  gateway: no platform configured (skipped)")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"   ⚠️  gateway: skipped ({e})")
        app.state.gateway_runner = None

    # ── Tool Runtime Health Check ──────────────────────────────────────
    # Verify tools actually execute (not just registered) by invoking a
    # read-only tool directly and checking the response.
    print_step_banner("HEALTH", "TOOL RUNTIME CHECK", "Verifying tools execute correctly...")
    try:
        test_tool = tool_loader.get_tool("session_list")
        if test_tool:
            test_result = test_tool.run()
            if test_result and isinstance(test_result, str):
                logger.info(f"   ✅ session_list: OK (response {len(test_result)} bytes)")
            else:
                logger.warning(f"   ❌ session_list: unexpected result type: {type(test_result)}")
        else:
            logger.warning("   ❌ session_list: tool not found in loader")
    except Exception as e:
        logger.error(f"   ❌ session_list: execution failed: {e}")

    # Claude Code CLI: re-apply the persisted version pin in the background
    # (manual + apply-pin-on-boot — a rollback or 'keep latest' choice
    # survives a container restart). Best-effort; never blocks startup.
    try:
        from service.claude_code.version_service import apply_pin_on_boot
        spawn_background(
            apply_pin_on_boot(),
            name="claude_code.pin_on_boot",
            key="claude_code.pin_on_boot",
        )
    except Exception:  # noqa: BLE001
        logger.debug("claude_code: pin-on-boot scheduling skipped", exc_info=True)

    print_step_banner("READY", "GENY AGENT READY", "All systems operational!")
    logger.info("Geny Agent startup complete! Ready to serve requests.")

    yield

    print_step_banner("SHUTDOWN", "GENY AGENT SHUTDOWN", "Cleaning up sessions...")
    logger.info("Shutting down Geny Agent")

    # Stop the library watcher first so it can't kick off an install
    # mid-shutdown. Cancellation propagates via asyncio.CancelledError;
    # the watcher loop catches it and logs cleanly.
    watcher_task = getattr(app.state, "library_watcher_task", None)
    if watcher_task is not None and not watcher_task.done():
        watcher_task.cancel()
        try:
            await watcher_task
        except (asyncio.CancelledError, Exception) as e:
            if not isinstance(e, asyncio.CancelledError):
                logger.warning(f"library_watcher shutdown failed: {e}")

    # Stop the audio backfill loop. Cancelling cleanly never throws —
    # any in-flight transcription gets a chance to finish on the
    # whisper client's own timeout (~120s default).
    backfill_task = getattr(app.state, "audio_backfill_task", None)
    if backfill_task is not None and not backfill_task.done():
        backfill_task.cancel()
        try:
            await backfill_task
        except (asyncio.CancelledError, Exception) as e:
            if not isinstance(e, asyncio.CancelledError):
                logger.warning(f"audio_backfill shutdown failed: {e}")

    # Stop the inbound gateway (geny-executor ≥2.11.0) — cancels poll loops
    # and in-flight turns, closes adapters.
    if getattr(app.state, "gateway_runner", None) is not None:
        try:
            await app.state.gateway_runner.shutdown(timeout=5)
        except Exception as e:
            logger.warning(f"gateway shutdown failed: {e}")

    # Stop cron runner before task runner (cron submits to task runner)
    if getattr(app.state, "cron_runner", None) is not None:
        try:
            await app.state.cron_runner.shutdown(timeout=5)
        except Exception as e:
            logger.warning(f"cron_runner shutdown failed: {e}")

    # Stop background task runner (geny-executor 1.1.0+)
    if getattr(app.state, "task_runner", None) is not None:
        try:
            await app.state.task_runner.shutdown(timeout=10)
        except Exception as e:
            logger.warning(f"task_runner shutdown failed: {e}")

    # Stop thinking trigger service
    if hasattr(app.state, 'thinking_trigger'):
        await app.state.thinking_trigger.stop()

    # Stop curation scheduler
    if hasattr(app.state, 'curation_scheduler'):
        app.state.curation_scheduler.stop()

    # Stop knowledge collection scheduler
    if hasattr(app.state, 'knowledge_scheduler'):
        app.state.knowledge_scheduler.stop()

    # Stop idle monitor
    await agent_manager.stop_idle_monitor()

    # Stop WS abandoned detector
    if hasattr(app.state, 'ws_detector_engine'):
        await app.state.ws_detector_engine.stop()

    # Stop creature state decay service + close provider (PR-X3-5).
    if getattr(app.state, "state_decay_service", None) is not None:
        try:
            await app.state.state_decay_service.stop()
            logger.info("   - CreatureStateDecayService stopped")
        except Exception as e:
            logger.warning(f"   - CreatureStateDecayService stop failed: {e}")
    if getattr(app.state, "state_provider", None) is not None:
        close = getattr(app.state.state_provider, "close", None)
        if callable(close):
            try:
                close()
                logger.info("   - CreatureState provider closed")
            except Exception as e:
                logger.warning(f"   - CreatureState provider close failed: {e}")

    # Stop all active sessions (processes only — storage + metadata preserved).
    # Mark each as ``stopped`` (NOT soft-deleted) so it survives the restart
    # and reappears in the session list, lazily re-hydrated on next access.
    # soft_delete is now reserved for explicit user delete. A crash skips this
    # hook entirely — the store still holds the sessions as non-deleted, so the
    # same lazy-restore path covers crash and graceful shutdown identically.
    async def stop_all_sessions():
        from service.sessions.store import get_session_store
        store = get_session_store()

        agents = agent_manager.list_agents()
        stop_tasks = []
        for agent in agents:
            sid = agent.session_id
            stop_tasks.append(agent.cleanup())
            # Interrupted, not deleted — restorable on next boot.
            store.update(sid, {"status": "stopped"})
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

    try:
        await asyncio.wait_for(stop_all_sessions(), timeout=10.0)
        logger.info("All session processes stopped (storage preserved)")
    except asyncio.TimeoutError:
        logger.warning("Session stop timed out, some processes may still be running")

    # Close database connection pool
    if hasattr(app.state, 'app_db') and app.state.app_db is not None:
        try:
            app.state.app_db.close()
            logger.info("Database connection pool closed")
        except Exception as e:
            logger.warning(f"Error closing database connection: {e}")


# Create FastAPI app
app = FastAPI(
    title="Geny Agent",
    description="Geny Agent - Multi-Session Management System",
    version="1.0.0",
    lifespan=lifespan
)

# ---------------------------------------------------------------------------
# Global "login required" gate.
#
# Registered BEFORE CORS on purpose: Starlette runs the LAST-added middleware
# OUTERMOST, so adding CORS after this one makes CORS the outer layer. That
# lets CORS attach Access-Control-* headers to the 401s this gate emits, so a
# cross-origin frontend can read the 401 and redirect to login. This gate is
# secure-by-default — every HTTP request needs a valid JWT except a small
# public allowlist (health, the login flow, the OAuth callback, static assets,
# and the self-authenticating MCP bridge). WebSocket routes keep their own
# auth (ws_auth_or_close); this gate ignores non-http scopes.
from service.auth.auth_middleware import RequireLoginMiddleware  # noqa: E402
from service.memory import inflight as memory_inflight  # noqa: E402
from service.utils.background import (
    background_task_count,
    install_asyncio_exception_handler,
    spawn_background,
)

app.add_middleware(RequireLoginMiddleware)


# CORS configuration. Origins are configurable via GENY_ALLOWED_ORIGINS
# (comma-separated); defaults to "*" to preserve current behavior. Note that
# with the login gate above, an unauthenticated cross-origin request is 401'd
# regardless of CORS, so "*" no longer implies unauthenticated data exposure.
def _cors_allowed_origins() -> list[str]:
    raw = os.getenv("GENY_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/dashboard")


async def _db_status() -> str:
    """Probe the database without ever holding the event loop.

    ``db_manager.health_check`` is synchronous. Awaiting it inline — which is
    what this endpoint used to do — means a slow or hung database blocks the
    loop for the whole probe. That inverts the purpose of a liveness check:
    the probe designed to detect a wedge would itself cause one, the docker
    healthcheck would then time out, and autoheal would restart a backend
    whose only problem was a slow database. Hence: off-loop, and bounded.
    """
    db = getattr(app.state, "app_db", None)
    if db is None:
        return "not_configured"
    try:
        healthy = await asyncio.wait_for(
            asyncio.to_thread(db.db_manager.health_check), timeout=3.0
        )
        return "healthy" if healthy else "unhealthy"
    except asyncio.TimeoutError:
        return "timeout"
    except Exception:  # noqa: BLE001 — a probe must never raise
        return "error"


@app.get("/health")
async def health_check():
    """LIVENESS — is this process still able to serve?

    This is the endpoint the container healthcheck polls, and going unhealthy
    here makes autoheal restart the process. So it must answer only the
    question a restart can fix: *is the event loop still running?* Simply
    reaching this handler and returning proves that.

    It must NOT fail on a database outage. Restarting the backend does not
    repair postgres; it would just add a restart loop on top of the outage.
    Dependency health is reported in the body (and enforced by /health/ready)
    rather than by failing this response.
    """
    agents = agent_manager.list_agents()
    db_status = await _db_status()

    # Memory is not a dependency you can see from outside the process, and it
    # is the one that takes conversations down when it stalls: every Synapse
    # call serialises behind one lock, so one that never returns ends every
    # turn at the 1800s timeout. That happened for 27 hours while this
    # endpoint answered "healthy" — the loop was idle, the DB was up, and
    # nothing here was looking at the part that was actually wedged.
    #
    # Reported, not enforced: a restart would clear a wedge, but a first
    # re-index of a large vault legitimately runs for minutes and must not be
    # killed halfway. Someone reading this should decide.
    memory = memory_inflight.status()
    # Host-side side-effects (conversation archiving, compaction writes)
    # run on their own single worker. A wedge there stalls every later
    # turn in stage s18, and used to be invisible until turns started
    # timing out — so it reports here too.
    try:
        from service.memory.sync_async_bridge import side_effect_status
        memory["side_effects"] = side_effect_status()
    except Exception:  # noqa: BLE001 — a probe must never fail /health
        pass
    if memory["stuck"]:
        logger.warning(
            "memory engine stalled — %s running for %.0fs (%d queued)",
            memory["oldest_operation"], memory["oldest_age_s"],
            memory["in_flight"],
        )

    degraded = db_status not in ("healthy", "not_configured") or memory["stuck"]

    return {
        # Honest, unlike the hardcoded "healthy" this replaces: the old
        # response reported healthy while its own database check said error.
        "status": "degraded" if degraded else "healthy",
        "live": True,
        "total_sessions": len(agents),
        "running_sessions": sum(1 for a in agents if a.status == "running"),
        "error_sessions": sum(1 for a in agents if a.status == "error"),
        "database": db_status,
        "background_tasks": background_task_count(),
        "memory": memory,
    }


@app.get("/health/tasks")
async def health_tasks(response: Response, limit: int = 40):
    """Where every pending coroutine is parked, right now.

    Thread dumps (py-spy, SIGUSR1) answer "what is the CPU doing" and say
    *idle* for the failure that actually hurts here: a turn awaiting
    something that will never arrive. The loop is healthy, every thread is
    asleep, and the product is dead — twice in this codebase's history the
    only way to find the line was to guess.

    This is the missing view. It is a diagnostic, not an API: the shape is
    free to change, and it is deliberately cheap enough to hit while a
    request is hanging.

    ``Task.get_stack()`` alone is not enough, and the gap is exactly the
    case this endpoint exists for: for a *suspended* task CPython returns
    only the outermost frame, so a turn parked twelve awaits deep reports
    a single line ("_run_pipeline") and the actual blocking call stays
    invisible. ``stack`` keeps that view; ``awaiting`` walks the
    ``cr_await`` chain by hand to the innermost frame — the line the turn
    is really stopped on.
    """
    import asyncio as _aio
    import traceback as _tb

    def _await_chain(root, depth: int = 40) -> list[str]:
        """Follow cr_await/ag_await/gi_yieldfrom down to the real block.

        Ends on whatever has no frame left to descend into — a Future
        (nothing scheduled it yet), a lock, a socket read — and names it,
        because *what* is being awaited is half the diagnosis.
        """
        import gc as _gc

        chain: list[str] = []
        node = root
        for _ in range(depth):
            if node is None:
                break
            frame = (getattr(node, "cr_frame", None)
                     or getattr(node, "ag_frame", None)
                     or getattr(node, "gi_frame", None))
            if frame is not None:
                chain.append(
                    f"{frame.f_code.co_filename}:{frame.f_lineno} "
                    f"{frame.f_code.co_name}"
                )
            nxt = (getattr(node, "cr_await", None)
                   or getattr(node, "ag_await", None)
                   or getattr(node, "gi_yieldfrom", None))
            if nxt is None:
                # ``async_generator_asend`` — what ``async for`` awaits —
                # exposes NO attribute pointing at its generator, so the
                # chain would end here, one frame short of every stall
                # that happens inside an async generator (which is most
                # of them: streaming clients are async generators). The
                # GC knows the edge even though the type won't name it.
                for ref in _gc.get_referents(node):
                    if hasattr(ref, "ag_frame") or hasattr(ref, "cr_frame"):
                        nxt = ref
                        break
            if nxt is None:
                if frame is None:
                    # A bare awaitable — a Future, an Event, a transport.
                    chain.append(f"<awaiting {type(node).__name__}>")
                break
            node = nxt
        return chain

    out = []
    for task in list(_aio.all_tasks())[:max(1, limit)]:
        frames = []
        try:
            for frame in task.get_stack(limit=12):
                info = _tb.extract_stack(frame, limit=1)
                if info:
                    f = info[0]
                    frames.append(f"{f.filename}:{f.lineno} {f.name}")
        except Exception:  # noqa: BLE001 — a diagnostic must never raise
            frames.append("<stack unavailable>")
        try:
            awaiting = _await_chain(task.get_coro())
        except Exception:  # noqa: BLE001 — a diagnostic must never raise
            awaiting = ["<await chain unavailable>"]
        out.append({
            "name": task.get_name(),
            "done": task.done(),
            "coro": str(task.get_coro())[:200],
            "stack": frames,
            "awaiting": awaiting,
        })
    response.headers["Cache-Control"] = "no-store"
    return {"count": len(out), "tasks": out}


@app.get("/health/ready")
async def readiness_check(response: Response):
    """READINESS — are dependencies usable right now?

    Separate from liveness on purpose: this one DOES fail (503) when the
    database is unreachable, which is the right signal for a load balancer or
    a human, and the wrong signal for a process supervisor. Nothing restarts
    on it.
    """
    db_status = await _db_status()
    ready = db_status in ("healthy", "not_configured")
    if not ready:
        response.status_code = 503
    return {"ready": ready, "database": db_status}


# Register routers
app.include_router(auth_router)  # Auth (must be first — no auth guard on itself)

# WebDAV — Geny Drive universal protocol surface. Mounted as a WSGI island
# (WsgiDAV via a2wsgi): its own Basic/app-password auth, so the JWT
# middleware stack above never sees /dav traffic. Guarded import — a build
# without the wsgidav extra still boots, minus the mount.
try:
    from a2wsgi import WSGIMiddleware as _A2WSGIMiddleware

    from service.webdav.app import get_or_build_dav_app

    app.mount("/dav", _A2WSGIMiddleware(get_or_build_dav_app()))
    logger.info("WebDAV mounted at /dav")
except Exception as _dav_exc:  # noqa: BLE001
    logger.warning(f"WebDAV unavailable: {_dav_exc}")
app.include_router(command_router)
app.include_router(agent_router)  # geny-executor agent sessions
app.include_router(agent_tasks_router)  # background tasks REST (PR-A.5.4)
app.include_router(hooks_router)  # Hooks (user automation) REST — agent-created
app.include_router(slash_router)  # slash commands REST (PR-A.6.2)
app.include_router(config_router)  # Configuration management
app.include_router(ssh_router)  # SSH server connection test
app.include_router(tool_settings_router)  # Per-environment tool settings schemas
app.include_router(gapt_router)  # GAPT integration status (header button detection)
app.include_router(gapt_settings_router)  # GAPT settings proxy (GAPT category in Settings)
app.include_router(sync_router)  # cross-service provider-key sync
app.include_router(avatar_router)  # geny-avatar integration (Avatar category)
app.include_router(llm_backends_router)  # LLM backend health + Claude Code login + subagent listing (Phase E4)
app.include_router(llm_accounts_router)  # Model accounts: many Claude/Codex logins, keys, and the route a session uses
app.include_router(mcp_bridge_router)  # Phase I — internal MCP endpoint for claude_code_cli tool wrap
app.include_router(chat_router)  # Chat broadcast
app.include_router(upload_router)  # File / image uploads (multipart)
app.include_router(tool_preset_router)  # Tool preset management
app.include_router(tool_catalog_router)  # Tool catalog API
app.include_router(custom_tools_router)  # Custom tools CRUD (Phase B — DB-backed)
app.include_router(sandbox_tool_packs_router)  # Sandbox Tool Packs (env+tools+skills bundles)
app.include_router(persona_presets_router)  # Persona Presets (reusable persona definitions)
app.include_router(google_router)  # Google Workspace (OAuth device flow + native tools)
app.include_router(connectors_router)  # MCP connectors (ecosystem registry)
app.include_router(sandbox_observability_router)  # Sandbox Logs (snapshot activity/diff viewer)
app.include_router(skills_router)  # Skills (SKILL.md registry) API
app.include_router(admin_router)  # Admin viewers — permissions/hooks (G13)
app.include_router(permission_router)  # Permission rules CRUD (PR-E.2.1)
app.include_router(hook_router)  # Hook entries CRUD (PR-E.3.1) — env lifecycle hooks, removal pending
app.include_router(agent_workspace_router)  # Where the agent works, and the exact record of what it did there
app.include_router(framework_settings_router)  # Framework settings sections (PR-F.1.x)
app.include_router(subagent_type_router)  # Subagent types viewer (PR-F.3.1)
app.include_router(mcp_custom_router)  # Custom MCP server CRUD (Cycle G)
app.include_router(notifications_router)  # Notifications viewer (Cycle G)
app.include_router(env_defaults_router)  # 1.0.2 — env-defaults (host-registered + env-pickable)
app.include_router(agent_oauth_router)  # MCP OAuth start (G10.2)
app.include_router(mcp_resource_router)  # mcp:// URI resolver (G10.3)
app.include_router(docs_router)  # Documentation API
app.include_router(memory_router)  # Memory management API
app.include_router(global_memory_router)  # Global memory API
app.include_router(transcripts_router)  # InteractionEvent stream view (cycle 20260430_3)
app.include_router(environment_router)  # Environment CRUD API (Phase 3)
app.include_router(trigger_preset_router)  # Trigger Preset CRUD (cycle 20260506)
app.include_router(catalog_router)  # Stage/Artifact catalog API (Phase 3)
app.include_router(vtuber_router)  # VTuber Live2D API
app.include_router(vtuber_baked_imports_router)  # geny-avatar baked-zip inbox (Phase C)
app.include_router(vtuber_library_router)  # geny-avatar library auto-sync (push/remove by puppet id)
app.include_router(tts_router)  # TTS (Text-to-Speech) API
app.include_router(voice_studio_router)  # Voice Studio (/voice-studio synth/preview + languages)
app.include_router(user_opsidian_router)  # User Opsidian (personal knowledge vault)
app.include_router(knowledge_router)  # Knowledge repository (documents + qdrant)
app.include_router(curated_knowledge_router)  # Curated Knowledge (refined knowledge layer)
app.include_router(whiteboard_router)  # Whiteboard captures + view ledger (P0)
app.include_router(stt_router)  # Whisper STT diagnostics + on-demand transcribe (voice-notes W1)
app.include_router(vtuber_screen_observation_router)  # V3 — screen share → [USER_OBSERVATION] trigger
app.include_router(playground2d_router)  # Playground 2D world layout & state
app.include_router(ws_execute_router)   # WebSocket: agent execution streaming
app.include_router(ws_chat_router)      # WebSocket: chat room event streaming
app.include_router(ws_avatar_router)    # WebSocket: avatar state streaming
app.include_router(ws_connector_router) # WebSocket: connector capability bridge (inverse MCP)
app.include_router(ws_workspace_router)  # WebSocket: workspace sync change notifications
app.include_router(ws_voice_realtime_router)  # WebSocket: realtime voice conversation loop (additive)

# Mount static files for Web UI Dashboard
static_dir = Path(__file__).parent / "static"
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"✅ Static files mounted from {static_dir}")

if templates_dir.exists():
    logger.info(f"✅ Jinja2 templates loaded from {templates_dir}")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the Web UI Dashboard with server-side rendered initial data"""
    # Get initial data for SSR
    agents = agent_manager.list_agents()
    sessions_data = [a.get_session_info().model_dump(mode="json") for a in agents]

    # Get prompts list
    prompts_data = get_prompts_list()

    # Get health status
    health_data = {
        "status": "healthy"
    }

    # Calculate stats
    stats_data = {
        "total": len(agents),
        "running": sum(1 for a in agents if a.status == "running"),
        "error": sum(1 for a in agents if a.status == "error")
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "initial_sessions": sessions_data,
            "initial_prompts": prompts_data,
            "initial_health": health_data,
            "initial_stats": stats_data
        }
    )

if __name__ == "__main__":
    try:
        host = os.environ.get("APP_HOST", "0.0.0.0")
        port = int(os.environ.get("APP_PORT", "8000"))
        debug = os.environ.get("DEBUG_MODE", "false").lower() in ('true', '1', 'yes', 'on')

        print(f"Starting server on {host}:{port} (debug={debug})")

        if debug:
            # In reload mode, pass as import string format
            # Exclude _mcp_server.py to prevent infinite reload loop
            # (MCPLoader generates this file on startup)
            uvicorn.run(
                "main:app",
                host=host,
                port=port,
                reload=True,
                reload_excludes=["*/_mcp_server.py", "_mcp_server.py"],
                timeout_keep_alive=120,
            )
        else:
            # In normal mode, pass app object directly
            uvicorn.run(app, host=host, port=port, reload=False, timeout_keep_alive=120)
    except Exception as e:
        logger.warning(f"Failed to load config for uvicorn: {e}")
        logger.info("Using default values for uvicorn")
        uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
