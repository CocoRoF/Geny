"""G.2 (cycle 20260426_2) — load_memory_tuning tests.

Verifies the per-session memory knob resolver:
- absent settings → historical defaults (role-aware max_inject_chars).
- single int max_inject_chars → applied to every role.
- per-role dict max_inject_chars → role-aware lookup.
- recent_turns / enable_vector_search / enable_reflection overrides.
- malformed values fall back to defaults.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

import service.memory_provider.config as cfg  # noqa: E402


@pytest.fixture
def stub_section(monkeypatch):
    """Replace ``_settings_section`` with a controllable dict so we
    don't depend on a real settings.json on disk."""
    holder = {"value": {}}

    def fake() -> dict:
        return holder["value"]

    monkeypatch.setattr(cfg, "_settings_section", fake)
    return holder


def test_defaults_when_section_absent(stub_section) -> None:
    stub_section["value"] = {}
    out = cfg.load_memory_tuning(is_vtuber=False)
    assert out == {
        "max_inject_chars": 10000,
        "recent_turns": 6,
        "enable_vector_search": True,
        "enable_reflection": True,
    }


def test_defaults_when_section_absent_vtuber(stub_section) -> None:
    stub_section["value"] = {}
    out = cfg.load_memory_tuning(is_vtuber=True)
    assert out["max_inject_chars"] == 8000


def test_single_int_max_inject_chars(stub_section) -> None:
    stub_section["value"] = {"tuning": {"max_inject_chars": 12345}}
    assert cfg.load_memory_tuning(is_vtuber=False)["max_inject_chars"] == 12345
    assert cfg.load_memory_tuning(is_vtuber=True)["max_inject_chars"] == 12345


def test_per_role_dict_max_inject_chars(stub_section) -> None:
    stub_section["value"] = {
        "tuning": {"max_inject_chars": {"vtuber": 9000, "worker": 11000}},
    }
    assert cfg.load_memory_tuning(is_vtuber=True)["max_inject_chars"] == 9000
    assert cfg.load_memory_tuning(is_vtuber=False)["max_inject_chars"] == 11000


def test_per_role_dict_missing_role_falls_back(stub_section) -> None:
    """Per-role dict with only one role set → other role gets the
    historical default (8000 / 10000)."""
    stub_section["value"] = {"tuning": {"max_inject_chars": {"vtuber": 7777}}}
    assert cfg.load_memory_tuning(is_vtuber=True)["max_inject_chars"] == 7777
    # Worker role isn't in the dict → historical worker default.
    assert cfg.load_memory_tuning(is_vtuber=False)["max_inject_chars"] == 10000


def test_recent_turns_override(stub_section) -> None:
    stub_section["value"] = {"tuning": {"recent_turns": 12}}
    assert cfg.load_memory_tuning(is_vtuber=False)["recent_turns"] == 12


def test_enable_flags_override(stub_section) -> None:
    stub_section["value"] = {
        "tuning": {"enable_vector_search": False, "enable_reflection": False},
    }
    out = cfg.load_memory_tuning(is_vtuber=False)
    assert out["enable_vector_search"] is False
    assert out["enable_reflection"] is False


def test_malformed_max_inject_falls_back(stub_section) -> None:
    """Non-int / non-dict value → fall back to historical default."""
    stub_section["value"] = {"tuning": {"max_inject_chars": "not-an-int"}}
    assert cfg.load_memory_tuning(is_vtuber=False)["max_inject_chars"] == 10000


def test_malformed_recent_turns_falls_back(stub_section) -> None:
    stub_section["value"] = {"tuning": {"recent_turns": "many"}}
    assert cfg.load_memory_tuning(is_vtuber=False)["recent_turns"] == 6


def test_non_dict_tuning_falls_back(stub_section) -> None:
    """If someone hand-edits ``tuning`` to a string, the loader still
    returns defaults instead of crashing."""
    stub_section["value"] = {"tuning": "garbage"}
    out = cfg.load_memory_tuning(is_vtuber=False)
    assert out["recent_turns"] == 6
    assert out["max_inject_chars"] == 10000
