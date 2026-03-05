import os
import sys
import asyncio
from logging import basicConfig, getLogger, INFO
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from controller.claude_controller import router as claude_router
from controller.command_controller import router as command_router, get_prompts_list
from controller.agent_controller import router as agent_router, agent_manager
from controller.config_controller import router as config_router
from controller.workflow_controller import router as workflow_router
from controller.tool_preset_controller import router as tool_preset_router
from controller.shared_folder_controller import router as shared_folder_router
from controller.chat_controller import router as chat_router
from service.redis.redis_client import RedisClient, get_redis_client
from service.config import get_config_manager, ConfigManager
from service.pod.pod_info import init_pod_info, get_pod_info
from service.middleware.session_router import SessionRoutingMiddleware
from service.proxy.internal_proxy import get_internal_proxy
from service.mcp_loader import MCPLoader, get_global_mcp_config
import uvicorn

# Load .env file
try:
    from dotenv import load_dotenv
    # Load .env file from project root
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[OK] Loaded environment from {env_path}")
    else:
        # Show info message if .env.example exists
        example_path = Path(__file__).parent / ".env.example"
        if example_path.exists():
            print("[INFO] No .env file found. Copy .env.example to .env and configure it.")
except ImportError:
    print("[WARN] python-dotenv not installed. Environment variables must be set manually.")

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


def init_redis_client(app: FastAPI) -> Optional[RedisClient]:
    """Initialize Redis client and register in app.state

    Only attempts Redis connection if USE_REDIS environment variable is set to 'true'.
    Returns None if Redis is disabled.
    """
    use_redis = os.getenv('USE_REDIS', 'false').lower() == 'true'

    if not use_redis:
        logger.info("ℹ️  Redis disabled (USE_REDIS=false) - running in local memory mode")
        app.state.redis_client = None
        return None

    redis_client = RedisClient()

    # Register in FastAPI app.state for global access
    app.state.redis_client = redis_client

    if redis_client.is_connected:
        logger.info("✅ Redis client initialization complete")
        stats = redis_client.get_stats()
        logger.info(f"   - Host: {stats['host']}:{stats['port']}")
        logger.info(f"   - DB: {stats['db']}")
        if stats.get('redis_info'):
            logger.info(f"   - Redis Version: {stats['redis_info'].get('version')}")
    else:
        logger.warning("⚠️  Redis connection failed - running in local memory mode")

    return redis_client


