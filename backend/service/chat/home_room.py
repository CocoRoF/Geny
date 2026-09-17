"""Where a session's conversation lives.

**One session, one room.** A room is not a group chat — it is the place you
talk to ONE agent, and the only reason it exists as a thing separate from the
session is so that every screen (the web page, the desktop app, the phone) can
open the same conversation and see the same state. That is its whole job.

It used to be a messenger: rooms held several sessions, a message was
broadcast to all of them, and the room list was a thing you browsed. That is
gone. What is left is this file, which answers one question — *which room is
this session's?* — and makes sure the answer stays unique:

1. the rooms that list this session, busiest first
2. the busiest one is the home; any others are folded INTO it (their messages
   moved, then deleted), because two rooms for one session is two
   conversations for one agent
3. no room at all → make one

The answer is written back to the session record, and the room's name follows
the session's, so the two never disagree about what they are.

Everything that needs a room calls ``resolve_home_room``: the REST door
(``GET /api/chat/rooms/for-session/{id}``), the session manager, and the
agent's own autonomous deliveries. A caller that picks a room by its own rule
re-creates the bug this module exists to make impossible — three surfaces,
three conversations.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def session_ids_of(room: Dict[str, Any]) -> List[str]:
    """Rooms loaded from the DB carry ``session_ids`` as a JSON string."""
    sids = room.get("session_ids")
    if isinstance(sids, str):
        try:
            sids = json.loads(sids)
        except Exception:  # noqa: BLE001
            return []
    return list(sids or [])


def rooms_of(session_id: str) -> List[Dict[str, Any]]:
    """Every room that lists this session, busiest first.

    Ties break on recency. Under the invariant this returns 0 or 1 rooms;
    more than that is history, and the caller folds them together.
    """
    from service.chat.conversation_store import get_chat_store

    try:
        rooms = get_chat_store().list_rooms() or []
    except Exception:  # noqa: BLE001
        logger.warning("[home-room] could not list rooms", exc_info=True)
        return []
    mine = [r for r in rooms if session_id in session_ids_of(r)]
    mine.sort(
        key=lambda r: (int(r.get("message_count") or 0), str(r.get("updated_at") or "")),
        reverse=True,
    )
    return mine


def best_existing_room(session_id: str) -> Optional[Dict[str, Any]]:
    """The room this session already talks in, or None."""
    found = rooms_of(session_id)
    return found[0] if found else None


def merge_rooms(source_id: str, target_id: str) -> int:
    """Move a stray room's messages into the home room and delete it.

    Returns how many messages moved. Ids and timestamps are preserved, so the
    merged history reads in the order it happened and a client that has
    already seen a message still recognises it.

    The move happens in one statement and the room only goes afterwards — the
    first version of this copied and then deleted, which loses everything the
    target refuses as a duplicate id. It refused all of them, because the
    originals were still there when they were offered.
    """
    from service.chat.conversation_store import get_chat_store

    if source_id == target_id:
        return 0
    store = get_chat_store()
    moved = store.move_messages(source_id, target_id)
    store.delete_room(source_id)
    logger.info(
        "[home-room] merged room %s into %s (%d messages)",
        source_id, target_id, moved,
    )
    return moved


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


def _session_label(session_id: str, record: Dict[str, Any], name_hint: str) -> str:
    return name_hint or record.get("session_name") or session_id[:8]


def resolve_home_room(
    session_id: str,
    *,
    create: bool = True,
    name_hint: str = "",
) -> Optional[Dict[str, Any]]:
    """This session's one conversation, creating it when there is none.

    Returns the room dict (``id``, ``name``, ``session_ids``, …), or None when
    the session has no room and ``create`` is False.
    """
    from service.chat.conversation_store import get_chat_store

    store = get_chat_store()

    record: Dict[str, Any] = {}
    try:
        from service.sessions.store import get_session_store

        record = get_session_store().get(session_id) or {}
    except Exception:  # noqa: BLE001
        logger.debug("[home-room] no session record for %s", session_id, exc_info=True)

    mine = rooms_of(session_id)

    if not mine:
        if not create:
            return None
        label = _session_label(session_id, record, name_hint)
        room = store.create_room(label, [session_id])
        room_id = room.get("id") or room.get("room_id")
        if room_id:
            _record_on_session(session_id, str(room_id))
        logger.info("[home-room] created room %s for session %s", room_id, session_id)
        return room

    home = mine[0]
    home_id = str(home.get("id") or home.get("room_id") or "")
    if not home_id:
        return None

    # One session, one room. Anything else this session sits in is folded in
    # here and gone — a second room is a second conversation nobody can find.
    for stray in mine[1:]:
        stray_id = str(stray.get("id") or stray.get("room_id") or "")
        if not stray_id:
            continue
        try:
            merge_rooms(stray_id, home_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "[home-room] could not merge %s into %s", stray_id, home_id, exc_info=True,
            )

    if record.get("chat_room_id") != home_id:
        _record_on_session(session_id, home_id)

    # The room is the session's, so it wears the session's name. Only the
    # label — renaming never moves a conversation.
    label = _session_label(session_id, record, name_hint)
    if label and home.get("name") != label:
        try:
            store.update_room_name(home_id, label)
        except Exception:  # noqa: BLE001
            logger.debug("[home-room] could not rename %s", home_id, exc_info=True)

    return store.get_room(home_id) or home
