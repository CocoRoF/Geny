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
        description="Maximum graph iterations"
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
            max_iterations=params.get("max_iterations", params.get("autonomous_max_iterations", 100)),
            role=SessionRole(params["role"]) if params.get("role") else SessionRole.WORKER,
            manager_id=params.get("manager_id"),
            graph_name=params.get("graph_name"),
            workflow_id=params.get("workflow_id"),
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
    Execute prompt with AgentSession via the compiled StateGraph.

    The session's graph type determines the execution flow automatically.
    """
    import time
    start_time = time.time()

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

        # Execute through the compiled StateGraph (invoke)
        # Routes to the appropriate graph based on graph_name
        result_text = await agent.invoke(
            input_text=request.prompt,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        # 응답 로깅
        if session_logger:
            session_logger.log_response(
                success=True,
                output=result_text,
                error=None,
                duration_ms=duration_ms,
            )

        return ExecuteResponse(
            success=True,
            session_id=session_id,
            output=result_text,
            error=None,
            cost_usd=None,
            duration_ms=duration_ms,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(f"❌ Agent execute failed: {e}", exc_info=True)

        if session_logger:
            session_logger.log_response(
                success=False,
                error=str(e),
                duration_ms=duration_ms,
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
# Stop Execution API
# ============================================================================


@router.post("/{session_id}/stop")
async def stop_execution(
    session_id: str = Path(..., description="Session ID")
):
    """
    Stop the current execution for a session.

    Graph execution is synchronous — cancel the HTTP request to stop.
    This endpoint marks the intent to stop.
    """
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"AgentSession not found: {session_id}")

    logger.info(f"[{session_id}] Stop requested — graph execution is synchronous, cancel the HTTP request")
    return {
        "success": True,
        "message": "Graph executes synchronously. Cancel the HTTP request to stop execution.",
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

        # Execute through the worker's graph
        output = await worker.invoke(
            input_text=request.prompt,
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


def _build_graph_structure_from_workflow(
    session_id: str,
    session_name: str,
    workflow: "WorkflowDefinition",
) -> GraphStructure:
    """Build a GraphStructure from a WorkflowDefinition for visualization.

    Converts the workflow's nodes and edges into the GraphStructure format
    used by the frontend graph viewer.
    """
    nodes = []
    edges = []

    for node in workflow.nodes:
        node_type = "node"
        if node.node_type == "start":
            node_type = "start"
        elif node.node_type == "end":
            node_type = "end"
        elif node.node_type in ("context_guard", "post_model", "iteration_gate", "memory_inject"):
            node_type = "resilience"

        nodes.append(GraphNodeInfo(
            id=node.id,
            label=node.label,
            type=node_type,
            description=f"{node.node_type} node",
            metadata=dict(node.config) if node.config else {},
        ))

    # Group edges by source to detect conditional routing
    from collections import defaultdict
    edges_by_source = defaultdict(list)
    for edge in workflow.edges:
        edges_by_source[edge.source].append(edge)

    for source_id, source_edges in edges_by_source.items():
        targets = {e.target for e in source_edges}
        is_conditional = len(targets) > 1

        if is_conditional:
            # Build condition map for conditional edges
            condition_map = {}
            for e in source_edges:
                port = e.source_port or "default"
                condition_map[port] = e.target

            for e in source_edges:
                port = e.source_port or "default"
                edges.append(GraphEdgeInfo(
                    source=e.source,
                    target=e.target,
                    label=e.label or port,
                    type="conditional",
                    condition_map=condition_map,
                ))
        else:
            for e in source_edges:
                edges.append(GraphEdgeInfo(
                    source=e.source,
                    target=e.target,
                    label=e.label or "",
                    type="edge",
                ))

    return GraphStructure(
        session_id=session_id,
        session_name=session_name,
        graph_type=workflow.template_name or "custom",
        nodes=nodes,
        edges=edges,
    )


@router.get("/{session_id}/graph", response_model=GraphStructure)
async def get_session_graph(
    session_id: str = Path(..., description="Session ID"),
):
    """
    Get the LangGraph graph structure for a session.

    Returns all nodes, edges, conditional edges, and metadata
    for complete graph visualization. Uses the session's linked
    WorkflowDefinition instead of hardcoded structures.
    """
    from service.workflow.workflow_store import get_workflow_store

    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    session_name = agent.session_name or session_id[:8]

    # Use the linked workflow from the agent session
    workflow = agent.workflow
    if not workflow:
        # Fallback: try to load from workflow_id or template
        store = get_workflow_store()
        workflow_id = getattr(agent, '_workflow_id', None)
        if workflow_id:
            workflow = store.load(workflow_id)
        if not workflow:
            template_id = "template-autonomous" if agent.autonomous else "template-simple"
            workflow = store.load(template_id)
        if not workflow:
            raise HTTPException(
                status_code=404,
                detail=f"No workflow definition found for session {session_id}",
            )

    return _build_graph_structure_from_workflow(session_id, session_name, workflow)


@router.get("/{session_id}/workflow")
async def get_session_workflow(
    session_id: str = Path(..., description="Session ID"),
):
    """
    Get the workflow definition associated with a session.

    Returns the raw WorkflowDefinition (nodes, edges, positions)
    so the frontend can render it with the same ReactFlow-based
    editor used in the Workflow tab.

    Uses the session's linked WorkflowDefinition directly,
    falling back to store lookup if needed.
    """
    from service.workflow.workflow_store import get_workflow_store

    agent: Optional[AgentSession] = agent_manager.get_agent(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # 1. Use the linked workflow from the agent session
    if agent.workflow:
        return agent.workflow.model_dump()

    # 2. Fallback: try workflow_id from store
    store = get_workflow_store()
    workflow_id = getattr(agent, '_workflow_id', None)
    if workflow_id:
        wf = store.load(workflow_id)
        if wf:
            return wf.model_dump()

    # 3. Fall back to built-in template based on graph_name
    template_id = "template-autonomous" if agent.autonomous else "template-simple"
    wf = store.load(template_id)
    if wf:
        return wf.model_dump()

    # 4. If nothing found, error
    raise HTTPException(
        status_code=404,
        detail=f"No workflow definition found for session {session_id}",
    )
