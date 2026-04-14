"""
WebSocket endpoint for streaming agent execution.

Replaces the two-step SSE pattern (POST /execute/start + GET /execute/events)
with a single persistent WebSocket connection that streams log events,
status updates, and execution results in real time.

Protocol:
  Client -> {"type": "execute", "prompt": "...", "timeout": null, "system_prompt": null, "max_turns": null}
  Client -> {"type": "stop"}
  Client -> {"type": "reconnect"}

  Server -> {"type": "log", "data": {...}}
  Server -> {"type": "status", "data": {"status": "...", "message": "..."}}
  Server -> {"type": "result", "data": {...}}
  Server -> {"type": "heartbeat", "data": {...}}
  Server -> {"type": "error", "data": {"error": "..."}}
  Server -> {"type": "done", "data": {}}
"""

from __future__ import annotations

import asyncio
import json
import time
from logging import getLogger
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from service.execution.agent_executor import (
    start_command_background,
    get_execution_holder,
    cleanup_execution,
    stop_execution,
    AgentNotFoundError,
    AgentNotAliveError,
    AlreadyExecutingError,
)
from service.logging.session_logger import get_session_logger

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


async def _send_event(ws: WebSocket, event_type: str, data: dict) -> bool:
    """Send a JSON event over WebSocket. Returns False if connection is lost."""
    try:
        await ws.send_json({"type": event_type, "data": _sanitize(data)})
        return True
    except Exception:
        return False


async def _emit_avatar_state_for_log(
    entry_dict: dict, session_id: str, app_state: Any
) -> None:
    """
    Emit avatar state update based on log content.
    Mirrors the SSE implementation in agent_controller.py.
    Best-effort: never raises.
    """
    if app_state is None:
        return
    if not hasattr(app_state, "avatar_state_manager") or not hasattr(
        app_state, "live2d_model_manager"
    ):
        return

    try:
        state_manager = app_state.avatar_state_manager
        model_manager = app_state.live2d_model_manager

        model = model_manager.get_agent_model(session_id)
        if not model:
            return

        level = entry_dict.get("level", "")
        message = entry_dict.get("message", "")

        from service.vtuber.emotion_extractor import EmotionExtractor

        extractor = EmotionExtractor(model.emotionMap)

        if level == "RESPONSE":
            emotion, index = extractor.resolve_emotion(message, None)
            await state_manager.update_state(
                session_id=session_id,
                emotion=emotion,
                expression_index=index,
                trigger="agent_output",
            )
        elif level == "TOOL":
            await state_manager.update_state(
                session_id=session_id,
                emotion="surprise",
                expression_index=model.emotionMap.get("surprise", 0),
                trigger="state_change",
            )
        elif level == "GRAPH":
            if "error" in message.lower() or "fail" in message.lower():
                await state_manager.update_state(
                    session_id=session_id,
                    emotion="fear",
                    expression_index=model.emotionMap.get("fear", 0),
                    trigger="state_change",
                )
            elif "complet" in message.lower() or "success" in message.lower():
                await state_manager.update_state(
                    session_id=session_id,
                    emotion="joy",
                    expression_index=model.emotionMap.get("joy", 0),
                    trigger="state_change",
                )
    except Exception:
        pass  # Best-effort


