"""GameConfig — cycle 20260422_5 (X7 follow-up).

Pins the shape of the Tamagotchi toggle so frontend/settings UI and
main.py lifespan both see a stable contract:

- defaults are ``enabled=True`` / ``state_db_path=""`` / ``vtuber_only=True``
- config name + category match what the Settings UI filters by
- field metadata exposes boolean toggles the UI auto-renders
- legacy env vars (``GENY_GAME_FEATURES`` / ``GENY_STATE_DB``) still
  drive ``get_default_instance`` for one-cycle backward-compat
"""

from __future__ import annotations

import os

import pytest

from service.config.base import FieldType
from service.config.sub_config.general.game_config import GameConfig


def test_default_instance_has_expected_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Strip env influence so we see the class-level defaults
    monkeypatch.delenv("GENY_GAME_FEATURES", raising=False)
    monkeypatch.delenv("GENY_STATE_DB", raising=False)
    cfg = GameConfig.get_default_instance()
    assert cfg.enabled is True
    assert cfg.state_db_path == ""
    assert cfg.vtuber_only is True


def test_config_name_and_category() -> None:
    assert GameConfig.get_config_name() == "game"
    assert GameConfig.get_category() == "general"


def test_fields_metadata_has_three_fields() -> None:
    fields = GameConfig.get_fields_metadata()
    names = {f.name for f in fields}
    assert names == {"enabled", "state_db_path", "vtuber_only"}


def test_enabled_and_vtuber_only_are_boolean_for_ui() -> None:
    """Settings UI auto-renders BOOLEAN fields as toggles. Regression
    guard against accidentally changing these to STRING."""
    fields = {f.name: f for f in GameConfig.get_fields_metadata()}
    assert fields["enabled"].field_type == FieldType.BOOLEAN
    assert fields["vtuber_only"].field_type == FieldType.BOOLEAN
    assert fields["state_db_path"].field_type == FieldType.STRING


def test_legacy_env_override_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """First-boot fallback — an operator who already set
    ``GENY_GAME_FEATURES=0`` in their deploy must not have Tamagotchi
    silently re-enabled on upgrade. The default-instance pulls env
    before falling through to the dataclass default."""
    monkeypatch.setenv("GENY_GAME_FEATURES", "0")
    cfg = GameConfig.get_default_instance()
    # ``read_env_defaults`` parses ``"0"`` as False for boolean fields
    assert cfg.enabled is False


def test_legacy_env_state_db_path_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENY_STATE_DB", "/tmp/custom-geny.sqlite3")
    cfg = GameConfig.get_default_instance()
    assert cfg.state_db_path == "/tmp/custom-geny.sqlite3"


def test_i18n_has_korean_and_english() -> None:
    """Settings UI renders Korean labels; keep these in lockstep."""
    i18n = GameConfig.get_i18n()
    assert "ko" in i18n
    assert "en" in i18n
    assert "enabled" in i18n["ko"]["fields"]
    assert "enabled" in i18n["en"]["fields"]
