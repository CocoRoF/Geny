"""A VTuber keeps the avatar it was given — through idle, eviction and restart.

Production, 2026-09-23: the VTuber session's avatar was ``null``. The binding
is kept in two places — the model registry file, which lives on the image
layer and is regenerated on every deploy, and the session record's
``extra_data`` as ``assigned_model``, which is the one meant to survive. But
the session manager re-registers a status SNAPSHOT of the session every time
it goes idle, is evicted, or wakes, and that upsert replaced ``extra_data``
wholesale with the snapshot's fields. ``assigned_model`` is not one of them,
so the first idle erased it, and the next deploy took the other copy: an
empty avatar window, with nothing in any log to say why.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from service.database import session_db_helper as h
from service.sessions.store import SessionStore


def _snapshot(status: str) -> Dict[str, Any]:
    """What ``agent.get_session_info().model_dump()`` looks like: no avatar."""
    return {"session_name": "ellen", "status": status, "role": "vtuber",
            "chat_room_id": "room-1", "env_id": "template-worker-env"}


class TestTheStoreKeepsWhatTheSnapshotDoesNotKnow:
    def test_an_idle_snapshot_does_not_erase_the_avatar(self, tmp_path: Path) -> None:
        store = SessionStore(path=tmp_path / "sessions.json")
        store.register("S", _snapshot("running"))
        store.update("S", {"assigned_model": "Chisa"})
        store.register("S", _snapshot("idle"))
        rec = store.get("S")
        assert rec["assigned_model"] == "Chisa"
        assert rec["status"] == "idle", "the snapshot's own fields must still win"

    def test_it_survives_a_reload_from_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "sessions.json"
        store = SessionStore(path=path)
        store.register("S", _snapshot("running"))
        store.update("S", {"assigned_model": "Chisa"})
        store.register("S", _snapshot("stopped"))
        assert SessionStore(path=path).get("S")["assigned_model"] == "Chisa"


class TestTheDatabaseRowMergesInsteadOfReplacing:
    def test_the_upsert_merges_extra_data(self, monkeypatch) -> None:
        seen: Dict[str, Any] = {}

        class _Mgr:
            def execute_insert(self, query, params):
                seen["query"] = query
                return 1

        monkeypatch.setattr(h, "_get_db_manager", lambda db: _Mgr())
        monkeypatch.setattr(h, "_is_db_available", lambda db: True)
        assert h.db_register_session(object(), "S", _snapshot("idle"))
        q = seen["query"]
        conflict = q.split("DO UPDATE SET", 1)[1]
        assert "extra_data = EXCLUDED.extra_data," not in conflict
        assert "sessions.extra_data::jsonb || EXCLUDED.extra_data::jsonb" in conflict
        assert "status = EXCLUDED.status" in conflict


class TestTheModelManagerRestoresIt:
    """The whole path: assign → idle snapshot → a restart that regenerated
    the registry file without its assignments → the avatar is still there."""

    def test_after_idle_and_restart(self, tmp_path: Path, monkeypatch) -> None:
        from service.vtuber import live2d_model_manager as mm

        models_dir = tmp_path / "models"
        models_dir.mkdir()
        registry = models_dir / "model_registry.json"
        registry.write_text(json.dumps({"models": [{
            "name": "Chisa", "display_name": "Chisa", "url": "/static/mmd-models/Chisa/c.pmx",
            "runtime": "mmd",
        }]}))
        store = SessionStore(path=tmp_path / "sessions.json")
        monkeypatch.setattr("service.sessions.store.get_session_store", lambda: store)

        manager = mm.Live2dModelManager(str(models_dir))
        store.register("S", _snapshot("running"))
        manager.assign_model_to_agent("S", "Chisa")
        store.register("S", _snapshot("idle"))

        # Redeploy: the registry is rebuilt from the baked imports, so the
        # assignments it mirrored are gone.
        data = json.loads(registry.read_text())
        data.pop("agent_model_assignments", None)
        registry.write_text(json.dumps(data))

        assert mm.Live2dModelManager(str(models_dir)).get_agent_model_name("S") == "Chisa"
