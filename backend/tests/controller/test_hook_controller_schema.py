"""H.1 (cycle 20260426_2) — hook controller schema tests.

Verifies:
- HookEntryPayload rejects the legacy ``command: List[str]`` shape.
- _normalize_legacy_entry migrates pre-H.1 entries cleanly.
- _validate_event normalizes uppercase → lowercase + rejects unknowns.
- _entry_to_dict emits the executor-compatible on-disk shape.

Direct unit tests against the helpers — full endpoint integration is
covered by H.3's roundtrip test.
"""

from __future__ import annotations

import pytest

# Pydantic + FastAPI required transitively.
pytest.importorskip("pydantic")
pytest.importorskip("fastapi")

from fastapi import HTTPException  # noqa: E402

import controller.hook_controller as hc  # noqa: E402


def test_payload_rejects_legacy_list_command() -> None:
    """The pre-H.1 frontend sent ``command: ["echo", "hi"]``. Schema
    must surface a clear validation error."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        hc.HookEntryPayload(event="pre_tool_use", command=["echo", "hi"])
    assert "command" in str(exc.value).lower()


def test_payload_accepts_modern_shape() -> None:
    payload = hc.HookEntryPayload(
        event="pre_tool_use",
        command="/usr/local/bin/audit",
        args=["--session", "${session_id}"],
        timeout_ms=2000,
        match={"tool": "Bash"},
        env={"DEBUG": "1"},
        working_dir="/tmp",
    )
    out = hc._entry_to_dict(payload)
    assert out == {
        "command": "/usr/local/bin/audit",
        "args": ["--session", "${session_id}"],
        "timeout_ms": 2000,
        "match": {"tool": "Bash"},
        "env": {"DEBUG": "1"},
        "working_dir": "/tmp",
    }


def test_entry_to_dict_omits_empty_optionals() -> None:
    """Optional fields should be elided so settings.json stays compact
    and round-trips cleanly through executor's parse_hook_config (which
    is happy with absent keys but rejects e.g. ``timeout_ms: null``)."""
    payload = hc.HookEntryPayload(event="post_tool_use", command="/bin/true")
    out = hc._entry_to_dict(payload)
    assert out == {"command": "/bin/true"}
    for absent_key in ("args", "timeout_ms", "match", "env", "working_dir"):
        assert absent_key not in out


def test_validate_event_normalizes_uppercase() -> None:
    """Operators with stale clients still send ``PRE_TOOL_USE``; we
    accept and lowercase."""
    assert hc._validate_event("PRE_TOOL_USE") == "pre_tool_use"
    assert hc._validate_event("pre_tool_use") == "pre_tool_use"
    assert hc._validate_event("  Stage_Enter  ") == "stage_enter"


def test_validate_event_rejects_unknown() -> None:
    with pytest.raises(HTTPException) as exc:
        hc._validate_event("not_a_real_event")
    assert exc.value.status_code == 400


def test_validate_event_rejects_legacy_only_events() -> None:
    """STOP / SUBAGENT_STOP / PRE_COMPACT were in Geny's _KNOWN_EVENTS
    pre-H.1 but never existed in the executor. They must now be
    rejected — using them would silently no-op at the executor side."""
    for legacy in ("STOP", "SUBAGENT_STOP", "PRE_COMPACT"):
        with pytest.raises(HTTPException):
            hc._validate_event(legacy)


def test_normalize_legacy_command_list() -> None:
    """Pre-H.1 ``command: List[str]`` migrates to head-as-command +
    tail-as-args."""
    raw = {"command": ["echo", "hello", "world"], "timeout_ms": 1000}
    out = hc._normalize_legacy_entry(raw)
    assert out is not None
    assert out["command"] == "echo"
    assert out["args"] == ["hello", "world"]
    assert out["timeout_ms"] == 1000


def test_normalize_legacy_tool_filter_to_match() -> None:
    """``tool_filter: ["Bash"]`` → ``match: {"tool": "Bash"}``."""
    raw = {"command": "audit", "tool_filter": ["Bash"]}
    out = hc._normalize_legacy_entry(raw)
    assert out is not None
    assert out["match"] == {"tool": "Bash"}


def test_normalize_legacy_tool_filter_multi_keeps_first(caplog) -> None:
    """Multi-tool tool_filter → first wins, rest logged."""
    import logging

    raw = {"command": "audit", "tool_filter": ["Bash", "Read", "Edit"]}
    with caplog.at_level(logging.WARNING):
        out = hc._normalize_legacy_entry(raw)
    assert out["match"] == {"tool": "Bash"}
    assert any(
        "tool_filter" in rec.message and "multiple" in rec.message
        for rec in caplog.records
    )


def test_normalize_legacy_skips_malformed() -> None:
    """Garbage entries return None (caller skips, list keeps moving)."""
    assert hc._normalize_legacy_entry("not a dict") is None
    assert hc._normalize_legacy_entry({}) is None
    assert hc._normalize_legacy_entry({"command": ""}) is None
    assert hc._normalize_legacy_entry({"command": []}) is None


def test_normalize_modern_entry_passes_through() -> None:
    """A new-shape entry round-trips with all fields preserved."""
    raw = {
        "command": "/x",
        "args": ["a"],
        "timeout_ms": 500,
        "match": {"tool": "Y"},
        "env": {"K": "V"},
        "working_dir": "/wd",
    }
    out = hc._normalize_legacy_entry(raw)
    assert out is not None
    assert out["command"] == "/x"
    assert out["args"] == ["a"]
    assert out["match"] == {"tool": "Y"}
    assert out["env"] == {"K": "V"}
    assert out["working_dir"] == "/wd"
