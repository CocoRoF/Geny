"""
Chat Controller

Provides:
  - Chat room CRUD (create, list, get, update, delete)
  - Room-scoped broadcast via SSE — streams each agent response in real-time
  - Message history persistence — all messages are stored and restorable
"""
import asyncio
import json
import time
from logging import getLogger
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from service.chat.conversation_store import get_chat_store
from service.langgraph import get_agent_session_manager

logger = getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

agent_manager = get_agent_session_manager()


# ============================================================================
# Request / Response Models
# ============================================================================

# ── Room models ──

class CreateRoomRequest(BaseModel):
    name: str = Field(..., description="Chat room display name")
    session_ids: List[str] = Field(..., description="Session IDs to include")


class UpdateRoomRequest(BaseModel):
    name: Optional[str] = None
    session_ids: Optional[List[str]] = None


class RoomResponse(BaseModel):
    id: str
    name: str
    session_ids: List[str]
    created_at: str
    updated_at: str
    message_count: int


class RoomListResponse(BaseModel):
    rooms: List[RoomResponse]
    total: int


# ── Message models ──

class MessageResponse(BaseModel):
    model_config = {"extra": "ignore"}  # ignore unexpected keys from storage

    id: str
    type: str  # 'user' | 'agent' | 'system'
    content: str
    timestamp: str
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    role: Optional[str] = None
    duration_ms: Optional[int] = None


class MessageListResponse(BaseModel):
    room_id: str
    messages: List[MessageResponse]
    total: int


# ── Broadcast models ──

class RoomBroadcastRequest(BaseModel):
    message: str = Field(..., description="Chat message to send")
    timeout: float = Field(default=120.0, description="Per-session timeout in seconds")


# ============================================================================
# Room CRUD Endpoints
# ============================================================================

@router.get("/rooms", response_model=RoomListResponse)
async def list_rooms():
    """List all chat rooms (sorted by last activity)."""
    store = get_chat_store()
    rooms = store.list_rooms()
    return RoomListResponse(
        rooms=[RoomResponse(**r) for r in rooms],
        total=len(rooms),
    )


@router.post("/rooms", response_model=RoomResponse)
async def create_room(request: CreateRoomRequest):
    """Create a new chat room with selected sessions."""
    store = get_chat_store()
    room = store.create_room(name=request.name, session_ids=request.session_ids)
    return RoomResponse(**room)


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str):
    """Get a single chat room by ID."""
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")
    return RoomResponse(**room)


