"""A room turn cut off by the process going away is closed off, once.

Before this, a deploy in the middle of a turn left the user's message with
nothing after it and no turn running: the question read as one the agent
never saw, and nothing on disk could tell it apart from a turn that finished
without a word.
"""

import pytest

from service.chat import open_turns


class _Store:
    def __init__(self):
        self.rooms = {"r1": {"id": "r1"}, "r2": {"id": "r2"}}
        self.added = []
        self.resorted = []

    def get_room(self, room_id):
        return self.rooms.get(room_id)

    def add_message(self, room_id, message):
        self.added.append((room_id, dict(message)))
        return message

    def resort_messages(self, room_id):
        self.resorted.append(room_id)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GENY_CHAT_CONVERSATIONS_DIR", str(tmp_path))
    open_turns._reset_for_tests()
    yield
    open_turns._reset_for_tests()


def _question(mid="m1", ts="2026-09-29T03:00:00.000000+00:00"):
    return {"id": mid, "timestamp": ts}


def test_a_turn_that_ended_leaves_nothing_behind():
    store = _Store()
    open_turns.open_turn("r1", "t1", _question())
    open_turns.close_turn("r1", "t1")
    open_turns._reset_for_tests()  # a new process
    assert open_turns.close_dead_turns(store, lambda _r: False) == 0
    assert store.added == []


def test_a_turn_cut_off_by_a_restart_is_closed_under_its_question():
    store = _Store()
    open_turns.open_turn("r1", "t1", _question())
    open_turns._reset_for_tests()  # the process went away mid-turn

    assert open_turns.close_dead_turns(store, lambda _r: False) == 1
    room, note = store.added[0]
    assert room == "r1"
    assert note["type"] == "system"
    assert note["content"] == open_turns.DEAD_TURN_NOTE
    assert note["timestamp"] == "2026-09-29T03:00:00.001000+00:00"
    assert store.resorted == ["r1"]
    # Once.
    assert open_turns.close_dead_turns(store, lambda _r: False) == 0


def test_a_running_turn_is_not_touched():
    store = _Store()
    open_turns.open_turn("r1", "t1", _question())
    assert open_turns.close_dead_turns(store, lambda r: r == "r1", room_id="r1") == 0
    assert store.added == []


def test_an_older_turn_ending_does_not_close_the_newer_one():
    store = _Store()
    open_turns.open_turn("r1", "old", _question("m1"))
    open_turns.open_turn("r1", "new", _question("m2"))  # the old one was preempted
    open_turns.close_turn("r1", "old")
    open_turns._reset_for_tests()
    assert open_turns.close_dead_turns(store, lambda _r: False) == 1


def test_a_deleted_room_is_skipped():
    store = _Store()
    open_turns.open_turn("gone", "t1", _question())
    open_turns._reset_for_tests()
    assert open_turns.close_dead_turns(store, lambda _r: False) == 0
