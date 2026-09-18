"""One session, one room.

A room is where you talk to ONE agent, and the only reason it is a thing
separate from the session is so every screen can open the same conversation.
These are the cases that broke that: a client picking a room by its own rule,
a session with several rooms, a session with none, and a session record still
pointing at a room it was taken out of.
"""

import sys
import types

import pytest


class FakeChatStore:
    def __init__(self, rooms=None):
        self.rooms = list(rooms or [])
        self.messages = {}
        self.created = []
        self.deleted = []
        self.renamed = []

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

    def update_room_name(self, room_id, name):
        self.renamed.append((room_id, name))
        room = self.get_room(room_id)
        if room:
            room["name"] = name
        return room

    def delete_room(self, room_id):
        self.deleted.append(room_id)
        self.rooms = [r for r in self.rooms if r["id"] != room_id]
        self.messages.pop(room_id, None)
        return True

    def get_messages(self, room_id, **_):
        return list(self.messages.get(room_id, []))

    def add_messages_batch(self, room_id, messages):
        # Like the real one: INSERT ... ON CONFLICT (message_id) DO NOTHING.
        # A message whose id already exists ANYWHERE is silently skipped, which
        # is what made copy-then-delete lose seven messages in production.
        known = {m.get("id") for msgs in self.messages.values() for m in msgs}
        fresh = [m for m in messages if m.get("id") not in known]
        self.messages.setdefault(room_id, []).extend(fresh)
        room = self.get_room(room_id)
        if room:
            room["message_count"] = len(self.messages[room_id])
        return fresh

    def resort_messages(self, room_id):
        self.messages.get(room_id, []).sort(key=lambda m: str(m.get("timestamp") or ""))

    def move_messages(self, source_id, target_id):
        moving = self.messages.pop(source_id, [])
        target = self.messages.setdefault(target_id, [])
        seen = {m.get("id") for m in target}
        target.extend(m for m in moving if m.get("id") not in seen)
        target.sort(key=lambda m: str(m.get("timestamp") or ""))
        room = self.get_room(target_id)
        if room:
            room["message_count"] = len(target)
        return len(moving)


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


def room(rid, sids, count, updated="2026-09-18T10:00:00Z", name="r"):
    return {"id": rid, "name": name, "session_ids": sids,
            "updated_at": updated, "message_count": count}


def test_creates_and_records_a_room_for_a_session_that_never_spoke(wired):
    home_room, chat, sessions = wired
    sessions.records["s1"] = {"session_name": "Worker"}

    made = home_room.resolve_home_room("s1")

    assert made["session_ids"] == ["s1"]
    assert made["name"] == "Worker"
    # Recorded, so every later caller gets the same answer without searching.
    assert ("s1", {"chat_room_id": made["id"]}) in sessions.updates
    assert home_room.resolve_home_room("s1")["id"] == made["id"]
    assert len(chat.created) == 1


def test_never_creates_when_asked_not_to(wired):
    home_room, chat, _ = wired
    assert home_room.resolve_home_room("s1", create=False) is None
    assert chat.created == []


def test_a_second_room_is_folded_into_the_first(wired):
    """The heart of it. Two rooms for one session is two conversations for one
    agent, and whichever one a screen picked was the one the other screens
    could not see."""
    home_room, chat, sessions = wired
    chat.rooms = [room("busy", ["s1"], 42), room("stray", ["s1"], 2, "2026-09-18T11:00:00Z")]
    chat.messages["busy"] = [{"id": "a", "timestamp": "t2"}]
    chat.messages["stray"] = [{"id": "b", "timestamp": "t1"}, {"id": "c", "timestamp": "t3"}]

    resolved = home_room.resolve_home_room("s1")

    assert resolved["id"] == "busy"
    assert chat.deleted == ["stray"], "the stray room must not survive the merge"
    # Its messages moved, keeping their ids, and the history reads in order.
    assert [m["id"] for m in chat.messages["busy"]] == ["b", "a", "c"]
    assert chat.created == []


