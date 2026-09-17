"""Where a session's conversation lives — one rule, held down.

These are the cases that produced three different conversations for one
session: a client scanning the room list with its own tie-break, a session
with no room at all, and a session record still pointing at a room it was
taken out of.
"""

import sys
import types

import pytest


class FakeChatStore:
    def __init__(self, rooms=None):
        self.rooms = list(rooms or [])
        self.created = []

    def list_rooms(self):
        return list(self.rooms)

    def get_room(self, room_id):
        for r in self.rooms:
            if r["id"] == room_id:
                return r
        return None

    def create_room(self, name, session_ids):
        room = {
            "id": f"room-{len(self.rooms) + 1}",
            "name": name,
            "session_ids": list(session_ids),
            "created_at": "2026-09-18T00:00:00Z",
            "updated_at": "2026-09-18T00:00:00Z",
            "message_count": 0,
        }
        self.rooms.append(room)
        self.created.append(room)
        return room


class FakeSessionStore:
    def __init__(self, records=None):
        self.records = dict(records or {})
        self.updates = []

    def get(self, session_id):
        return self.records.get(session_id)

    def update(self, session_id, updates):
        self.updates.append((session_id, updates))
        self.records.setdefault(session_id, {}).update(updates)


@pytest.fixture
def wired(monkeypatch):
    """Point the module's two lazy imports at fakes."""
    chat = FakeChatStore()
    sessions = FakeSessionStore()

    conv = types.ModuleType("service.chat.conversation_store")
    conv.get_chat_store = lambda: chat
    monkeypatch.setitem(sys.modules, "service.chat.conversation_store", conv)

    store_mod = types.ModuleType("service.sessions.store")
    store_mod.get_session_store = lambda: sessions
    monkeypatch.setitem(sys.modules, "service.sessions.store", store_mod)

    # The agent manager is best-effort; make its absence explicit rather than
    # importing the real executor into a unit test.
    executor = types.ModuleType("service.executor")

    def _boom():
        raise RuntimeError("no manager in this test")

    executor.get_agent_session_manager = _boom
    monkeypatch.setitem(sys.modules, "service.executor", executor)

    import importlib

    module = importlib.import_module("service.chat.home_room")
    return module, chat, sessions


def test_creates_and_records_a_room_for_a_session_that_never_spoke(wired):
    home_room, chat, sessions = wired
    sessions.records["s1"] = {"session_name": "Worker"}

    room = home_room.resolve_home_room("s1")

    assert room["session_ids"] == ["s1"]
    assert room["name"] == "Worker Chat"
    # Recorded, so every later caller gets the same answer without searching.
    assert ("s1", {"chat_room_id": room["id"]}) in sessions.updates
    assert home_room.resolve_home_room("s1")["id"] == room["id"]
    assert len(chat.created) == 1


def test_never_creates_when_asked_not_to(wired):
    home_room, chat, _ = wired
    assert home_room.resolve_home_room("s1", create=False) is None
    assert chat.created == []


def test_adopts_the_busiest_existing_room_rather_than_opening_a_new_one(wired):
    """The bug this file exists for: a session that already has a conversation
    must not be handed an empty room because nobody wrote it down."""
    home_room, chat, sessions = wired
    chat.rooms = [
        {"id": "quiet", "name": "q", "session_ids": ["s1"],
         "updated_at": "2026-09-18T10:00:00Z", "message_count": 0},
        {"id": "busy", "name": "b", "session_ids": ["s1", "s2"],
         "updated_at": "2026-09-17T09:00:00Z", "message_count": 42},
    ]

    room = home_room.resolve_home_room("s1")

    assert room["id"] == "busy"
    assert chat.created == []
    assert ("s1", {"chat_room_id": "busy"}) in sessions.updates


def test_session_ids_stored_as_json_text_still_match(wired):
    """DB rows carry session_ids as a JSON string; a client-side rule that
    only understood lists silently found no room at all."""
    home_room, chat, _ = wired
    chat.rooms = [{"id": "r1", "name": "r", "session_ids": '["s1"]',
                   "updated_at": "2026-09-18T10:00:00Z", "message_count": 3}]

    assert home_room.resolve_home_room("s1")["id"] == "r1"


def test_a_stale_claim_falls_through_instead_of_dead_ending(wired):
    home_room, chat, sessions = wired
    sessions.records["s1"] = {"chat_room_id": "deleted-room"}
    chat.rooms = [{"id": "real", "name": "r", "session_ids": ["s1"],
                   "updated_at": "2026-09-18T10:00:00Z", "message_count": 5}]

    assert home_room.resolve_home_room("s1")["id"] == "real"


def test_a_claim_on_a_room_the_session_left_is_not_honoured(wired):
    """The room editor can take a session out of a room. Staying pinned to it
    would show the user a conversation they are no longer part of."""
    home_room, chat, sessions = wired
    sessions.records["s1"] = {"chat_room_id": "old"}
    chat.rooms = [
        {"id": "old", "name": "o", "session_ids": ["s2"],
         "updated_at": "2026-09-18T10:00:00Z", "message_count": 9},
        {"id": "mine", "name": "m", "session_ids": ["s1"],
         "updated_at": "2026-09-18T11:00:00Z", "message_count": 1},
    ]

    assert home_room.resolve_home_room("s1")["id"] == "mine"
