"""``service.memory.tuning.load_memory_tuning`` tests.

Verifies the per-session memory knob resolver:
- absent settings → historical defaults (role-aware max_inject_chars).
- single int max_inject_chars → applied to every role.
- per-role dict max_inject_chars → role-aware lookup.
- recent_turns / enable_vector_search / enable_reflection overrides.
- pinned-facts tier knobs (pin_budget_ratio, category_boosts,
  always_render_vault_map, slim_mode).
- malformed values fall back to defaults.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

import service.memory.tuning as tuning  # noqa: E402


@pytest.fixture
def stub_section(monkeypatch):
    """Replace ``_settings_section`` with a controllable dict so we
    don't depend on a real settings.json on disk."""
    holder = {"value": {}}

    def fake() -> dict:
        return holder["value"]

    monkeypatch.setattr(tuning, "_settings_section", fake)
    return holder


def test_defaults_when_section_absent(stub_section) -> None:
    stub_section["value"] = {}
    out = tuning.load_memory_tuning(is_vtuber=False)
    assert out["max_inject_chars"] == 10000
    assert out["recent_turns"] == 3
    assert out["enable_vector_search"] is True
    assert out["enable_reflection"] is True
    assert out["pin_budget_ratio"] == 0.30
    assert out["always_render_vault_map"] is True
    assert out["slim_mode"] is False
    assert out["category_boosts"] == {
        "insights": 1.2,
        "projects": 1.2,
        "critical": 1.5,
    }


def test_defaults_when_section_absent_vtuber(stub_section) -> None:
    stub_section["value"] = {}
    assert tuning.load_memory_tuning(is_vtuber=True)["max_inject_chars"] == 8000


def test_single_int_max_inject_chars(stub_section) -> None:
    stub_section["value"] = {"tuning": {"max_inject_chars": 12345}}
    assert tuning.load_memory_tuning(is_vtuber=False)["max_inject_chars"] == 12345
    assert tuning.load_memory_tuning(is_vtuber=True)["max_inject_chars"] == 12345


def test_per_role_dict_max_inject_chars(stub_section) -> None:
    stub_section["value"] = {
        "tuning": {"max_inject_chars": {"vtuber": 9000, "worker": 11000}},
    }
    assert tuning.load_memory_tuning(is_vtuber=True)["max_inject_chars"] == 9000
    assert tuning.load_memory_tuning(is_vtuber=False)["max_inject_chars"] == 11000


def test_per_role_dict_missing_role_falls_back(stub_section) -> None:
    stub_section["value"] = {"tuning": {"max_inject_chars": {"vtuber": 7777}}}
    assert tuning.load_memory_tuning(is_vtuber=True)["max_inject_chars"] == 7777
    assert tuning.load_memory_tuning(is_vtuber=False)["max_inject_chars"] == 10000


def test_recent_turns_override(stub_section) -> None:
    stub_section["value"] = {"tuning": {"recent_turns": 12}}
    assert tuning.load_memory_tuning(is_vtuber=False)["recent_turns"] == 12


def test_enable_flags_override(stub_section) -> None:
    stub_section["value"] = {
        "tuning": {"enable_vector_search": False, "enable_reflection": False},
    }
    out = tuning.load_memory_tuning(is_vtuber=False)
    assert out["enable_vector_search"] is False
    assert out["enable_reflection"] is False


def test_pin_budget_ratio_clamped(stub_section) -> None:
    stub_section["value"] = {"tuning": {"pin_budget_ratio": 1.5}}
    assert tuning.load_memory_tuning(is_vtuber=False)["pin_budget_ratio"] == 0.7
    stub_section["value"] = {"tuning": {"pin_budget_ratio": -0.2}}
    assert tuning.load_memory_tuning(is_vtuber=False)["pin_budget_ratio"] == 0.0


def test_category_boosts_override(stub_section) -> None:
    stub_section["value"] = {
        "tuning": {"category_boosts": {"insights": 2.0, "topics": 0.5}},
    }
    out = tuning.load_memory_tuning(is_vtuber=False)
    assert out["category_boosts"] == {"insights": 2.0, "topics": 0.5}


def test_always_render_vault_map_and_slim_mode(stub_section) -> None:
    stub_section["value"] = {
        "tuning": {"always_render_vault_map": False, "slim_mode": True},
    }
    out = tuning.load_memory_tuning(is_vtuber=False)
    assert out["always_render_vault_map"] is False
    assert out["slim_mode"] is True


def test_malformed_max_inject_falls_back(stub_section) -> None:
    stub_section["value"] = {"tuning": {"max_inject_chars": "not-an-int"}}
    assert tuning.load_memory_tuning(is_vtuber=False)["max_inject_chars"] == 10000


def test_malformed_recent_turns_falls_back(stub_section) -> None:
    stub_section["value"] = {"tuning": {"recent_turns": "many"}}
    assert tuning.load_memory_tuning(is_vtuber=False)["recent_turns"] == 3


def test_non_dict_tuning_falls_back(stub_section) -> None:
    stub_section["value"] = {"tuning": "garbage"}
    out = tuning.load_memory_tuning(is_vtuber=False)
    assert out["recent_turns"] == 3
    assert out["max_inject_chars"] == 10000
