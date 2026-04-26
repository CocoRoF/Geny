"""Hooks install dual-read tests (PR-D.2.2)."""

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
    monkeypatch.setenv("GENY_ALLOW_HOOKS", "1")
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


# ── settings.json:hooks present ──────────────────────────────────────


def test_settings_section_builds_runner(tmp_path: Path):
    _bind_settings(tmp_path, {
        "hooks": {
            "enabled": True,
            "entries": {},
        },
    })
    from service.hooks.install import install_hook_runner
    runner = install_hook_runner()
    assert runner is not None


def test_settings_disabled_returns_none(tmp_path: Path):
    _bind_settings(tmp_path, {
        "hooks": {"enabled": False, "entries": {}},
    })
    from service.hooks.install import install_hook_runner
    assert install_hook_runner() is None


# ── No section / no env ──────────────────────────────────────────────


def test_no_section_falls_through_to_yaml(tmp_path: Path):
    _bind_settings(tmp_path, {"unrelated": "x"})
    from service.hooks.install import install_hook_runner
    # No yaml at the canonical path either → None.
    assert install_hook_runner() is None


def test_env_opt_out_returns_none_immediately(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GENY_ALLOW_HOOKS", raising=False)
    _bind_settings(tmp_path, {"hooks": {"enabled": True}})
    from service.hooks.install import install_hook_runner
    # Env gate beats settings — must opt in to subprocess hooks at all.
    assert install_hook_runner() is None
