"""One environment means one, including on a server that used to have five."""

import json
from types import SimpleNamespace

import pytest

from service.environment.prune import prune, survey


def _service(rows):
    store = {r["id"]: r for r in rows}
    return SimpleNamespace(
        list_all=lambda: list(store.values()),
        load=lambda env_id: store.get(env_id),
        delete=lambda env_id: bool(store.pop(env_id, None)),
        _store=store,
    )


def test_the_canonical_environment_stays_and_the_rest_go(tmp_path):
    from service.environment.templates import WORKER_ENV_ID

    service = _service([
        {"id": WORKER_ENV_ID, "name": "Geny"},
        {"id": "template-vtuber-env", "name": "VTuber 환경"},
        {"id": "52a7eb77f2bb", "name": "엘렌_new"},
    ])

    result = prune(service, apply=True, backup=tmp_path / "envs.json")

    assert result["kept"] == [WORKER_ENV_ID]
    assert sorted(result["dropped"]) == ["52a7eb77f2bb", "template-vtuber-env"]
    assert list(service._store) == [WORKER_ENV_ID]


def test_what_is_removed_is_written_down_first(tmp_path):
    from service.environment.templates import WORKER_ENV_ID

    service = _service([
        {"id": WORKER_ENV_ID, "name": "Geny"},
        {"id": "custom", "name": "엘렌", "manifest": {"stages": 21}},
    ])
    backup = tmp_path / "envs.json"

    prune(service, apply=True, backup=backup)

    saved = json.loads(backup.read_text(encoding="utf-8"))
    assert [e["id"] for e in saved["environments"]] == ["custom"]
    assert saved["environments"][0]["manifest"] == {"stages": 21}


def test_it_refuses_to_delete_without_a_backup():
    from service.environment.templates import WORKER_ENV_ID

    service = _service([{"id": WORKER_ENV_ID}, {"id": "custom"}])
    with pytest.raises(ValueError):
        prune(service, apply=True, backup=None)
    assert "custom" in service._store


def test_sessions_that_still_name_one_are_reported_not_blocked(tmp_path):
    from service.environment.templates import WORKER_ENV_ID

    service = _service([{"id": WORKER_ENV_ID}, {"id": "custom"}])
    store = SimpleNamespace(list_all=lambda: [{"session_id": "s1", "env_id": "custom"}])

    result = prune(service, apply=True, backup=tmp_path / "b.json", session_store=store)

    assert result["pointing_sessions"] == ["s1"]
    assert "custom" not in service._store  # every session resolves to the one


def test_running_it_again_does_nothing(tmp_path):
    from service.environment.templates import WORKER_ENV_ID

    service = _service([{"id": WORKER_ENV_ID}, {"id": "custom"}])
    prune(service, apply=True, backup=tmp_path / "b.json")

    again = prune(service, apply=True, backup=tmp_path / "b2.json")
    assert again["dropped"] == []
    assert not (tmp_path / "b2.json").exists()


def test_a_dry_run_touches_nothing():
    from service.environment.templates import WORKER_ENV_ID

    service = _service([{"id": WORKER_ENV_ID}, {"id": "custom"}])
    assert survey(service)["drop"][0]["id"] == "custom"
    prune(service, apply=False)
    assert "custom" in service._store
