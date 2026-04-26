"""Settings migrator tests (PR-B.3.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("yaml")
import yaml  # noqa: E402

from service.settings.migrator import migrate_yaml_to_settings_json  # noqa: E402


def _write_yaml(path: Path, data) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


# ── Migration ────────────────────────────────────────────────────────


class TestMigrate:
    def test_migrates_existing_yaml_files(self, tmp_path: Path):
        home = tmp_path / "geny"
        home.mkdir()
        _write_yaml(home / "permissions.yaml", {"mode": "default", "rules": []})
        _write_yaml(home / "hooks.yaml", {"enabled": True, "entries": {}})
        summary = migrate_yaml_to_settings_json(home=home)
        assert "permissions" in summary["migrated"]
        assert "hooks" in summary["migrated"]
        assert "notifications" in summary["skipped"]
        # settings.json written.
        settings = json.loads((home / "settings.json").read_text())
        assert settings["permissions"]["mode"] == "default"

    def test_creates_bak_for_each_source(self, tmp_path: Path):
        home = tmp_path / "g"
        home.mkdir()
        _write_yaml(home / "permissions.yaml", {"mode": "x"})
        migrate_yaml_to_settings_json(home=home)
        assert (home / "permissions.yaml.bak").exists()

    def test_idempotent_does_not_overwrite_existing_section(self, tmp_path: Path):
        home = tmp_path / "g"
        home.mkdir()
        # Pre-existing settings.json wins over yaml.
        (home / "settings.json").write_text(
            json.dumps({"permissions": {"mode": "user-set"}}),
        )
        _write_yaml(home / "permissions.yaml", {"mode": "would-be-overwrite"})
        summary = migrate_yaml_to_settings_json(home=home)
        assert "permissions" in summary["kept"]
        assert "permissions" not in summary["migrated"]
        # Existing user choice preserved.
        merged = json.loads((home / "settings.json").read_text())
        assert merged["permissions"]["mode"] == "user-set"

    def test_no_yaml_files_returns_clean_summary(self, tmp_path: Path):
        home = tmp_path / "g"
        home.mkdir()
        summary = migrate_yaml_to_settings_json(home=home)
        assert summary["migrated"] == []
        assert "permissions" in summary["skipped"]
        # No write attempted.
        assert not (home / "settings.json").exists()

    def test_invalid_yaml_skipped(self, tmp_path: Path, caplog):
        home = tmp_path / "g"
        home.mkdir()
        (home / "permissions.yaml").write_text("not: valid: yaml: !@#$", encoding="utf-8")
        caplog.set_level("WARNING")
        summary = migrate_yaml_to_settings_json(home=home)
        # Permissions neither migrated nor kept — invalid.
        assert "permissions" not in summary["migrated"]

    def test_yaml_root_not_dict_skipped(self, tmp_path: Path):
        home = tmp_path / "g"
        home.mkdir()
        _write_yaml(home / "permissions.yaml", ["not", "a", "dict"])
        summary = migrate_yaml_to_settings_json(home=home)
        assert "permissions" not in summary["migrated"]

    def test_existing_settings_json_backed_up_before_write(self, tmp_path: Path):
        home = tmp_path / "g"
        home.mkdir()
        (home / "settings.json").write_text(json.dumps({"unrelated": "x"}))
        _write_yaml(home / "hooks.yaml", {"enabled": True})
        migrate_yaml_to_settings_json(home=home)
        # Backup exists.
        assert (home / "settings.json.bak").exists()
        # Original still recoverable.
        bak = json.loads((home / "settings.json.bak").read_text())
        assert bak == {"unrelated": "x"}

    def test_summary_includes_settings_path(self, tmp_path: Path):
        home = tmp_path / "g"
        home.mkdir()
        summary = migrate_yaml_to_settings_json(home=home)
        assert summary["settings_path"].endswith("settings.json")
