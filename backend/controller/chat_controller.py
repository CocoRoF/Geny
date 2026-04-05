"""
Chat Controller

Provides:
  - Chat room CRUD (create, list, get, update, delete)
  - Fire-and-forget broadcast — agent processing runs in background, results
    are persisted independently of client connection
  - Reconnectable SSE event stream — clients subscribe to new messages and
    can reconnect at any time without losing data
  - Message history persistence — all messages are stored and restorable
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from logging import getLogger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from service.chat.conversation_store import get_chat_store
from service.langgraph import get_agent_session_manager
from service.execution.agent_executor import (
    execute_command,
    is_executing,
    get_execution_holder,
    AlreadyExecutingError,
    AgentNotFoundError,
    AgentNotAliveError,
)

logger = getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

agent_manager = get_agent_session_manager()


# ============================================================================
# Background Broadcast Tracking
# ============================================================================

@dataclass
class AgentExecutionState:
    """Tracks an individual agent's execution state during a broadcast."""
    session_id: str
    session_name: str
    role: str
    status: str = "pending"  # pending | executing | completed | failed | queued
    thinking_preview: Optional[str] = None  # Latest log message (1 line)
    started_at: Optional[float] = None
    last_activity_at: Optional[float] = None  # monotonic timestamp of last log entry
    last_tool_name: Optional[str] = None  # tool name if last log was TOOL level
    recent_logs: List[Dict[str, Any]] = field(default_factory=list)  # ringbuffer of recent log entries
    log_cursor: int = 0  # total log entries seen (for client-side dedup)
    recent_logs: List[Dict[str, Any]] = field(default_factory=list)  # ringbuffer of recent log entries
    log_cursor: int = 0  # total log entries seen (for client-side dedup)


@dataclass
class BroadcastState:
    """Tracks a single in-flight broadcast."""
    broadcast_id: str
    room_id: str
    total: int
    completed: int = 0
    responded: int = 0
    finished: bool = False
    cancelled: bool = False
    started_at: float = field(default_factory=time.time)
    # NEW: per-agent execution states
    agent_states: Dict[str, AgentExecutionState] = field(default_factory=dict)


# room_id → BroadcastState for the currently active broadcast
_active_broadcasts: Dict[str, BroadcastState] = {}
# room_id → asyncio.Event signalling "new message was saved"
_room_new_msg_events: Dict[str, asyncio.Event] = {}


def _extract_thinking_preview(entry) -> Optional[str]:
    """Extract a 1-line thinking preview from a log entry.

    Prioritizes GRAPH events (node enter/exit) and TOOL events.
    Returns None if the entry is not interesting for preview.
    """
    level = entry.level.value if hasattr(entry.level, "value") else str(entry.level)
    meta = entry.metadata or {}

    # Skip command/response entries (too verbose or final)
    if level in ("COMMAND", "RESPONSE"):
        return None

    # GRAPH events — show node execution
    if level == "GRAPH":
        event_type = meta.get("event_type", "")
        node = meta.get("node_name", "")
        if event_type == "node_enter" and node:
            return f"→ {node}"
        if event_type == "node_exit" and node:
            preview = meta.get("output_preview", "")[:60]
            if preview:
                return f"✓ {node}: {preview}"
            return f"✓ {node}"
        if event_type == "edge_decision":
            decision = meta.get("decision", "")
            return f"⋯ {decision}" if decision else None
        return None

    # TOOL events — show tool invocation
    if level == "TOOL":
        tool_name = meta.get("tool_name", "")
        if tool_name:
            return f"🔧 {tool_name}"
        return None

    # TOOL_RES — show brief result
    if level == "TOOL_RES":
        tool_name = meta.get("tool_name", "")
        preview = meta.get("preview", "")[:50]
        if tool_name and preview:
            return f"🔧 {tool_name}: {preview}"
        return None

    # INFO/DEBUG — use message directly (truncated)
    if level in ("INFO", "DEBUG"):
        msg = entry.message[:80] if entry.message else None
        return msg

    return None


def _notify_room(room_id: str):
    """Signal all SSE listeners that a new message appeared for this room."""
    ev = _room_new_msg_events.get(room_id)
    if ev:
        ev.set()


