"""Tests for the Claude Code health probe — specifically the OAuth
``expiresAt`` check that distinguishes "logged in with valid token"
from "logged in with stale token, refresh failed".

Without this check, the LLM-backends settings card showed "준비됨"
(ready) for tokens whose ``accessToken`` expired hours ago and
whose ``refreshToken`` also wasn't producing new credentials —
every Developer session would then crash with the unhelpful
``CLI '/usr/bin/claude' exited with code 1:`` empty-stderr line.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

import pytest


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _write_credentials(home: Path, *, expires_at_ms: int) -> Path:
    """Drop a Claude Code-shaped credentials file under *home*.
    Returns the file path."""
    creds_dir = home / ".claude"
    creds_dir.mkdir(parents=True, exist_ok=True)
    path = creds_dir / ".credentials.json"
    path.write_text(json.dumps({
        "claudeAiOauth": {
            "accessToken": "fake-access-token",
            "refreshToken": "fake-refresh-token",
            "expiresAt": expires_at_ms,
            "scopes": ["user:inference"],
            "subscriptionType": "max",
            "rateLimitTier": "default_claude_max_20x",
        }
    }), encoding="utf-8")
    return path


@pytest.fixture
def _temp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


# ── Pure expires-at parsing ──────────────────────────────────────────


def test_expires_at_returns_int_when_valid(_temp_home: Path) -> None:
    from controller.llm_backends_controller import _read_claude_oauth_expires_at_ms

    _write_credentials(_temp_home, expires_at_ms=1779107407695)
    assert _read_claude_oauth_expires_at_ms() == 1779107407695


def test_expires_at_returns_none_when_file_missing(_temp_home: Path) -> None:
    from controller.llm_backends_controller import _read_claude_oauth_expires_at_ms
    assert _read_claude_oauth_expires_at_ms() is None


def test_expires_at_returns_none_when_schema_unexpected(_temp_home: Path) -> None:
    """File exists but doesn't carry ``claudeAiOauth`` (e.g. API-key
    authentication, future schema migration). Must not crash."""
    from controller.llm_backends_controller import _read_claude_oauth_expires_at_ms

    creds_dir = _temp_home / ".claude"
    creds_dir.mkdir()
    (creds_dir / ".credentials.json").write_text(
        '{"apiKey": "sk-..."}', encoding="utf-8",
    )
    assert _read_claude_oauth_expires_at_ms() is None


def test_expires_at_returns_none_for_malformed_json(_temp_home: Path) -> None:
    from controller.llm_backends_controller import _read_claude_oauth_expires_at_ms

    creds_dir = _temp_home / ".claude"
    creds_dir.mkdir()
    (creds_dir / ".credentials.json").write_text(
        'not valid json', encoding="utf-8",
    )
    assert _read_claude_oauth_expires_at_ms() is None


# ── Health probe end-to-end ──────────────────────────────────────────


class _FakeBundleCreds:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key


class _FakeBundle:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self._creds = _FakeBundleCreds(api_key=api_key)

    def get(self, _: str) -> _FakeBundleCreds:
        return self._creds


def _install_probe_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    binary: str = "/usr/bin/claude",
    version: str = "2.1.143 (Claude Code)",
    auth_status_rc: int = 0,
) -> None:
    from controller import llm_backends_controller as ctl

    monkeypatch.setattr(ctl, "_detect", lambda *_a, **_kw: binary)

    async def _fake_run_cmd(argv, **kwargs):
        if argv[-1] == "--version":
            return (0, version, "")
        # auth status / whoami / --auth-status probes
        return (auth_status_rc, "", "")

    monkeypatch.setattr(ctl, "_run_cmd", _fake_run_cmd)


def test_health_probe_flags_expired_subscription_token(
    _temp_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The token expired 1 hour ago. ``loggedIn`` reports true (the
    file's there) but our probe must mark ``auth_ok=False`` so the
    settings card doesn't show "준비됨" on stale credentials."""
    from controller.llm_backends_controller import _check_claude_code
    from service.config.sub_config.general.cli_backends_config import (
        CLIBackendClaudeCodeConfig,
    )

    expired_ms = int(time.time() * 1000) - 3_600_000  # 1h ago
    _write_credentials(_temp_home, expires_at_ms=expired_ms)
    _install_probe_stubs(monkeypatch)

    cfg = CLIBackendClaudeCodeConfig(enabled=True)
    health = _run(_check_claude_code(_FakeBundle(), cfg))

    assert health.available is False
    assert health.auth_ok is False
    assert health.detail_code == "claude_code.auth_expired"
    assert "만료" in health.detail
    assert "다시 로그인" in health.detail or "Sign in" in health.detail
    assert health.detail_params["expired"] == "true"
    assert health.detail_params["expires_at_ms"] == str(expired_ms)


