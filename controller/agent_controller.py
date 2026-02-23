"""
Agent Session Controller

REST API endpoints for AgentSession (LangGraph + Claude CLI) management.

AgentSession(CompiledStateGraph) 기반 세션을 관리합니다.

AgentSession API:   /api/agents (primary)
Legacy Session API: /api/sessions (deprecated, backward compatibility)
"""
from logging import getLogger
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from service.claude_manager.models import (
    CreateSessionRequest,
    SessionInfo,
    SessionRole,
    ExecuteRequest,
    ExecuteResponse,
    AutonomousExecuteRequest,
    AutonomousExecuteResponse,
    DelegateTaskRequest,
    DelegateTaskResponse,
    StorageFile,
    StorageListResponse,
    StorageFileContent,
    ManagerEvent,
    ManagerEventType,
    ManagerDashboard,
    WorkerStatus,
)
from service.langgraph import (
    get_agent_session_manager,
    AgentSession,
)
from service.logging.session_logger import get_session_logger
from service.claude_manager.session_store import get_session_store

logger = getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/agents", tags=["agents"])

# AgentSessionManager 싱글톤
agent_manager = get_agent_session_manager()


# ============================================================================
# Request/Response Models
# ============================================================================


class CreateAgentRequest(CreateSessionRequest):
    """
    AgentSession 생성 요청.

    CreateSessionRequest를 상속하며 추가 옵션 제공.
    """
    enable_checkpointing: bool = Field(
        default=False,
        description="Enable state checkpointing for replay/resume"
    )


class AgentInvokeRequest(BaseModel):
    """
    AgentSession invoke 요청.

    LangGraph 상태 기반 실행.
    """
    input_text: str = Field(
        ...,
        description="Input text for the agent"
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="Thread ID for checkpointing (optional)"
    )
    max_iterations: Optional[int] = Field(
        default=None,
        description="Maximum iterations for autonomous execution"
    )


class AgentInvokeResponse(BaseModel):
    """
    AgentSession invoke 응답.
    """
    success: bool
    session_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    thread_id: Optional[str] = None


class AgentStateResponse(BaseModel):
    """
    AgentSession 상태 조회 응답.
    """
    session_id: str
    current_step: Optional[str] = None
    last_output: Optional[str] = None
    iteration: Optional[int] = None
    error: Optional[str] = None
    is_complete: bool = False


class UpgradeToAgentRequest(BaseModel):
    """
    기존 세션을 AgentSession으로 업그레이드 요청.
    """
    enable_checkpointing: bool = Field(
        default=False,
        description="Enable state checkpointing"
    )


# ============================================================================
# Agent Session Management API
# ============================================================================


