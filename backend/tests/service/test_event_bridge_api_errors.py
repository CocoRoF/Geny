"""Tests for the provider error-envelope bridge in ``agent_session``.

A provider failure arrives as a first-class ``api.error`` event carrying
a code, a category and the vendor's own message; the bridge turns it
into the sentence the user sees in the session log.

This file used to cover tool events too — ``api.cli_tool_call`` and
``api.tool_result {source: "cli"}`` — because a CLI backend ran its own
loop and its tool calls never reached Stage 10. No backend does that any
more (executor 2.68.0): every tool call goes through Stage 10, which
logs it itself, and ``api.cli_tool_call`` can no longer be emitted at
all. Bridging it would double-render.

``_tool_result_text`` stays tested here — it still normalises the
``content`` shapes that reach the tool log.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from service.executor.agent_session import (
    _AUTH_EXPIRED_MESSAGE,
    _bridge_cli_stream_event,
    _friendly_api_error_message,
    _tool_result_text,
)


class _FakeSessionLogger:
    """Records the bridge's ``log`` calls."""

    def __init__(self) -> None:
        self.logs: List[Dict[str, Any]] = []

    def log(self, level: Any = None, message: str = "", metadata: Optional[Dict] = None) -> None:
        self.logs.append({"level": level, "message": message, "metadata": metadata or {}})


# ── api.error → friendly Korean error log ────────────────────────────


def test_api_error_auth_code_logs_korean_message() -> None:
    sl = _FakeSessionLogger()
    _bridge_cli_stream_event(
        sl,
        "api.error",
        {
            "code": "exec.cli.auth_failed",
            "category": "cli_auth_failed",
            "provider": "geny_claude_code",
            "message": "Failed to authenticate. API Error: 401",
        },
    )
    assert len(sl.logs) == 1
    assert _AUTH_EXPIRED_MESSAGE in sl.logs[0]["message"]
    assert "401" in sl.logs[0]["message"], "original message preserved as suffix"
    assert sl.logs[0]["metadata"]["error_code"] == "exec.cli.auth_failed"


def test_api_error_generic_includes_code_and_message() -> None:
    sl = _FakeSessionLogger()
    _bridge_cli_stream_event(
        sl,
        "api.error",
        {
            "code": "exec.api.rate_limited",
            "category": "rate_limited",
            "provider": "anthropic",
            "message": "429 too many requests",
        },
    )
    assert len(sl.logs) == 1
    msg = sl.logs[0]["message"]
    assert "exec.api.rate_limited" in msg
    assert "429 too many requests" in msg


def test_friendly_message_auth_category_without_code() -> None:
    msg = _friendly_api_error_message({"category": "auth", "message": "expired"})
    assert msg.startswith(_AUTH_EXPIRED_MESSAGE)


def test_bridge_never_raises_on_logger_failure() -> None:
    class _Boom:
        def log(self, **kwargs: Any) -> None:
            raise RuntimeError("boom")

    _bridge_cli_stream_event(
        _Boom(), "api.error", {"code": "x", "message": "y"},
    )  # must not raise


def test_tool_events_are_not_bridged() -> None:
    """Stage 10 logs every dispatch itself; bridging would double-render."""
    sl = _FakeSessionLogger()
    for event_type, data in (
        ("api.cli_tool_call", {"id": "t", "name": "Bash", "input": {}}),
        ("api.tool_use", {"id": "t", "name": "Bash", "input": {}, "source": "api"}),
        ("api.tool_result", {"tool_use_id": "t", "content": "ok", "source": "api"}),
    ):
        _bridge_cli_stream_event(sl, event_type, data)
    assert sl.logs == []


# ── result-text normalisation ────────────────────────────────────────


def test_tool_result_text_shapes() -> None:
    assert _tool_result_text(None) is None
    assert _tool_result_text("plain") == "plain"
    assert _tool_result_text([{"type": "text", "text": "a"}, "b"]) == "a\nb"
    assert _tool_result_text({"k": 1}) == '{"k": 1}'
