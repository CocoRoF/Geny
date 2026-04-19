import os
import sys
import asyncio
from logging import basicConfig, getLogger, INFO
from pathlib import Path
from contextlib import asynccontextmanager

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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from controller.claude_controller import router as claude_router
from controller.command_controller import router as command_router, get_prompts_list
from controller.agent_controller import router as agent_router, agent_manager
from controller.config_controller import router as config_router
from controller.shared_folder_controller import router as shared_folder_router
from controller.chat_controller import router as chat_router
from controller.tool_preset_controller import router as tool_preset_router
from controller.tool_controller import router as tool_catalog_router
from controller.docs_controller import router as docs_router
from controller.memory_controller import router as memory_router
from controller.memory_controller import global_router as global_memory_router
from controller.session_memory_controller import router as session_memory_router
from controller.environment_controller import router as environment_router
from controller.vtuber_controller import router as vtuber_router
from controller.tts_controller import router as tts_router
from controller.auth_controller import router as auth_router
from controller.user_opsidian_controller import router as user_opsidian_router
from controller.curated_knowledge_controller import router as curated_knowledge_router
from routers.playground2d import router as playground2d_router
from ws.execute_stream import router as ws_execute_router
from ws.chat_stream import router as ws_chat_router
from ws.avatar_stream import router as ws_avatar_router
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
    else:
        app.state.auth_service = None
        logger.info("   - Auth service: disabled (no database)")

    config_manager = get_config_manager()

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
    from service.claude_manager.session_store import get_session_store
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
    tool_preset_templates_installed = install_tool_preset_templates(tool_preset_store)
    logger.info(f"   - Tool preset templates installed: {tool_preset_templates_installed}")
    logger.info(f"   - Total tool presets: {len(tool_preset_store.list_all())}")

    # Initialize Shared Folder
    print_step_banner("SHARED", "SHARED FOLDER", "Initializing shared folder for cross-session collaboration...")
    from service.shared_folder import get_shared_folder_manager
    from service.config.sub_config.general.shared_folder_config import SharedFolderConfig
    shared_folder_cfg = config_manager.load_config(SharedFolderConfig)
    shared_mgr = get_shared_folder_manager()
    # Apply custom path from config if set
    if shared_folder_cfg.shared_folder_path:
        shared_mgr.update_path(shared_folder_cfg.shared_folder_path)
    app.state.shared_folder_manager = shared_mgr
    logger.info(f"   - Shared folder: {shared_mgr.shared_path}")
    logger.info(f"   - Enabled: {shared_folder_cfg.enabled}")
    logger.info(f"   - Link name: {shared_folder_cfg.link_name}")

    # Pass shared folder config to agent manager for session initialization
    agent_manager.set_shared_folder_config(
        enabled=shared_folder_cfg.enabled,
        shared_folder_manager=shared_mgr,
        link_name=shared_folder_cfg.link_name,
    )

    # Start background idle monitor (transitions idle sessions to IDLE status)
    agent_manager.start_idle_monitor()
    logger.info("   - Session idle monitor: started (10min threshold)")

    # ── MemoryProvider Registry (Phase 2) ──────────────────────────────
    # Registry sits next to the legacy SessionMemoryManager. Its default
    # config is resolved from MEMORY_* env vars; if MEMORY_PROVIDER is
    # unset / "disabled", the registry stays dormant and the new
    # /api/sessions/{id}/memory endpoints return 404. agent_manager gets
    # a handle via set_memory_registry() so Phase 4 can attach providers
    # to Stage 2.
    from service.memory_provider import (
        MemoryConfigError,
        MemorySessionRegistry,
        build_default_memory_config,
    )
    try:
        default_memory_config = build_default_memory_config()
    except MemoryConfigError as exc:
        logger.error(f"   - MemorySessionRegistry: config error: {exc}")
        raise
    memory_registry = MemorySessionRegistry(default_config=default_memory_config)
    app.state.memory_registry = memory_registry
    agent_manager.set_memory_registry(memory_registry)
    if default_memory_config:
        logger.info(
            f"   - MemorySessionRegistry: default provider='{default_memory_config['provider']}' "
            f"scope='{default_memory_config.get('scope', 'session')}'"
        )
    else:
        logger.info("   - MemorySessionRegistry: dormant (MEMORY_PROVIDER=disabled or unset)")

    # ── EnvironmentService (Phase 3) ───────────────────────────────────
    # Persists EnvironmentManifest templates to ./data/environments/*.json
    # (or ENVIRONMENT_STORAGE_PATH). Routers are wired in the follow-up PRs
    # (#6 environment_controller, #7 catalog_controller); until then the
    # service sits on app.state ready for use.
    from service.environment import EnvironmentService
    environment_service = EnvironmentService()
    app.state.environment_service = environment_service
    logger.info(f"   - EnvironmentService: storage={environment_service.storage_path}")

    # ── VTuber Service: Live2D model management + avatar state ─────────
    print_step_banner("VTUBER", "VTUBER SERVICE", "Initializing Live2D model management...")
    from service.vtuber import Live2dModelManager, AvatarStateManager

    live2d_models_dir = str(Path(__file__).parent / "static" / "live2d-models")
    live2d_model_manager = Live2dModelManager(live2d_models_dir)
    avatar_state_manager = AvatarStateManager()
    app.state.live2d_model_manager = live2d_model_manager
    app.state.avatar_state_manager = avatar_state_manager
    logger.info(f"   - Live2D models: {len(live2d_model_manager.models)}")
    logger.info(f"   - Default model: {live2d_model_manager.default_model_name}")

    # Give agent_executor access to app.state for avatar state emission
    from service.execution.agent_executor import set_app_state
    set_app_state(app.state)

    # ── VTuber Thinking Trigger Service ────────────────────────────────
    from service.vtuber.thinking_trigger import get_thinking_trigger_service
    thinking_trigger = get_thinking_trigger_service()
    thinking_trigger.start()
    app.state.thinking_trigger = thinking_trigger

    # ── Curation Scheduler Service ────────────────────────────────────
    from service.memory.curation_scheduler import get_curation_scheduler
    curation_scheduler = get_curation_scheduler()
    curation_scheduler.start()
    app.state.curation_scheduler = curation_scheduler

    # ── Tool Runtime Health Check ──────────────────────────────────────
    # Verify tools actually execute (not just registered) by invoking a
    # read-only tool directly and checking the response.
    print_step_banner("HEALTH", "TOOL RUNTIME CHECK", "Verifying tools execute correctly...")
    try:
        test_tool = tool_loader.get_tool("geny_session_list")
        if test_tool:
            test_result = test_tool.run()
            if test_result and isinstance(test_result, str):
                logger.info(f"   ✅ geny_session_list: OK (response {len(test_result)} bytes)")
            else:
                logger.warning(f"   ❌ geny_session_list: unexpected result type: {type(test_result)}")
        else:
            logger.warning("   ❌ geny_session_list: tool not found in loader")
    except Exception as e:
        logger.error(f"   ❌ geny_session_list: execution failed: {e}")

    print_step_banner("READY", "GENY AGENT READY", "All systems operational!")
    logger.info("Geny Agent startup complete! Ready to serve requests.")

    yield

    print_step_banner("SHUTDOWN", "GENY AGENT SHUTDOWN", "Cleaning up sessions...")
    logger.info("Shutting down Geny Agent")

    # Stop thinking trigger service
    if hasattr(app.state, 'thinking_trigger'):
        app.state.thinking_trigger.stop()

    # Stop curation scheduler
    if hasattr(app.state, 'curation_scheduler'):
        app.state.curation_scheduler.stop()

    # Stop idle monitor
    await agent_manager.stop_idle_monitor()

    # Stop all active sessions (processes only — storage preserved)
    # Soft-delete all active sessions so they appear in "deleted sessions" on restart
    async def stop_all_sessions():
        from service.claude_manager.session_store import get_session_store
        store = get_session_store()

        sessions = agent_manager.list_sessions()
        stop_tasks = []
        for session in sessions:
            sid = session.session_id
            agent = agent_manager.get_agent(sid)
            if agent:
                stop_tasks.append(agent.cleanup())
                # Mark as soft-deleted so the session shows up in "deleted sessions"
                store.soft_delete(sid)
            else:
                # Legacy process — just stop, don't delete storage
                process = agent_manager._local_processes.get(sid)
                if process:
                    stop_tasks.append(process.stop())
                # Also soft-delete legacy sessions
                store.soft_delete(sid)
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

