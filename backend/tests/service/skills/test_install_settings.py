"""Skills install dual-read tests (PR-D.2.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

pytest.importorskip("geny_executor")

from geny_executor.settings.loader import reset_default_loader  # noqa: E402
from geny_executor.settings.section_registry import (  # noqa: E402
    reset_section_registry,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("GENY_ALLOW_USER_SKILLS", raising=False)
    reset_default_loader()
    reset_section_registry()
    yield
    reset_default_loader()
    reset_section_registry()


def _bind_settings(tmp_path: Path, content: Dict[str, Any]) -> None:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(content), encoding="utf-8")
    from geny_executor.settings import get_default_loader
    get_default_loader().add_path(p)


# ── settings.json wins over env ──────────────────────────────────────


def test_settings_true_enables(tmp_path: Path):
    _bind_settings(tmp_path, {"skills": {"user_skills_enabled": True}})
    from service.skills.install import _user_skills_opted_in
    assert _user_skills_opted_in() is True


def test_settings_false_overrides_env_true(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GENY_ALLOW_USER_SKILLS", "1")
    _bind_settings(tmp_path, {"skills": {"user_skills_enabled": False}})
    from service.skills.install import _user_skills_opted_in
    assert _user_skills_opted_in() is False


# ── No settings → env fallback ───────────────────────────────────────


def test_env_only_enables(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GENY_ALLOW_USER_SKILLS", "1")
    _bind_settings(tmp_path, {})
    from service.skills.install import _user_skills_opted_in
    assert _user_skills_opted_in() is True


def test_env_false_disables(tmp_path: Path):
    _bind_settings(tmp_path, {})
    from service.skills.install import _user_skills_opted_in
    assert _user_skills_opted_in() is False


def test_env_truthy_variants(tmp_path: Path, monkeypatch):
    _bind_settings(tmp_path, {})
    for v in ("1", "true", "True", "yes", "ON"):
        monkeypatch.setenv("GENY_ALLOW_USER_SKILLS", v)
        from service.skills.install import _user_skills_opted_in
        assert _user_skills_opted_in() is True, f"failed for {v!r}"


def test_settings_section_no_user_skills_key_falls_through(tmp_path: Path, monkeypatch):
    """When settings.skills exists but user_skills_enabled key is
    absent, env fallback runs."""
    monkeypatch.setenv("GENY_ALLOW_USER_SKILLS", "1")
    _bind_settings(tmp_path, {"skills": {"unrelated": True}})
    from service.skills.install import _user_skills_opted_in
    assert _user_skills_opted_in() is True
