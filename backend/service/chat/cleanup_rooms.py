"""The room janitor: one session, one room, nothing else.

Rooms accumulated for years under rules that no longer hold. A room was a
messenger room — you made them, you could make several for the same session,
and nothing removed one when its session was deleted. The result on the
production server was 325 rooms for 1 live session: 263 of them empty, 204
belonging to sessions that no longer exist, and the live session itself
holding four rooms, three of which had a handful of stranded messages in them.

This puts that right, and is safe to run again afterwards (it does nothing on
a clean store):

* **merge** — a session with several rooms keeps the busiest, and the others'
  messages move into it before they go. Nothing is dropped on the floor.
* **retire** — a room whose sessions no longer exist is unreachable: with the
  messenger gone there is no list to open it from and no session to resolve it
  through. It is backed up, then deleted.
* **report** — what it would do, and what it did.

Dry by default. Deleting a conversation is not undoable, so it writes every
room it removes (metadata AND messages) to a JSON backup first, and refuses to
delete without one.

    python -m service.chat.cleanup_rooms                    # report only
    python -m service.chat.cleanup_rooms --apply            # do it
    python -m service.chat.cleanup_rooms --apply --backup /data/rooms.json
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Plan:
    """What the janitor found, and what it would do about it."""
    total_rooms: int = 0
    live_sessions: int = 0
    keep: List[str] = field(default_factory=list)
    merge: List[Dict[str, Any]] = field(default_factory=list)
    retire: List[Dict[str, Any]] = field(default_factory=list)
    merged_messages: int = 0
    retired_messages: int = 0

    def render(self) -> str:
        lines = [
            f"rooms            : {self.total_rooms}",
            f"live sessions    : {self.live_sessions}",
            f"keep             : {len(self.keep)}",
            f"merge away       : {len(self.merge)}  ({self.merged_messages} messages move)",
            f"retire           : {len(self.retire)}  ({self.retired_messages} messages, backed up)",
        ]
        for m in self.merge[:10]:
            lines.append(f"   merge {m['room_id'][:8]} → {m['into'][:8]}  ({m['messages']} msgs)")
        for r in self.retire[:10]:
            lines.append(f"   retire {r['room_id'][:8]} {r['name'][:28]!r}  ({r['messages']} msgs)")
        if len(self.retire) > 10:
            lines.append(f"   … and {len(self.retire) - 10} more")
        return "\n".join(lines)


def attach_database() -> bool:
    """Wire the stores to PostgreSQL, as ``main.py`` does at startup.

    Run as a one-off process this matters more than it looks: sessions live
    ONLY in the database, while rooms also have a JSON backup on disk. So an
    unwired process sees every room and no sessions at all — and concludes
    that every conversation on the server is an orphan. The first dry run of
    this tool said exactly that: retire 325 rooms, 5,698 messages, including
    the live one.
    """
    try:
        from service.database import APPLICATION_MODELS, AppDatabaseManager

        app_db = AppDatabaseManager()
        app_db.register_models(APPLICATION_MODELS)
        # Registering models is not connecting. Without the pool every read
        # comes back empty and nothing raises — which is the same silence as
        # "this server has no sessions".
        if not app_db.connect():
            logger.error("[rooms] could not connect to PostgreSQL")
            return False
    except Exception:  # noqa: BLE001
        logger.error("[rooms] no database — refusing to judge what is orphaned", exc_info=True)
        return False

    from service.chat.conversation_store import get_chat_store
    from service.sessions.store import get_session_store

    sessions = get_session_store()
    sessions.set_database(app_db)
    get_chat_store().set_database(app_db)

    # `_db_available` is the exact predicate the store itself uses to decide
    # whether a read goes to the database or falls back to the JSON copy on
    # disk. If it says no, this tool is about to compare rooms it CAN see
    # against sessions it cannot.
    if not sessions._db_available:
        logger.error("[rooms] the session store is not reading from the database")
        return False
    return True


def _live_session_ids() -> set:
    from service.sessions.store import get_session_store

    store = get_session_store()
    ids = {r.get("session_id") for r in (store.list_all() or [])}
    # A soft-deleted session can still be restored, and restoring one whose
    # conversation had been swept would hand the user an empty room.
    try:
        ids |= {r.get("session_id") for r in (store.list_deleted() or [])}
    except Exception:  # noqa: BLE001
        logger.debug("[rooms] could not list deleted sessions", exc_info=True)
    return {i for i in ids if i}


def survey() -> Plan:
    """Work out what should happen. Touches nothing."""
    from service.chat.conversation_store import get_chat_store
    from service.chat.home_room import session_ids_of

    store = get_chat_store()
    rooms = store.list_rooms() or []
    live = _live_session_ids()

    plan = Plan(total_rooms=len(rooms), live_sessions=len(live))

    by_session: Dict[str, List[Dict[str, Any]]] = {}
    for room in rooms:
        owners = [s for s in session_ids_of(room) if s in live]
        if not owners:
            plan.retire.append({
                "room_id": str(room.get("id") or room.get("room_id") or ""),
                "name": str(room.get("name") or ""),
                "messages": int(room.get("message_count") or 0),
                "session_ids": session_ids_of(room),
            })
            plan.retired_messages += int(room.get("message_count") or 0)
            continue
        # A room shared by several live sessions is the messenger's last
        # artefact. Its home is the first session that owns it; the others
        # will resolve to their own.
        by_session.setdefault(owners[0], []).append(room)

    for session_id, mine in by_session.items():
        mine.sort(
            key=lambda r: (int(r.get("message_count") or 0), str(r.get("updated_at") or "")),
            reverse=True,
        )
        home = str(mine[0].get("id") or mine[0].get("room_id") or "")
        plan.keep.append(home)
        for stray in mine[1:]:
            count = int(stray.get("message_count") or 0)
            plan.merge.append({
                "room_id": str(stray.get("id") or stray.get("room_id") or ""),
                "into": home,
                "session_id": session_id,
                "messages": count,
            })
            plan.merged_messages += count

    return plan


def _write_backup(path: Path, rooms: List[Dict[str, Any]]) -> int:
    """Save rooms and their messages before anything is deleted."""
    from service.chat.conversation_store import get_chat_store

    store = get_chat_store()
    payload = {
        "written_at": datetime.now(timezone.utc).isoformat(),
        "reason": "room cleanup — sessions no longer exist",
        "rooms": [],
    }
    saved = 0
    for room in rooms:
        room_id = room["room_id"]
        try:
            messages = store.get_messages(room_id) or []
        except Exception:  # noqa: BLE001
            logger.warning("[rooms] could not read %s for backup", room_id, exc_info=True)
            messages = []
        payload["rooms"].append({**room, "messages": messages})
        saved += len(messages)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return saved


def clean(apply: bool = False, backup: Optional[Path] = None) -> Plan:
    """Report, and when asked, carry it out."""
    from service.chat.conversation_store import get_chat_store
    from service.chat.home_room import merge_rooms

    plan = survey()
    if not apply:
        return plan

    # "No sessions at all" is not a finding, it is a failed lookup — and it
    # is the one that would delete every conversation on the server. A store
    # that cannot see a single session cannot be trusted to say which rooms
    # are orphans.
    if plan.live_sessions == 0 and plan.total_rooms > 0:
        raise RuntimeError(
            f"{plan.total_rooms} rooms and 0 sessions — the session store is not "
            "connected. Refusing to treat every conversation as an orphan."
        )

    store = get_chat_store()

    for item in plan.merge:
        try:
            merge_rooms(item["room_id"], item["into"])
        except Exception:  # noqa: BLE001
            logger.error("[rooms] merge failed for %s", item["room_id"], exc_info=True)

    if plan.retire:
        if backup is None:
            raise ValueError("refusing to delete rooms without a backup path")
        written = _write_backup(backup, plan.retire)
        logger.info("[rooms] backed up %d rooms / %d messages to %s",
                    len(plan.retire), written, backup)
        for item in plan.retire:
            try:
                store.delete_room(item["room_id"])
            except Exception:  # noqa: BLE001
                logger.error("[rooms] delete failed for %s", item["room_id"], exc_info=True)

    # Re-resolve every surviving session so its record points at the room it
    # actually has, and its name matches.
    try:
        from service.chat.home_room import resolve_home_room

        for session_id in _live_session_ids():
            resolve_home_room(session_id, create=False)
    except Exception:  # noqa: BLE001
        logger.warning("[rooms] post-clean resolve failed", exc_info=True)

    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="carry it out")
    parser.add_argument(
        "--backup",
        default="/data/mcp/room-cleanup-backup.json",
        help="where to save rooms before deleting them",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not attach_database():
        print("database unavailable — nothing was touched")
        return 2
    plan = clean(apply=args.apply, backup=Path(args.backup) if args.apply else None)
    print(plan.render())
    print("APPLIED" if args.apply else "DRY RUN — pass --apply to carry it out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
