"""Permission install dual-read tests (PR-D.2.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("geny_executor")

from geny_executor.settings.loader import reset_default_loader  # noqa: E402
from geny_executor.settings.section_registry import (  # noqa: E402
    reset_section_registry,
)


@pytest.fixture(autouse=True)
def _isolate_settings_singleton(monkeypatch, tmp_path):
    """Each test starts with a fresh settings loader bound to a tmp
    settings.json so cross-test bleed is impossible."""
    reset_default_loader()
    reset_section_registry()
    yield
    reset_default_loader()
    reset_section_registry()


def _write_settings(home: Path, content: Dict[str, Any]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps(content), encoding="utf-8")


def _bind_loader(path: Path) -> None:
    from geny_executor.settings import get_default_loader
    get_default_loader().add_path(path)


# ── settings.json wins ───────────────────────────────────────────────


def test_settings_json_rules_used(tmp_path: Path):
    _write_settings(tmp_path, {
        "permissions": {
            "rules": [
                {
                    "tool_name": "Bash",
                    "behavior": "ask",
                    "pattern": "git push *",
                    "reason": "destructive",
                },
            ],
        },
    })
    _bind_loader(tmp_path / "settings.json")
    from service.permission.install import install_permission_rules
    rules, _mode = install_permission_rules()
    assert len(rules) == 1
    assert rules[0].tool_name == "Bash"
    assert rules[0].pattern == "git push *"


def test_settings_empty_rules_returns_empty(tmp_path: Path):
    _write_settings(tmp_path, {"permissions": {"rules": []}})
    _bind_loader(tmp_path / "settings.json")
    from service.permission.install import install_permission_rules
    rules, _mode = install_permission_rules()
    assert rules == []


def test_unknown_behavior_skipped(tmp_path: Path, caplog):
    _write_settings(tmp_path, {
        "permissions": {
            "rules": [
                {"tool_name": "Bash", "behavior": "totally_invalid"},
                {"tool_name": "Read", "behavior": "allow"},
            ],
        },
    })
    _bind_loader(tmp_path / "settings.json")
    caplog.set_level("WARNING")
    from service.permission.install import install_permission_rules
    rules, _mode = install_permission_rules()
    assert len(rules) == 1
    assert rules[0].tool_name == "Read"


def test_non_dict_rule_entry_skipped(tmp_path: Path):
    _write_settings(tmp_path, {
        "permissions": {
            "rules": [
                "this is not a rule dict",
                {"tool_name": "Read", "behavior": "allow"},
            ],
        },
    })
    _bind_loader(tmp_path / "settings.json")
    from service.permission.install import install_permission_rules
    rules, _mode = install_permission_rules()
    assert len(rules) == 1


# ── No settings → legacy yaml ────────────────────────────────────────


def test_no_settings_section_falls_through(tmp_path: Path):
    """When settings.json has no permissions section, legacy yaml flow
    runs unchanged (returns empty list when no yaml exists either)."""
    _write_settings(tmp_path, {"unrelated": "section"})
    _bind_loader(tmp_path / "settings.json")
    from service.permission.install import install_permission_rules
    rules, _mode = install_permission_rules()
    # No yaml at the well-known paths in this test env → empty.
    assert rules == []


# ── Mode resolution still works ──────────────────────────────────────


def test_mode_resolved_independent_of_rules(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GENY_PERMISSION_MODE", "enforce")
    _write_settings(tmp_path, {"permissions": {"rules": []}})
    _bind_loader(tmp_path / "settings.json")
    from service.permission.install import install_permission_rules
    _rules, mode = install_permission_rules()
    assert mode == "enforce"


# ── _load_from_settings_section helper ───────────────────────────────


def test_loader_returns_none_when_section_absent(tmp_path: Path):
    _write_settings(tmp_path, {})
    _bind_loader(tmp_path / "settings.json")
    from service.permission.install import _load_from_settings_section
    assert _load_from_settings_section() is None


def test_loader_returns_empty_list_when_section_present_but_no_rules(tmp_path: Path):
    _write_settings(tmp_path, {"permissions": {}})
    _bind_loader(tmp_path / "settings.json")
    from service.permission.install import _load_from_settings_section
    out = _load_from_settings_section()
    assert out == []
