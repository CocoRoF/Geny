"""Room turns that were started and have not finished — kept on disk.

A room turn runs detached from the request that started it. When the process
goes away in the middle of one (a deploy, a crash, the OOM killer), the
user's message stays in the room with nothing after it and no turn running:
the conversation reads as a question the agent never saw. Nothing on disk
said the turn had ever started, so nothing could tell that apart from a turn
that finished without saying anything.

Every turn is written here when it starts and removed when it ends, however
it ends. Whatever is still here when nothing is running died with the
process; it is closed off with a note placed right after the question, once.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

#: What the room says under a question whose turn died with the process.
DEAD_TURN_NOTE = "응답이 중간에 끊겼습니다"

_lock = threading.Lock()
_turns: Optional[Dict[str, Dict[str, Any]]] = None


def _path() -> Path:
    from service.chat.conversation_store import _resolve_default_dir

    return _resolve_default_dir() / "open_turns.json"


def _load() -> Dict[str, Dict[str, Any]]:
    global _turns
    if _turns is None:
        try:
            raw = json.loads(_path().read_text(encoding="utf-8"))
            _turns = {k: v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}
        except FileNotFoundError:
            _turns = {}
        except Exception:  # noqa: BLE001 — a bad file must not stop a turn
            logger.warning("open_turns: unreadable %s — starting empty", _path(), exc_info=True)
            _turns = {}
    return _turns


def _save(turns: Dict[str, Dict[str, Any]]) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(turns, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 — bookkeeping, never the turn itself
        logger.warning("open_turns: could not write %s", path, exc_info=True)


def open_turn(room_id: str, turn_id: str, user_message: Dict[str, Any]) -> None:
    """A turn for ``user_message`` has started in ``room_id``."""
    with _lock:
        turns = _load()
        turns[room_id] = {
            "turn_id": turn_id,
            "message_id": user_message.get("id"),
            "timestamp": user_message.get("timestamp"),
        }
        _save(turns)


def close_turn(room_id: str, turn_id: str) -> None:
    """The turn has ended. A newer turn in the same room is left alone."""
    with _lock:
        turns = _load()
        entry = turns.get(room_id)
        if entry is not None and entry.get("turn_id") == turn_id:
            del turns[room_id]
            _save(turns)


def _note_timestamp(question_ts: Any) -> Optional[str]:
    """Just after the question, so the note sits under it — not at the end of
    whatever was said since."""
    try:
        return (datetime.fromisoformat(str(question_ts)) + timedelta(milliseconds=1)).isoformat()
    except (TypeError, ValueError):
        return None


def close_dead_turns(store: Any, is_running: Callable[[str], bool], room_id: Optional[str] = None) -> int:
    """Close off every open turn that is not running; returns how many.

    ``room_id`` limits it to one room (the cheap check a history read makes).
    """
    with _lock:
        turns = _load()
        rooms = [room_id] if room_id is not None else list(turns)
        dead = [(r, turns[r]) for r in rooms if r in turns and not is_running(r)]
        if not dead:
            return 0
        for r, _ in dead:
            del turns[r]
        _save(turns)

    closed = 0
    for r, entry in dead:
        note: Dict[str, Any] = {"type": "system", "content": DEAD_TURN_NOTE}
        ts = _note_timestamp(entry.get("timestamp"))
        if ts:
            note["timestamp"] = ts
        try:
            if store.get_room(r) is None:
                continue
            store.add_message(r, note)
            if ts and hasattr(store, "resort_messages"):
                store.resort_messages(r)
            closed += 1
        except Exception:  # noqa: BLE001
            logger.warning("open_turns: could not close the turn in room %s", r, exc_info=True)
    if closed:
        logger.info("open_turns: closed %d turn(s) that ended with the process", closed)
    return closed


def _reset_for_tests() -> None:
    global _turns
    with _lock:
        _turns = None


__all__ = ["DEAD_TURN_NOTE", "close_dead_turns", "close_turn", "open_turn"]
