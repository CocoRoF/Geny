"""H.3 (cycle 20260426_2) — end-to-end hook config roundtrip.

Writes hooks via Geny's REST endpoints (calling the controller
handlers directly), reads the resulting settings.json off disk, then
passes the file through the executor's ``parse_hook_config`` to assert
it parses without raising and the resulting :class:`HookConfig`
contains the entries we wrote.

This is the regression guard for the H.1 schema rewrite — if anyone
re-introduces a shape mismatch, this test will fail loudly instead of
hooks silently never firing again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

# pydantic + fastapi + executor are all required transitively.
pytest.importorskip("pydantic")
pytest.importorskip("fastapi")
pytest.importorskip("geny_executor")

from geny_executor.hooks import HookEvent, parse_hook_config  # noqa: E402

import controller.hook_controller as hc  # noqa: E402


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path) -> Path:
    """Redirect the controller's user settings path to a temp file so
    each test starts with a clean slate and never touches the real
    ``~/.geny/settings.json``."""
    fake = tmp_path / ".geny" / "settings.json"
    fake.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(hc, "_user_settings_path", lambda: fake)
    # Disable the loader reload — we read the file directly here so the
    # process-wide loader doesn't matter for this test.
    monkeypatch.setattr(hc, "_reload_loader", lambda: None)
    return fake


def _read_section(path: Path) -> Dict[str, Any]:
    """Read settings.json:hooks off disk."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("hooks") or {}


def _wrap_for_executor(section: Dict[str, Any]) -> Dict[str, Any]:
    """Translate Geny's on-disk shape ({enabled, entries:{event:[…]}})
    into the wrapper ``parse_hook_config`` consumes
    ({enabled, hooks:{event:[…]}}). Mirrors the production
    install layer."""
    out: Dict[str, Any] = {"enabled": bool(section.get("enabled", False))}
    if "audit_log_path" in section:
        out["audit_log_path"] = section["audit_log_path"]
    out["hooks"] = section.get("entries") or {}
    return out


@pytest.mark.asyncio
async def test_modern_payload_parses_in_executor(isolated_settings) -> None:
    """Happy path: write via the controller, parse via the executor."""
    payload = hc.HookEntryPayload(
        event="pre_tool_use",
        command="/usr/local/bin/audit",
        args=["--session", "${session_id}"],
        timeout_ms=2000,
        match={"tool": "Bash"},
        env={"DEBUG": "1"},
        working_dir="/tmp",
    )
    await hc.append_entry(payload, _auth={})

    section = _read_section(isolated_settings)
    cfg = parse_hook_config(_wrap_for_executor(section), source="test")

    assert cfg.enabled is False  # entries persist independent of enabled flag
    entries = cfg.entries.get(HookEvent.PRE_TOOL_USE) or []
    assert len(entries) == 1
    entry = entries[0]
    assert entry.command == "/usr/local/bin/audit"
    assert entry.args == ["--session", "${session_id}"]
    assert entry.timeout_ms == 2000
    assert entry.match == {"tool": "Bash"}
    assert entry.env == {"DEBUG": "1"}
    assert entry.working_dir == "/tmp"


@pytest.mark.asyncio
async def test_minimal_entry_parses(isolated_settings) -> None:
    """Optional fields elided → still valid for the executor."""
    payload = hc.HookEntryPayload(event="post_tool_use", command="/bin/true")
    await hc.append_entry(payload, _auth={})

    section = _read_section(isolated_settings)
    cfg = parse_hook_config(_wrap_for_executor(section), source="test")

    entries = cfg.entries.get(HookEvent.POST_TOOL_USE) or []
    assert len(entries) == 1
    assert entries[0].command == "/bin/true"
    assert entries[0].args == []
    assert entries[0].match == {}


@pytest.mark.asyncio
async def test_audit_log_path_roundtrips(isolated_settings) -> None:
    """Top-level audit_log_path PATCH lands in settings.json and the
    executor parses it on the wrapper."""
    await hc.patch_audit_log(
        hc.HookAuditLogPatch(audit_log_path="/var/log/geny/hooks.jsonl"),
        _auth={},
    )

    section = _read_section(isolated_settings)
    cfg = parse_hook_config(_wrap_for_executor(section), source="test")

    assert cfg.audit_log_path == "/var/log/geny/hooks.jsonl"


@pytest.mark.asyncio
async def test_legacy_entry_migrates_on_next_write(isolated_settings) -> None:
    """A pre-H.1 settings.json (capitalized event keys, command list,
    tool_filter) reads cleanly via the controller's normalizer; a
    follow-up write rewrites the file in the new shape."""
    # Seed legacy file by hand.
    legacy = {
        "hooks": {
            "enabled": True,
            "entries": {
                "PRE_TOOL_USE": [
                    {
                        "command": ["/old/audit", "--legacy"],
                        "tool_filter": ["Bash"],
                        "timeout_ms": 1500,
                    },
                ],
            },
        },
    }
    isolated_settings.write_text(json.dumps(legacy), encoding="utf-8")

    # List endpoint should normalize without raising.
    response = await hc.list_entries(_auth={})
    assert len(response.entries) == 1
    row = response.entries[0]
    assert row.command == "/old/audit"
    assert row.args == ["--legacy"]
    assert row.match == {"tool": "Bash"}
    assert row.timeout_ms == 1500

    # Append a new entry — file should rewrite with both in the new shape.
    await hc.append_entry(
        hc.HookEntryPayload(
            event="pre_tool_use",
            command="/new/audit",
        ),
        _auth={},
    )

    section = _read_section(isolated_settings)
    # After rewrite the legacy uppercase key is migrated to lowercase.
    assert "pre_tool_use" in section["entries"]
    # Executor parses the resulting file cleanly.
    cfg = parse_hook_config(_wrap_for_executor(section), source="test")
    assert len(cfg.entries.get(HookEvent.PRE_TOOL_USE) or []) == 2
