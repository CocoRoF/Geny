"""Session-agnostic autonomous-message delivery.

``post_autonomous_message`` posts an autonomous agent result (from a Hook fire
or a VTuber thinking trigger) into the owning session's chat room and wakes SSE
listeners. Unlike the original VTuber-only path, it resolves-or-creates the
home room, so it works for Command sessions too — they have no
``agent._chat_room_id`` until the first delivery.

Silence contract: an event Hook that finds nothing must NOT spam the chat. The
agent signals "nothing to report" with a leading ``[SILENT]`` tag; delivery is
skipped before the tag is stripped (so ``[SILENT] trailing`` cannot leak).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Anchored: only a result that STARTS with [SILENT] is treated as silence, so a
# normal message that merely mentions the word is unaffected.
_SILENT_RE = re.compile(r"^\s*\[SILENT\]", re.IGNORECASE)


def _is_silent(raw: str) -> bool:
    return bool(_SILENT_RE.match(raw or ""))


def _resolve_or_create_room(agent: Any, session_id: str) -> Optional[str]:
    """This session's chat room, creating one if it has none yet.

    The rule lives in ``service.chat.home_room`` — the same one the REST door
    (``GET /api/chat/rooms/for-session/{id}``) answers with, so an autonomous
    delivery lands in the room the user is actually looking at.
    """
    room_id = getattr(agent, "_chat_room_id", None)
    if room_id:
        return room_id
    from service.chat.home_room import resolve_home_room

    room = resolve_home_room(
        session_id,
        create=True,
        name_hint=getattr(agent, "_session_name", "") or "",
    )
    if not room:
        logger.warning("[autonomous-delivery] room resolve failed for %s", session_id)
        return None
    room_id = room.get("id") or room.get("room_id")
    if room_id:
        agent._chat_room_id = room_id
    return room_id


def post_autonomous_message(session_id: str, result: Any, *, source: str = "hook") -> Optional[str]:
    """Deliver an autonomous agent result into ``session_id``'s chat room.

    Returns the room id on success, or None when nothing was delivered (empty
    result, silence sentinel, no agent, or room resolution failed). Never
    raises — autonomous delivery must not break the caller.
    """
    try:
        raw = (getattr(result, "output", "") or "") if getattr(result, "success", False) else ""
        if _is_silent(raw):
            logger.info("[autonomous-delivery] %s silent for %s — skipping", source, session_id)
            return None

        from service.utils.text_sanitizer import sanitize_for_display

        cleaned = sanitize_for_display(raw)
        if not cleaned:
            return None

        from service.executor import get_agent_session_manager

        mgr = get_agent_session_manager()
        agent = mgr.get_agent(session_id)
        if not agent:
            logger.warning("[autonomous-delivery] no agent for %s — skipping", session_id)
            return None

        room_id = _resolve_or_create_room(agent, session_id)
        if not room_id:
            logger.warning("[autonomous-delivery] no chat room for %s — skipping", session_id)
            return None

        from service.chat.conversation_store import get_chat_store

        store = get_chat_store()
        session_name = getattr(agent, "_session_name", None) or session_id
        role_val = getattr(agent, "_role", None)
        role = role_val.value if hasattr(role_val, "value") else str(role_val or "agent")

        msg_payload: Dict[str, Any] = {
            "type": "agent",
            "content": cleaned,
            "session_id": session_id,
            "session_name": session_name,
            "role": role,
            "duration_ms": getattr(result, "duration_ms", None),
            "cost_usd": getattr(result, "cost_usd", None),
            "source": source,
            # The emotion cues, for the avatar and the voice (see ExecutionResult.spoken).
            "spoken": getattr(result, "spoken", None),
        }
        # Files delivered via SendUserFile during this autonomous turn
        # (workspace-canvas P1) — same attachments contract as chat turns.
        _atts = getattr(result, "attachments", None)
        if _atts:
            msg_payload["attachments"] = list(_atts)
        msg = store.add_message(room_id, msg_payload)
        logger.info(
            "[autonomous-delivery] %s → room %s (msg_id=%s, len=%d)",
            source, room_id, msg.get("id", "?"), len(cleaned),
        )

        try:
            from controller.chat_controller import _notify_room

            _notify_room(room_id)
        except Exception:  # noqa: BLE001
            logger.warning("[autonomous-delivery] _notify_room failed for %s", room_id, exc_info=True)

        return room_id
    except Exception:  # noqa: BLE001
        logger.warning("[autonomous-delivery] failed to deliver for %s", session_id, exc_info=True)
        return None
