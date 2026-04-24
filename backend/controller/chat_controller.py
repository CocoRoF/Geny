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
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from service.chat.conversation_store import get_chat_store
from service.executor import get_agent_session_manager
from service.utils.text_sanitizer import sanitize_for_display
from service.execution.agent_executor import (
    execute_command,
    is_executing,
    get_execution_holder,
    stop_execution,
    AlreadyExecutingError,
    AgentNotFoundError,
    AgentNotAliveError,
)

logger = getLogger(__name__)


# Absolute path of the on-disk upload root that backs ``/static/uploads/...``
# URLs emitted by ``controller/upload_controller``. Kept here (not in
# ``service/executor``) because the URL↔path mapping is intrinsically a
# chat-layer concern: it converts the *web* URL the frontend sees into a
# local-filesystem reference the executor pipeline can read. Everything
# downstream of this boundary (``geny-executor`` s01 normalizer) handles
# ``file://`` URIs in a vendor-agnostic way.
_UPLOAD_ROOT: Path = Path(__file__).resolve().parent.parent / "static" / "uploads"


def _rewrite_local_attachment_url(att: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite a server-relative upload URL to a ``file://`` URI.

    The executor's ``MultimodalNormalizer`` knows how to inline
    ``file://`` URIs and absolute filesystem paths as base64 image
    sources, but it has no way to resolve Geny's web-layer
    ``/static/uploads/<shard>/<sha>.<ext>`` convention on its own. We
    perform that single mapping here so the rest of the pipeline only
    sees vendor-neutral references.

    Returns a *new* dict; never mutates the input. Attachments that are
    already ``data``/``https://``/``file://`` are passed through.
    """
    out = dict(att)
    url = (out.get("url") or "").strip()
    if not url or not url.startswith("/static/uploads/"):
        return out
    rel = url[len("/static/uploads/") :]
    abs_path = (_UPLOAD_ROOT / rel).resolve()
    out["url"] = abs_path.as_uri()  # "file:///..."
    return out

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
    streaming_text: Optional[str] = None  # Sanitized view of streaming_raw — what the UI renders
    streaming_raw: Optional[str] = None  # Raw accumulator: next token may complete a partial tag, so strip only after concatenation
    started_at: Optional[float] = None
    last_activity_at: Optional[float] = None  # monotonic timestamp of last log entry
    last_tool_name: Optional[str] = None  # tool name if last log was TOOL level
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


# room_id -> BroadcastState for the currently active broadcast
_active_broadcasts: Dict[str, BroadcastState] = {}
# room_id -> asyncio.Event signalling "new message was saved"
_room_new_msg_events: Dict[str, asyncio.Event] = {}


def _extract_thinking_preview(entry) -> Optional[str]:
    """Extract a 1-line thinking preview from a log entry.

    Prioritizes STAGE events (stage enter/exit/bypass/error) and TOOL
    events. Legacy ``GRAPH`` rows with old ``node_enter``/``node_exit``
    event_types render the same way so older sessions still surface a
    coherent preview.
    """
    level = entry.level.value if hasattr(entry.level, "value") else str(entry.level)
    meta = entry.metadata or {}

    # Skip command/response entries (too verbose or final)
    if level in ("COMMAND", "RESPONSE"):
        return None

    # STAGE events (new) + GRAPH events (legacy) — same visual treatment.
    if level in ("STAGE", "GRAPH"):
        event_type = meta.get("event_type", "")
        display = meta.get("stage_display_name") or meta.get("node_name", "")
        iteration = meta.get("iteration")
        iter_suffix = f" (iter {iteration})" if iteration else ""
        if event_type in ("stage_enter", "node_enter") and display:
            return f"\u2192 {display}{iter_suffix}"
        if event_type in ("stage_exit", "node_exit") and display:
            preview = (meta.get("output_preview") or "")[:60]
            if preview:
                return f"\u2713 {display}: {preview}"
            return f"\u2713 {display}{iter_suffix}"
        if event_type == "stage_bypass" and display:
            return f"\u2298 {display} (skipped)"
        if event_type == "stage_error" and display:
            return f"\u2717 {display}: error"
        if event_type == "edge_decision":
            decision = meta.get("decision", "")
            return f"\u22ef {decision}" if decision else None
        return None

    # TOOL events -- show tool invocation
    if level == "TOOL":
        tool_name = meta.get("tool_name", "")
        if tool_name:
            return f"\U0001f527 {tool_name}"
        return None

    # TOOL_RES -- show brief result
    if level == "TOOL_RES":
        tool_name = meta.get("tool_name", "")
        preview = meta.get("preview", "")[:50]
        if tool_name and preview:
            return f"\U0001f527 {tool_name}: {preview}"
        return None

    # INFO/DEBUG -- use message directly (truncated)
    if level in ("INFO", "DEBUG"):
        msg = entry.message[:80] if entry.message else None
        return msg

    return None


def _notify_room(room_id: str):
    """Signal all SSE listeners that a new message appeared for this room."""
    ev = _room_new_msg_events.get(room_id)
    if ev:
        ev.set()
        logger.debug("[Broadcast:%s] room event notified (listeners present)", room_id[:8])
    else:
        logger.debug("[Broadcast:%s] room event notify skipped (no listeners)", room_id[:8])


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
        "streaming_text": astate.streaming_text,
    }
    if astate.started_at:
        data["elapsed_ms"] = int((now - astate.started_at) * 1000)
    if astate.last_activity_at:
        data["last_activity_ms"] = int((now_mono - astate.last_activity_at) * 1000)
    elif astate.started_at:
        # No log entries yet -- use full elapsed as last_activity_ms
        data["last_activity_ms"] = int((now - astate.started_at) * 1000)
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

# -- Room models --

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


# -- Message models --

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
    attachments: Optional[List[Dict[str, Any]]] = None
    meta: Optional[Dict[str, Any]] = None


class MessageListResponse(BaseModel):
    room_id: str
    messages: List[MessageResponse]
    total: int
    has_more: bool = False


# -- Broadcast models --

class BroadcastAttachment(BaseModel):
    """Reference to an uploaded file (see ``upload_controller``).

    The frontend uploads files via ``POST /api/uploads`` first and only
    sends back the lightweight metadata here. The actual bytes never
    travel through the broadcast endpoint, keeping JSON payloads small.

    Either ``attachment_id`` (preferred) or ``url`` is required so the
    backend can locate the stored file. ``data`` (inline base64) is
    accepted for tiny pasted images that bypass the upload step.
    """

    kind: str = Field(..., description="image | file")
    name: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[int] = None
    sha256: Optional[str] = None
    attachment_id: Optional[str] = None  # sha256 hex from POST /api/uploads
    url: Optional[str] = None             # /static/uploads/.../<sha>.<ext>
    data: Optional[str] = None            # base64 fallback (small inline pastes)


class RoomBroadcastRequest(BaseModel):
    message: str = Field("", description="Chat message to send (may be empty if attachments present)")
    attachments: Optional[List[BroadcastAttachment]] = Field(
        default=None,
        description="Optional list of image/file references uploaded via /api/uploads.",
    )


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
        before: Message ID cursor -- return only messages older than this.
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

@router.post("/rooms/{room_id}/broadcast")
async def broadcast_to_room(room_id: str, request: RoomBroadcastRequest):
    """
    Send a message to all sessions in a chat room.

    Core philosophy: a chat room is just multi-command.
    Each agent in the room receives the same message and executes it
    through the exact same execute_command path used by the command tab.
    This guarantees identical session logging, cost tracking,
    auto-revival, and double-execution prevention.

    Processing is fire-and-forget. Agent results are persisted in the
    background regardless of whether any client is connected.  Clients
    subscribe to live updates via GET /rooms/{room_id}/events.

    Returns the saved user message immediately.
    """
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    # Reject empty broadcasts: must have either text or at least one attachment.
    has_attachments = bool(request.attachments)
    if not request.message.strip() and not has_attachments:
        raise HTTPException(status_code=400, detail="Message or attachments required")

    # Materialize attachments to plain dicts for the background runner —
    # Pydantic models don't survive ``asyncio.create_task`` boundaries cleanly
    # when executors thread them through ``**invoke_kwargs``.
    attachments_payload: Optional[List[Dict[str, Any]]] = None
    if has_attachments:
        attachments_payload = [
            _rewrite_local_attachment_url(a.model_dump(exclude_none=True))
            for a in request.attachments
        ]

    # 1. Save user message
    try:
        user_msg_data: Dict[str, Any] = {
            "type": "user",
            "content": request.message,
        }
        if attachments_payload:
            # Store attachment metadata on the user turn for replay /
            # rendering. Raw bytes are NOT stored here — only the URL
            # / attachment_id references that point back at
            # ``backend/static/uploads``.
            user_msg_data["attachments"] = attachments_payload
        user_msg = store.add_message(room_id, user_msg_data)
    except Exception as e:
        logger.error("Failed to save user message: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="\uba54\uc2dc\uc9c0 \uc800\uc7a5\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4")

    _notify_room(room_id)

    # 2. Resolve target session IDs and display info
    #    Auto-revival & execution are handled by execute_command -- no need here.
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

    # 3. Cancel any in-flight broadcast for this room before starting a new one.
    #    Without this, _active_broadcasts[room_id] would be silently overwritten,
    #    causing the old broadcast's state to be lost and its broadcast_done event
    #    to never reach clients.
    existing_broadcast = _active_broadcasts.get(room_id)
    if existing_broadcast and not existing_broadcast.finished:
        logger.warning(
            "Room %s: cancelling previous broadcast %s (still in-flight) before starting new one",
            room_id[:8], existing_broadcast.broadcast_id[:8],
        )
        existing_broadcast.cancelled = True
        # Best-effort stop of executing agents from the old broadcast
        for sid, astate in existing_broadcast.agent_states.items():
            if astate.status == "executing":
                try:
                    stopped = await stop_execution(sid)
                    if stopped:
                        astate.status = "cancelled"
                except Exception as cancel_err:
                    logger.debug(
                        "Room %s: failed to stop agent %s during auto-cancel: %s",
                        room_id[:8], sid[:8], cancel_err,
                    )
            elif astate.status in ("pending", "queued"):
                astate.status = "cancelled"
        existing_broadcast.finished = True
        _notify_room(room_id)

    # Create broadcast state and launch background processing
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
        "Room %s: broadcast %s -> %d sessions: %s",
        room_id, broadcast_id, len(room_session_ids), request.message[:80],
    )

    # Fire-and-forget background task
    asyncio.create_task(
        _run_broadcast(
            room_id, broadcast_id, broadcast_state,
            room_session_ids, agent_info, request.message, store,
            attachments=attachments_payload,
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
    *,
    attachments: Optional[List[Dict[str, Any]]] = None,
):
    """
    Background task: runs one command per agent and persists results.

    This is the concrete expression of "chat room = multi-command".
    Each agent goes through the exact same execute_command path
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

        logger.info(
            "[Broadcast:%s] _invoke_one started for session=%s (%s, role=%s)",
            room_id[:8], session_id[:8], sname, role,
        )

        # Get per-agent state tracker
        agent_state = state.agent_states.get(session_id)

        # Cancellation guard
        if state.cancelled:
            logger.info("[Broadcast:%s] session=%s skipped (broadcast cancelled)", room_id[:8], session_id[:8])
            if agent_state:
                agent_state.status = "cancelled"
            state.completed += 1
            _notify_room(room_id)
            return

        if agent_state:
            agent_state.status = "executing"
            agent_state.started_at = time.time()
            logger.debug("[Broadcast:%s] session=%s status -> executing", room_id[:8], session_id[:8])
            _notify_room(room_id)

        # Start log-polling task to capture thinking preview
        log_poll_task: Optional[asyncio.Task] = None
        session_logger = get_session_logger(session_id, create_if_missing=False)
        pre_exec_cursor = session_logger.get_cache_length() if session_logger else 0

        if session_logger and agent_state:
            _MAX_RECENT_LOGS = 20

            async def _poll_logs():
                """Poll session logs and update thinking_preview, streaming_text, recent_logs."""
                cache_cursor = session_logger.get_cache_length()
                had_new = False
                try:
                    while True:
                        await asyncio.sleep(0.05)  # 50ms polling for token-level streaming
                        new_entries, cache_cursor = session_logger.get_cache_entries_since(cache_cursor)
                        if not new_entries:
                            continue

                        had_new = False
                        for entry in new_entries:
                            level = entry.level.value if hasattr(entry.level, "value") else str(entry.level)
                            meta = entry.metadata or {}

                            # Token-level streaming: accumulate STREAM entries
                            if level == "STREAM":
                                raw = (agent_state.streaming_raw or "") + (entry.message or "")
                                agent_state.streaming_raw = raw
                                agent_state.streaming_text = sanitize_for_display(raw)
                                agent_state.last_activity_at = time.monotonic()
                                had_new = True
                                continue

                            # Extract meaningful preview from log entry
                            preview = _extract_thinking_preview(entry)
                            if preview:
                                agent_state.thinking_preview = preview
                                agent_state.last_activity_at = time.monotonic()
                                had_new = True

                            # Track last tool name
                            if level in ("TOOL", "TOOL_RES"):
                                agent_state.last_tool_name = meta.get("tool_name")
                            elif level not in ("DEBUG", "INFO", "STREAM"):
                                agent_state.last_tool_name = None

                            # Accumulate recent logs (exclude noisy levels)
                            if level not in ("DEBUG", "COMMAND", "RESPONSE", "STREAM"):
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
                                if len(agent_state.recent_logs) > _MAX_RECENT_LOGS:
                                    agent_state.recent_logs = agent_state.recent_logs[-_MAX_RECENT_LOGS:]
                                agent_state.log_cursor += 1

                        if had_new:
                            _notify_room(room_id)

                except asyncio.CancelledError:
                    pass

            log_poll_task = asyncio.create_task(_poll_logs())

        try:
            # THE core call -- with broadcast context
            logger.info(
                "[Broadcast:%s] calling execute_command for session=%s, prompt=%s",
                room_id[:8], session_id[:8], message[:60],
            )
            result = await execute_command(
                session_id=session_id,
                prompt=message,
                is_chat_message=True,
                attachments=attachments,
            )
            logger.info(
                "[Broadcast:%s] execute_command returned for session=%s: success=%s, output_len=%d, duration=%dms, cost=%s",
                room_id[:8], session_id[:8], result.success,
                len(result.output or ""), result.duration_ms, result.cost_usd,
            )

            cleaned_output = sanitize_for_display(result.output) if result.success else ""
            if cleaned_output:
                msg_data: Dict[str, Any] = {
                    "type": "agent",
                    "content": cleaned_output,
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
                        logger.debug("[Broadcast:%s] session=%s: %d file changes", room_id[:8], session_id[:8], len(fc))
                store.add_message(room_id, msg_data)
                state.responded += 1
                if agent_state:
                    agent_state.status = "completed"
                logger.info(
                    "[Broadcast:%s] session=%s: agent message saved (responded=%d/%d)",
                    room_id[:8], session_id[:8], state.responded, state.total,
                )
                _notify_room(room_id)
            elif not result.success:
                # Execution failed (timeout, error, etc.)
                logger.warning(
                    "[Broadcast:%s] session=%s FAILED: %s",
                    room_id[:8], session_id[:8], result.error,
                )
                store.add_message(room_id, {
                    "type": "system",
                    "content": f"{sname}: {result.error or 'Unknown error'}",
                })
                if agent_state:
                    agent_state.status = "failed"
                _notify_room(room_id)
            else:
                logger.debug(
                    "[Broadcast:%s] session=%s completed with no output",
                    room_id[:8], session_id[:8],
                )
                if agent_state:
                    agent_state.status = "completed"

        except AlreadyExecutingError:
            # Agent is busy with a real (non-trigger) execution.
            # Triggers are auto-preempted by execute_command, so if we
            # reach here the agent is handling real work.  Queue the
            # user message in the inbox.
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
                    "content": f"{sname}: \ud604\uc7ac \uc791\uc5c5 \uc644\ub8cc \ud6c4 \ucc98\ub9ac\ud569\ub2c8\ub2e4\u2026",
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
                    "content": f"{sname}: \ud604\uc7ac \ub2e4\ub978 \uc791\uc5c5 \uc911\uc774\uba70, \uba54\uc2dc\uc9c0 \ub300\uae30\uc5f4 \uc800\uc7a5\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4",
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
                "content": f"{sname}: \uc5d0\uc774\uc804\ud2b8\ub97c \uc2e4\ud589\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4 (\uc138\uc158\uc774 \ube44\ud65c\uc131 \uc0c1\ud0dc)",
            })
            if agent_state:
                agent_state.status = "failed"
            _notify_room(room_id)

        except Exception as e:
            logger.error("Broadcast error for session %s: %s", session_id, e, exc_info=True)
            store.add_message(room_id, {
                "type": "system",
                "content": f"{sname}: \uc2e4\ud589 \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4",
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

    # Launch all concurrently -- each is an independent command execution
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



# NOTE: SSE endpoint removed — chat room streaming is now handled by
# ws/chat_stream.py (WebSocket at /ws/chat/rooms/{room_id}).


def _get_messages_after(store, room_id: str, after_id: Optional[str]) -> List[dict]:
    """Return messages in the room that come after the given message ID."""
    all_msgs = store.get_messages(room_id)
    if not after_id:
        return []  # No reference point

    # Find the index of after_id
    idx = -1
    for i, m in enumerate(all_msgs):
        if m.get("id") == after_id:
            idx = i
            break

    if idx == -1:
        # after_id not found -- return all messages (client may have stale reference)
        return all_msgs

    return all_msgs[idx + 1:]