def get_app_redis_client(app: FastAPI) -> RedisClient:
    """Get Redis client from app.state"""
    return getattr(app.state, 'redis_client', None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    print_geny_agent_logo()
    print_step_banner("START", "GENY AGENT STARTUP", "Initializing agent session management system")
    logger.info("Starting Geny Agent")

    # Initialize Pod info
    print_step_banner("POD", "POD INFO", "Initializing pod information...")
    pod_info = init_pod_info()
    app.state.pod_info = pod_info
    logger.info(f"   - Pod Name: {pod_info.pod_name}")
    logger.info(f"   - Pod IP: {pod_info.pod_ip}")
    logger.info(f"   - Service Port: {pod_info.service_port}")

    # Initialize Redis client and register in app.state (only if USE_REDIS=true)
    use_redis = os.getenv('USE_REDIS', 'false').lower() == 'true'
    if use_redis:
        print_step_banner("REDIS", "REDIS CONNECTION", "Connecting to Redis server...")
    else:
        print_step_banner("REDIS", "REDIS DISABLED", "Running in local memory mode")
    redis_client = init_redis_client(app)

    # Inject Redis client into AgentSessionManager
    agent_manager.set_redis_client(redis_client)

    # Initialize Config Manager
    print_step_banner("CONFIG", "CONFIG MANAGER", "Loading configurations...")
    config_manager = get_config_manager()
    app.state.config_manager = config_manager
    registered_configs = config_manager.get_registered_config_classes()
    logger.info(f"   - Registered Configs: {len(registered_configs)}")
    for config_name, config_class in registered_configs.items():
        # Load (and create if missing) each config
        config_manager.load_config(config_class)
        logger.info(f"     - {config_name}")

    # Auto-load MCP configs and tools
    print_step_banner("MCP", "MCP LOADER", "Loading MCP configs and tools...")
    mcp_loader = MCPLoader()
    mcp_config = mcp_loader.load_all()
    app.state.mcp_loader = mcp_loader
    app.state.global_mcp_config = mcp_config

    # Inject global MCP config into AgentSessionManager
    agent_manager.set_global_mcp_config(mcp_config)
    logger.info(f"   - MCP Servers: {mcp_loader.get_server_count()}")
    logger.info(f"   - Custom Tools: {mcp_loader.get_tool_count()}")

    # Initialize tool preset store (creates built-in templates)
    print_step_banner("TOOLS", "TOOL PRESETS", "Initializing tool preset store...")
    from service.tool_policy.tool_preset_store import get_tool_preset_store
    tool_preset_store = get_tool_preset_store()
    logger.info(f"   - Tool presets: {len(tool_preset_store.list_all())}")

    # Register workflow nodes and install templates
    print_step_banner("WORKFLOW", "WORKFLOW ENGINE", "Registering workflow nodes and templates...")
    from service.workflow.nodes import register_all_nodes
    from service.workflow.workflow_store import get_workflow_store
    from service.workflow.templates import install_templates
    register_all_nodes()
    workflow_store = get_workflow_store()
    templates_installed = install_templates(workflow_store)
    logger.info(f"   - Workflow templates installed: {templates_installed}")
    logger.info(f"   - Total workflows: {len(workflow_store.list_all())}")

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

    print_step_banner("READY", "GENY AGENT READY", "All systems operational!")
    logger.info("Geny Agent startup complete! Ready to serve requests.")

    yield

    print_step_banner("SHUTDOWN", "GENY AGENT SHUTDOWN", "Cleaning up sessions...")
    logger.info("Shutting down Geny Agent")

    # Shutdown Internal Proxy client
    proxy = get_internal_proxy()
    await proxy.close()

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

# Session routing middleware (Session-based proxy for multi-pod environment)
# Note: add_middleware executes in reverse order (last added runs first)
app.add_middleware(SessionRoutingMiddleware)


@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/dashboard")


@app.get("/health")
async def health_check():
    """Detailed health check"""
    sessions = agent_manager.list_sessions()
    pod_info = get_pod_info()

    # Check Redis status (get from app.state)
    redis_client = get_app_redis_client(app)
    redis_status = "disconnected"
    if redis_client and redis_client.is_connected:
        redis_status = "connected" if redis_client.health_check() else "error"

    # Number of sessions running on current pod
    local_sessions = len(agent_manager.sessions)

    return {
        "status": "healthy",
        "pod_name": pod_info.pod_name,
        "pod_ip": pod_info.pod_ip,
        "redis": redis_status,
        "total_sessions": len(sessions),
        "local_sessions": local_sessions,
        "running_sessions": sum(1 for s in sessions if s.status == "running"),
        "error_sessions": sum(1 for s in sessions if s.status == "error")
    }


@app.get("/redis/stats")
async def redis_stats():
    """Redis status and statistics"""
    redis_client = get_app_redis_client(app)
    if redis_client:
        return redis_client.get_stats()
    return {"error": "Redis client not initialized"}


# Register routers
app.include_router(claude_router)
app.include_router(command_router)
app.include_router(agent_router)  # LangGraph agent sessions
app.include_router(config_router)  # Configuration management
app.include_router(workflow_router)  # Workflow editor
app.include_router(tool_preset_router)  # Tool preset management
app.include_router(shared_folder_router)  # Shared folder
app.include_router(chat_router)  # Chat broadcast

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
    pod_info = get_pod_info()
    redis_client = get_app_redis_client(app)
    redis_status = "disconnected"
    if redis_client and redis_client.is_connected:
        redis_status = "connected" if redis_client.health_check() else "error"

    health_data = {
        "status": "healthy",
        "pod_name": pod_info.pod_name,
        "pod_ip": pod_info.pod_ip,
        "redis": redis_status
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
                reload_excludes=["*/_mcp_server.py", "_mcp_server.py"]
            )
        else:
            # In normal mode, pass app object directly
            uvicorn.run(app, host=host, port=port, reload=False)
    except Exception as e:
        logger.warning(f"Failed to load config for uvicorn: {e}")
        logger.info("Using default values for uvicorn")
        uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
