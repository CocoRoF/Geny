"""
AgentSessionManager - AgentSession 관리자

기존 SessionManager를 확장하여 AgentSession(CompiledStateGraph) 기반
세션을 관리합니다.

기존 SessionManager의 모든 기능을 유지하면서
AgentSession 전용 메서드를 추가합니다.

사용 예:
    from service.langgraph import get_agent_session_manager

    manager = get_agent_session_manager()

    # AgentSession 생성
    agent = await manager.create_agent_session(CreateSessionRequest(
        working_dir="/path/to/project",
        model="claude-sonnet-4-20250514",
    ))

    # AgentSession 가져오기
    agent = manager.get_agent(session_id)

    # 실행
    result = await agent.invoke("Hello")

    # 기존 SessionManager 호환
    process = manager.get_process(session_id)  # ClaudeProcess 반환
    sessions = manager.list_sessions()  # SessionInfo 리스트 반환
"""

from logging import getLogger
from typing import Dict, List, Optional

from service.claude_manager.session_manager import SessionManager, is_redis_enabled, merge_mcp_configs
from service.claude_manager.models import (
    CreateSessionRequest,
    MCPConfig,
    SessionInfo,
    SessionRole,
    SessionStatus,
)
from service.claude_manager.process_manager import ClaudeProcess
from service.redis.redis_client import RedisClient
from service.pod.pod_info import get_pod_info
from service.logging.session_logger import get_session_logger, remove_session_logger

from service.langgraph.agent_session import AgentSession
from service.prompt.sections import build_agent_prompt
from service.prompt.context_loader import ContextLoader
from service.tool_policy import ToolPolicyEngine, ToolProfile
from service.prompt.builder import PromptMode
from service.claude_manager.session_store import get_session_store

logger = getLogger(__name__)


