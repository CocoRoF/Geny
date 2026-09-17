"""permanent_delete must cascade to the session's side data, not just the
`sessions` row. Regression: on prod, permanently deleted sessions left 78% of
chat rooms/messages and 267k session_logs orphaned because these were never
cleaned. This pins the cascade: session_logs + chat rooms/messages.
"""

from __future__ import annotations

import pytest

from service.sessions import store as store_mod


@pytest.fixture
def patched(monkeypatch, tmp_path):
    calls = {"session": [], "memory": [], "logs": [], "room_del": [], "room_upd": [],
             "tasks": [], "crons": []}
    monkeypatch.setattr(
        "service.database.session_db_helper.db_delete_tasks_by_session",
        lambda db, sid: (calls["tasks"].append(sid) or 2),
    )
    monkeypatch.setattr(
        "service.database.session_db_helper.db_delete_crons_by_session",
        lambda db, sid: (calls["crons"].append(sid) or 1),
    )

    # Make _db_available true and stub the row/memory deletes.
    monkeypatch.setattr("service.database.session_db_helper._is_db_available", lambda db: True)
    monkeypatch.setattr(
        "service.database.session_db_helper.db_permanent_delete_session",
        lambda db, sid: (calls["session"].append(sid) or True),
    )
    monkeypatch.setattr(
        "service.database.memory_db_helper.db_delete_session_memory",
        lambda db, sid: (calls["memory"].append(sid) or True),
    )
    # The new cascade targets.
    monkeypatch.setattr(
        "service.database.session_log_db_helper.db_delete_session_logs",
        lambda db, sid: (calls["logs"].append(sid) or True),
    )
    # The shape db_list_rooms ACTUALLY returns: keyed "id" (not "room_id"),
    # with session_ids already parsed out of its JSON column. This fixture used
    # to say "room_id", which is what the cascade asked for — so the test was
    # green while production quietly kept every room it was supposed to delete.
    # 204 of the 207 rooms on the server belonged to sessions long gone.
    rooms = [
        {"id": "r-solo", "session_ids": ["S"]},             # only S → delete
        {"id": "r-shared", "session_ids": ["S", "OTHER"]},  # shared → update
        {"id": "r-unrelated", "session_ids": ["X", "Y"]},   # skip
    ]
    monkeypatch.setattr("service.database.chat_db_helper.db_list_rooms", lambda db: rooms)
    monkeypatch.setattr(
        "service.database.chat_db_helper.db_delete_room",
        lambda db, rid: (calls["room_del"].append(rid) or True),
    )
    monkeypatch.setattr(
        "service.database.chat_db_helper.db_update_room_sessions",
        lambda db, rid, sids: (calls["room_upd"].append((rid, sids)) or True),
    )

    s = store_mod.SessionStore(path=tmp_path / "sessions.json")
    s._app_db = object()  # non-None → _db_available consults the (patched) checker
    return s, calls


def test_permanent_delete_cascades_logs_and_rooms(patched):
    store, calls = patched
    ok = store.permanent_delete("S")
    assert ok is True
    # core row + memory (already existed) ...
    assert calls["session"] == ["S"]
    assert calls["memory"] == ["S"]
    # ... plus the newly-wired cascades:
    assert calls["logs"] == ["S"], "session_logs must be deleted"
    # solo room deleted (with its messages), shared room keeps only OTHER,
    # unrelated room untouched.
    assert calls["room_del"] == ["r-solo"]
    assert calls["room_upd"] == [("r-shared", ["OTHER"])]
    # ... plus the agent's own runtime side-effects: work queue + self-crons.
    assert calls["tasks"] == ["S"], "background tasks must be deleted"
    assert calls["crons"] == ["S"], "self-scheduled crons must be deleted"


def test_cascade_failure_never_blocks_delete(patched, monkeypatch):
    """A side-data cleanup error must not abort the session delete itself."""
    store, calls = patched
    monkeypatch.setattr(
        "service.database.session_log_db_helper.db_delete_session_logs",
        lambda db, sid: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    # Still returns True (session row deletion succeeded); no exception escapes.
    assert store.permanent_delete("S") is True
    assert calls["session"] == ["S"]
