"""Where a session's conversation lives.

One rule, one place. A Geny session's conversation is a chat **room**, and
every surface — the web page, the desktop app, the phone, and the agent's own
autonomous deliveries — must agree on which room that is. When they each
decided for themselves they drifted: the web read the room with the most
messages, a client read the most recently updated one, and a session with no
room at all got a fresh empty one from whoever asked first. Three surfaces,
three conversations, which is exactly the bug this module exists to make
impossible.

The rule, in order:

1. the session record's ``chat_room_id`` — what the session itself says
2. the best existing room that lists this session: most messages, tiebreak
   most recently updated (an old conversation is never orphaned behind a new
   empty room)
3. a new room, created and recorded on the session

Resolution is idempotent and the answer is written back to the session record,
so step 1 answers every subsequent call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _session_ids_of(room: Dict[str, Any]) -> List[str]:
    """Rooms loaded from the DB carry ``session_ids`` as a JSON string."""
    sids = room.get("session_ids")
    if isinstance(sids, str):
        try:
            sids = json.loads(sids)
        except Exception:  # noqa: BLE001
            return []
    return list(sids or [])


def best_existing_room(session_id: str) -> Optional[Dict[str, Any]]:
    """The room this session already talks in, or None."""
    from service.chat.conversation_store import get_chat_store

    try:
        rooms = get_chat_store().list_rooms() or []
    except Exception:  # noqa: BLE001
        logger.warning("[home-room] could not list rooms", exc_info=True)
        return None
    mine = [r for r in rooms if session_id in _session_ids_of(r)]
    if not mine:
        return None
    mine.sort(
        key=lambda r: (int(r.get("message_count") or 0), str(r.get("updated_at") or "")),
        reverse=True,
    )
    return mine[0]


def _record_on_session(session_id: str, room_id: str) -> None:
    """Remember the answer, so the next call is a single lookup."""
    try:
        from service.sessions.store import get_session_store

        get_session_store().update(session_id, {"chat_room_id": room_id})
    except Exception:  # noqa: BLE001
        logger.debug("[home-room] could not record room on %s", session_id, exc_info=True)
    # An agent already in memory caches it too; keeping the two in step means a
    # hook delivery and a user message land in the same place.
    try:
        from service.executor import get_agent_session_manager

        agent = get_agent_session_manager().get_agent(session_id)
        if agent is not None:
            agent._chat_room_id = room_id
    except Exception:  # noqa: BLE001
        pass


def resolve_home_room(
    session_id: str,
    *,
    create: bool = True,
    name_hint: str = "",
) -> Optional[Dict[str, Any]]:
    """This session's conversation room, creating one when it has none.

    Returns the room dict (``id``, ``name``, ``session_ids``, …) or None when
    the session has no room and ``create`` is False.
    """
    from service.chat.conversation_store import get_chat_store

    store = get_chat_store()

    # 1. what the session says
    record: Dict[str, Any] = {}
    try:
        from service.sessions.store import get_session_store

        record = get_session_store().get(session_id) or {}
    except Exception:  # noqa: BLE001
        logger.debug("[home-room] no session record for %s", session_id, exc_info=True)
    claimed = record.get("chat_room_id")
    if claimed:
        room = store.get_room(claimed)
        # A stale id — the room was deleted, or the session was taken out of it
        # in the room editor — falls through to the search rather than pinning
        # the session to a conversation it is no longer part of.
        if room and session_id in _session_ids_of(room):
            return room

    # 2. the best room that already lists it
    found = best_existing_room(session_id)
    if found:
        room_id = found.get("id") or found.get("room_id")
        if room_id:
            if room_id != claimed:
                _record_on_session(session_id, str(room_id))
            # list_rooms rows are summaries; hand back the full room.
            return store.get_room(str(room_id)) or found

    if not create:
        return None

    # 3. a new one
    label = name_hint or record.get("session_name") or session_id[:8]
    room = store.create_room(f"{label} Chat", [session_id])
    room_id = room.get("id") or room.get("room_id")
    if room_id:
        _record_on_session(session_id, str(room_id))
    logger.info("[home-room] created room %s for session %s", room_id, session_id)
    return room
