"""Coverage for G6.3 — host-side permission rule loading.

The install module is the bridge between Geny's (very loose) rule
file convention and the executor's typed
:class:`~geny_executor.permission.types.PermissionRule` list. Three
shapes that matter for downstream:

1. **No file present** — empty list returned, attach_kwargs() returns
   ``{}`` so older executor builds without the kwarg keep booting.
2. **One user file** — loaded and tagged with PermissionSource.USER.
3. **Hierarchical merge** — user + project + local files all
   contribute; counts add up.

Mode resolution is environment-driven; we cover the default,
override, and unknown-value fallback.

Skipped when the geny-executor venv doesn't ship the permission
module (older pin) — same defensive pattern as test_endpoints.py.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("geny_executor.permission")

from geny_executor.permission import (  # noqa: E402
    PermissionBehavior,
    PermissionSource,
)

from service.permission import install as perm_install  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def isolated_env(monkeypatch, tmp_path) -> Iterator[Path]:
    """Replace HOME and CWD so the loader can't see real files."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".geny").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GENY_PERMISSIONS_PATH", raising=False)
    monkeypatch.delenv("GENY_PERMISSION_MODE", raising=False)
    monkeypatch.delenv("GENY_PERMISSIONS_STRICT", raising=False)
    yield tmp_path


def _write_yaml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ── No file present ─────────────────────────────────────────────────


def test_install_empty_when_no_file_present(isolated_env: Path) -> None:
    rules, mode = perm_install.install_permission_rules()
    assert rules == []
    assert mode == "advisory"


def test_attach_kwargs_omits_keys_when_empty(isolated_env: Path) -> None:
    """Older executor builds without the kwarg shouldn't see it."""
    assert perm_install.attach_kwargs() == {}


# ── User-scope file ─────────────────────────────────────────────────


def test_install_loads_user_yaml(isolated_env: Path) -> None:
    user_path = perm_install.permissions_yaml_path()
    _write_yaml(user_path, """
allow:
  - tool: web_fetch
    pattern: "*"
deny:
  - tool: memory_delete
    pattern: "*"
    reason: "destructive — must be approved"
""")

    rules, mode = perm_install.install_permission_rules()
    assert mode == "advisory"
    assert len(rules) == 2

    by_tool = {r.tool_name: r for r in rules}
    assert by_tool["web_fetch"].behavior == PermissionBehavior.ALLOW
    assert by_tool["web_fetch"].source == PermissionSource.USER
    assert by_tool["memory_delete"].behavior == PermissionBehavior.DENY
    assert by_tool["memory_delete"].reason == "destructive — must be approved"


def test_attach_kwargs_passthrough_when_rules_present(isolated_env: Path) -> None:
    user_path = perm_install.permissions_yaml_path()
    _write_yaml(user_path, "deny:\n  - tool: bash\n    pattern: 'rm -rf *'\n")

    kwargs = perm_install.attach_kwargs()
    assert "permission_rules" in kwargs
    assert "permission_mode" in kwargs
    assert kwargs["permission_mode"] == "advisory"
    assert len(kwargs["permission_rules"]) == 1
    assert kwargs["permission_rules"][0].tool_name == "bash"


# ── Hierarchical sources ────────────────────────────────────────────


def test_install_merges_user_project_local(isolated_env: Path, monkeypatch) -> None:
    user_path = perm_install.permissions_yaml_path()
    project_path = isolated_env / "permissions.yaml"
    local_path = isolated_env / "permissions.local.yaml"

    _write_yaml(user_path, "allow:\n  - tool: web_fetch\n    pattern: '*'\n")
    _write_yaml(project_path, "deny:\n  - tool: memory_delete\n    pattern: '*'\n")
    _write_yaml(local_path, "ask:\n  - tool: edit\n    pattern: '*'\n")

    rules, _ = perm_install.install_permission_rules()
    assert len(rules) == 3

    sources = {r.tool_name: r.source for r in rules}
    assert sources["web_fetch"] == PermissionSource.USER
    assert sources["memory_delete"] == PermissionSource.PROJECT
    assert sources["edit"] == PermissionSource.LOCAL


def test_env_override_path_wins(isolated_env: Path, monkeypatch, tmp_path) -> None:
    """``GENY_PERMISSIONS_PATH`` is loaded *in addition* to the default
    candidates — it's a way for ops to pin a specific file without
    shadowing user / project entries."""
    custom = tmp_path / "custom.yaml"
    _write_yaml(custom, "allow:\n  - tool: read\n    pattern: '*'\n")
    monkeypatch.setenv("GENY_PERMISSIONS_PATH", str(custom))

    rules, _ = perm_install.install_permission_rules()
    tool_names = [r.tool_name for r in rules]
    assert "read" in tool_names


# ── Mode resolution ─────────────────────────────────────────────────


def test_default_mode_is_advisory(isolated_env: Path) -> None:
    _, mode = perm_install.install_permission_rules()
    assert mode == "advisory"


def test_env_mode_enforce(isolated_env: Path, monkeypatch) -> None:
    monkeypatch.setenv("GENY_PERMISSION_MODE", "enforce")
    _, mode = perm_install.install_permission_rules()
    assert mode == "enforce"


def test_env_mode_unknown_falls_back(isolated_env: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("GENY_PERMISSION_MODE", "lenient")  # not in PERMISSION_MODES
    with caplog.at_level("WARNING"):
        _, mode = perm_install.install_permission_rules()
    assert mode == "advisory"
    assert any("lenient" in r.message for r in caplog.records)


# ── Failure handling ────────────────────────────────────────────────


def test_malformed_yaml_skipped_by_default(isolated_env: Path, caplog) -> None:
    _write_yaml(perm_install.permissions_yaml_path(), "allow:\n  - not a mapping\n")
    with caplog.at_level("WARNING"):
        rules, _ = perm_install.install_permission_rules()
    assert rules == []
    assert any("failed to load" in r.message for r in caplog.records)


def test_malformed_yaml_raises_in_strict_mode(isolated_env: Path, monkeypatch) -> None:
    _write_yaml(perm_install.permissions_yaml_path(), "allow:\n  - not a mapping\n")
    monkeypatch.setenv("GENY_PERMISSIONS_STRICT", "1")
    with pytest.raises(Exception):
        perm_install.install_permission_rules()