async def _stream_execution_ws(
    ws: WebSocket,
    holder: dict,
    session_id: str,
    app_state: Any = None,
) -> None:
    """
    Stream execution events over WebSocket until the execution completes.

    Replaces the SSE generator _stream_execution_sse with a push-based
    WebSocket loop. Same event types: log, status, result, heartbeat, done.
    """
    session_logger = get_session_logger(session_id, create_if_missing=False)
    cache_cursor = holder.get("cache_cursor", 0)
    heartbeat_interval = 15.0
    poll_interval = 0.10  # 100ms — faster than SSE's 150ms since WS has no buffering overhead
    last_event_time = time.monotonic()
    start_time = holder.get("start_time", time.time())

    # Initial status
    if not await _send_event(ws, "status", {"status": "running", "message": "Execution started"}):
        return
    last_event_time = time.monotonic()

    def _build_heartbeat() -> dict:
        now = time.time()
        now_mono = time.monotonic()
        elapsed_ms = int((now - start_time) * 1000)
        last_write = session_logger.get_last_write_at() if session_logger else 0
        last_activity_ms = (
            int((now_mono - last_write) * 1000) if last_write > 0 else elapsed_ms
        )
        entry_info = session_logger.get_last_entry_info() if session_logger else {}
        return {
            "ts": now,
            "elapsed_ms": elapsed_ms,
            "last_activity_ms": last_activity_ms,
            "log_count": cache_cursor,
            "last_event_level": entry_info.get("level"),
            "last_tool_name": entry_info.get("tool_name"),
        }

    try:
        while not holder.get("done"):
            had_data = False

            if session_logger:
                new_entries, cache_cursor = session_logger.get_cache_entries_since(
                    cache_cursor
                )
                for entry in new_entries:
                    entry_dict = entry.to_dict()
                    if not await _send_event(ws, "log", entry_dict):
                        return  # Connection lost
                    if app_state:
                        await _emit_avatar_state_for_log(entry_dict, session_id, app_state)
                    had_data = True

            if had_data:
                last_event_time = time.monotonic()
            elif time.monotonic() - last_event_time >= heartbeat_interval:
                if not await _send_event(ws, "heartbeat", _build_heartbeat()):
                    return
                last_event_time = time.monotonic()

            await asyncio.sleep(poll_interval)

        # Final drain — pick up entries written during last poll cycle
        await asyncio.sleep(0.05)
        if session_logger:
            final_entries, cache_cursor = session_logger.get_cache_entries_since(
                cache_cursor
            )
            for entry in final_entries:
                entry_dict = entry.to_dict()
                await _send_event(ws, "log", entry_dict)

    except Exception as e:
        logger.error("WebSocket stream error: %s", e, exc_info=True)
        await _send_event(ws, "error", {"error": str(e)})

    # Emit final result or error
    if holder.get("error"):
        await _send_event(
            ws, "status", {"status": "error", "message": holder["error"]}
        )
        await _send_event(ws, "result", holder.get("result", {}))
    else:
        await _send_event(
            ws, "status", {"status": "completed", "message": "Execution completed"}
        )
        await _send_event(ws, "result", holder.get("result", {}))

    await _send_event(ws, "done", {})

    # Cleanup execution holder
    cleanup_execution(session_id)


@router.websocket("/ws/execute/{session_id}")
async def ws_execute_stream(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for streaming agent execution.

    Supports three message types from the client:

    1. execute — Start a new execution:
       {"type": "execute", "prompt": "...", "timeout": null, "system_prompt": null, "max_turns": null}

    2. stop — Stop the current execution:
       {"type": "stop"}

    3. reconnect — Reconnect to an active execution:
       {"type": "reconnect"}

    The server streams events in real time until execution completes,
    then sends a "done" event. The connection stays open for further
    commands (multi-turn conversation over a single WebSocket).
    """
    await websocket.accept()
    app_state = websocket.app.state

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_event(
                    websocket, "error", {"error": "Invalid JSON"}
                )
                continue

            msg_type = msg.get("type", "")

            if msg_type == "execute":
                prompt = (msg.get("prompt") or "").strip()
                if not prompt:
                    await _send_event(
                        websocket, "error", {"error": "Prompt must not be empty"}
                    )
                    continue

                try:
                    holder = await start_command_background(
                        session_id=session_id,
                        prompt=prompt,
                        timeout=msg.get("timeout"),
                        system_prompt=msg.get("system_prompt"),
                        max_turns=msg.get("max_turns"),
                    )
                except AgentNotFoundError:
                    await _send_event(
                        websocket,
                        "error",
                        {"error": f"AgentSession not found: {session_id}"},
                    )
                    continue
                except AgentNotAliveError as e:
                    await _send_event(
                        websocket, "error", {"error": str(e)}
                    )
                    continue
                except AlreadyExecutingError:
                    await _send_event(
                        websocket,
                        "error",
                        {"error": "Execution already in progress"},
                    )
                    continue

                await _stream_execution_ws(
                    websocket, holder, session_id, app_state=app_state
                )

            elif msg_type == "stop":
                stopped = await stop_execution(session_id)
                await _send_event(
                    websocket,
                    "status",
                    {
                        "status": "stopped" if stopped else "idle",
                        "message": "Execution stopped" if stopped else "No active execution",
                    },
                )

            elif msg_type == "reconnect":
                holder = get_execution_holder(session_id)
                if holder and not holder.get("done", True):
                    await _stream_execution_ws(
                        websocket, holder, session_id, app_state=app_state
                    )
                else:
                    await _send_event(
                        websocket,
                        "status",
                        {"status": "idle", "message": "No active execution to reconnect"},
                    )

            else:
                await _send_event(
                    websocket,
                    "error",
                    {"error": f"Unknown message type: {msg_type}"},
                )

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for session %s", session_id)
    except Exception as e:
        logger.error(
            "WebSocket error for session %s: %s", session_id, e, exc_info=True
        )
        try:
            await _send_event(websocket, "error", {"error": str(e)})
        except Exception:
            pass
