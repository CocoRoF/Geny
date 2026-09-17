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
import os
import time
import uuid
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from service.auth.auth_middleware import require_auth
from service.utils.background import spawn_background
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

    Cycle 20260424_3 PR-2 — fail loudly when the referenced file is
    missing on disk or the URL escapes the upload root, instead of
    letting the executor silently drop the image block downstream.
    """
    out = dict(att)
    url = (out.get("url") or "").strip()
    if not url or not url.startswith("/static/uploads/"):
        return out
    rel = url[len("/static/uploads/") :]
    upload_root = _UPLOAD_ROOT.resolve()
    abs_path = (upload_root / rel).resolve()
    # Defend against path traversal: `/static/uploads/../../etc/passwd`
    try:
        abs_path.relative_to(upload_root)
    except ValueError:
        logger.warning(
            "rejected attachment outside upload root: url=%r resolved=%s",
            url, abs_path,
        )
        raise HTTPException(
            status_code=400,
            detail=f"invalid attachment url: {url}",
        )
    if not abs_path.is_file():
        logger.warning(
            "attachment missing on disk: url=%r path=%s — refusing broadcast",
            url, abs_path,
        )
        raise HTTPException(
            status_code=400,
            detail=f"attachment not found on server: {url}",
        )
    out["url"] = abs_path.as_uri()  # "file:///..."
    return out


_OBSERVATION_SOURCE = "screen_observation"


def _screen_image_send_enabled() -> bool:
    """Mirror of ``screen_observation._send_image_enabled`` — whether
    auto-captured screen frames are allowed to reach the persona."""
    return os.environ.get(
        "GENY_SCREEN_OBS_SEND_IMAGE", "true"
    ).strip().lower() not in ("0", "false", "no", "off")


def _filter_observation_frames_for_send(
    attachments: Optional[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    """Drop auto-captured screen frames before they reach the executor when
    the screen-image kill-switch is off (honours GENY_SCREEN_OBS_SEND_IMAGE
    for the P3 turn-attach path, mirroring the P1 trigger path). User-uploaded
    attachments always pass through."""
    if not attachments or _screen_image_send_enabled():
        return attachments
    kept = [a for a in attachments if a.get("source") != _OBSERVATION_SOURCE]
    return kept or None


def _has_observation_frame(
    attachments: Optional[List[Dict[str, Any]]],
) -> bool:
    """True if the turn already carries a screen-observation frame (the
    frontend grabbed one from the live overlay stream) — so the backend
    doesn't capture a second one."""
    return bool(attachments) and any(
        a.get("source") == _OBSERVATION_SOURCE for a in attachments
    )


