"""A session must keep the persona its environment was giving it.

The only way to give one agent a different character used to be to copy an
environment and change its persona — so cutting the link between the two
without moving that choice onto the session would have agents quietly start
speaking as nobody.
"""

from types import SimpleNamespace

from service.sessions.migrate_attachments import migrate_session_attachments


class FakeStore:
    def __init__(self, records):
        self.records = records
        self.updates = []

    def list_all(self):
        return list(self.records)

    def update(self, session_id, changes):
        self.updates.append((session_id, changes))
        for r in self.records:
            if r["session_id"] == session_id:
                r.update(changes)


class FakeEnvironments:
    def __init__(self, personas):
        self.personas = personas

    def load_manifest(self, env_id):
        if env_id not in self.personas:
            return None
        return SimpleNamespace(
            host_selections=SimpleNamespace(
                extras={"persona_preset_id": self.personas[env_id]},
            ),
        )


def test_the_environments_persona_becomes_the_sessions_own():
    store = FakeStore([
        {"session_id": "s1", "env_id": "custom-ellen", "persona_preset_id": None},
    ])
    envs = FakeEnvironments({"custom-ellen": "persona-ellen"})

    result = migrate_session_attachments(store, envs)

    assert result == {"checked": 1, "moved": 1}
    assert store.records[0]["persona_preset_id"] == "persona-ellen"


def test_a_session_that_already_chose_is_not_overwritten():
    store = FakeStore([
        {"session_id": "s1", "env_id": "vtuber", "persona_preset_id": "mine"},
    ])
    envs = FakeEnvironments({"vtuber": "the-default-one"})

    assert migrate_session_attachments(store, envs) == {"checked": 1, "moved": 0}
    assert store.records[0]["persona_preset_id"] == "mine"


def test_a_session_whose_environment_had_none_is_left_alone():
    store = FakeStore([{"session_id": "s1", "env_id": "worker", "persona_preset_id": None}])
    envs = FakeEnvironments({"worker": ""})

    assert migrate_session_attachments(store, envs)["moved"] == 0
    assert store.updates == []


def test_running_it_again_does_nothing():
    store = FakeStore([{"session_id": "s1", "env_id": "e", "persona_preset_id": None}])
    envs = FakeEnvironments({"e": "p"})

    migrate_session_attachments(store, envs)
    store.updates.clear()

    assert migrate_session_attachments(store, envs)["moved"] == 0
    assert store.updates == []


def test_an_unreadable_store_does_not_stop_the_server():
    class Broken:
        def list_all(self):
            raise RuntimeError("no database")

    assert migrate_session_attachments(Broken(), FakeEnvironments({})) == {"checked": 0, "moved": 0}