@router.post("", response_model=SessionInfo)
async def create_agent_session(request: CreateAgentRequest):
    """
    Create a new AgentSession.

    AgentSession은 CompiledStateGraph 기반으로 동작하며,
    LangGraph의 상태 관리 기능을 제공합니다.
    """
    try:
        agent = await agent_manager.create_agent_session(
            request=request,
            enable_checkpointing=request.enable_checkpointing,
        )

        session_info = agent.get_session_info()
        logger.info(f"✅ AgentSession created: {agent.session_id}")
        return session_info

    except Exception as e:
        logger.error(f"❌ Failed to create AgentSession: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[SessionInfo])
async def list_agent_sessions():
    """
    List all AgentSessions.

    Returns only AgentSession instances (not regular sessions).
    """
    agents = agent_manager.list_agents()
    return [agent.get_session_info() for agent in agents]


# ============================================================================
# Session Store API (MUST be before /{session_id} to avoid path capture)
# ============================================================================


@router.get("/store/deleted", response_model=List[dict])
async def list_deleted_sessions():
    """
    List all soft-deleted sessions from the persistent store.
    """
    store = get_session_store()
    return store.list_deleted()


@router.get("/store/all", response_model=List[dict])
async def list_all_stored_sessions():
    """
    List ALL sessions from the persistent store (active + deleted).
    """
    store = get_session_store()
    return store.list_all()


@router.get("/store/{session_id}")
async def get_stored_session_info(
    session_id: str = Path(..., description="Session ID"),
):
    """
    Get detailed metadata for any session (active or deleted) from the store.
    """
    store = get_session_store()
    record = store.get(session_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found in store")
    return record


# ============================================================================
# Session CRUD (with /{session_id} path parameter)
# ============================================================================


@router.get("/{session_id}", response_model=SessionInfo)
async def get_agent_session(
    session_id: str = Path(..., description="Session ID")
):
    """
    Get specific AgentSession information.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        # 기존 세션에서 조회 시도
        session_info = agent_manager.get_session_info(session_id)
        if session_info:
            raise HTTPException(
                status_code=400,
                detail=f"Session {session_id} is not an AgentSession. Use /api/agents/{session_id}/upgrade to convert it."
            )
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    return agent.get_session_info()


@router.delete("/{session_id}")
async def delete_agent_session(
    session_id: str = Path(..., description="Session ID"),
    cleanup_storage: bool = Query(True, description="Also delete storage")
):
    """
    Delete AgentSession (soft-delete — metadata preserved in sessions.json).
    """
    success = await agent_manager.delete_session(session_id, cleanup_storage)
    if not success:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    logger.info(f"✅ AgentSession soft-deleted: {session_id}")
    return {"success": True, "session_id": session_id}


@router.delete("/{session_id}/permanent")
async def permanent_delete_session(
    session_id: str = Path(..., description="Session ID"),
):
    """
    Permanently delete a session from the persistent store.
    The session record is irrecoverably removed from sessions.json.
    """
    store = get_session_store()
    # Also delete from live agents if still active
    if agent_manager.has_agent(session_id):
        await agent_manager.delete_session(session_id, cleanup_storage=True)
    removed = store.permanent_delete(session_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found in store")
    logger.info(f"✅ Session permanently deleted: {session_id}")
    return {"success": True, "session_id": session_id}


@router.post("/{session_id}/restore")
async def restore_session(
    session_id: str = Path(..., description="Session ID to restore"),
):
    """
    Restore a soft-deleted session.

    Re-creates the AgentSession using the original creation parameters
    stored in sessions.json, with the same session_name and settings.
    Returns the new SessionInfo (note: session_id will be NEW).
    """
    store = get_session_store()
    record = store.get(session_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found in store")
    if not record.get("is_deleted"):
        raise HTTPException(status_code=400, detail="Session is not deleted — nothing to restore")

    # Check not already live
    if agent_manager.has_agent(session_id):
        raise HTTPException(status_code=400, detail="Session is already running")

    # Build creation params from stored record
    params = store.get_creation_params(session_id)
    if not params:
        raise HTTPException(status_code=500, detail="Could not extract creation params")

    try:
        request = CreateSessionRequest(
            session_name=params.get("session_name"),
            working_dir=params.get("working_dir"),
            model=params.get("model"),
            max_turns=params.get("max_turns", 100),
            timeout=params.get("timeout", 1800),
            autonomous=params.get("autonomous", True),
            autonomous_max_iterations=params.get("autonomous_max_iterations", 100),
            role=SessionRole(params["role"]) if params.get("role") else SessionRole.WORKER,
            manager_id=params.get("manager_id"),
        )

        # Reuse the SAME session_id → preserves storage_path
        agent = await agent_manager.create_agent_session(
            request=request,
            session_id=session_id,
        )

        # register() in create_agent_session already updates the store record
        # with is_deleted=False and fresh session info

        session_info = agent.get_session_info()
        logger.info(f"✅ Session restored: {session_id} (same ID, storage preserved)")
        return session_info
    except Exception as e:
        logger.error(f"❌ Failed to restore session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Agent Graph Execution API
# ============================================================================


@router.post("/{session_id}/invoke", response_model=AgentInvokeResponse)
async def invoke_agent(
    session_id: str = Path(..., description="Session ID"),
    request: AgentInvokeRequest = ...
):
    """
    Invoke AgentSession with LangGraph state execution.

    상태 기반 그래프 실행을 수행합니다.
    체크포인팅이 활성화된 경우 thread_id로 상태를 복원/저장합니다.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    if not agent.is_initialized:
        raise HTTPException(
            status_code=400,
            detail=f"AgentSession is not initialized"
        )

    # 세션 로거
    session_logger = get_session_logger(session_id, create_if_missing=False)

    try:
        # 입력 로깅
        if session_logger:
            session_logger.log_command(
                prompt=request.input_text,
                max_turns=request.max_iterations,
            )

        # LangGraph 그래프 실행
        output = await agent.invoke(
            input_text=request.input_text,
            thread_id=request.thread_id,
            max_iterations=request.max_iterations,
        )

        # 응답 로깅
        if session_logger:
            session_logger.log_response(
                success=True,
                output=output,
            )

        return AgentInvokeResponse(
            success=True,
            session_id=session_id,
            output=output,
            thread_id=request.thread_id,
        )

    except Exception as e:
        logger.error(f"❌ Agent invoke failed: {e}", exc_info=True)

        if session_logger:
            session_logger.log_response(
                success=False,
                error=str(e),
            )

        return AgentInvokeResponse(
            success=False,
            session_id=session_id,
            error=str(e),
            thread_id=request.thread_id,
        )


@router.post("/{session_id}/execute", response_model=ExecuteResponse)
async def execute_agent_prompt(
    session_id: str = Path(..., description="Session ID"),
    request: ExecuteRequest = ...
):
    """
    Execute prompt with AgentSession (기존 방식 호환).

    기존 claude_controller의 execute와 동일한 인터페이스를 제공합니다.
    내부적으로 ClaudeProcess.execute()를 직접 호출합니다.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    if not agent.is_alive():
        raise HTTPException(
            status_code=400,
            detail=f"AgentSession is not running (status: {agent.status})"
        )

    # 세션 로거
    session_logger = get_session_logger(session_id, create_if_missing=False)

    try:
        # 입력 로깅
        if session_logger:
            session_logger.log_command(
                prompt=request.prompt,
                timeout=request.timeout,
                system_prompt=request.system_prompt,
                max_turns=request.max_turns,
            )

        # 기존 방식으로 실행 (ClaudeProcess.execute 호출)
        result = await agent.execute(
            prompt=request.prompt,
            timeout=request.timeout or agent.timeout,
            skip_permissions=request.skip_permissions,
        )

        # 응답 로깅
        if session_logger:
            session_logger.log_response(
                success=result.get("success", False),
                output=result.get("output"),
                error=result.get("error"),
                duration_ms=result.get("duration_ms"),
                cost_usd=result.get("cost_usd"),
            )

        return ExecuteResponse(
            success=result.get("success", False),
            session_id=session_id,
            output=result.get("output"),
            error=result.get("error"),
            cost_usd=result.get("cost_usd"),
            duration_ms=result.get("duration_ms"),
        )

    except Exception as e:
        logger.error(f"❌ Agent execute failed: {e}", exc_info=True)

        if session_logger:
            session_logger.log_response(
                success=False,
                error=str(e),
            )

        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Agent State API
# ============================================================================


@router.get("/{session_id}/state", response_model=AgentStateResponse)
async def get_agent_state(
    session_id: str = Path(..., description="Session ID"),
    thread_id: Optional[str] = Query(None, description="Thread ID")
):
    """
    Get current AgentSession state.

    체크포인팅이 활성화된 경우에만 상태를 조회할 수 있습니다.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    state = agent.get_state(thread_id=thread_id)

    if state is None:
        return AgentStateResponse(
            session_id=session_id,
            error="State not available (checkpointing disabled or no execution yet)",
        )

    metadata = state.get("metadata", {})

    return AgentStateResponse(
        session_id=session_id,
        current_step=state.get("current_step"),
        last_output=state.get("last_output"),
        iteration=metadata.get("iteration"),
        error=state.get("error"),
        is_complete=state.get("is_complete", False),
    )


@router.get("/{session_id}/history")
async def get_agent_history(
    session_id: str = Path(..., description="Session ID"),
    thread_id: Optional[str] = Query(None, description="Thread ID")
):
    """
    Get AgentSession execution history.

    체크포인팅이 활성화된 경우에만 히스토리를 조회할 수 있습니다.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    history = agent.get_history(thread_id=thread_id)

    return {
        "session_id": session_id,
        "thread_id": thread_id,
        "history": history,
    }


# ============================================================================
# Agent Upgrade API
# ============================================================================


@router.post("/{session_id}/upgrade", response_model=SessionInfo)
async def upgrade_to_agent_session(
    session_id: str = Path(..., description="Session ID"),
    request: UpgradeToAgentRequest = UpgradeToAgentRequest()
):
    """
    Upgrade existing ClaudeProcess session to AgentSession.

    기존 세션의 ClaudeProcess를 유지하면서 AgentSession으로 래핑합니다.
    """
    # 이미 AgentSession인지 확인
    if agent_manager.has_agent(session_id):
        agent = agent_manager.get_agent(session_id)
        logger.info(f"Session {session_id} is already an AgentSession")
        return agent.get_session_info()

    # 업그레이드 시도
    agent = agent_manager.upgrade_to_agent(
        session_id=session_id,
        enable_checkpointing=request.enable_checkpointing,
    )

    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found or cannot be upgraded: {session_id}"
        )

    logger.info(f"✅ Session upgraded to AgentSession: {session_id}")
    return agent.get_session_info()


# ============================================================================
# Manager/Worker API
# ============================================================================


@router.get("/managers", response_model=List[SessionInfo])
async def list_agent_managers():
    """
    Get all AgentSession managers.
    """
    managers = agent_manager.get_agent_managers()
    return [m.get_session_info() for m in managers]


@router.get("/{manager_id}/workers", response_model=List[SessionInfo])
async def get_agent_workers(
    manager_id: str = Path(..., description="Manager session ID")
):
    """
    Get workers under a manager AgentSession.
    """
    workers = agent_manager.get_agent_workers_by_manager(manager_id)
    return [w.get_session_info() for w in workers]


# ============================================================================
# Autonomous Execution API (NEW: 난이도 기반 AutonomousGraph 사용)
# ============================================================================


@router.post("/{session_id}/execute/autonomous")
async def execute_autonomous(
    session_id: str = Path(..., description="Session ID"),
    request: AutonomousExecuteRequest = ...
):
    """
    Execute a task autonomously using the new difficulty-based AutonomousGraph.

    난이도 기반 자율 실행:
    - EASY: 바로 답변
    - MEDIUM: 답변 + 검토
    - HARD: TODO 생성 → 개별 실행 → 검토 → 최종 답변
    """
    import time
    start_time = time.time()

    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    if not agent.is_initialized:
        raise HTTPException(
            status_code=400,
            detail="AgentSession is not initialized"
        )

    session_logger = get_session_logger(session_id, create_if_missing=False)
    all_outputs = []
    node_count = 0

    try:
        if session_logger:
            session_logger.log_command(
                prompt=f"[AUTONOMOUS] {request.prompt}",
                timeout=request.timeout_per_iteration,
                system_prompt=request.system_prompt,
                max_turns=request.max_turns
            )

        logger.info(f"[{session_id}] 🚀 Starting autonomous execution with AutonomousGraph...")

        # 스트리밍으로 실행하여 각 노드 이벤트를 로깅
        final_result = None
        async for event in agent.astream(
            input_text=request.prompt,
            max_iterations=request.max_iterations or agent.autonomous_max_iterations,
        ):
            node_count += 1

            # 이벤트에서 노드 정보 추출 및 로깅
            if isinstance(event, dict):
                for node_name, node_result in event.items():
                    if node_name.startswith("__"):
                        continue

                    # 노드 결과에서 출력 추출
                    if isinstance(node_result, dict):
                        output = (
                            node_result.get("final_answer") or
                            node_result.get("answer") or
                            node_result.get("last_output") or
                            node_result.get("review_feedback")
                        )
                        if output:
                            all_outputs.append(f"[{node_name}] {output[:500]}")

                        # 최종 결과 저장
                        if node_result.get("is_complete") or node_result.get("final_answer"):
                            final_result = node_result

                    logger.debug(f"[{session_id}] Node: {node_name}")

        # 최종 결과 추출
        duration_ms = int((time.time() - start_time) * 1000)

        if final_result:
            final_output = (
                final_result.get("final_answer") or
                final_result.get("answer") or
                final_result.get("last_output") or
                ""
            )
            is_complete = final_result.get("is_complete", True)
            error = final_result.get("error")
            difficulty = final_result.get("difficulty")
            stop_reason = f"completed ({difficulty})" if not error else error
        else:
            final_output = all_outputs[-1] if all_outputs else "No output"
            is_complete = True
            error = None
            stop_reason = "completed"

        success = error is None

        if session_logger:
            session_logger.log_response(
                success=success,
                output=f"[Autonomous: {node_count} nodes] {final_output[:500] if final_output else 'No output'}",
                error=error,
                duration_ms=duration_ms
            )

        logger.info(f"[{session_id}] ✅ Autonomous execution completed: {stop_reason}")

        return AutonomousExecuteResponse(
            success=success,
            session_id=session_id,
            is_complete=is_complete,
            total_iterations=node_count,
            original_request=request.prompt,
            final_output=final_output,
            all_outputs=all_outputs if all_outputs else None,
            error=error,
            total_duration_ms=duration_ms,
            stop_reason=stop_reason
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(f"❌ Autonomous execution failed: {e}", exc_info=True)
        if session_logger:
            session_logger.error(f"Autonomous execution failed: {str(e)}")

        return AutonomousExecuteResponse(
            success=False,
            session_id=session_id,
            is_complete=False,
            total_iterations=node_count,
            original_request=request.prompt,
            final_output=all_outputs[-1] if all_outputs else None,
            all_outputs=all_outputs if all_outputs else None,
            error=str(e),
            total_duration_ms=duration_ms,
            stop_reason=f"error: {type(e).__name__}"
        )


@router.post("/{session_id}/execute/autonomous/stop")
async def stop_autonomous_execution(
    session_id: str = Path(..., description="Session ID")
):
    """
    Stop the autonomous execution loop.

    Note: 새로운 AutonomousGraph는 동기 실행이므로 중간 중단이 제한적입니다.
    실행 중인 요청을 취소하려면 HTTP 요청 자체를 취소하세요.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    # AutonomousGraph는 동기 실행이므로 중단 불가능
    logger.info(f"[{session_id}] ℹ️ AutonomousGraph uses synchronous execution - cancel HTTP request to stop")
    return {
        "success": True,
        "message": "AutonomousGraph executes synchronously. Cancel the HTTP request to stop execution.",
        "graph_type": "autonomous_graph" if agent.autonomous else "simple"
    }


@router.get("/{session_id}/execute/autonomous/status")
async def get_autonomous_status(
    session_id: str = Path(..., description="Session ID")
):
    """
    Get the current autonomous execution status.

    AutonomousGraph는 동기 실행이므로 실행 중일 때는
    HTTP 요청이 블로킹되어 이 엔드포인트에 접근할 수 없습니다.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    return {
        "session_id": session_id,
        "is_running": False,  # 동기 실행이므로 이 엔드포인트 호출 시점에는 실행 중이 아님
        "max_iterations": agent.autonomous_max_iterations,
        "graph_type": "autonomous_graph" if agent.autonomous else "simple",
        "mode": "difficulty_based",  # 난이도 기반 그래프
        "paths": ["easy (direct_answer)", "medium (answer + review)", "hard (todos + review + final)"]
    }


# ============================================================================
# Storage API
# ============================================================================


@router.get("/{session_id}/storage")
async def list_storage_files(
    session_id: str = Path(..., description="Session ID"),
    path: str = Query("", description="Subdirectory path")
):
    """
    List session storage files.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    process = agent.process
    if not process:
        raise HTTPException(status_code=400, detail="AgentSession process not available")

    files_data = process.list_storage_files(path)
    files = [StorageFile(**f) for f in files_data]

    return StorageListResponse(
        session_id=session_id,
        storage_path=process.storage_path,
        files=files
    )


@router.get("/{session_id}/storage/{file_path:path}")
async def read_storage_file(
    session_id: str = Path(..., description="Session ID"),
    file_path: str = Path(..., description="File path"),
    encoding: str = Query("utf-8", description="File encoding")
):
    """
    Read storage file content.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    process = agent.process
    if not process:
        raise HTTPException(status_code=400, detail="AgentSession process not available")

    file_content = process.read_storage_file(file_path, encoding)
    if not file_content:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    return StorageFileContent(
        session_id=session_id,
        **file_content
    )


# ============================================================================
# Manager Dashboard API
# ============================================================================


@router.post("/{session_id}/delegate")
async def delegate_task(
    session_id: str = Path(..., description="Manager session ID"),
    request: DelegateTaskRequest = ...
):
    """
    Delegate a task from manager to worker.
    """
    import uuid
    from datetime import datetime

    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Manager AgentSession not found: {session_id}")

    if agent.role != SessionRole.MANAGER:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not a manager (role: {agent.role})"
        )

    # Get worker
    worker = agent_manager.get_agent(request.worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker AgentSession not found: {request.worker_id}")

    if worker.manager_id != session_id:
        raise HTTPException(
            status_code=400,
            detail=f"Worker {request.worker_id} is not managed by this manager"
        )

    worker_process = worker.process
    if not worker_process or not worker_process.is_alive():
        raise HTTPException(
            status_code=400,
            detail=f"Worker session is not running"
        )

    manager_logger = get_session_logger(session_id, create_if_missing=True)
    delegation_id = str(uuid.uuid4())[:8]

    try:
        if manager_logger:
            manager_logger.log_task_delegated(
                worker_id=request.worker_id,
                worker_name=worker.session_name,
                task_prompt=request.prompt,
                context=request.context
            )

        worker_process.is_busy = True
        worker_process.current_task = request.prompt[:100]
        worker_process.last_activity = datetime.now()

        # 새로운 AutonomousGraph 기반 실행 (autonomous/non-autonomous 모두 지원)
        output = await worker.invoke(
            input_text=request.prompt,
            max_iterations=worker.autonomous_max_iterations if worker.autonomous else 1,
        )
        success = bool(output and not output.startswith("Error:"))

        worker_process.is_busy = False
        worker_process.last_output = output[:500] if output else None
        worker_process.last_activity = datetime.now()

        if manager_logger:
            manager_logger.log_worker_completed(
                worker_id=request.worker_id,
                worker_name=worker.session_name,
                success=success,
                output_preview=output[:200] if output else None,
                duration_ms=None,
                cost_usd=None
            )

        return DelegateTaskResponse(
            success=success,
            manager_id=session_id,
            worker_id=request.worker_id,
            delegation_id=delegation_id,
            status="completed" if success else "error",
            output=output,
            error=None if success else output
        )

    except Exception as e:
        worker_process.is_busy = False
        worker_process.last_activity = datetime.now()
        logger.error(f"❌ Task delegation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/events")
async def get_manager_events(
    session_id: str = Path(..., description="Manager session ID"),
    limit: int = Query(50, description="Maximum number of events to return")
):
    """
    Get manager event log.
    """
    import uuid
    from datetime import datetime

    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    if agent.role != SessionRole.MANAGER:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not a manager (role: {agent.role})"
        )

    session_logger = get_session_logger(session_id, create_if_missing=False)
    if not session_logger:
        return []

    raw_events = session_logger.get_manager_events(limit=limit)

    events = []
    for raw in raw_events:
        metadata = raw.get("metadata", {})
        events.append(ManagerEvent(
            event_id=metadata.get("event_id", str(uuid.uuid4())[:8]),
            event_type=ManagerEventType(metadata.get("event_type", "status_check")),
            timestamp=datetime.fromisoformat(raw.get("timestamp")) if raw.get("timestamp") else datetime.now(),
            manager_id=session_id,
            worker_id=metadata.get("worker_id"),
            message=raw.get("message", ""),
            data=metadata.get("data")
        ))

    return events


@router.get("/{session_id}/dashboard")
async def get_manager_dashboard(
    session_id: str = Path(..., description="Manager session ID")
):
    """
    Get manager dashboard data.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    if agent.role != SessionRole.MANAGER:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not a manager (role: {agent.role})"
        )

    workers = agent_manager.get_agent_workers_by_manager(session_id)
    worker_statuses = []

    for worker in workers:
        process = worker.process

        worker_status = WorkerStatus(
            worker_id=worker.session_id,
            worker_name=worker.session_name,
            status=worker.status,
            is_busy=process.is_busy if process else False,
            current_task=process.current_task if process else None,
            last_output=process.last_output if process else None,
            last_activity=process.last_activity if process else None
        )
        worker_statuses.append(worker_status)

    events_response = await get_manager_events(session_id, limit=20)

    active_delegations = sum(1 for w in worker_statuses if w.is_busy)
    completed_delegations = sum(
        1 for e in events_response
        if e.event_type in [ManagerEventType.WORKER_COMPLETED, ManagerEventType.WORKER_ERROR]
    )

    return ManagerDashboard(
        manager_id=session_id,
        manager_name=agent.session_name,
        workers=worker_statuses,
        recent_events=events_response,
        active_delegations=active_delegations,
        completed_delegations=completed_delegations
    )


# ============================================================================
# Graph Introspection API
# ============================================================================


class GraphNodeInfo(BaseModel):
    """Single node/state in the graph."""
    id: str
    label: str
    type: str = "node"  # node | start | end
    description: str = ""
    prompt_template: Optional[str] = None
    metadata: dict = {}


class GraphEdgeInfo(BaseModel):
    """Single edge in the graph."""
    source: str
    target: str
    label: str = ""
    type: str = "edge"  # edge | conditional
    condition_map: Optional[dict] = None


class GraphStructure(BaseModel):
    """Complete graph topology for visualization."""
    session_id: str
    session_name: str = ""
    graph_type: str = "simple"  # simple | autonomous
    nodes: list[GraphNodeInfo] = []
    edges: list[GraphEdgeInfo] = []


def _build_simple_graph_structure(session_id: str, session_name: str) -> GraphStructure:
    """Build the simple (non-autonomous) graph structure for visualization."""
    nodes = [
        GraphNodeInfo(
            id="__start__", label="START", type="start",
            description="Entry point of the graph.",
        ),
        GraphNodeInfo(
            id="context_guard", label="Context Guard", type="node",
            description=(
                "Checks the context window budget. "
                "If token count exceeds the warn/block threshold, "
                "auto-compacts messages to stay within limits."
            ),
            metadata={
                "warn_ratio": 0.75,
                "block_ratio": 0.90,
                "auto_compact_keep": 20,
            },
        ),
        GraphNodeInfo(
            id="agent", label="Agent", type="node",
            description=(
                "Core agent node — invokes the Claude CLI model with the "
                "current message history, records the response to state, "
                "and updates short-term memory."
            ),
        ),
        GraphNodeInfo(
            id="process_output", label="Process Output", type="node",
            description=(
                "Increments the iteration counter and inspects the last "
                "response for a completion signal (e.g. TASK_COMPLETE). "
                "Decides whether to continue or end."
            ),
            metadata={
                "signals": ["TASK_COMPLETE", "DONE", "FINISHED"],
            },
        ),
        GraphNodeInfo(
            id="__end__", label="END", type="end",
            description="Terminal state — execution is complete.",
        ),
    ]
    edges = [
        GraphEdgeInfo(source="__start__", target="context_guard", label=""),
        GraphEdgeInfo(source="context_guard", target="agent", label=""),
        GraphEdgeInfo(source="agent", target="process_output", label=""),
        GraphEdgeInfo(
            source="process_output", target="context_guard",
            label="continue", type="conditional",
            condition_map={"continue": "context_guard", "end": "__end__"},
        ),
        GraphEdgeInfo(
            source="process_output", target="__end__",
            label="end", type="conditional",
            condition_map={"continue": "context_guard", "end": "__end__"},
        ),
    ]
    return GraphStructure(
        session_id=session_id,
        session_name=session_name,
        graph_type="simple",
        nodes=nodes,
        edges=edges,
    )


def _build_autonomous_graph_structure(session_id: str, session_name: str) -> GraphStructure:
    """Build the enhanced autonomous graph structure for visualization.

    Reflects the full 28-node resilience-enhanced topology with
    memory_inject, context guards, post-model processors, and iteration gates.
    """
    from service.prompt.sections import AutonomousPrompts

    nodes = [
        GraphNodeInfo(
            id="__start__", label="START", type="start",
            description="Entry point of the autonomous graph.",
        ),
        # -- Common entry --
        GraphNodeInfo(
            id="memory_inject", label="Memory Inject", type="resilience",
            description=(
                "Loads relevant long-term and short-term memory into state. "
                "Records user input to transcript."
            ),
            metadata={"concern": "memory"},
        ),
        GraphNodeInfo(
            id="guard_classify", label="Guard: Classify", type="resilience",
            description="Checks context budget before difficulty classification.",
            metadata={"concern": "context_guard"},
        ),
        GraphNodeInfo(
            id="classify_difficulty", label="Classify Difficulty", type="node",
            description=(
                "Analyzes the input task and classifies it as easy, medium, or hard. "
                "Routes to the appropriate execution path."
            ),
            prompt_template=AutonomousPrompts.classify_difficulty(),
            metadata={"outputs": ["easy", "medium", "hard"]},
        ),
        GraphNodeInfo(
            id="post_classify", label="Post: Classify", type="resilience",
            description="Increments iteration counter and records transcript after classification.",
            metadata={"concern": "post_model"},
        ),
        # -- Easy path --
        GraphNodeInfo(
            id="guard_direct", label="Guard: Direct", type="resilience",
            description="Checks context budget before direct answer.",
            metadata={"concern": "context_guard", "path": "easy"},
        ),
        GraphNodeInfo(
            id="direct_answer", label="Direct Answer", type="node",
            description=(
                "Handles easy tasks — provides a direct answer in a single "
                "model call without review or planning."
            ),
            metadata={"path": "easy"},
        ),
        GraphNodeInfo(
            id="post_direct", label="Post: Direct", type="resilience",
            description="Completion signal detection and transcript recording for direct answer.",
            metadata={"concern": "post_model", "path": "easy"},
        ),
        # -- Medium path --
        GraphNodeInfo(
            id="guard_answer", label="Guard: Answer", type="resilience",
            description="Checks context budget before answer generation.",
            metadata={"concern": "context_guard", "path": "medium"},
        ),
        GraphNodeInfo(
            id="answer", label="Answer", type="node",
            description=(
                "Generates an answer for medium-complexity tasks. "
                "Incorporates review feedback on retries."
            ),
            metadata={"path": "medium"},
        ),
        GraphNodeInfo(
            id="post_answer", label="Post: Answer", type="resilience",
            description="Iteration increment and transcript recording after answer generation.",
            metadata={"concern": "post_model", "path": "medium"},
        ),
        GraphNodeInfo(
            id="guard_review", label="Guard: Review", type="resilience",
            description="Checks context budget before quality review.",
            metadata={"concern": "context_guard", "path": "medium"},
        ),
        GraphNodeInfo(
            id="review", label="Review", type="node",
            description=(
                "Quality reviewer — evaluates the answer for accuracy and "
                "completeness. Produces VERDICT: approved or rejected."
            ),
            prompt_template=AutonomousPrompts.review(),
            metadata={"path": "medium", "max_retries": 3},
        ),
        GraphNodeInfo(
            id="post_review", label="Post: Review", type="resilience",
            description="Completion signal detection and transcript recording after review.",
            metadata={"concern": "post_model", "path": "medium"},
        ),
        GraphNodeInfo(
            id="iter_gate_medium", label="Gate: Medium", type="resilience",
            description=(
                "Iteration gate for medium retry loop. Checks global iteration limit, "
                "context budget, and completion signals before allowing retry."
            ),
            metadata={"concern": "iteration_gate", "path": "medium"},
        ),
        # -- Hard path --
        GraphNodeInfo(
            id="guard_create_todos", label="Guard: Todos", type="resilience",
            description="Checks context budget before TODO creation.",
            metadata={"concern": "context_guard", "path": "hard"},
        ),
        GraphNodeInfo(
            id="create_todos", label="Create TODOs", type="node",
            description=(
                "Task planner — decomposes a complex task into a structured "
                "JSON list of TODO items. Capped at 20 items."
            ),
            prompt_template=AutonomousPrompts.create_todos(),
            metadata={"path": "hard", "max_todos": 20},
        ),
        GraphNodeInfo(
            id="post_create_todos", label="Post: Todos", type="resilience",
            description="Iteration increment and transcript recording after TODO creation.",
            metadata={"concern": "post_model", "path": "hard"},
        ),
        GraphNodeInfo(
            id="guard_execute", label="Guard: Execute", type="resilience",
            description="Checks context budget before TODO execution.",
            metadata={"concern": "context_guard", "path": "hard"},
        ),
        GraphNodeInfo(
            id="execute_todo", label="Execute TODO", type="node",
            description=(
                "Executes a single TODO item from the plan. Uses budget-aware "
                "compaction for previous results."
            ),
            prompt_template=AutonomousPrompts.execute_todo(),
            metadata={"path": "hard"},
        ),
        GraphNodeInfo(
            id="post_execute", label="Post: Execute", type="resilience",
            description="Completion signal detection and transcript recording after TODO execution.",
            metadata={"concern": "post_model", "path": "hard"},
        ),
        GraphNodeInfo(
            id="check_progress", label="Check Progress", type="node",
            description=(
                "Checks TODO completion progress — completed, failed, remaining counts."
            ),
            metadata={"path": "hard", "outputs": ["continue", "complete"]},
        ),
        GraphNodeInfo(
            id="iter_gate_hard", label="Gate: Hard", type="resilience",
            description=(
                "Iteration gate for hard TODO loop. Checks global iteration limit, "
                "context budget, and completion signals before next TODO."
            ),
            metadata={"concern": "iteration_gate", "path": "hard"},
        ),
        GraphNodeInfo(
            id="guard_final_review", label="Guard: Final Review", type="resilience",
            description="Checks context budget before final review.",
            metadata={"concern": "context_guard", "path": "hard"},
        ),
        GraphNodeInfo(
            id="final_review", label="Final Review", type="node",
            description=(
                "Conducts a comprehensive review of all completed TODO items "
                "with budget-aware result compaction."
            ),
            prompt_template=AutonomousPrompts.final_review(),
            metadata={"path": "hard"},
        ),
        GraphNodeInfo(
            id="post_final_review", label="Post: Final Review", type="resilience",
            description="Completion signal detection and transcript recording after final review.",
            metadata={"concern": "post_model", "path": "hard"},
        ),
        GraphNodeInfo(
            id="guard_final_answer", label="Guard: Final Answer", type="resilience",
            description="Checks context budget before final answer synthesis.",
            metadata={"concern": "context_guard", "path": "hard"},
        ),
        GraphNodeInfo(
            id="final_answer", label="Final Answer", type="node",
            description=(
                "Synthesizes all completed work and review feedback into "
                "a final, polished, comprehensive answer."
            ),
            prompt_template=AutonomousPrompts.final_answer(),
            metadata={"path": "hard"},
        ),
        GraphNodeInfo(
            id="post_final_answer", label="Post: Final Answer", type="resilience",
            description="Completion signal detection and transcript recording for final answer.",
            metadata={"concern": "post_model", "path": "hard"},
        ),
        GraphNodeInfo(
            id="__end__", label="END", type="end",
            description="Terminal state — autonomous execution is complete.",
        ),
    ]

    edges = [
        # -- Common entry --
        GraphEdgeInfo(source="__start__", target="memory_inject", label=""),
        GraphEdgeInfo(source="memory_inject", target="guard_classify", label=""),
        GraphEdgeInfo(source="guard_classify", target="classify_difficulty", label=""),
        GraphEdgeInfo(source="classify_difficulty", target="post_classify", label=""),

        # post_classify → route by difficulty
        GraphEdgeInfo(
            source="post_classify", target="guard_direct",
            label="easy", type="conditional",
            condition_map={"easy": "guard_direct", "medium": "guard_answer", "hard": "guard_create_todos", "end": "__end__"},
        ),
        GraphEdgeInfo(
            source="post_classify", target="guard_answer",
            label="medium", type="conditional",
            condition_map={"easy": "guard_direct", "medium": "guard_answer", "hard": "guard_create_todos", "end": "__end__"},
        ),
        GraphEdgeInfo(
            source="post_classify", target="guard_create_todos",
            label="hard", type="conditional",
            condition_map={"easy": "guard_direct", "medium": "guard_answer", "hard": "guard_create_todos", "end": "__end__"},
        ),
        GraphEdgeInfo(
            source="post_classify", target="__end__",
            label="end", type="conditional",
            condition_map={"easy": "guard_direct", "medium": "guard_answer", "hard": "guard_create_todos", "end": "__end__"},
        ),

        # -- Easy path --
        GraphEdgeInfo(source="guard_direct", target="direct_answer", label=""),
        GraphEdgeInfo(source="direct_answer", target="post_direct", label=""),
        GraphEdgeInfo(source="post_direct", target="__end__", label=""),

        # -- Medium path --
        GraphEdgeInfo(source="guard_answer", target="answer", label=""),
        GraphEdgeInfo(source="answer", target="post_answer", label=""),
        GraphEdgeInfo(source="post_answer", target="guard_review", label=""),
        GraphEdgeInfo(source="guard_review", target="review", label=""),
        GraphEdgeInfo(source="review", target="post_review", label=""),

        # post_review → route after review
        GraphEdgeInfo(
            source="post_review", target="__end__",
            label="approved", type="conditional",
            condition_map={"approved": "__end__", "retry": "iter_gate_medium", "end": "__end__"},
        ),
        GraphEdgeInfo(
            source="post_review", target="iter_gate_medium",
            label="retry", type="conditional",
            condition_map={"approved": "__end__", "retry": "iter_gate_medium", "end": "__end__"},
        ),

        # iter_gate_medium → route
        GraphEdgeInfo(
            source="iter_gate_medium", target="guard_answer",
            label="continue", type="conditional",
            condition_map={"continue": "guard_answer", "stop": "__end__"},
        ),
        GraphEdgeInfo(
            source="iter_gate_medium", target="__end__",
            label="stop", type="conditional",
            condition_map={"continue": "guard_answer", "stop": "__end__"},
        ),

        # -- Hard path --
        GraphEdgeInfo(source="guard_create_todos", target="create_todos", label=""),
        GraphEdgeInfo(source="create_todos", target="post_create_todos", label=""),
        GraphEdgeInfo(source="post_create_todos", target="guard_execute", label=""),
        GraphEdgeInfo(source="guard_execute", target="execute_todo", label=""),
        GraphEdgeInfo(source="execute_todo", target="post_execute", label=""),
        GraphEdgeInfo(source="post_execute", target="check_progress", label=""),

        # check_progress → route after progress
        GraphEdgeInfo(
            source="check_progress", target="iter_gate_hard",
            label="continue", type="conditional",
            condition_map={"continue": "iter_gate_hard", "complete": "guard_final_review"},
        ),
        GraphEdgeInfo(
            source="check_progress", target="guard_final_review",
            label="complete", type="conditional",
            condition_map={"continue": "iter_gate_hard", "complete": "guard_final_review"},
        ),

        # iter_gate_hard → route
        GraphEdgeInfo(
            source="iter_gate_hard", target="guard_execute",
            label="continue", type="conditional",
            condition_map={"continue": "guard_execute", "stop": "guard_final_review"},
        ),
        GraphEdgeInfo(
            source="iter_gate_hard", target="guard_final_review",
            label="stop", type="conditional",
            condition_map={"continue": "guard_execute", "stop": "guard_final_review"},
        ),

        # Final review/answer chain
        GraphEdgeInfo(source="guard_final_review", target="final_review", label=""),
        GraphEdgeInfo(source="final_review", target="post_final_review", label=""),
        GraphEdgeInfo(source="post_final_review", target="guard_final_answer", label=""),
        GraphEdgeInfo(source="guard_final_answer", target="final_answer", label=""),
        GraphEdgeInfo(source="final_answer", target="post_final_answer", label=""),
        GraphEdgeInfo(source="post_final_answer", target="__end__", label=""),
    ]

    return GraphStructure(
        session_id=session_id,
        session_name=session_name,
        graph_type="autonomous",
        nodes=nodes,
        edges=edges,
    )


@router.get("/{session_id}/graph", response_model=GraphStructure)
async def get_session_graph(
    session_id: str = Path(..., description="Session ID"),
):
    """
    Get the LangGraph graph structure for a session.

    Returns all nodes, edges, conditional edges, prompt templates,
    and metadata for complete graph visualization.
    """
    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    session_name = agent.session_name or session_id[:8]
    is_autonomous = agent.autonomous

    if is_autonomous:
        graph = _build_autonomous_graph_structure(session_id, session_name)
        # Also include the inner simple graph as metadata
        simple = _build_simple_graph_structure(session_id, session_name)
        graph.nodes[0].metadata["inner_graph"] = {
            "description": "The inner simple graph runs inside each autonomous node that invokes the model.",
            "nodes": [n.model_dump() for n in simple.nodes],
            "edges": [e.model_dump() for e in simple.edges],
        }
    else:
        graph = _build_simple_graph_structure(session_id, session_name)

    return graph