def _build_agent_progress_data(astate: AgentExecutionState) -> dict:
    """Build a single agent's progress dict with timing info."""
    now = time.time()
    now_mono = time.monotonic()
    data = {
        "session_id": astate.session_id,
        "session_name": astate.session_name,
        "role": astate.role,
        "status": astate.status,
        "thinking_preview": astate.thinking_preview,
    }
    if astate.started_at:
        data["elapsed_ms"] = int((now - astate.started_at) * 1000)
    if astate.last_activity_at:
        data["last_activity_ms"] = int((now_mono - astate.last_activity_at) * 1000)
    elif astate.started_at:
        # No log entries yet — use full elapsed as last_activity_ms
        data["last_activity_ms"] = int((now - astate.started_at) * 1000)
    if astate.recent_logs:
        data["recent_logs"] = astate.recent_logs
        data["log_cursor"] = astate.log_cursor
    if astate.last_tool_name:
        data["last_tool_name"] = astate.last_tool_name
    if astate.recent_logs:
        data["recent_logs"] = astate.recent_logs
        data["log_cursor"] = astate.log_cursor
    return data


def _get_room_event(room_id: str) -> asyncio.Event:
    """Get-or-create the notification event for a room."""
    if room_id not in _room_new_msg_events:
        _room_new_msg_events[room_id] = asyncio.Event()
    return _room_new_msg_events[room_id]


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
    cost_usd: Optional[float] = None
    file_changes: Optional[List[Dict[str, Any]]] = None
    meta: Optional[Dict[str, Any]] = None


class MessageListResponse(BaseModel):
    room_id: str
    messages: List[MessageResponse]
    total: int
    has_more: bool = False


# ── Broadcast models ──

class RoomBroadcastRequest(BaseModel):
    message: str = Field(..., description="Chat message to send")


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
async def get_room_messages(
    room_id: str,
    limit: int = 0,
    before: Optional[str] = None,
):
    """Get messages for a chat room with optional cursor-based pagination.

    Args:
        limit: Max messages to return. 0 = all (backwards compat).
        before: Message ID cursor — return only messages older than this.
    """
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    # Fetch one extra to detect whether more messages exist
    fetch_limit = (limit + 1) if limit > 0 else 0
    raw_messages = store.get_messages(room_id, limit=fetch_limit, before=before or "")

    has_more = False
    if limit > 0 and len(raw_messages) > limit:
        raw_messages = raw_messages[1:]  # drop the oldest extra row
        has_more = True

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
        has_more=has_more,
    )


@router.post("/messages/cleanup")
async def cleanup_old_messages():
    """Delete messages older than the configured retention period."""
    from service.config.sub_config.general.chat_config import ChatConfig
    cfg = ChatConfig.get_default_instance()
    if cfg.message_retention_days <= 0:
        return {"deleted": 0, "message": "Retention policy disabled (0 = keep forever)"}
    store = get_chat_store()
    deleted = store.cleanup_old_messages(cfg.message_retention_days)
    return {"deleted": deleted, "retention_days": cfg.message_retention_days}


# ============================================================================
# Room-Scoped Broadcast Endpoint (Fire-and-Forget)
# ============================================================================

