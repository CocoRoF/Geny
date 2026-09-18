"""An agent's speaking schedule is its own.

Editing when one agent speaks used to mean editing a preset every agent
sharing it would feel — or building another environment to hold a different
one. The editor asks for a private ladder first; these pin what that means.
"""

import pytest


class FakeRecord:
    def __init__(self, rid, name, manifest):
        self.id = rid
        self.name = name
        self.manifest = manifest


class FakeManifest:
    def __init__(self, marker):
        self.marker = marker

    def model_dump(self, mode="json"):
        return {"marker": self.marker}


class FakePresets:
    def __init__(self, default_id="default-ladder"):
        self.records = {default_id: FakeRecord(default_id, "기본", FakeManifest("default"))}
        self.default_id = default_id
        self.created = []

    def get(self, pid):
        return self.records.get(pid)

    def get_default(self):
        return self.records.get(self.default_id)

    def create(self, name, description="", tags=None, manifest=None, clone_from=None):
        new_id = f"own-{len(self.created) + 1}"
        source = self.records.get(clone_from)
        self.records[new_id] = FakeRecord(
            new_id, name, FakeManifest(source.manifest.marker if source else "blank"),
        )
        self.created.append((name, clone_from))
        return new_id


class FakeTriggers:
    def __init__(self, attached=None):
        self.attached = dict(attached or {})

    def get_attached_preset(self, sid):
        return self.attached.get(sid)

    def attach_preset(self, sid, pid):
        self.attached[sid] = pid


class FakeStore:
    def __init__(self, record):
        self.record = record
        self.updates = []

    def get(self, _sid):
        return self.record

    def update(self, sid, patch):
        self.updates.append((sid, patch))


@pytest.fixture
def wired(monkeypatch):
    presets, triggers = FakePresets(), FakeTriggers()
    store = FakeStore({"session_name": "엘렌"})
    import controller.agent_controller as ctrl

    monkeypatch.setattr("service.trigger_preset.get_trigger_preset_service", lambda: presets)
    monkeypatch.setattr(
        "service.vtuber.thinking_trigger.get_thinking_trigger_service", lambda: triggers,
    )
    monkeypatch.setattr(ctrl, "get_session_store", lambda: store)
    monkeypatch.setattr(ctrl, "_enforce_session_owner", lambda *a, **k: None)
    return ctrl, presets, triggers, store


@pytest.mark.asyncio
async def test_an_agent_on_the_shared_default_gets_a_private_copy(wired):
    ctrl, presets, triggers, store = wired

    out = await ctrl.make_own_trigger_preset(session_id="s1", auth={})

    assert out["trigger_preset_id"] == "own-1"
    assert out["name"] == "엘렌 트리거"
    # A copy of what it was already running, not a blank ladder.
    assert presets.created == [("엘렌 트리거", "default-ladder")]
    assert out["manifest"] == {"marker": "default"}
    assert triggers.attached["s1"] == "own-1"
    assert store.updates == [("s1", {"trigger_preset_id": "own-1"})]


@pytest.mark.asyncio
async def test_asking_twice_changes_nothing(wired):
    ctrl, presets, triggers, _ = wired

    first = await ctrl.make_own_trigger_preset(session_id="s1", auth={})
    presets.created.clear()
    second = await ctrl.make_own_trigger_preset(session_id="s1", auth={})

    assert second["trigger_preset_id"] == first["trigger_preset_id"]
    assert presets.created == []


@pytest.mark.asyncio
async def test_an_attachment_pointing_at_a_deleted_ladder_is_replaced(wired):
    """Otherwise the editor opens on nothing and saving writes nowhere."""
    ctrl, presets, triggers, _ = wired
    triggers.attach_preset("s1", "was-deleted")

    out = await ctrl.make_own_trigger_preset(session_id="s1", auth={})

    assert out["trigger_preset_id"] == "own-1"
    assert triggers.attached["s1"] == "own-1"
