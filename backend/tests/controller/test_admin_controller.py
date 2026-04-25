"""Endpoint tests for the admin viewers (G13)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("fastapi")

from controller.admin_controller import list_hooks, list_permissions  # noqa: E402


@pytest.fixture
def isolated_home(monkeypatch, tmp_path) -> Iterator[Path]:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".geny").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GENY_PERMISSIONS_PATH", raising=False)
    monkeypatch.delenv("GENY_PERMISSION_MODE", raising=False)
    monkeypatch.delenv("GENY_ALLOW_HOOKS", raising=False)
    yield tmp_path


@pytest.mark.asyncio
async def test_permissions_empty_when_no_yaml(isolated_home: Path) -> None:
    resp = await list_permissions(_auth={})
    assert resp.mode == "advisory"
    assert resp.rules == []
    assert len(resp.sources_consulted) >= 3  # user / project / local minimum


@pytest.mark.asyncio
async def test_permissions_loaded_from_user_yaml(isolated_home: Path) -> None:
    user_yaml = isolated_home / "home" / ".geny" / "permissions.yaml"
    user_yaml.write_text(
        """
allow:
  - tool: web_fetch
    pattern: "*"
deny:
  - tool: memory_delete
    pattern: "*"
    reason: destructive
""",
        encoding="utf-8",
    )
    resp = await list_permissions(_auth={})
    assert len(resp.rules) == 2
    by_tool = {r.tool_name: r for r in resp.rules}
    assert by_tool["web_fetch"].behavior == "allow"
    assert by_tool["memory_delete"].behavior == "deny"
    assert by_tool["memory_delete"].reason == "destructive"


@pytest.mark.asyncio
async def test_hooks_disabled_when_env_off(isolated_home: Path) -> None:
    resp = await list_hooks(_auth={})
    assert resp.env_opt_in is False
    assert resp.entries == []


@pytest.mark.asyncio
async def test_hooks_loaded_when_env_on(isolated_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("GENY_ALLOW_HOOKS", "1")
    yaml_path = isolated_home / "home" / ".geny" / "hooks.yaml"
    yaml_path.write_text(
        """
enabled: true
entries:
  pre_tool_use:
    - command: ["bash", "/tmp/audit.sh"]
      timeout_ms: 200
""",
        encoding="utf-8",
    )
    resp = await list_hooks(_auth={})
    assert resp.env_opt_in is True
    assert resp.enabled is True
    assert len(resp.entries) == 1
    entry = resp.entries[0]
    assert entry.event == "pre_tool_use"
    assert entry.command == ["bash", "/tmp/audit.sh"]
    assert entry.timeout_ms == 200
