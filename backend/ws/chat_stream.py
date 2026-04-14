"""
WebSocket endpoint for real-time chat room event streaming.

Replaces the GET /api/chat/rooms/{room_id}/events SSE endpoint
with a persistent WebSocket connection that pushes new messages,
broadcast status, and agent progress in real time.

Protocol:
  Client -> {"type": "subscribe", "after": "msg_id_or_null"}
  Client -> {"type": "ping"}

  Server -> {"type": "message", "data": {...}}
  Server -> {"type": "broadcast_status", "data": {...}}
  Server -> {"type": "agent_progress", "data": {...}}
  Server -> {"type": "broadcast_done", "data": {...}}
  Server -> {"type": "heartbeat", "data": {"ts": ...}}
  Server -> {"type": "error", "data": {"error": "..."}}
"""

from __future__ import annotations

import asyncio
import json
import time
from logging import getLogger
from typing import Any, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = getLogger(__name__)

router = APIRouter()


def _sanitize(obj: Any) -> Any:
    """Recursively ensure all values are JSON-serializable."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


async def _send_event(ws: WebSocket, event_type: str, data: Any) -> bool:
    """Send a JSON event over WebSocket. Returns False if connection lost."""
    try:
        await ws.send_json({"type": event_type, "data": _sanitize(data)})
        return True
    except Exception:
        return False


def _get_messages_after(store, room_id: str, after_id: Optional[str]) -> List[dict]:
    """Return messages in the room that come after the given message ID."""
    all_msgs = store.get_messages(room_id)
    if not after_id:
        return []

    idx = -1
    for i, m in enumerate(all_msgs):
        if m.get("id") == after_id:
            idx = i
            break

    if idx < 0:
        return all_msgs
    return all_msgs[idx + 1 :]


@router.websocket("/ws/chat/rooms/{room_id}")
async def ws_chat_room_stream(websocket: WebSocket, room_id: str):
    """
    WebSocket endpoint for real-time chat room events.

    After connection, client sends a subscribe message to begin receiving events:
      {"type": "subscribe", "after": "last_seen_msg_id_or_null"}

    Server pushes events in real time: message, broadcast_status,
    agent_progress, broadcast_done, heartbeat.
    """
    await websocket.accept()

    from service.chat.conversation_store import get_chat_store
    from controller.chat_controller import (
        _active_broadcasts,
        _get_room_event,
        _build_agent_progress_data,
    )
    from service.config.sub_config.general.chat_config import ChatConfig

    store = get_chat_store()
    room = store.get_room(room_id)
    if not room:
        await _send_event(websocket, "error", {"error": f"Room not found: {room_id}"})
        await websocket.close()
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_event(websocket, "error", {"error": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "subscribe":
                last_seen_id = msg.get("after")
                await _stream_room_events(
                    websocket, store, room_id, last_seen_id,
                    _active_broadcasts, _get_room_event, _build_agent_progress_data,
                )

            elif msg_type == "ping":
                await _send_event(websocket, "pong", {"ts": time.time()})

            else:
                await _send_event(
                    websocket, "error", {"error": f"Unknown message type: {msg_type}"}
                )

    except WebSocketDisconnect:
        logger.debug("Chat WebSocket disconnected for room %s", room_id)
    except Exception as e:
        logger.error(
            "Chat WebSocket error for room %s: %s", room_id, e, exc_info=True
        )
        try:
            await _send_event(websocket, "error", {"error": str(e)})
        except Exception:
            pass


async def _stream_room_events(
    ws: WebSocket,
    store,
    room_id: str,
    last_seen_id: Optional[str],
    active_broadcasts: dict,
    get_room_event,
    build_agent_progress_data,
) -> None:
    """
    Push room events over WebSocket until the client disconnects.

    Mirrors the SSE event_generator in chat_controller.py but uses
    WebSocket push instead of SSE yield.
    """
    from service.config.sub_config.general.chat_config import ChatConfig

    _chat_cfg = ChatConfig.get_default_instance()
    heartbeat_interval = float(_chat_cfg.sse_heartbeat_interval_s)
    room_event = get_room_event(room_id)

    # On initial subscribe: send any messages newer than after
    if last_seen_id:
        missed = _get_messages_after(store, room_id, last_seen_id)
        for m in missed:
            if not await _send_event(ws, "message", m):
                return
            last_seen_id = m["id"]
    else:
        all_msgs = store.get_messages(room_id)
        if all_msgs:
            last_seen_id = all_msgs[-1]["id"]

    # Send current broadcast status if active
    bstate = active_broadcasts.get(room_id)
    if bstate and not bstate.finished:
        await _send_event(ws, "broadcast_status", {
            "broadcast_id": bstate.broadcast_id,
            "total": bstate.total,
            "completed": bstate.completed,
            "responded": bstate.responded,
            "finished": False,
        })
        if bstate.agent_states:
            agent_progress_list = [
                build_agent_progress_data(astate)
                for astate in bstate.agent_states.values()
            ]
            await _send_event(ws, "agent_progress", {
                "broadcast_id": bstate.broadcast_id,
                "agents": agent_progress_list,
            })

    # Main loop: wait for new messages or heartbeat
    while True:
        room_event.clear()

        try:
            # Use asyncio.wait to handle both room events and incoming WS messages
            done, _ = await asyncio.wait(
                [
                    asyncio.create_task(room_event.wait()),
                    asyncio.create_task(_ws_receive_or_timeout(ws, heartbeat_interval)),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Check if we received a client message (e.g., unsubscribe)
            for task in done:
                result = task.result()
                if isinstance(result, dict):
                    # Client sent a message — break the stream loop
                    if result.get("type") == "unsubscribe":
                        return
            # Cancel pending tasks
            for task in _:
                task.cancel()

        except asyncio.CancelledError:
            return

        # Check for new messages
        if last_seen_id is not None:
            new_msgs = _get_messages_after(store, room_id, last_seen_id)
        else:
            new_msgs = store.get_messages(room_id)

        for m in new_msgs:
            if not await _send_event(ws, "message", m):
                return
            last_seen_id = m["id"]

        # Broadcast status update
        bstate = active_broadcasts.get(room_id)
        if bstate:
            await _send_event(ws, "broadcast_status", {
                "broadcast_id": bstate.broadcast_id,
                "total": bstate.total,
                "completed": bstate.completed,
                "responded": bstate.responded,
                "finished": bstate.finished,
            })

            if not bstate.finished and bstate.agent_states:
                agent_progress_list = [
                    build_agent_progress_data(astate)
                    for astate in bstate.agent_states.values()
                ]
                await _send_event(ws, "agent_progress", {
                    "broadcast_id": bstate.broadcast_id,
                    "agents": agent_progress_list,
                })

            if bstate.finished:
                await _send_event(ws, "broadcast_done", {
                    "broadcast_id": bstate.broadcast_id,
                    "total": bstate.total,
                    "responded": bstate.responded,
                })
        elif not new_msgs:
            # No active broadcast, no new messages — just heartbeat
            await _send_event(ws, "heartbeat", {"ts": time.time()})


async def _ws_receive_or_timeout(ws: WebSocket, timeout: float) -> Optional[dict]:
    """
    Try to receive a WebSocket message within timeout.
    Returns the parsed message dict, or None on timeout.
    """
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
        return json.loads(raw)
    except asyncio.TimeoutError:
        return None
    except (json.JSONDecodeError, WebSocketDisconnect):
        return None
