"""The janitor, on the shape the production store was actually in.

325 rooms for one live session: empty duplicates, and hundreds belonging to
sessions that were deleted years ago. The rules have to hold on that, and the
run has to be safe to repeat.
"""

import json
import sys
import types

import pytest

from tests.service.chat.test_home_room import FakeChatStore, FakeSessionStore


@pytest.fixture
def wired(monkeypatch, tmp_path):
    chat = FakeChatStore()
    sessions = FakeSessionStore()
    live, deleted = [], []

    conv = types.ModuleType("service.chat.conversation_store")
    conv.get_chat_store = lambda: chat
    monkeypatch.setitem(sys.modules, "service.chat.conversation_store", conv)

    store_mod = types.ModuleType("service.sessions.store")
    store_mod.get_session_store = lambda: sessions
    monkeypatch.setitem(sys.modules, "service.sessions.store", store_mod)
    sessions.list_all = lambda: [{"session_id": s} for s in live]
    sessions.list_deleted = lambda: [{"session_id": s} for s in deleted]

    executor = types.ModuleType("service.executor")

    def _boom():
        raise RuntimeError("no manager in this test")

    executor.get_agent_session_manager = _boom
    monkeypatch.setitem(sys.modules, "service.executor", executor)

    import importlib

    module = importlib.reload(importlib.import_module("service.chat.cleanup_rooms"))
    return module, chat, sessions, live, deleted, tmp_path


def room(rid, sids, count, updated="2026-09-18T10:00:00Z"):
    return {"id": rid, "name": f"{rid} Chat", "session_ids": sids,
            "updated_at": updated, "message_count": count}


def test_a_live_session_keeps_its_busiest_room_and_the_strays_merge(wired):
    cleanup, chat, _, live, _, tmp = wired
    live.append("s1")
    chat.rooms = [room("busy", ["s1"], 2455), room("side", ["s1"], 3),
                  room("empty1", ["s1"], 0), room("empty2", ["s1"], 0)]
    chat.messages["side"] = [{"id": "x", "timestamp": "t1"}]

    plan = cleanup.clean(apply=True, backup=tmp / "backup.json")

    assert plan.keep == ["busy"]
    assert sorted(m["room_id"] for m in plan.merge) == ["empty1", "empty2", "side"]
    assert sorted(chat.deleted) == ["empty1", "empty2", "side"]
    # The stranded message is in the conversation now, not gone.
    assert [m["id"] for m in chat.messages["busy"]] == ["x"]


def test_rooms_of_deleted_sessions_are_backed_up_before_they_go(wired):
    cleanup, chat, _, live, _, tmp = wired
    live.append("alive")
    chat.rooms = [room("mine", ["alive"], 1), room("ghost", ["gone"], 893)]
    chat.messages["ghost"] = [{"id": "g1", "content": "오래된 대화"}]
    backup = tmp / "rooms.json"

    plan = cleanup.clean(apply=True, backup=backup)

    assert [r["room_id"] for r in plan.retire] == ["ghost"]
    assert chat.deleted == ["ghost"]
    saved = json.loads(backup.read_text(encoding="utf-8"))
    assert saved["rooms"][0]["room_id"] == "ghost"
    assert saved["rooms"][0]["messages"][0]["content"] == "오래된 대화"


def test_a_soft_deleted_session_keeps_its_conversation(wired):
    """It can be restored, and restoring it must not hand the user an empty
    room."""
    cleanup, chat, _, live, deleted, tmp = wired
    deleted.append("resting")
    chat.rooms = [room("kept", ["resting"], 40)]

    plan = cleanup.clean(apply=True, backup=tmp / "b.json")

    assert plan.retire == []
    assert chat.deleted == []


def test_it_refuses_to_delete_without_a_backup(wired):
    cleanup, chat, _, live, _, _tmp = wired
    live.append("alive")
    chat.rooms = [room("mine", ["alive"], 2), room("ghost", ["gone"], 5)]

    with pytest.raises(ValueError):
        cleanup.clean(apply=True, backup=None)
    assert chat.deleted == []


def test_running_it_again_does_nothing(wired):
    cleanup, chat, _, live, _, tmp = wired
    live.append("s1")
    chat.rooms = [room("busy", ["s1"], 10), room("stray", ["s1"], 1)]

    cleanup.clean(apply=True, backup=tmp / "b.json")
    chat.deleted.clear()
    second = cleanup.clean(apply=True, backup=tmp / "b2.json")

    assert second.merge == []
    assert second.retire == []
    assert chat.deleted == []


def test_a_dry_run_touches_nothing(wired):
    cleanup, chat, _, live, _, _tmp = wired
    live.append("s1")
    chat.rooms = [room("busy", ["s1"], 10), room("stray", ["s1"], 1), room("ghost", ["gone"], 3)]

    plan = cleanup.clean(apply=False)

    assert len(plan.merge) == 1 and len(plan.retire) == 1
    assert chat.deleted == []
    assert "DRY" not in plan.render()  # the render is the finding, not the verdict


def test_it_refuses_when_it_cannot_see_a_single_session(wired):
    """The dry run that found this would have retired every room on the
    production server — 325 of them, the live 2,457-message conversation
    included — because a one-off process reads rooms from their JSON backup
    but sessions only from the database. No sessions is a failed lookup, not
    a server with nothing on it."""
    cleanup, chat, _, live, _, tmp = wired
    live.clear()
    chat.rooms = [room("real", ["s1"], 2457), room("also", ["s2"], 3)]

    with pytest.raises(RuntimeError, match="not connected"):
        cleanup.clean(apply=True, backup=tmp / "b.json")
    assert chat.deleted == []


def test_an_empty_server_is_still_fine(wired):
    cleanup, chat, _, live, _, tmp = wired
    live.clear()
    chat.rooms = []

    plan = cleanup.clean(apply=True, backup=tmp / "b.json")
    assert plan.retire == [] and chat.deleted == []


def test_the_json_backup_is_made_to_agree_with_the_database(wired):
    """The fallback copy only ever grew: rooms deleted from the database
    stayed in it, ready to come back as real conversations the moment the
    database was unavailable. Production carried 118 of those."""
    cleanup, chat, _, live, _, tmp = wired
    live.append("s1")
    chat.rooms = [room("home", ["s1"], 5)]
    chat.reconciled = []
    chat.reconcile_json_backup = lambda: ({"rooms_removed": 118, "message_files_removed": 120})

    plan = cleanup.clean(apply=True, backup=tmp / "b.json")

    assert plan.backup_rooms_removed == 118
    assert "118 stale rooms" in plan.render()