@router.patch("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(room_id: str, request: UpdateRoomRequest):
    """Update a chat room (name and/or sessions)."""
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    if request.name is not None:
        store.update_room_name(room_id, request.name)
    if request.session_ids is not None:
        store.update_room_sessions(room_id, request.session_ids)

    updated = store.get_room(room_id)
    return RoomResponse(**updated)


@router.delete("/rooms/{room_id}")
async def delete_room(room_id: str):
    """Delete a chat room and all its history."""
    store = get_chat_store()
    deleted = store.delete_room(room_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")
    return {"success": True, "room_id": room_id}


# ============================================================================
# Message History Endpoint
# ============================================================================

@router.get("/rooms/{room_id}/messages", response_model=MessageListResponse)
async def get_room_messages(room_id: str):
    """Get all messages for a chat room (for history restoration)."""
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    raw_messages = store.get_messages(room_id)
    messages: List[MessageResponse] = []
    for m in raw_messages:
        try:
            messages.append(MessageResponse(**m))
        except Exception as e:
            logger.warning("Skipping malformed message %s: %s", m.get("id", "?"), e)

    return MessageListResponse(
        room_id=room_id,
        messages=messages,
        total=len(messages),
    )


# ============================================================================
# Room-Scoped Broadcast Endpoint (SSE Streaming)
# ============================================================================

def _sse_event(event_type: str, data: Any) -> str:
    """Format a single SSE event."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/rooms/{room_id}/broadcast")
async def broadcast_to_room(room_id: str, request: RoomBroadcastRequest):
    """
    Send a message to sessions in a specific chat room via SSE streaming.

    Streams events as each agent responds — no waiting for all agents.

    SSE event types:
      - user_saved:      user message persisted
      - agent_response:  an agent responded (message saved)
      - agent_skip:      an agent skipped (not relevant)
      - agent_error:     an agent errored
      - summary:         summary system message
      - done:            stream complete
      - error:           top-level error
    """
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    async def event_stream():
        start_time = time.time()

        # 1. Save & emit user message
        try:
            user_msg = store.add_message(room_id, {
                "type": "user",
                "content": request.message,
            })
            yield _sse_event("user_saved", user_msg)
        except Exception as e:
            logger.error("Failed to save user message: %s", e, exc_info=True)
            yield _sse_event("error", {"error": f"Failed to save message: {e}"})
            yield _sse_event("done", {})
            return

        # 2. Resolve alive agents in this room
        all_agents = agent_manager.list_agents()
        room_session_ids = set(room["session_ids"])
        target_agents = [
            a for a in all_agents
            if a.session_id in room_session_ids and a.is_alive()
        ]

        if not target_agents:
            sys_msg = store.add_message(room_id, {
                "type": "system",
                "content": "No active sessions in this room.",
            })
            yield _sse_event("summary", sys_msg)
            yield _sse_event("done", {})
            return

        logger.info(
            "Room %s: broadcasting to %d sessions: %s",
            room_id, len(target_agents), request.message[:80],
        )

        # 3. Invoke sessions concurrently, stream results as they arrive
        result_queue: asyncio.Queue = asyncio.Queue()

        async def _invoke_and_enqueue(agent):
            """Invoke a single session and push the result to the queue."""
            session_start = time.time()
            sid = agent.session_id
            sname = agent.session_name
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
                has_response = bool(result_text and result_text.strip())

                await result_queue.put({
                    "session_id": sid,
                    "session_name": sname,
                    "role": role,
                    "responded": has_response,
                    "output": result_text.strip() if has_response else None,
                    "duration_ms": duration_ms,
                })

            except asyncio.TimeoutError:
                duration_ms = int((time.time() - session_start) * 1000)
                logger.warning("Chat broadcast timeout for session %s", sid)
                await result_queue.put({
                    "session_id": sid, "session_name": sname, "role": role,
                    "responded": False, "error": "Timeout", "duration_ms": duration_ms,
                })

            except asyncio.CancelledError:
                duration_ms = int((time.time() - session_start) * 1000)
                logger.warning("Chat broadcast cancelled for session %s", sid)
                await result_queue.put({
                    "session_id": sid, "session_name": sname, "role": role,
                    "responded": False, "error": "Cancelled", "duration_ms": duration_ms,
                })

            except Exception as e:
                duration_ms = int((time.time() - session_start) * 1000)
                logger.error("Chat broadcast error for session %s: %s", sid, e)
                await result_queue.put({
                    "session_id": sid, "session_name": sname, "role": role,
                    "responded": False, "error": str(e)[:200], "duration_ms": duration_ms,
                })

        # Launch all tasks
        tasks = [
            asyncio.create_task(_invoke_and_enqueue(agent))
            for agent in target_agents
        ]

        responded_count = 0
        total_count = len(tasks)
        completed_count = 0
        heartbeat_interval = 5.0  # seconds between keep-alive pings

        # Consume results as they arrive, with heartbeat to keep SSE alive.
        # NOTE: We use asyncio.wait() instead of asyncio.wait_for() because
        # wait_for cancels the underlying Queue.get() on timeout, which can
        # lose an item that was mid-dequeue.  With asyncio.wait(), the
        # get-task survives across heartbeat iterations.
        pending_get: asyncio.Task | None = None

        while completed_count < total_count:
            if pending_get is None:
                pending_get = asyncio.ensure_future(result_queue.get())

            done, _ = await asyncio.wait(
                {pending_get}, timeout=heartbeat_interval,
            )

            if not done:
                # No result yet — send heartbeat to keep SSE connection alive
                elapsed = int(time.time() - start_time)
                yield _sse_event("heartbeat", {"elapsed_s": elapsed})
                continue  # pending_get is still alive — reuse next iteration

            # A result arrived
            try:
                result = pending_get.result()
            except Exception as e:
                logger.error("Queue get error: %s", e)
                pending_get = None
                completed_count += 1
                continue

            pending_get = None
            completed_count += 1

            if result.get("responded") and result.get("output"):
                # Save agent message and stream it
                try:
                    saved_msg = store.add_message(room_id, {
                        "type": "agent",
                        "content": result["output"],
                        "session_id": result["session_id"],
                        "session_name": result["session_name"],
                        "role": result["role"],
                        "duration_ms": result["duration_ms"],
                    })
                    responded_count += 1
                    yield _sse_event("agent_response", saved_msg)
                except Exception as e:
                    logger.error("Failed to save agent message: %s", e)
                    yield _sse_event("agent_error", {
                        "session_id": result["session_id"],
                        "session_name": result["session_name"],
                        "role": result["role"],
                        "error": f"Save failed: {e}",
                    })
            elif result.get("error"):
                yield _sse_event("agent_error", {
                    "session_id": result["session_id"],
                    "session_name": result["session_name"],
                    "role": result["role"],
                    "error": result["error"],
                    "duration_ms": result.get("duration_ms"),
                })
            else:
                # Skipped (not relevant) — no output, no error
                yield _sse_event("agent_skip", {
                    "session_id": result["session_id"],
                    "session_name": result["session_name"],
                    "role": result["role"],
                    "duration_ms": result.get("duration_ms"),
                })

        # Ensure all tasks are done (prevent dangling)
        await asyncio.gather(*tasks, return_exceptions=True)

        # 4. Summary
        total_duration_ms = int((time.time() - start_time) * 1000)
        try:
            summary_msg = store.add_message(room_id, {
                "type": "system",
                "content": f"{responded_count}/{total_count} sessions responded ({total_duration_ms / 1000:.1f}s)",
            })
            yield _sse_event("summary", summary_msg)
        except Exception as e:
            logger.error("Failed to save summary: %s", e)

        logger.info(
            "Room %s: broadcast complete: %d/%d responded (%dms)",
            room_id, responded_count, total_count, total_duration_ms,
        )

        yield _sse_event("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