def _attachments_for_storage(
    attachments: Optional[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    """Storage copy of the turn's attachments. Auto-captured screen frames are
    ambient CONTEXT (not user content) and carry raw base64 — exclude them so
    chat history (DB + JSON backup) is never bloated with hundreds of KB per
    turn. User uploads (url / attachment_id references) are kept verbatim."""
    if not attachments:
        return None
    kept = [a for a in attachments if a.get("source") != _OBSERVATION_SOURCE]
    return kept or None


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
class TurnState:
    """The turn running in a room right now.

    One room holds one agent, so this holds one agent state. It stays a dict
    keyed by session id because that is the shape the wire has always carried
    (``agent_progress`` sends a list), and a client installed before this
    change still reads it.
    """
    turn_id: str
    room_id: str
    finished: bool = False
    cancelled: bool = False
    started_at: float = field(default_factory=time.time)
    agent_states: Dict[str, AgentExecutionState] = field(default_factory=dict)

    # ── the wire's older vocabulary ──
    @property
    def broadcast_id(self) -> str:
        return self.turn_id

    @property
    def total(self) -> int:
        return len(self.agent_states)

    @property
    def completed(self) -> int:
        return sum(
            1 for a in self.agent_states.values()
            if a.status in ("completed", "failed", "cancelled")
        )

    @property
    def responded(self) -> int:
        return sum(1 for a in self.agent_states.values() if a.status == "completed")


# The name the rest of the file used while a room was a group chat.
BroadcastState = TurnState

# room_id -> the turn running in it
_active_turns: Dict[str, TurnState] = {}
_active_broadcasts = _active_turns  # ws/chat_stream.py still says this
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
    """Signal all SSE listeners that a new message appeared for this room.

    Guarded, because every one of its nine call sites runs AFTER the message
    has already been persisted. Letting a notification failure propagate would
    throw away committed work and report a 500 for a request that succeeded —
    the exact shape of the screen-observation outage. A missed nudge costs a
    listener one poll interval; a raised exception costs the user their
    message.
    """
    try:
        ev = _room_new_msg_events.get(room_id)
        if ev:
            ev.set()
            logger.debug("[Broadcast:%s] room event notified (listeners present)", room_id[:8])
        else:
            logger.debug("[Broadcast:%s] room event notify skipped (no listeners)", room_id[:8])
    except Exception:  # noqa: BLE001
        logger.warning("[Broadcast:%s] room notify failed", room_id[:8], exc_info=True)


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

    kind: str = Field(..., description="image | audio | file")
    name: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[int] = None
    sha256: Optional[str] = None
    attachment_id: Optional[str] = None  # sha256 hex from POST /api/uploads
    url: Optional[str] = None             # /static/uploads/.../<sha>.<ext>
    data: Optional[str] = None            # base64 fallback (small inline pastes)
    # Provenance discriminator. ``screen_observation`` marks an auto-captured
    # screen frame attached to a turn (VTuber vision) — it is ambient context,
    # not user content: it must NOT be persisted into chat history (raw bytes),
    # and is dropped when the screen-image kill-switch is off.
    source: Optional[str] = None


class RoomMessageRequest(BaseModel):
    message: str = Field("", description="Chat message to send (may be empty if attachments present)")
    attachments: Optional[List[BroadcastAttachment]] = Field(
        default=None,
        description="Optional list of image/file references uploaded via /api/uploads.",
    )


# The room used to be a group chat and this used to be a broadcast. It is one
# agent now; the old name stays only so nothing that imports it breaks.
RoomBroadcastRequest = RoomMessageRequest


# ============================================================================
# Room CRUD Endpoints
# ============================================================================

@router.get("/rooms", response_model=RoomListResponse)
async def list_rooms():
    """Every room, newest activity first.

    Diagnostics only. A room belongs to one session and is reached through it
    (``GET /rooms/for-session/{id}``); browsing the list and picking one is
    what the messenger did, and it is how three screens came to disagree about
    which conversation a session was having.
    """
    store = get_chat_store()
    rooms = store.list_rooms()
    return RoomListResponse(
        rooms=[RoomResponse(**r) for r in rooms],
        total=len(rooms),
    )


@router.get("/rooms/for-session/{session_id}", response_model=RoomResponse)
async def room_for_session(session_id: str, create: bool = True):
    """Where this session's conversation lives.

    Every surface asks this rather than scanning the room list and applying a
    rule of its own — that is how the web page, the desktop app and the phone
    ended up showing three different conversations for one session. The rule
    is in ``service.chat.home_room``; this is only its door.

    ``create=false`` asks without making one, for a caller that wants to know
    whether a conversation exists at all.
    """
    from service.chat.home_room import resolve_home_room

    room = resolve_home_room(session_id, create=create)
    if not room:
        raise HTTPException(
            status_code=404, detail=f"No chat room for session: {session_id}"
        )
    return RoomResponse(**room)


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str):
    """Get a single chat room by ID."""
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")
    return RoomResponse(**room)


@router.delete("/rooms/{room_id}")
async def delete_room(room_id: str, auth: dict = Depends(require_auth)):
    """Throw this conversation away, history and all.

    The session keeps going and gets a fresh room the next time it speaks —
    so this is "start over", not "delete the agent". The link on the session
    record is cleared here rather than left pointing at a room that is gone.
    """
    from service.chat.home_room import session_ids_of

    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")
    owners = session_ids_of(room)

    deleted = store.delete_room(room_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    try:
        from service.sessions.store import get_session_store

        sessions = get_session_store()
        for sid in owners:
            record = sessions.get(sid) or {}
            if record.get("chat_room_id") == room_id:
                sessions.update(sid, {"chat_room_id": None})
    except Exception:  # noqa: BLE001
        logger.debug("Could not clear chat_room_id after deleting %s", room_id, exc_info=True)
    try:
        from service.executor import get_agent_session_manager

        manager = get_agent_session_manager()
        for sid in owners:
            agent = manager.get_agent(sid)
            if agent is not None and getattr(agent, "_chat_room_id", None) == room_id:
                agent._chat_room_id = None
    except Exception:  # noqa: BLE001
        pass

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
async def cleanup_old_messages(auth: dict = Depends(require_auth)):
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

@router.post("/rooms/{room_id}/message")
async def send_to_room(
    room_id: str,
    request: RoomMessageRequest,
    auth: dict = Depends(require_auth),
):
    """Say something to the agent whose room this is.

    One room, one agent, one conversation. The message goes through the same
    ``execute_command`` path every other entry point uses, so the turn is
    logged, costed, revived and de-duplicated exactly like any other — the
    room adds nowhere for a turn to behave differently.

    Processing is fire-and-forget: the answer is persisted into the room
    whether or not anybody is still connected, and clients watch the room over
    ``WS /ws/chat/rooms/{room_id}``. The saved user message comes back
    immediately so the screen that sent it can adopt its own bubble.
    """
    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room not found: {room_id}")

    # A message must say something. Empty text with no attachment is a
    # mis-click, not a turn.
    has_attachments = bool(request.attachments)
    if not request.message.strip() and not has_attachments:
        raise HTTPException(status_code=400, detail="Message or attachments required")

    # Materialize attachments to plain dicts for the background runner —
    # Pydantic models don't survive ``asyncio.create_task`` boundaries cleanly
    # when executors thread them through ``**invoke_kwargs``.
    attachments_payload: Optional[List[Dict[str, Any]]] = None
    attachments_for_storage: Optional[List[Dict[str, Any]]] = None
    if has_attachments:
        # Raw dicts carry the browser-facing ``/static/uploads/...`` URL.
        # VTuber screen-vision: auto-captured screen frames are ambient
        # CONTEXT, not user content — honour the screen-image kill-switch by
        # dropping them before they reach the executor AND before we persist
        # them (raw base64 bloats the DB + JSON backup). Filter keys on
        # ``source`` (not url), so it runs safely on the pre-rewrite dicts.
        raw = _filter_observation_frames_for_send(
            [a.model_dump(exclude_none=True) for a in request.attachments]
        )
        # Executor payload: rewrite ``/static/uploads/...`` → ``file:///...``
        # so the executor's MultimodalNormalizer can inline the bytes as
        # base64. This URI points at the SERVER filesystem — usable by the
        # executor, but NOT loadable by a browser.
        if raw:
            attachments_payload = [_rewrite_local_attachment_url(a) for a in raw]
        # Storage / broadcast copy: keep the ORIGINAL public URL. The UI
        # renders ``<img src="/static/uploads/...">`` which nginx serves 200
        # (allowlisted, no auth); the server-side ``file:///app/...`` URI the
        # executor needs would render as a BROKEN image in the browser. Never
        # let the executor rewrite leak into what the client sees.
        attachments_for_storage = _attachments_for_storage(raw)

    # 1. Save user message
    try:
        user_msg_data: Dict[str, Any] = {
            "type": "user",
            "content": request.message,
        }
        if attachments_for_storage:
            # Store attachment metadata on the user turn for replay /
            # rendering. Raw bytes are NOT stored here — only the URL
            # / attachment_id references that point back at
            # ``backend/static/uploads`` (and auto-screen frames are excluded).
            user_msg_data["attachments"] = attachments_for_storage
        user_msg = store.add_message(room_id, user_msg_data)
    except Exception as e:
        logger.error("Failed to save user message: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="\uba54\uc2dc\uc9c0 \uc800\uc7a5\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4")

    _notify_room(room_id)

    # 2. Whose room is this? Exactly one session — the invariant lives in
    #    service/chat/home_room.py, and a room that has lost its session can
    #    only be an artefact of the messenger this used to be.
    from service.chat.home_room import session_ids_of

    room_sessions = session_ids_of(room)
    if not room_sessions:
        store.add_message(room_id, {
            "type": "system",
            "content": "이 대화방에 연결된 에이전트가 없습니다.",
        })
        _notify_room(room_id)
        return {"user_message": user_msg, "broadcast_id": None, "target_count": 0}
    session_id = room_sessions[0]

    # Display metadata, best-effort — the executor does the real work.
    info: Dict[str, str] = {}
    for a in agent_manager.list_agents():
        if a.session_id == session_id:
            info = {
                "session_name": a.session_name,
                "role": a.role.value if hasattr(a.role, "value") else str(a.role),
            }
            break

    # 3. One turn at a time in a room. A second message while the first is
    #    still running would overwrite the tracked state, and the first turn's
    #    completion would never reach the screen.
    running = _active_turns.get(room_id)
    if running and not running.finished:
        logger.warning(
            "Room %s: cancelling turn %s (still in flight) before starting a new one",
            room_id[:8], running.turn_id[:8],
        )
        running.cancelled = True
        for sid, astate in running.agent_states.items():
            if astate.status == "executing":
                try:
                    if await stop_execution(sid):
                        astate.status = "cancelled"
                except Exception as cancel_err:  # noqa: BLE001
                    logger.debug(
                        "Room %s: could not stop %s: %s", room_id[:8], sid[:8], cancel_err,
                    )
            elif astate.status in ("pending", "queued"):
                astate.status = "cancelled"
        running.finished = True
        _notify_room(room_id)

    turn_id = str(uuid.uuid4())
    state = TurnState(
        turn_id=turn_id,
        room_id=room_id,
        agent_states={
            session_id: AgentExecutionState(
                session_id=session_id,
                session_name=info.get("session_name", session_id[:8]),
                role=info.get("role", "worker"),
                status="pending",
            )
        },
    )
    _active_turns[room_id] = state

    # Say so before the work starts, so a client that just connected sees the
    # agent as busy rather than as silent.
    _notify_room(room_id)

    logger.info(
        "Room %s: turn %s -> session %s: %s",
        room_id[:8], turn_id[:8], session_id[:8], request.message[:80],
    )

    # Detached: the HTTP response returns now, the turn runs on.
    spawn_background(
        _run_turn(
            room_id, state, session_id, info, request.message, store,
            attachments=attachments_payload,
        ),
        name=f"chat.turn:{room_id}",
    )

    return {
        "user_message": user_msg,
        # Named for the wire, which older phones still speak.
        "broadcast_id": turn_id,
        "target_count": 1,
    }


@router.post("/rooms/{room_id}/broadcast")
async def broadcast_to_room(
    room_id: str,
    request: RoomMessageRequest,
    auth: dict = Depends(require_auth),
):
    """Deprecated name for :func:`send_to_room`.

    A room held several sessions once and this fanned out to all of them.
    Kept as a door, not as a second implementation, because a phone installed
    before the rename still knocks on it.
    """
    return await send_to_room(room_id, request, auth)


@router.post("/rooms/{room_id}/cancel")
async def cancel_turn(room_id: str, auth: dict = Depends(require_auth)):
    """Stop the turn running in this room."""
    bstate = _active_turns.get(room_id)
    if not bstate or bstate.finished:
        raise HTTPException(status_code=404, detail="No turn is running in this room")

    if bstate.cancelled:
        return {"status": "already_cancelled", "broadcast_id": bstate.turn_id}

    bstate.cancelled = True

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
        "broadcast_id": bstate.turn_id,
        "cancelled_agents": cancelled_count,
    }


@router.post("/rooms/{room_id}/broadcast/cancel")
async def cancel_broadcast(room_id: str, auth: dict = Depends(require_auth)):
    """Deprecated name for :func:`cancel_turn`."""
    return await cancel_turn(room_id, auth)


async def _run_turn(
    room_id: str,
    state: TurnState,
    session_id: str,
    agent_info: Dict[str, str],
    message: str,
    store,
    *,
    attachments: Optional[List[Dict[str, Any]]] = None,
):
    """Background task: run the turn and persist what it said.

    The agent goes through the exact same ``execute_command`` path as every
    other entry point, inheriting session logging, cost persistence,
    auto-revival, double-execution prevention and timeout handling. The room
    is a place to watch a turn from, never a second way to run one.
    """
    from service.logging.session_logger import get_session_logger

    async def _invoke_one(session_id: str):
        info = agent_info
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
        # Resolve the live agent — used downstream by the memory event
        # consumer which owns its own cursor (boot events would never
        # ship under pre_exec_cursor's convention).
        agent = agent_manager.get_agent(session_id)

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
                                # What the call WAS, not just that there was
                                # one. The web renders the same timeline the
                                # desktop app does (shared/chat/tool-view),
                                # and without these it can only print the log
                                # line — which is what it used to do.
                                for key in ("tool_id", "input_preview",
                                            "result_preview", "duration_ms"):
                                    if meta.get(key) is not None:
                                        log_entry[key] = meta[key]
                                if level == "TOOL_RES":
                                    log_entry["is_error"] = bool(meta.get("is_error"))
                                agent_state.recent_logs.append(log_entry)
                                if len(agent_state.recent_logs) > _MAX_RECENT_LOGS:
                                    agent_state.recent_logs = agent_state.recent_logs[-_MAX_RECENT_LOGS:]
                                agent_state.log_cursor += 1

                        if had_new:
                            _notify_room(room_id)

                except asyncio.CancelledError:
                    pass

            log_poll_task = asyncio.create_task(_poll_logs())

        # Real-time vision (P3b): for a VTuber turn that didn't already carry a
        # screen frame (e.g. typed in the /connector window, which has no live
        # stream), grab the CURRENT screen from the connector so the persona
        # judges what's literally on screen now. Gated (toggle on + vision model
        # + kill-switch + connector present) and fully best-effort — never
        # blocks or fails the turn. The frame is sent to the executor for THIS
        # turn only; it is not persisted into chat history.
        sess_attachments = attachments
        if role == "vtuber" and not _has_observation_frame(attachments):
            try:
                from service.vtuber.screen_observation import (
                    capture_current_screen_attachment,
                )
                fresh = await capture_current_screen_attachment(session_id)
                if fresh:
                    sess_attachments = list(attachments or []) + [fresh]
                    logger.info(
                        "[Broadcast:%s] attached live screen frame for session=%s",
                        room_id[:8], session_id[:8],
                    )
            except Exception:  # noqa: BLE001
                logger.debug("[Broadcast] live screen capture skipped", exc_info=True)

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
                attachments=sess_attachments,
            )
            logger.info(
                "[Broadcast:%s] execute_command returned for session=%s: success=%s, output_len=%d, duration=%dms, cost=%s",
                room_id[:8], session_id[:8], result.success,
                len(result.output or ""), result.duration_ms, result.cost_usd,
            )

            cleaned_output = sanitize_for_display(result.output) if result.success else ""
            # Files delivered via SendUserFile this turn (workspace-canvas P1).
            # A file-only turn (no final text) must still produce a message —
            # mirrors how user messages may be attachment-only.
            result_attachments = list(getattr(result, "attachments", None) or [])
            if cleaned_output or result_attachments:
                msg_data: Dict[str, Any] = {
                    "type": "agent",
                    "content": cleaned_output,
                    "session_id": session_id,
                    "session_name": sname,
                    "role": role,
                    "duration_ms": result.duration_ms,
                    "cost_usd": result.cost_usd,
                }
                if result_attachments:
                    msg_data["attachments"] = result_attachments
                # Attach file changes from this execution's log entries
                if session_logger:
                    fc = session_logger.extract_file_changes_from_cache(pre_exec_cursor)
                    if fc:
                        msg_data["file_changes"] = fc
                        logger.debug("[Broadcast:%s] session=%s: %d file changes", room_id[:8], session_id[:8], len(fc))
                    # Memory subsystem events (note writes, vector
                    # indexing, curated promotions, knowledge searches).
                    # We avoid the `pre_exec_cursor` convention used by
                    # `file_changes` because boot-time events
                    # (`provider_initialized`, etc.) fire *before* the
                    # very first turn even starts — pre_exec_cursor
                    # would skip them forever. Instead the session
                    # owns its own memory cursor that starts at 0 and
                    # advances after every successful drain, so the
                    # first broadcast captures the boot rows and the
                    # rest follow turn-by-turn deltas.
                    if agent is not None:
                        me = agent.consume_memory_events()
                    else:
                        me = session_logger.extract_memory_events_from_cache(0)
                    if me:
                        msg_data["memory_events"] = me
                        # INFO so the operator can confirm in the
                        # backend log that the channel is alive without
                        # toggling DEBUG. Empty case stays silent — no
                        # need to spam the log for "no memory events
                        # this turn".
                        logger.info(
                            "[Broadcast:%s] session=%s: forwarding %d memory event(s) (events=%s)",
                            room_id[:8], session_id[:8], len(me),
                            [ev.get("event_type", "?") for ev in me[:5]],
                        )
                    else:
                        logger.info(
                            "[Broadcast:%s] session=%s: 0 memory events this turn "
                            "(agent=%s, cursor=%s)",
                            room_id[:8], session_id[:8],
                            "live" if agent is not None else "none",
                            getattr(agent, "_memory_events_cursor", None) if agent else None,
                        )
                store.add_message(room_id, msg_data)
                if agent_state:
                    agent_state.status = "completed"
                logger.info(
                    "[Turn:%s] session=%s: the agent's answer is saved",
                    room_id[:8], session_id[:8],
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
                    "content": result.error or "실행에 실패했습니다",
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
                    "content": "\ud604\uc7ac \uc791\uc5c5 \uc644\ub8cc \ud6c4 \ucc98\ub9ac\ud569\ub2c8\ub2e4\u2026",
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
                    "content": "\ud604\uc7ac \ub2e4\ub978 \uc791\uc5c5 \uc911\uc774\uba70, \uba54\uc2dc\uc9c0 \ub300\uae30\uc5f4 \uc800\uc7a5\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4",
                })
                if agent_state:
                    agent_state.status = "failed"
            _notify_room(room_id)

        except AgentNotFoundError:
            store.add_message(room_id, {
                "type": "system",
                "content": "세션을 찾을 수 없습니다",
            })
            if agent_state:
                agent_state.status = "failed"
            _notify_room(room_id)

        except AgentNotAliveError as e:
            logger.warning("Agent not alive for session %s: %s", session_id, e)
            store.add_message(room_id, {
                "type": "system",
                "content": "\uc5d0\uc774\uc804\ud2b8\ub97c \uc2e4\ud589\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4 (\uc138\uc158\uc774 \ube44\ud65c\uc131 \uc0c1\ud0dc)",
            })
            if agent_state:
                agent_state.status = "failed"
            _notify_room(room_id)

        except Exception as e:
            logger.error("Broadcast error for session %s: %s", session_id, e, exc_info=True)
            store.add_message(room_id, {
                "type": "system",
                "content": "\uc2e4\ud589 \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4",
            })
            if agent_state:
                agent_state.status = "failed"
            _notify_room(room_id)

        finally:
            # Cancel log polling
            if log_poll_task:
                log_poll_task.cancel()
                try:
                    await log_poll_task
                except asyncio.CancelledError:
                    pass

    await _invoke_one(session_id)

    # No summary line. "1/1 sessions responded (7.1s)" was a scoreboard for a
    # fan-out that no longer exists, and it landed in the conversation after
    # every successful answer — a receipt nobody asked for, printed under
    # every reply.
    state.finished = True

    logger.info(
        "Room %s: turn %s finished in %dms (%s)",
        room_id[:8], state.turn_id[:8],
        int((time.time() - state.started_at) * 1000),
        "answered" if state.responded else "no answer",
    )

    # Hold the finished state briefly so a client that connects right after
    # the turn still learns how it ended, then drop it. The id guard stops a
    # newer turn's state being deleted by an older turn's timer.
    from service.config.sub_config.general.chat_config import ChatConfig
    _chat_cfg = ChatConfig.get_default_instance()
    await asyncio.sleep(_chat_cfg.broadcast_cleanup_delay_s)
    current = _active_turns.get(room_id)
    if current is not None and current.turn_id == state.turn_id:
        del _active_turns[room_id]



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