def test_merging_keeps_going_when_one_stray_fails(wired):
    home_room, chat, _ = wired
    chat.rooms = [room("busy", ["s1"], 9), room("bad", ["s1"], 1), room("ok", ["s1"], 0)]

    original = chat.delete_room

    def explode(room_id):
        if room_id == "bad":
            raise RuntimeError("DB said no")
        return original(room_id)

    chat.delete_room = explode
    resolved = home_room.resolve_home_room("s1")

    assert resolved["id"] == "busy"
    assert "ok" in chat.deleted, "one bad room must not strand the others"


def test_the_room_wears_the_session_name(wired):
    home_room, chat, sessions = wired
    sessions.records["s1"] = {"session_name": "엘렌"}
    chat.rooms = [room("r1", ["s1"], 5, name="ellen_new Chat")]

    assert home_room.resolve_home_room("s1")["name"] == "엘렌"
    assert chat.renamed == [("r1", "엘렌")]


def test_session_ids_stored_as_json_text_still_match(wired):
    """DB rows carry session_ids as a JSON string; a rule that only understood
    lists silently found no room at all."""
    home_room, chat, _ = wired
    chat.rooms = [{"id": "r1", "name": "r", "session_ids": '["s1"]',
                   "updated_at": "2026-09-18T10:00:00Z", "message_count": 3}]

    assert home_room.resolve_home_room("s1")["id"] == "r1"


def test_a_session_that_left_a_room_is_not_pinned_to_it(wired):
    home_room, chat, sessions = wired
    sessions.records["s1"] = {"chat_room_id": "old"}
    chat.rooms = [room("old", ["s2"], 9), room("mine", ["s1"], 1)]

    assert home_room.resolve_home_room("s1")["id"] == "mine"
    assert ("s1", {"chat_room_id": "mine"}) in sessions.updates


def test_a_stale_claim_falls_through_instead_of_dead_ending(wired):
    home_room, chat, sessions = wired
    sessions.records["s1"] = {"chat_room_id": "deleted-room"}
    chat.rooms = [room("real", ["s1"], 5)]

    assert home_room.resolve_home_room("s1")["id"] == "real"


def test_a_merge_never_loses_a_message(wired):
    """It did, on production, seven of them. Inserts are ON CONFLICT DO
    NOTHING, so copying messages that still exist under the source room wrote
    nothing at all — and the delete that followed took the only copy. The
    merge moves them now, and this fake refuses duplicate ids exactly like
    the database does."""
    home_room, chat, _ = wired
    chat.rooms = [room("home", ["s1"], 9), room("stray", ["s1"], 3)]
    chat.messages["home"] = [{"id": "h1", "timestamp": "t5"}]
    chat.messages["stray"] = [
        {"id": "m1", "timestamp": "t1", "content": "내꺼 화면에서 네이버 보고"},
        {"id": "m2", "timestamp": "t2", "content": "잠깐만, 화면 보고 직접 해볼게."},
        {"id": "m3", "timestamp": "t3", "content": "1/1 sessions responded"},
    ]

    home_room.resolve_home_room("s1")

    surviving = [m["id"] for m in chat.messages["home"]]
    assert surviving == ["m1", "m2", "m3", "h1"], surviving
    assert "stray" not in chat.messages


def test_a_session_that_does_not_exist_gets_no_room(wired):
    """A deleted session left its agent in memory, and the first client to ask
    where its chat was got a brand new room built for a session that no longer
    existed — a conversation nobody can ever open again."""
    home_room, chat, _ = wired

    assert home_room.resolve_home_room("ghost") is None
    assert chat.created == []


def test_a_real_session_still_gets_one(wired):
    home_room, chat, sessions = wired
    sessions.records["s1"] = {"session_name": "Worker"}

    assert home_room.resolve_home_room("s1") is not None
    assert len(chat.created) == 1
