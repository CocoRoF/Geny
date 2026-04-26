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


async def _send_event(ws: WebSocket, event_type: str, data: dict, session_id: str = "") -> bool:
    """Send a JSON event over WebSocket. Returns False if connection is lost."""
    try:
        await ws.send_json({"type": event_type, "data": _sanitize(data)})
        if event_type not in ("heartbeat", "log"):
            logger.debug(
                "[ExecWS:%s] sent event=%s data_keys=%s",
                session_id[:8] if session_id else "?",
                event_type,
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            )
        return True
    except Exception as exc:
        logger.warning(
            "[ExecWS:%s] failed to send event=%s: %s",
            session_id[:8] if session_id else "?",
            event_type,
            exc,
        )
        return False


# Per-session dedupe of (emotion, expression_index) so identical avatar
# states emitted on consecutive RESPONSE log entries don't spam the
# frontend. Cleared lazily — entries die naturally with the session;
# the upper bound is "one tuple per active VTuber session".
_LAST_EMITTED_AVATAR_STATE: dict = {}


async def _emit_avatar_state_for_log(
    entry_dict: dict, session_id: str, app_state: Any
) -> None:
    """
    Emit avatar state update based on log content.
    Mirrors the SSE implementation in agent_controller.py.
    Best-effort: never raises.

    TTS-fix (2026-04-26): dedupes consecutive identical
    ``(emotion, expression_index)`` for ``trigger=agent_output`` so a
    long response producing many RESPONSE log entries doesn't flood
    the frontend with redundant ``agent_output: joy`` events. The
    dedup is per-session and only applies to ``agent_output`` —
    ``state_change`` triggers (TOOL / GRAPH) keep firing because they
    represent transitions the operator wants to see.
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
            # Dedupe: skip if (emotion, index) hasn't changed.
            key = (emotion, index)
            if _LAST_EMITTED_AVATAR_STATE.get(session_id) == key:
                return
            _LAST_EMITTED_AVATAR_STATE[session_id] = key
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
    except Exception as exc:
        logger.debug("[ExecWS:%s] avatar state emission failed: %s", session_id[:8], exc)


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
    poll_interval = 0.10  # 100ms
    last_event_time = time.monotonic()
    start_time = holder.get("start_time", time.time())
    total_logs_sent = 0

    logger.info(
        "[ExecWS:%s] _stream_execution_ws started, cache_cursor=%d, has_logger=%s",
        session_id[:8], cache_cursor, session_logger is not None,
    )

    # Initial status
    if not await _send_event(ws, "status", {"status": "running", "message": "Execution started"}, session_id):
        logger.warning("[ExecWS:%s] connection lost on initial status", session_id[:8])
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
                if new_entries:
                    logger.debug(
                        "[ExecWS:%s] polling: %d new log entries (cursor=%d)",
                        session_id[:8], len(new_entries), cache_cursor,
                    )
                for entry in new_entries:
                    entry_dict = entry.to_dict()
                    if not await _send_event(ws, "log", entry_dict, session_id):
                        logger.warning("[ExecWS:%s] connection lost while streaming logs", session_id[:8])
                        return  # Connection lost
                    if app_state:
                        await _emit_avatar_state_for_log(entry_dict, session_id, app_state)
                    had_data = True
                    total_logs_sent += 1

            if had_data:
                last_event_time = time.monotonic()
            elif time.monotonic() - last_event_time >= heartbeat_interval:
                if not await _send_event(ws, "heartbeat", _build_heartbeat(), session_id):
                    logger.warning("[ExecWS:%s] connection lost on heartbeat", session_id[:8])
                    return
                last_event_time = time.monotonic()

            await asyncio.sleep(poll_interval)

        # Final drain
        await asyncio.sleep(0.05)
        if session_logger:
            final_entries, cache_cursor = session_logger.get_cache_entries_since(
                cache_cursor
            )
            if final_entries:
                logger.debug(
                    "[ExecWS:%s] final drain: %d entries", session_id[:8], len(final_entries),
                )
            for entry in final_entries:
                entry_dict = entry.to_dict()
                await _send_event(ws, "log", entry_dict, session_id)
                total_logs_sent += 1

    except Exception as e:
        logger.error("[ExecWS:%s] stream error: %s", session_id[:8], e, exc_info=True)
        await _send_event(ws, "error", {"error": str(e)}, session_id)

    # Emit final result or error
    if holder.get("error"):
        logger.info(
            "[ExecWS:%s] execution finished with error: %s (total_logs=%d)",
            session_id[:8], holder["error"][:100], total_logs_sent,
        )
        await _send_event(
            ws, "status", {"status": "error", "message": holder["error"]}, session_id,
        )
        await _send_event(ws, "result", holder.get("result", {}), session_id)
    else:
        logger.info(
            "[ExecWS:%s] execution completed successfully (total_logs=%d)",
            session_id[:8], total_logs_sent,
        )
        await _send_event(
            ws, "status", {"status": "completed", "message": "Execution completed"}, session_id,
        )
        await _send_event(ws, "result", holder.get("result", {}), session_id)

    await _send_event(ws, "done", {}, session_id)

    # Cleanup execution holder
    cleanup_execution(session_id)
    logger.debug("[ExecWS:%s] execution holder cleaned up", session_id[:8])


@router.websocket("/ws/execute/{session_id}")
async def ws_execute_stream(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for streaming agent execution.

    Supports three message types from the client:

    1. execute -- Start a new execution:
       {"type": "execute", "prompt": "...", "timeout": null, "system_prompt": null, "max_turns": null}

    2. stop -- Stop the current execution:
       {"type": "stop"}

    3. reconnect -- Reconnect to an active execution:
       {"type": "reconnect"}

    The server streams events in real time until execution completes,
    then sends a "done" event. The connection stays open for further
    commands (multi-turn conversation over a single WebSocket).
    """
    logger.info("[ExecWS:%s] WebSocket connection attempt", session_id[:8])
    await websocket.accept()
    logger.info("[ExecWS:%s] WebSocket accepted", session_id[:8])
    app_state = websocket.app.state

    # Cycle 20260421_8 PR-X2-6 — WS abandoned detector. When this is the
    # only attached WS and stays disconnected past the detector's
    # threshold, SESSION_ABANDONED fires on the lifecycle bus.
    abandoned_detector = getattr(app_state, "ws_abandoned_detector", None)
    if abandoned_detector is not None:
        abandoned_detector.connect(session_id)

    try:
        while True:
            raw = await websocket.receive_text()
            logger.debug("[ExecWS:%s] received: %s", session_id[:8], raw[:200])
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[ExecWS:%s] invalid JSON: %s", session_id[:8], raw[:100])
                await _send_event(
                    websocket, "error", {"error": "Invalid JSON"}, session_id,
                )
                continue

            msg_type = msg.get("type", "")

            if msg_type == "execute":
                prompt = (msg.get("prompt") or "").strip()
                if not prompt:
                    await _send_event(
                        websocket, "error", {"error": "Prompt must not be empty"}, session_id,
                    )
                    continue

                logger.info(
                    "[ExecWS:%s] execute request: prompt=%s, timeout=%s, max_turns=%s",
                    session_id[:8], prompt[:80], msg.get("timeout"), msg.get("max_turns"),
                )

                try:
                    holder = await start_command_background(
                        session_id=session_id,
                        prompt=prompt,
                        timeout=msg.get("timeout"),
                        system_prompt=msg.get("system_prompt"),
                        max_turns=msg.get("max_turns"),
                    )
                    logger.info(
                        "[ExecWS:%s] execution started, exec_id=%s",
                        session_id[:8], holder.get("exec_id", "?")[:8],
                    )
                except AgentNotFoundError:
                    logger.warning("[ExecWS:%s] agent not found", session_id[:8])
                    await _send_event(
                        websocket,
                        "error",
                        {"error": f"AgentSession not found: {session_id}"},
                        session_id,
                    )
                    continue
                except AgentNotAliveError as e:
                    logger.warning("[ExecWS:%s] agent not alive: %s", session_id[:8], e)
                    await _send_event(
                        websocket, "error", {"error": str(e)}, session_id,
                    )
                    continue
                except AlreadyExecutingError:
                    logger.warning("[ExecWS:%s] already executing", session_id[:8])
                    await _send_event(
                        websocket,
                        "error",
                        {"error": "Execution already in progress"},
                        session_id,
                    )
                    continue

                await _stream_execution_ws(
                    websocket, holder, session_id, app_state=app_state
                )

            elif msg_type == "stop":
                logger.info("[ExecWS:%s] stop request", session_id[:8])
                stopped = await stop_execution(session_id)
                logger.info("[ExecWS:%s] stop result: %s", session_id[:8], stopped)
                await _send_event(
                    websocket,
                    "status",
                    {
                        "status": "stopped" if stopped else "idle",
                        "message": "Execution stopped" if stopped else "No active execution",
                    },
                    session_id,
                )

            elif msg_type == "reconnect":
                logger.info("[ExecWS:%s] reconnect request", session_id[:8])
                holder = get_execution_holder(session_id)
                if holder and not holder.get("done", True):
                    logger.info(
                        "[ExecWS:%s] reconnecting to active execution, exec_id=%s",
                        session_id[:8], holder.get("exec_id", "?")[:8],
                    )
                    await _stream_execution_ws(
                        websocket, holder, session_id, app_state=app_state
                    )
                else:
                    logger.info("[ExecWS:%s] no active execution to reconnect", session_id[:8])
                    await _send_event(
                        websocket,
                        "status",
                        {"status": "idle", "message": "No active execution to reconnect"},
                        session_id,
                    )

            else:
                logger.warning("[ExecWS:%s] unknown message type: %s", session_id[:8], msg_type)
                await _send_event(
                    websocket,
                    "error",
                    {"error": f"Unknown message type: {msg_type}"},
                    session_id,
                )

    except WebSocketDisconnect:
        logger.info("[ExecWS:%s] WebSocket disconnected", session_id[:8])
    except Exception as e:
        logger.error(
            "[ExecWS:%s] WebSocket error: %s", session_id[:8], e, exc_info=True
        )
        try:
            await _send_event(websocket, "error", {"error": str(e)}, session_id)
        except Exception:
            pass
    finally:
        if abandoned_detector is not None:
            abandoned_detector.disconnect(session_id)