class AgentSessionManager(SessionManager):
    """
    AgentSession 관리자.

    SessionManager를 상속하여 기존 기능을 모두 유지하면서
    AgentSession(CompiledStateGraph) 기반 세션 관리 기능을 추가합니다.

    핵심 구조:
    - _local_agents: AgentSession 저장소 (로컬)
    - _local_processes: ClaudeProcess 저장소 (기존, 호환성을 위해 유지)

    두 방식 모두 지원:
    1. AgentSession 방식 (LangGraph 상태 관리)
       - create_agent_session() -> AgentSession
       - get_agent() -> AgentSession

    2. 기존 방식 (ClaudeProcess 직접 사용)
       - create_session() -> SessionInfo
       - get_process() -> ClaudeProcess
    """

    def __init__(self, redis_client: Optional[RedisClient] = None):
        """
        AgentSessionManager 초기화.

        Args:
            redis_client: Redis 클라이언트 (옵션)
        """
        super().__init__(redis_client)

        # AgentSession 저장소 (로컬)
        self._local_agents: Dict[str, AgentSession] = {}

        # Persistent session metadata store (sessions.json)
        self._store = get_session_store()

        logger.info("✅ AgentSessionManager initialized")

    # ========================================================================
    # Prompt Builder
    # ========================================================================

    def _build_system_prompt(self, request: CreateSessionRequest) -> str:
        """Build the system prompt using the modular prompt builder.

        Applies the OpenClaw-inspired buildAgentSystemPrompt() pattern:
        assembles the prompt dynamically based on role, mode, context files,
        and (if available) previously persisted session memory.

        Args:
            request: Session creation request.

        Returns:
            Assembled system prompt string.
        """
        # Determine role
        role = request.role.value if request.role else "worker"

        # Resolve tool policy for this role
        policy = ToolPolicyEngine.for_role(
            role=role,
            explicit_tools=request.allowed_tools,
        )
        logger.debug(f"  ToolPolicy: {policy}")

        # Merge global + per-session MCP configs, then filter by policy
        merged_mcp = merge_mcp_configs(self._global_mcp_config, request.mcp_config)
        filtered_mcp = policy.filter_mcp_config(merged_mcp)
        mcp_servers: list[str] = []
        if filtered_mcp and filtered_mcp.servers:
            mcp_servers = list(filtered_mcp.servers.keys())

        # Load bootstrap context files from working directory
        context_files: dict[str, str] = {}
        if request.working_dir:
            try:
                loader = ContextLoader(
                    working_dir=request.working_dir,
                    include_readme=(role in ("researcher", "manager")),
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
        storage_path = request.working_dir  # May be overridden by process storage_path later
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
        if role in ("manager", "self-manager", "developer", "researcher"):
            mode = PromptMode.FULL
        elif request.manager_id:
            # Worker with a manager → MINIMAL (sub-agent)
            mode = PromptMode.MINIMAL
        else:
            # Standalone worker → FULL
            mode = PromptMode.FULL

        # Allowed tools list (filtered by policy)
        tools = policy.filter_tool_names(request.allowed_tools)

        # Build prompt
        prompt = build_agent_prompt(
            agent_name="Claude Control Agent",
            role=role,
            agent_id=None,
            working_dir=request.working_dir,
            model=request.model,
            session_id=None,  # Session ID not yet created at this point
            tools=tools,
            mcp_servers=mcp_servers,
            autonomous=request.autonomous if request.autonomous is not None else True,
            mode=mode,
            context_files=context_files if context_files else None,
            extra_system_prompt=request.system_prompt,
        )

        # Append memory context if available
        if memory_context:
            prompt = prompt + "\n\n" + memory_context

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
    ) -> AgentSession:
        """
        새 AgentSession 생성.

        1. ClaudeProcess 생성 (via AgentSession.create())
        2. CompiledStateGraph 빌드
        3. 로컬 저장소에 등록

        Args:
            request: 세션 생성 요청
            enable_checkpointing: 체크포인팅 활성화 여부
            session_id: 기존 session_id 재사용 (복원 시)

        Returns:
            생성된 AgentSession 인스턴스
        """
        logger.info(f"Creating new AgentSession...")
        logger.info(f"  session_name: {request.session_name}")
        logger.info(f"  working_dir: {request.working_dir}")
        logger.info(f"  model: {request.model}")
        logger.info(f"  role: {request.role.value if request.role else 'worker'}")

        # Merge MCP configs and apply tool policy
        role = request.role.value if request.role else "worker"
        policy = ToolPolicyEngine.for_role(
            role=role,
            explicit_tools=request.allowed_tools,
        )
        merged_mcp_config = merge_mcp_configs(self._global_mcp_config, request.mcp_config)
        merged_mcp_config = policy.filter_mcp_config(merged_mcp_config)

        if merged_mcp_config and merged_mcp_config.servers:
            logger.info(f"  mcp_servers (policy={policy.profile.value}): {list(merged_mcp_config.servers.keys())}")

        # 시스템 프롬프트 준비 — 모듈러 프롬프트 빌더 사용
        system_prompt = self._build_system_prompt(request)
        logger.info(f"  📋 System prompt built via PromptBuilder ({len(system_prompt)} chars)")

        # AgentSession 생성
        agent = await AgentSession.create(
            working_dir=request.working_dir,
            model_name=request.model,
            session_name=request.session_name,
            session_id=session_id,
            system_prompt=system_prompt,
            env_vars=request.env_vars,
            mcp_config=merged_mcp_config,
            max_turns=request.max_turns or 100,
            timeout=request.timeout or 1800.0,
            autonomous=request.autonomous if request.autonomous is not None else True,
            autonomous_max_iterations=request.autonomous_max_iterations or 100,
            role=request.role or SessionRole.WORKER,
            manager_id=request.manager_id,
            enable_checkpointing=enable_checkpointing,
        )

        session_id = agent.session_id

        # 로컬 저장소에 등록
        self._local_agents[session_id] = agent

        # 기존 호환성: ClaudeProcess도 _local_processes에 등록
        if agent.process:
            self._local_processes[session_id] = agent.process

        # Pod 정보
        pod_info = get_pod_info()

        # SessionInfo 생성
        session_info = agent.get_session_info(
            pod_name=pod_info.pod_name,
            pod_ip=pod_info.pod_ip,
        )

        # Redis에 세션 메타데이터 저장
        self._save_session_to_redis(session_id, session_info)

        # 세션 로거 생성
        session_logger = get_session_logger(session_id, request.session_name, create_if_missing=True)
        if session_logger:
            session_logger.log_session_event("created", {
                "model": request.model,
                "working_dir": request.working_dir,
                "max_turns": request.max_turns,
                "type": "agent_session",
            })
            logger.info(f"[{session_id}] 📝 Session logger created")

        # Persist session metadata to sessions.json
        self._store.register(session_id, session_info.model_dump(mode="json"))

        logger.info(f"[{session_id}] ✅ AgentSession created successfully")
        return agent

    # ========================================================================
    # AgentSession Access
    # ========================================================================

    def get_agent(self, session_id: str) -> Optional[AgentSession]:
        """
        AgentSession 가져오기.

        Args:
            session_id: 세션 ID

        Returns:
            AgentSession 인스턴스 또는 None
        """
        return self._local_agents.get(session_id)

    def has_agent(self, session_id: str) -> bool:
        """
        AgentSession 존재 여부 확인.

        Args:
            session_id: 세션 ID

        Returns:
            존재 여부
        """
        return session_id in self._local_agents

    def list_agents(self) -> List[AgentSession]:
        """
        모든 AgentSession 목록 반환.

        Returns:
            AgentSession 리스트
        """
        return list(self._local_agents.values())

    # ========================================================================
    # Session Management (Override for AgentSession support)
    # ========================================================================

    async def delete_session(self, session_id: str, cleanup_storage: bool = True) -> bool:
        """
        세션 삭제 (AgentSession 및 기존 방식 모두 지원).

        Args:
            session_id: 세션 ID
            cleanup_storage: 스토리지 정리 여부

        Returns:
            삭제 성공 여부
        """
        # AgentSession인 경우
        agent = self._local_agents.get(session_id)
        if agent:
            logger.info(f"[{session_id}] Deleting AgentSession...")

            # 세션 로거 이벤트
            session_logger = get_session_logger(session_id, create_if_missing=False)
            if session_logger:
                session_logger.log_session_event("deleted")

            # AgentSession 정리
            await agent.cleanup()

            # 로컬 저장소에서 제거
            del self._local_agents[session_id]

            # _local_processes에서도 제거 (호환성)
            if session_id in self._local_processes:
                del self._local_processes[session_id]

            # 세션 로거 제거
            remove_session_logger(session_id)

            # Redis에서도 삭제
            if self.redis and self.redis.is_connected:
                self.redis.delete_session(session_id)
                logger.info(f"[{session_id}] Session deleted from Redis")

            # Soft-delete in persistent store (keeps metadata for restore)
            self._store.soft_delete(session_id)

            logger.info(f"[{session_id}] ✅ AgentSession deleted (soft)")
            return True

        # 기존 방식 (ClaudeProcess 직접)
        return await super().delete_session(session_id, cleanup_storage)

    async def cleanup_dead_sessions(self):
        """
        죽은 세션 정리 (AgentSession 및 기존 방식 모두).
        """
        # AgentSession 정리
        dead_agents = [
            session_id
            for session_id, agent in self._local_agents.items()
            if not agent.is_alive()
        ]

        for session_id in dead_agents:
            logger.info(f"[{session_id}] Cleaning up dead AgentSession")
            await self.delete_session(session_id)

        # 기존 프로세스 정리 (AgentSession이 아닌 것만)
        dead_processes = [
            session_id
            for session_id, process in self._local_processes.items()
            if session_id not in self._local_agents and not process.is_alive()
        ]

        for session_id in dead_processes:
            logger.info(f"[{session_id}] Cleaning up dead session")
            await super().delete_session(session_id)

    # ========================================================================
    # Compatibility: Upgrade/Convert
    # ========================================================================

    def upgrade_to_agent(
        self,
        session_id: str,
        enable_checkpointing: bool = False,
    ) -> Optional[AgentSession]:
        """
        기존 ClaudeProcess 세션을 AgentSession으로 업그레이드.

        기존 세션의 ClaudeProcess를 유지하면서
        AgentSession으로 래핑합니다.

        Args:
            session_id: 세션 ID
            enable_checkpointing: 체크포인팅 활성화

        Returns:
            AgentSession 인스턴스 또는 None
        """
        # 이미 AgentSession인 경우
        if session_id in self._local_agents:
            logger.info(f"[{session_id}] Already an AgentSession")
            return self._local_agents[session_id]

        # ClaudeProcess 가져오기
        process = self._local_processes.get(session_id)
        if not process:
            logger.warning(f"[{session_id}] Session not found")
            return None

        # AgentSession으로 변환
        agent = AgentSession.from_process(process, enable_checkpointing=enable_checkpointing)

        # 저장소에 등록
        self._local_agents[session_id] = agent

        logger.info(f"[{session_id}] ✅ Upgraded to AgentSession")
        return agent

    # ========================================================================
    # Manager/Worker Methods (Override)
    # ========================================================================

    def get_agent_workers_by_manager(self, manager_id: str) -> List[AgentSession]:
        """
        매니저의 워커 AgentSession 목록 반환.

        Args:
            manager_id: 매니저 세션 ID

        Returns:
            워커 AgentSession 리스트
        """
        return [
            agent for agent in self._local_agents.values()
            if agent.manager_id == manager_id and agent.role == SessionRole.WORKER
        ]

    def get_agent_managers(self) -> List[AgentSession]:
        """
        매니저 AgentSession 목록 반환.

        Returns:
            매니저 AgentSession 리스트
        """
        return [
            agent for agent in self._local_agents.values()
            if agent.role == SessionRole.MANAGER
        ]


# ============================================================================
# Singleton
# ============================================================================

_agent_session_manager: Optional[AgentSessionManager] = None


def get_agent_session_manager() -> AgentSessionManager:
    """
    싱글톤 AgentSessionManager 인스턴스 반환.

    Returns:
        AgentSessionManager 인스턴스
    """
    global _agent_session_manager
    if _agent_session_manager is None:
        _agent_session_manager = AgentSessionManager()
    return _agent_session_manager


def reset_agent_session_manager():
    """
    AgentSessionManager 싱글톤 리셋 (테스트용).
    """
    global _agent_session_manager
    _agent_session_manager = None