# CORS configuration (allow backend access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/dashboard")


@app.get("/health")
async def health_check():
    """Detailed health check including database status"""
    sessions = agent_manager.list_sessions()

    # Database health check
    db_status = "not_configured"
    if hasattr(app.state, 'app_db') and app.state.app_db is not None:
        try:
            healthy = app.state.app_db.db_manager.health_check()
            db_status = "healthy" if healthy else "unhealthy"
        except Exception:
            db_status = "error"

    return {
        "status": "healthy",
        "total_sessions": len(sessions),
        "running_sessions": sum(1 for s in sessions if s.status == "running"),
        "error_sessions": sum(1 for s in sessions if s.status == "error"),
        "database": db_status
    }


# Register routers
app.include_router(auth_router)  # Auth (must be first — no auth guard on itself)
app.include_router(claude_router)
app.include_router(command_router)
app.include_router(agent_router)  # LangGraph agent sessions
app.include_router(config_router)  # Configuration management
app.include_router(shared_folder_router)  # Shared folder
app.include_router(chat_router)  # Chat broadcast
app.include_router(tool_preset_router)  # Tool preset management
app.include_router(tool_catalog_router)  # Tool catalog API
app.include_router(docs_router)  # Documentation API
app.include_router(memory_router)  # Memory management API
app.include_router(global_memory_router)  # Global memory API
app.include_router(session_memory_router)  # Per-session MemoryProvider API (Phase 2)
app.include_router(environment_router)  # Environment CRUD API (Phase 3)
app.include_router(vtuber_router)  # VTuber Live2D API
app.include_router(tts_router)  # TTS (Text-to-Speech) API
app.include_router(user_opsidian_router)  # User Opsidian (personal knowledge vault)
app.include_router(curated_knowledge_router)  # Curated Knowledge (refined knowledge layer)
app.include_router(playground2d_router)  # Playground 2D world layout & state
app.include_router(ws_execute_router)   # WebSocket: agent execution streaming
app.include_router(ws_chat_router)      # WebSocket: chat room event streaming
app.include_router(ws_avatar_router)    # WebSocket: avatar state streaming

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
    sessions = agent_manager.list_sessions()
    sessions_data = [s.model_dump(mode="json") for s in sessions]

    # Get prompts list
    prompts_data = get_prompts_list()

    # Get health status
    health_data = {
        "status": "healthy"
    }

    # Calculate stats
    stats_data = {
        "total": len(sessions),
        "running": sum(1 for s in sessions if s.status == "running"),
        "error": sum(1 for s in sessions if s.status == "error")
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
