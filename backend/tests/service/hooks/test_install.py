"""Coverage for G6.5 — HookRunner install + dual-gate.

Both gates must open for the runner to be returned:
1. ``GENY_ALLOW_HOOKS`` env truthy
2. Hooks YAML present + ``enabled: true``

Either gate closed → ``install_hook_runner()`` returns None and
``attach_kwargs()`` returns ``{}`` so older executor pins keep
working.

Skipped when geny-executor's hooks subsystem isn't importable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("geny_executor.hooks")

from geny_executor.hooks import HookRunner  # noqa: E402

from service.hooks import install as hook_install  # noqa: E402


@pytest.fixture
def isolated_env(monkeypatch, tmp_path) -> Iterator[Path]:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".geny").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("GENY_ALLOW_HOOKS", raising=False)
    yield tmp_path


def _write_yaml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ── Both gates closed ──────────────────────────────────────────────


def test_no_runner_when_env_off_and_no_yaml(isolated_env: Path) -> None:
    assert hook_install.install_hook_runner() is None
    assert hook_install.attach_kwargs() == {}


def test_no_runner_when_env_off_with_yaml(isolated_env: Path) -> None:
    _write_yaml(hook_install.hooks_yaml_path(), "enabled: true\nentries: {}\n")
    assert hook_install.install_hook_runner() is None


def test_no_runner_when_env_on_but_no_yaml(isolated_env: Path, monkeypatch) -> None:
    monkeypatch.setenv("GENY_ALLOW_HOOKS", "1")
    # No file → load_hooks_config returns disabled config → runner None.
    assert hook_install.install_hook_runner() is None


def test_no_runner_when_env_on_yaml_disabled(isolated_env: Path, monkeypatch) -> None:
    monkeypatch.setenv("GENY_ALLOW_HOOKS", "1")
    _write_yaml(hook_install.hooks_yaml_path(), "enabled: false\nentries: {}\n")
    assert hook_install.install_hook_runner() is None


# ── Both gates open ────────────────────────────────────────────────


def test_runner_built_when_both_gates_open(isolated_env: Path, monkeypatch) -> None:
    monkeypatch.setenv("GENY_ALLOW_HOOKS", "1")
    _write_yaml(hook_install.hooks_yaml_path(), """\
enabled: true
entries:
  pre_tool_use:
    - command: ["echo", "hello"]
      timeout_ms: 100
""")
    runner = hook_install.install_hook_runner()
    assert isinstance(runner, HookRunner)
    assert runner.config.enabled is True


def test_attach_kwargs_returns_runner_when_both_open(
    isolated_env: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GENY_ALLOW_HOOKS", "1")
    _write_yaml(hook_install.hooks_yaml_path(), """\
enabled: true
entries:
  pre_tool_use:
    - command: ["true"]
      timeout_ms: 50
""")
    kwargs = hook_install.attach_kwargs()
    assert "hook_runner" in kwargs
    assert isinstance(kwargs["hook_runner"], HookRunner)


# ── Env opt-in parsing ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected_runner",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("anything-else", False),
    ],
)
def test_env_opt_in_parsing(
    isolated_env: Path, monkeypatch, value: str, expected_runner: bool
) -> None:
    monkeypatch.setenv("GENY_ALLOW_HOOKS", value)
    _write_yaml(hook_install.hooks_yaml_path(), """\
enabled: true
entries:
  pre_tool_use:
    - command: ["true"]
      timeout_ms: 50
""")
    result = hook_install.install_hook_runner()
    if expected_runner:
        assert isinstance(result, HookRunner)
    else:
        assert result is None
