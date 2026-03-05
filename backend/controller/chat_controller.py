"""
Chat Controller

Broadcast chat endpoint — sends a message to all active sessions
and collects responses. Each session's relevance gate determines
whether it should respond.
"""
import asyncio
import time
from logging import getLogger
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from service.langgraph import get_agent_session_manager

logger = getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# AgentSessionManager singleton
agent_manager = get_agent_session_manager()


# ============================================================================
# Request / Response Models
# ============================================================================


class ChatBroadcastRequest(BaseModel):
    """Broadcast a chat message to all active sessions."""
    message: str = Field(..., description="Chat message to broadcast")
    timeout: float = Field(
        default=120.0,
        description="Per-session timeout in seconds",
    )


class ChatSessionResponse(BaseModel):
    """Individual session's response to a broadcast message."""
    session_id: str
    session_name: Optional[str] = None
    role: Optional[str] = None
    responded: bool = False
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


class ChatBroadcastResponse(BaseModel):
    """Aggregated broadcast result."""
    success: bool
    message: str
    total_sessions: int
    responded_count: int
    responses: List[ChatSessionResponse]
    total_duration_ms: int


# ============================================================================
# Endpoint
# ============================================================================


@router.post("/broadcast", response_model=ChatBroadcastResponse)
async def broadcast_chat(request: ChatBroadcastRequest):
    """
    Broadcast a chat message to ALL active (alive) sessions.

    Each session runs through its graph with ``is_chat_message=True``,
    which activates the relevance gate. Sessions that determine the
    message is irrelevant return empty output without full execution.

    Returns aggregated responses from all sessions.
    """
    start_time = time.time()

    # Get all alive sessions
    all_agents = agent_manager.list_agents()
    alive_agents = [a for a in all_agents if a.is_alive()]

    if not alive_agents:
        return ChatBroadcastResponse(
            success=True,
            message=request.message,
            total_sessions=0,
            responded_count=0,
            responses=[],
            total_duration_ms=0,
        )

    logger.info(
        f"Broadcasting chat to {len(alive_agents)} alive sessions: "
        f"{request.message[:80]}"
    )

    async def _invoke_session(agent):
        """Invoke a single session with the broadcast message."""
        session_start = time.time()
        session_id = agent.session_id
        session_name = agent.session_name
        role = agent.role.value if hasattr(agent.role, 'value') else str(agent.role)

        try:
            result_text = await asyncio.wait_for(
                agent.invoke(
                    input_text=request.message,
                    is_chat_message=True,
                ),
                timeout=request.timeout,
            )
            duration_ms = int((time.time() - session_start) * 1000)

            # Empty or whitespace-only output means the session skipped
            has_response = bool(result_text and result_text.strip())

            return ChatSessionResponse(
                session_id=session_id,
                session_name=session_name,
                role=role,
                responded=has_response,
                output=result_text.strip() if has_response else None,
                duration_ms=duration_ms,
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.time() - session_start) * 1000)
            logger.warning(f"Chat broadcast timeout for session {session_id}")
            return ChatSessionResponse(
                session_id=session_id,
                session_name=session_name,
                role=role,
                responded=False,
                error="Timeout",
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - session_start) * 1000)
            logger.error(f"Chat broadcast error for session {session_id}: {e}")
            return ChatSessionResponse(
                session_id=session_id,
                session_name=session_name,
                role=role,
                responded=False,
                error=str(e)[:200],
                duration_ms=duration_ms,
            )

    # Execute all sessions concurrently
    tasks = [_invoke_session(agent) for agent in alive_agents]
    results: List[ChatSessionResponse] = await asyncio.gather(*tasks)

    total_duration_ms = int((time.time() - start_time) * 1000)
    responded = [r for r in results if r.responded]

    logger.info(
        f"Chat broadcast complete: {len(responded)}/{len(results)} responded "
        f"({total_duration_ms}ms)"
    )

    return ChatBroadcastResponse(
        success=True,
        message=request.message,
        total_sessions=len(results),
        responded_count=len(responded),
        responses=results,
        total_duration_ms=total_duration_ms,
    )