def test_health_probe_keeps_ready_for_valid_token(
    _temp_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token is valid for another day — card must still show
    "준비됨" (``detail_code = claude_code.ready``)."""
    from controller.llm_backends_controller import _check_claude_code
    from service.config.sub_config.general.cli_backends_config import (
        CLIBackendClaudeCodeConfig,
    )

    fresh_ms = int(time.time() * 1000) + 24 * 3_600_000
    _write_credentials(_temp_home, expires_at_ms=fresh_ms)
    _install_probe_stubs(monkeypatch)

    cfg = CLIBackendClaudeCodeConfig(enabled=True)
    health = _run(_check_claude_code(_FakeBundle(), cfg))

    assert health.available is True
    assert health.auth_ok is True
    assert health.detail_code == "claude_code.ready"
    assert health.detail_params["expired"] == "false"


def test_health_probe_handles_missing_credentials_gracefully(
    _temp_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``auth status`` returns 0 but the file we cross-check is
    absent. Must not crash — fall back to "ready" (we have no
    expiry info to invalidate the CLI's say-so)."""
    from controller.llm_backends_controller import _check_claude_code
    from service.config.sub_config.general.cli_backends_config import (
        CLIBackendClaudeCodeConfig,
    )

    # No credentials file written.
    _install_probe_stubs(monkeypatch)

    cfg = CLIBackendClaudeCodeConfig(enabled=True)
    health = _run(_check_claude_code(_FakeBundle(), cfg))

    # ``loggedIn`` was true (probe rc=0), expires-check returned None
    # → leave auth_ok=True. False-negative is worse than false-
    # positive here; the user will hit the auth error at session
    # exec time and get the friendly message from the assembler
    # patch instead.
    assert health.available is True
    assert health.auth_ok is True
    assert health.detail_params["expired"] == "false"
    assert health.detail_params["expires_at_ms"] == ""


# The connection-test endpoint that used to be covered here is gone with the
# server-wide Claude login it belonged to. Testing a login now means testing
# an ACCOUNT: POST /api/llm-accounts/{id}/test, covered in
# tests/controller/test_llm_accounts_endpoints.py.


def test_health_probe_api_key_path_skips_expires_check(
    _temp_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user picked the API key auth mode, the expires-check on
    the OAuth credential file is irrelevant — that's a different auth
    method. Even with a stale OAuth file lingering on disk, the
    api_key mode stays healthy."""
    from controller.llm_backends_controller import _check_claude_code
    from service.config.sub_config.general.cli_backends_config import (
        CLIBackendClaudeCodeConfig,
    )

    _write_credentials(
        _temp_home,
        expires_at_ms=int(time.time() * 1000) - 3_600_000,
    )
    _install_probe_stubs(monkeypatch)
    # New behaviour: auth detection follows ``auth_mode`` strictly.
    # Selecting api_key here is the explicit "I want API key auth" pick
    # from the LLM Backends modal radio.
    cfg = CLIBackendClaudeCodeConfig(enabled=True, auth_mode="api_key", api_key="sk-fake")
    health = _run(_check_claude_code(_FakeBundle(api_key="sk-fake"), cfg))

    assert health.auth_method == "api_key"
    assert health.auth_ok is True
    assert health.detail_code == "claude_code.ready"
