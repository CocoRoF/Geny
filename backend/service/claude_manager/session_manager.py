"""
Claude Session Manager

Uses Redis as the true source for multi-pod environment support.
Local processes are managed in memory, session metadata is stored in Redis.
"""
import os
import uuid
from logging import getLogger
from typing import Dict, Optional, List

from service.claude_manager.process_manager import ClaudeProcess
from service.claude_manager.models import (
    SessionStatus,
    SessionRole,
    SessionInfo,
    CreateSessionRequest,
    MCPConfig
)
from service.redis.redis_client import RedisClient, get_redis_client
from service.pod.pod_info import get_pod_info
from service.logging.session_logger import get_session_logger, remove_session_logger

logger = getLogger(__name__)


def is_redis_enabled() -> bool:
    """Check if Redis is enabled via environment variable."""
    return os.getenv('USE_REDIS', 'false').lower() == 'true'


def merge_mcp_configs(base: Optional[MCPConfig], override: Optional[MCPConfig]) -> Optional[MCPConfig]:
    """
    Merge two MCP configurations (override takes priority).
    """
    if not base and not override:
        return None
    if not base:
        return override
    if not override:
        return base

    merged_servers = {**base.servers, **override.servers}
    return MCPConfig(servers=merged_servers)


class SessionManager:
    """
    Claude Session Manager.

    - Redis: True source for session metadata (multi-pod sharing)
    - Local memory: Manages processes running on current pod
    - Global MCP: MCP configuration automatically applied to all sessions
    """

    def __init__(self, redis_client: Optional[RedisClient] = None):
        # Local process storage (only processes running on current pod)
        self._local_processes: Dict[str, ClaudeProcess] = {}

        # Redis client (for session metadata storage)
        self._redis: Optional[RedisClient] = redis_client

        # Global MCP configuration (automatically applied to all sessions)
        self._global_mcp_config: Optional[MCPConfig] = None

        # Cache whether Redis is enabled at startup
        self._redis_enabled: bool = is_redis_enabled()

    def set_redis_client(self, redis_client: RedisClient):
        """Set Redis client (lazy injection)."""
        self._redis = redis_client
        logger.info("✅ Redis client connected to SessionManager")

    def set_global_mcp_config(self, config: MCPConfig):
        """Set global MCP configuration (automatically applied to all sessions)."""
        self._global_mcp_config = config
        if config and config.servers:
            logger.info(f"✅ Global MCP config registered: {list(config.servers.keys())}")

    @property
    def global_mcp_config(self) -> Optional[MCPConfig]:
        """Return global MCP configuration."""
        return self._global_mcp_config

    @property
    def redis(self) -> Optional[RedisClient]:
        """Return Redis client (None if Redis is disabled)."""
        # If Redis is disabled, don't even try to get the client
        if not self._redis_enabled:
            return None

        if self._redis is None:
            try:
                self._redis = get_redis_client()
            except Exception as e:
                logger.warning(f"Could not get Redis client: {e}")
        return self._redis

    @property
    def sessions(self) -> Dict[str, ClaudeProcess]:
        """Sessions property for compatibility (returns local processes)."""
        return self._local_processes

    async def create_session(self, request: CreateSessionRequest) -> SessionInfo:
        """
        Create a new Claude session.

        Args:
            request: Session creation request.

        Returns:
            Created session information.
        """
        session_id = str(uuid.uuid4())

        logger.info(f"[{session_id}] Creating new Claude session...")
        logger.info(f"[{session_id}]   session_name: {request.session_name}")
        logger.info(f"[{session_id}]   working_dir: {request.working_dir}")
        logger.info(f"[{session_id}]   model: {request.model}")
        logger.info(f"[{session_id}]   role: {request.role.value if request.role else 'worker'}")

        # Merge global MCP config with session MCP config
        # Session config takes priority over global config
        merged_mcp_config = merge_mcp_configs(self._global_mcp_config, request.mcp_config)

        if merged_mcp_config and merged_mcp_config.servers:
            logger.info(f"[{session_id}]   mcp_servers: {list(merged_mcp_config.servers.keys())}")

        # Prepare system prompt - add manager prompt if role is manager
        system_prompt = request.system_prompt or ""
        if request.role and request.role.value == "manager":
            manager_prompt = self._load_manager_prompt()
            if manager_prompt:
                system_prompt = manager_prompt + "\n\n" + system_prompt if system_prompt else manager_prompt
                logger.info(f"[{session_id}]   📋 Manager prompt added automatically")

        # Create ClaudeProcess instance
        process = ClaudeProcess(
            session_id=session_id,
            session_name=request.session_name,
            working_dir=request.working_dir,
            env_vars=request.env_vars,
            model=request.model,
            max_turns=request.max_turns,
            timeout=request.timeout,  # Execution timeout
            mcp_config=merged_mcp_config,  # Use merged MCP config
            system_prompt=system_prompt,  # System prompt (includes manager prompt if role is manager)
            role=request.role.value if request.role else "worker",  # Session role
            manager_id=request.manager_id  # Manager ID for worker sessions
        )

        # Initialize session
        success = await process.initialize()

        if not success:
            raise RuntimeError(f"Failed to initialize session: {process.error_message}")

        # Store local process
        self._local_processes[session_id] = process

        # Get pod information
        pod_info = get_pod_info()

        # Create SessionInfo
        session_info = SessionInfo(
            session_id=session_id,
            session_name=process.session_name,
            status=process.status,
            created_at=process.created_at,
            pid=process.pid,
            error_message=process.error_message,
            model=process.model,
            max_turns=process.max_turns,
            timeout=process.timeout,
            storage_path=process.storage_path,
            pod_name=pod_info.pod_name,
            pod_ip=pod_info.pod_ip,
            role=SessionRole(process.role),
            manager_id=process.manager_id
        )

        # Save session metadata to Redis
        self._save_session_to_redis(session_id, session_info)

        # Create session logger
        session_logger = get_session_logger(session_id, request.session_name, create_if_missing=True)
        if session_logger:
            session_logger.log_session_event("created", {
                "model": request.model,
                "working_dir": request.working_dir,
                "max_turns": request.max_turns
            })
            logger.info(f"[{session_id}] 📝 Session logger created")

        logger.info(f"[{session_id}] ✅ Session created successfully")
        return session_info

    def get_process(self, session_id: str) -> Optional[ClaudeProcess]:
        """
        Get session process (local).

        Only returns processes running on local pod.
        Sessions on other pods can only be queried for metadata from Redis.
        """
        return self._local_processes.get(session_id)

    def get_session_info(self, session_id: str) -> Optional[SessionInfo]:
        """
        Get session metadata (Redis priority).

        Retrieves session info from Redis (supports multi-pod environment).
        """
        # First try Redis
        if self.redis and self.redis.is_connected:
            session_data = self.redis.get_session(session_id)
            if session_data:
                return self._dict_to_session_info(session_data)

        # If not in Redis, generate from local process
        process = self._local_processes.get(session_id)
        if process:
            return self._process_to_session_info(session_id, process)

        return None

    def list_sessions(self) -> List[SessionInfo]:
        """
        List all sessions.

        If Redis is available, queries Redis (all sessions across multi-pod).
        Otherwise returns only local processes.
        """
        sessions_info = []

        # Query all sessions from Redis (multi-pod environment)
        if self.redis and self.redis.is_connected:
            all_sessions = self.redis.get_all_sessions()

            for session_data in all_sessions:
                session_id = session_data.get('session_id')

                # Update status if local process exists
                local_process = self._local_processes.get(session_id)
                if local_process:
                    # Check and update process status
                    if not local_process.is_alive() and local_process.status == SessionStatus.RUNNING:
                        local_process.status = SessionStatus.STOPPED
                        session_data['status'] = SessionStatus.STOPPED.value
                        self.redis.update_session_field(session_id, 'status', SessionStatus.STOPPED.value)
                    else:
                        session_data['status'] = local_process.status.value
                        session_data['pid'] = local_process.pid

                sessions_info.append(self._dict_to_session_info(session_data))

            return sessions_info

        # Without Redis, return only local processes
        for session_id, process in self._local_processes.items():
            # Update process status
            if not process.is_alive() and process.status == SessionStatus.RUNNING:
                process.status = SessionStatus.STOPPED

            sessions_info.append(self._process_to_session_info(session_id, process))

        return sessions_info

    async def delete_session(self, session_id: str, cleanup_storage: bool = True) -> bool:
        """
        Delete session and terminate process.

        Args:
            session_id: Session ID to delete.
            cleanup_storage: Whether to also delete storage.

        Returns:
            Whether deletion was successful.
        """
        # Check local process
        process = self._local_processes.get(session_id)

        if process:
            logger.info(f"[{session_id}] Deleting session...")

            # Log session end event
            session_logger = get_session_logger(session_id, create_if_missing=False)
            if session_logger:
                session_logger.log_session_event("deleted")

            # Stop process
            await process.stop()

            # Cleanup storage
            if cleanup_storage:
                await process.cleanup_storage()

            # Remove session logger
            remove_session_logger(session_id)

            # Remove from local
            del self._local_processes[session_id]

        # Also delete from Redis
        if self.redis and self.redis.is_connected:
            self.redis.delete_session(session_id)
            logger.info(f"[{session_id}] Session deleted from Redis")
            return True

        # If only deleted from local (no Redis)
        return process is not None

    async def cleanup_dead_sessions(self):
        """Cleanup dead sessions (based on local processes)."""
        dead_sessions = [
            session_id
            for session_id, process in self._local_processes.items()
            if not process.is_alive()
        ]

        for session_id in dead_sessions:
            logger.info(f"[{session_id}] Cleaning up dead session")
            await self.delete_session(session_id)

    # ========== Helper Methods ==========

    def _save_session_to_redis(self, session_id: str, session_info: SessionInfo):
        """Save session information to Redis (only if Redis is enabled)."""
        # Skip silently if Redis is disabled
        if not self._redis_enabled:
            return

        if not self.redis or not self.redis.is_connected:
            # Only log warning if Redis was supposed to be available but isn't
            logger.warning(f"Redis enabled but not connected - session {session_id} stored locally only")
            return

        session_data = {
            'session_id': session_id,
            'session_name': session_info.session_name,
            'status': session_info.status.value if session_info.status else None,
            'created_at': session_info.created_at,
            'pid': session_info.pid,
            'error_message': session_info.error_message,
            'model': session_info.model,
            'max_turns': session_info.max_turns,
            'timeout': session_info.timeout,
            'storage_path': session_info.storage_path,
            'pod_name': session_info.pod_name,
            'pod_ip': session_info.pod_ip,
            'role': session_info.role.value if session_info.role else 'worker',
            'manager_id': session_info.manager_id
        }

        self.redis.save_session(session_id, session_data)
        logger.debug(f"Session saved to Redis: {session_id}")

    def _load_manager_prompt(self) -> Optional[str]:
        """Load the manager prompt from prompts/manager.md"""
        try:
            import os
            # Get project root (where prompts/ folder is)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            prompt_path = os.path.join(project_root, "prompts", "manager.md")

            if os.path.exists(prompt_path):
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                logger.warning(f"Manager prompt not found: {prompt_path}")
                return None
        except Exception as e:
            logger.warning(f"Failed to load manager prompt: {e}")
            return None

    def _process_to_session_info(self, session_id: str, process: ClaudeProcess) -> SessionInfo:
        """Convert ClaudeProcess to SessionInfo."""
        pod_info = get_pod_info()
        return SessionInfo(
            session_id=session_id,
            session_name=process.session_name,
            status=process.status,
            created_at=process.created_at,
            pid=process.pid,
            error_message=process.error_message,
            model=process.model,
            max_turns=process.max_turns,
            timeout=process.timeout,
            storage_path=process.storage_path,
            pod_name=pod_info.pod_name,
            pod_ip=pod_info.pod_ip,
            role=SessionRole(process.role),
            manager_id=process.manager_id
        )

    def _dict_to_session_info(self, data: dict) -> SessionInfo:
        """Convert dictionary to SessionInfo."""
        status = data.get('status')
        if isinstance(status, str):
            status = SessionStatus(status)

        role = data.get('role', 'worker')
        if isinstance(role, str):
            role = SessionRole(role)

        return SessionInfo(
            session_id=data.get('session_id', ''),
            session_name=data.get('session_name'),
            status=status,
            created_at=data.get('created_at'),
            pid=data.get('pid'),
            error_message=data.get('error_message'),
            model=data.get('model'),
            max_turns=data.get('max_turns', 100),
            timeout=data.get('timeout', 1800.0),
            storage_path=data.get('storage_path'),
            pod_name=data.get('pod_name'),
            pod_ip=data.get('pod_ip'),
            role=role,
            manager_id=data.get('manager_id'),
            workflow_id=data.get('workflow_id'),
            graph_name=data.get('graph_name'),
        )

    # ========== Manager/Worker Methods ==========

    def get_workers_by_manager(self, manager_id: str) -> List[SessionInfo]:
        """
        Get all worker sessions under a manager.

        Args:
            manager_id: Manager session ID

        Returns:
            List of worker SessionInfo objects
        """
        all_sessions = self.list_sessions()
        return [
            session for session in all_sessions
            if session.manager_id == manager_id and session.role == SessionRole.WORKER
        ]

    def get_managers(self) -> List[SessionInfo]:
        """
        Get all manager sessions.

        Returns:
            List of manager SessionInfo objects
        """
        all_sessions = self.list_sessions()
        return [
            session for session in all_sessions
            if session.role == SessionRole.MANAGER
        ]


# Singleton session manager
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Return singleton session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