def _sse_event(event_type: str, data: Any) -> str:
    """Format a single SSE event."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/rooms/{room_id}/broadcast")
async def broadcast_to_room(room_id: str, request: RoomBroadcastRequest):
    """
    Send a message to all sessions in a chat room.

    Core philosophy: **a chat room is just multi-command.**
    Each agent in the room receives the same message and executes it
    through the exact same ``execute_command`` path used by the
    command tab.  This guarantees identical session logging, cost
    tracking, auto-revival, and double-execution prevention.

    Processing is fire-and-forget — agent results are persisted in the
    background regardless of whether any client is connected.  Clients
    subscribe to live updates via GET /rooms/{room_id}/events.

    Returns the saved user message immediately.
    """
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    # 1. Save user message
    try:
        user_msg = store.add_message(room_id, {
            "type": "user",
            "content": request.message,
        })
    except Exception as e:
        logger.error("Failed to save user message: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="메시지 저장에 실패했습니다")

    _notify_room(room_id)

    # 2. Resolve target session IDs and display info
    #    Auto-revival & execution are handled by execute_command — no need here.
    room_session_ids = list(room["session_ids"])
    if not room_session_ids:
        store.add_message(room_id, {
            "type": "system",
            "content": "No sessions in this room.",
        })
        _notify_room(room_id)
        return {
            "user_message": user_msg,
            "broadcast_id": None,
            "target_count": 0,
        }

    # Collect display metadata (best-effort; executor handles the real work)
    all_agents = agent_manager.list_agents()
    agent_info: Dict[str, Dict[str, str]] = {}
    for a in all_agents:
        if a.session_id in set(room_session_ids):
            agent_info[a.session_id] = {
                "session_name": a.session_name,
                "role": a.role.value if hasattr(a.role, "value") else str(a.role),
            }

    # 3. Create broadcast state and launch background processing
    broadcast_id = str(uuid.uuid4())

    # Initialize per-agent states
    initial_agent_states: Dict[str, AgentExecutionState] = {}
    for sid in room_session_ids:
        info = agent_info.get(sid, {})
        initial_agent_states[sid] = AgentExecutionState(
            session_id=sid,
            session_name=info.get("session_name", sid[:8]),
            role=info.get("role", "worker"),
            status="pending",
        )

    broadcast_state = BroadcastState(
        broadcast_id=broadcast_id,
        room_id=room_id,
        total=len(room_session_ids),
        agent_states=initial_agent_states,
    )
    _active_broadcasts[room_id] = broadcast_state

    # Notify SSE clients so they immediately see initial agent states
    _notify_room(room_id)

    logger.info(
        "Room %s: broadcast %s → %d sessions: %s",
        room_id, broadcast_id, len(room_session_ids), request.message[:80],
    )

    # Fire-and-forget background task
    asyncio.create_task(
        _run_broadcast(
            room_id, broadcast_id, broadcast_state,
            room_session_ids, agent_info, request.message, store,
        )
    )

    return {
        "user_message": user_msg,
        "broadcast_id": broadcast_id,
        "target_count": len(room_session_ids),
    }


@router.post("/rooms/{room_id}/broadcast/cancel")
async def cancel_broadcast(room_id: str):
    """Cancel an active broadcast, stopping pending and running agents."""
    bstate = _active_broadcasts.get(room_id)
    if not bstate or bstate.finished:
        raise HTTPException(status_code=404, detail="No active broadcast for this room")

    if bstate.cancelled:
        return {"status": "already_cancelled", "broadcast_id": bstate.broadcast_id}

    bstate.cancelled = True

    # Stop agents that are currently executing
    cancelled_count = 0
    for sid, astate in bstate.agent_states.items():
        if astate.status == "executing":
            try:
                from service.execution.agent_executor import stop_execution
                stopped = await stop_execution(sid)
                if stopped:
                    astate.status = "cancelled"
                    cancelled_count += 1
            except Exception as e:
                logger.warning("Failed to stop agent %s during broadcast cancel: %s", sid, e)
        elif astate.status in ("pending", "queued"):
            astate.status = "cancelled"
            cancelled_count += 1

    _notify_room(room_id)

    return {
        "status": "cancelled",
        "broadcast_id": bstate.broadcast_id,
        "cancelled_agents": cancelled_count,
    }


async def _run_broadcast(
    room_id: str,
    broadcast_id: str,
    state: BroadcastState,
    session_ids: List[str],
    agent_info: Dict[str, Dict[str, str]],
    message: str,
    store,
):
    """
    Background task — runs one command per agent and persists results.

    This is the concrete expression of "chat room = multi-command".
    Each agent goes through the **exact same** ``execute_command`` path
    as the command tab, inheriting:
      - session logging  (log_command / log_response)
      - cost persistence (increment_cost)
      - auto-revival     (agent.revive)
      - double-execution prevention
      - timeout handling
    """
    from service.logging.session_logger import get_session_logger

    start_time = time.time()

    async def _invoke_one(session_id: str):
        info = agent_info.get(session_id, {})
        sname = info.get("session_name", session_id[:8])
        role = info.get("role", "unknown")

        # Get per-agent state tracker
        agent_state = state.agent_states.get(session_id)

        # ── Cancellation guard ──
        if state.cancelled:
            if agent_state:
                agent_state.status = "cancelled"
            state.completed += 1
            _notify_room(room_id)
            return

        if agent_state:
            agent_state.status = "executing"
            agent_state.started_at = time.time()
            _notify_room(room_id)

        # Start log-polling task to capture thinking preview
        log_poll_task: Optional[asyncio.Task] = None
        session_logger = get_session_logger(session_id, create_i + recent_logs."""
                _MAX_RECENT_LOGS = 20
                cache_cursor = session_logger.get_cache_length()  # Start from current position
                try:
                    while True:
                        await asyncio.sleep(0.2)
                        new_entries, cache_cursor = session_logger.get_cache_entries_since(cache_cursor)
                        for entry in new_entries:
                            # Extract meaningful preview from log entry
                            preview = _extract_thinking_preview(entry)
                            if preview:
                                agent_state.thinking_preview = preview
                                agent_state.last_activity_at = time.monotonic()
                                _notify_room(room_id)
                            # Track last tool name for tool execution detection
                            level = entry.level.value if hasattr(entry.level, "value") else str(entry.level)
                            meta = entry.metadata or {}
                            if level in ("TOOL", "TOOL_RES"):
                                agent_state.last_tool_name = meta.get("tool_name")
                            elif level not in ("DEBUG", "INFO"):
                                agent_state.last_tool_name = None
                            # Accumulate recent logs for client-side display
                            if level not in ("DEBUG", "COMMAND", "RESPONSE"):
                                log_entry = {
                                    "level": level,
                                    "message": (entry.message or "")[:120],
                                    "ts": entry.timestamp if hasattr(entry, "timestamp") else None,
                                }
                                if meta.get("tool_name"):
                                    log_entry["tool_name"] = meta["tool_name"]
                                if meta.get("node_name"):
                                    log_entry["node_name"] = meta["node_name"]
                                agent_state.recent_logs.append(log_entry)
                                # Keep only last N entries
                                if len(agent_state.recent_logs) > _MAX_RECENT_LOGS:
                                    agent_state.recent_logs = agent_state.recent_logs[-_MAX_RECENT_LOGS:]
                                agent_state.log_cursor += 1tion detection
                            level = entry.level.value if hasattr(entry.level, "value") else str(entry.level)
                            meta = entry.metadata or {}
                            if level in ("TOOL", "TOOL_RES"):
                                agent_state.last_tool_name = meta.get("tool_name")
                            elif level not in ("DEBUG", "INFO"):
                                agent_state.last_tool_name = None
                            # Accumulate recent logs for client-side display
                            if level not in ("DEBUG", "COMMAND", "RESPONSE"):
                                log_entry = {
                                    "level": level,
                                    "message": (entry.message or "")[:120],
                                    "ts": entry.timestamp if hasattr(entry, "timestamp") else None,
                                }
                                if meta.get("tool_name"):
                                    log_entry["tool_name"] = meta["tool_name"]
                                if meta.get("node_name"):
                                    log_entry["node_name"] = meta["node_name"]
                                agent_state.recent_logs.append(log_entry)
                                # Keep only last N entries
                                if len(agent_state.recent_logs) > _MAX_RECENT_LOGS:
                                    agent_state.recent_logs = agent_state.recent_logs[-_MAX_RECENT_LOGS:]
                                agent_state.log_cursor += 1
                except asyncio.CancelledError:
                    pass

            log_poll_task = asyncio.create_task(_poll_logs())

        try:
            # ── THE core call — with broadcast context ──
            result = await execute_command(
                session_id=session_id,
                prompt=message,
                is_chat_message=True,
            )

            if result.success and result.output and result.output.strip():
                msg_data: Dict[str, Any] = {
                    "type": "agent",
                    "content": result.output.strip(),
                    "session_id": session_id,
                    "session_name": sname,
                    "role": role,
                    "duration_ms": result.duration_ms,
                    "cost_usd": result.cost_usd,
                }
                # Attach file changes from this execution's log entries
                if session_logger:
                    fc = session_logger.extract_file_changes_from_cache(pre_exec_cursor)
                    if fc:
                        msg_data["file_changes"] = fc
                store.add_message(room_id, msg_data)
                state.responded += 1
                if agent_state:
                    agent_state.status = "completed"
                _notify_room(room_id)
            elif not result.success:
                # Execution failed (timeout, error, etc.) — show in room
                store.add_message(room_id, {
                    "type": "system",
                    "content": f"{sname}: {result.error or 'Unknown error'}",
                })
                if agent_state:
                    agent_state.status = "failed"
                _notify_room(room_id)
            else:
                logger.debug("Session %s skipped (no output)", session_id)
                if agent_state:
                    agent_state.status = "completed"

        except AlreadyExecutingError:
            # Agent is busy with a real (non-trigger) execution.
            # Triggers are auto-preempted by execute_command, so if we
            # reach here the agent is handling real work.  Queue the
            # user message in the inbox — it will be processed
            # automatically after the current execution finishes
            # (via post-execution inbox drain).
            try:
                from service.chat.inbox import get_inbox_manager
                inbox = get_inbox_manager()
                inbox.deliver(
                    target_session_id=session_id,
                    content=f"[USER_MESSAGE from chat room {room_id}]\n{message}",
                    sender_name="User",
                )
                store.add_message(room_id, {
                    "type": "system",
                    "content": f"{sname}: 현재 작업 완료 후 처리합니다…",
                    "meta": {"busy_reason": "executing", "queued": True},
                })
                if agent_state:
                    agent_state.status = "queued"
            except Exception as inbox_err:
                logger.error(
                    "Failed to queue user message in inbox for %s: %s",
                    session_id, inbox_err, exc_info=True,
                )
                # Store in DLQ for later recovery
                try:
                    inbox.send_to_dlq(
                        target_session_id=session_id,
                        content=f"[USER_MESSAGE from chat room {room_id}]\n{message}",
                        sender_name="User",
                        reason="inbox_delivery_failed",
                        original_error=str(inbox_err),
                    )
                except Exception:
                    logger.error("DLQ fallback also failed for %s", session_id, exc_info=True)
                store.add_message(room_id, {
                    "type": "system",
                    "content": f"{sname}: 현재 다른 작업 중이며, 메시지 대기열 저장에 실패했습니다",
                })
                if agent_state:
                    agent_state.status = "failed"
            _notify_room(room_id)

        except AgentNotFoundError:
            store.add_message(room_id, {
                "type": "system",
                "content": f"{sname}: Session not found",
            })
            if agent_state:
                agent_state.status = "failed"
            _notify_room(room_id)

        except AgentNotAliveError as e:
            logger.warning("Agent not alive for session %s: %s", session_id, e)
            store.add_message(room_id, {
                "type": "system",
                "content": f"{sname}: 에이전트를 실행할 수 없습니다 (세션이 비활성 상태)",
            })
            if agent_state:
                agent_state.status = "failed"
            _notify_room(room_id)

        except Exception as e:
            logger.error("Broadcast error for session %s: %s", session_id, e, exc_info=True)
            store.add_message(room_id, {
                "type": "system",
                "content": f"{sname}: 실행 중 오류가 발생했습니다",
            })
            if agent_state:
                agent_state.status = "failed"
            _notify_room(room_id)

        finally:
            state.completed += 1
            # Cancel log polling
            if log_poll_task:
                log_poll_task.cancel()
                try:
                    await log_poll_task
                except asyncio.CancelledError:
                    pass

    # Launch all concurrently — each is an independent command execution
    tasks = [asyncio.create_task(_invoke_one(sid)) for sid in session_ids]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Summary
    total_duration_ms = int((time.time() - start_time) * 1000)
    try:
        store.add_message(room_id, {
            "type": "system",
            "content": f"{state.responded}/{state.total} sessions responded ({total_duration_ms / 1000:.1f}s)",
        })
        _notify_room(room_id)
    except Exception as e:
        logger.error("Failed to save broadcast summary: %s", e)

    state.finished = True

    logger.info(
        "Room %s: broadcast %s complete: %d/%d responded (%dms)",
        room_id, broadcast_id, state.responded, state.total, total_duration_ms,
    )

    # Cleanup broadcast state after a delay (allow clients to read final state).
    # Uses broadcast_id guard to prevent accidentally deleting a newer broadcast's state.
    from service.config.sub_config.general.chat_config import ChatConfig
    _chat_cfg = ChatConfig.get_default_instance()
    await asyncio.sleep(_chat_cfg.broadcast_cleanup_delay_s)
    current_state = _active_broadcasts.get(room_id)
    if current_state is not None and current_state.broadcast_id == broadcast_id:
        del _active_broadcasts[room_id]


