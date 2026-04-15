"""
WebSocket endpoint for real-time avatar state streaming.

Replaces the GET /api/vtuber/agents/{session_id}/events SSE endpoint
with a persistent WebSocket connection.

Protocol:
  Client -> {"type": "subscribe"}
  Client -> {"type": "ping"}

  Server -> {"type": "avatar_state", "data": {...}}
  Server -> {"type": "heartbeat", "data": {"ts": ...}}
  Server -> {"type": "pong", "data": {"ts": ...}}
  Server -> {"type": "error", "data": {"error": "..."}}
"""

from __future__ import annotations

import asyncio
import json
import time
from logging import getLogger
from typing import Any

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


async def _send_event(ws: WebSocket, event_type: str, data: Any, session_id: str = "") -> bool:
    """Send a JSON event over WebSocket. Returns False if connection lost."""
    try:
        await ws.send_json({"type": event_type, "data": _sanitize(data)})
        return True
    except Exception as exc:
        logger.debug(
            "[AvatarWS:%s] failed to send event=%s: %s",
            session_id[:8] if session_id else "?", event_type, exc,
        )
        return False


@router.websocket("/ws/vtuber/agents/{session_id}/state")
async def ws_avatar_state_stream(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time avatar state changes.

    After connection, client sends a subscribe message to begin receiving
    avatar_state events whenever the avatar's emotion, expression, or
    motion changes.
    """
    logger.info("[AvatarWS:%s] connection attempt", session_id[:8])
    await websocket.accept()
    logger.info("[AvatarWS:%s] accepted", session_id[:8])

    app_state = websocket.app.state
    if not hasattr(app_state, "avatar_state_manager"):
        await _send_event(websocket, "error", {"error": "Avatar state manager not available"}, session_id)
        await websocket.close()
        return

    state_manager = app_state.avatar_state_manager

    # Queue for state changes from the avatar_state_manager subscription
    state_queue: asyncio.Queue = asyncio.Queue()

    async def _on_state_change(state):
        await state_queue.put(state)

    # Dedicated receiver task for client messages
    client_queue: asyncio.Queue[dict] = asyncio.Queue()
    disconnected = asyncio.Event()

    async def _receiver():
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                    await client_queue.put(msg)
                except json.JSONDecodeError:
                    pass
        except WebSocketDisconnect:
            disconnected.set()
        except Exception:
            disconnected.set()

    subscribed = False
    receiver_task = asyncio.create_task(_receiver())

    try:
        while not disconnected.is_set():
            # Wait for client messages (subscribe/ping) before entering stream loop
            if not subscribed:
                try:
                    msg = await asyncio.wait_for(client_queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    if disconnected.is_set():
                        break
                    if not await _send_event(websocket, "heartbeat", {"ts": time.time()}, session_id):
                        break
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "subscribe":
                    subscribed = True
                    state_manager.subscribe(session_id, _on_state_change)
                    logger.info("[AvatarWS:%s] subscribed to avatar state", session_id[:8])

                    # Send initial current state
                    current = state_manager.get_state(session_id)
                    if not await _send_event(websocket, "avatar_state", current.to_sse_data(), session_id):
                        break

                elif msg_type == "ping":
                    await _send_event(websocket, "pong", {"ts": time.time()}, session_id)
                    continue
                else:
                    await _send_event(websocket, "error", {"error": f"Unknown type: {msg_type}"}, session_id)
                    continue

            # Stream loop — push state changes and handle heartbeat
            if subscribed:
                await _stream_avatar_state(
                    websocket, session_id, state_queue, client_queue, disconnected,
                )
                break  # stream ended (disconnect or unsubscribe)

    finally:
        if subscribed:
            state_manager.unsubscribe(session_id, _on_state_change)
        receiver_task.cancel()
        try:
            await receiver_task
        except asyncio.CancelledError:
            pass
        logger.info("[AvatarWS:%s] cleanup done", session_id[:8])


async def _stream_avatar_state(
    ws: WebSocket,
    session_id: str,
    state_queue: asyncio.Queue,
    client_queue: asyncio.Queue,
    disconnected: asyncio.Event,
) -> None:
    """Push avatar state changes until client disconnects or unsubscribes."""
    heartbeat_interval = 30.0

    while not disconnected.is_set():
        # Wait for state change or heartbeat timeout
        try:
            state = await asyncio.wait_for(state_queue.get(), timeout=heartbeat_interval)
            if not await _send_event(ws, "avatar_state", state.to_sse_data(), session_id):
                return
        except asyncio.TimeoutError:
            if disconnected.is_set():
                return
            if not await _send_event(ws, "heartbeat", {"ts": time.time()}, session_id):
                return

        # Drain any client messages
        while not client_queue.empty():
            msg = client_queue.get_nowait()
            msg_type = msg.get("type", "")
            if msg_type == "unsubscribe":
                logger.info("[AvatarWS:%s] client unsubscribed", session_id[:8])
                return
            elif msg_type == "ping":
                if not await _send_event(ws, "pong", {"ts": time.time()}, session_id):
                    return