# ============================================================================
# Reconnectable SSE Event Stream
# ============================================================================

@router.get("/rooms/{room_id}/events")
async def room_event_stream(
    room_id: str,
    after: Optional[str] = Query(None, description="Last seen message ID — only newer messages will be sent"),
):
    """
    SSE stream of new messages in a room.

    - Reconnectable: pass `after=<last_msg_id>` to resume from where you left off.
    - Sends `message` events for each new message (user, agent, system).
    - Sends `broadcast_status` events with progress info.
    - Sends `heartbeat` events every 5s to keep the connection alive.
    - Sends `broadcast_done` when all agents have finished.

    The stream stays open until the client disconnects.
    """
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    async def event_generator():
        last_seen_id = after
        room_event = _get_room_event(room_id)
        from service.config.sub_config.general.chat_config import ChatConfig
        _chat_cfg = ChatConfig.get_default_instance()
        heartbeat_interval = float(_chat_cfg.sse_heartbeat_interval_s)

        # On initial connect: send any messages newer than `after`
        if last_seen_id:
            missed = _get_messages_after(store, room_id, last_seen_id)
            for msg in missed:
                yield _sse_event("message", msg)
                last_seen_id = msg["id"]
        else:
            # No reference point: anchor to the current latest message
            # so that any messages added after this moment are detected.
            all_msgs = store.get_messages(room_id)
            if all_msgs:
                last_seen_id = all_msgs[-1]["id"]

        # Send current broadcast status if active
        bstate = _active_broadcasts.get(room_id)
        if bstate and not bstate.finished:
            yield _sse_event("broadcast_status", {
                "broadcast_id": bstate.broadcast_id,
                "total": bstate.total,
                "completed": bstate.completed,
                "responded": bstate.responded,
                "finished": False,
            })
            # Send initial per-agent progress
            if bstate.agent_states:
                agent_progress_list = [
                    _build_agent_progress_data(astate)
                    for astate in bstate.agent_states.values()
                ]
                yield _sse_event("agent_progress", {
                    "broadcast_id": bstate.broadcast_id,
                    "agents": agent_progress_list,
                })

        # Main loop: wait for new messages or heartbeat
        while True:
            room_event.clear()

            # Wait for notification or timeout (heartbeat)
            try:
                await asyncio.wait_for(room_event.wait(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                return

            # Check for new messages
            if last_seen_id is not None:
                new_msgs = _get_messages_after(store, room_id, last_seen_id)
            else:
                # No anchor yet (connected to empty room) — get all messages
                new_msgs = store.get_messages(room_id)
            for msg in new_msgs:
                yield _sse_event("message", msg)
                last_seen_id = msg["id"]

            # Broadcast status update
            bstate = _active_broadcasts.get(room_id)
            if bstate:
                # Send overall progress
                yield _sse_event("broadcast_status", {
                    "broadcast_id": bstate.broadcast_id,
                    "total": bstate.total,
                    "completed": bstate.completed,
                    "responded": bstate.responded,
                    "finished": bstate.finished,
                })

                # Send per-agent progress if not finished
                if not bstate.finished and bstate.agent_states:
                    agent_progress_list = [
                        _build_agent_progress_data(astate)
                        for astate in bstate.agent_states.values()
                    ]
                    yield _sse_event("agent_progress", {
                        "broadcast_id": bstate.broadcast_id,
                        "agents": agent_progress_list,
                    })

                if bstate.finished:
                    yield _sse_event("broadcast_done", {
                        "broadcast_id": bstate.broadcast_id,
                        "total": bstate.total,
                        "responded": bstate.responded,
                    })
            elif not new_msgs:
                # No active broadcast, no new messages — just heartbeat
                yield _sse_event("heartbeat", {"ts": time.time()})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _get_messages_after(store, room_id: str, after_id: Optional[str]) -> List[dict]:
    """Return messages in the room that come after the given message ID."""
    all_msgs = store.get_messages(room_id)
    if not after_id:
        return []  # No reference point — return nothing (history was loaded separately)

    # Find the index of after_id
    idx = -1
    for i, m in enumerate(all_msgs):
        if m.get("id") == after_id:
            idx = i
            break

    if idx == -1:
        # after_id not found — return all messages (client may have stale reference)
        return all_msgs

    return all_msgs[idx + 1:]
