"""The record of what an agent did while nobody was watching.

The ledger is derived from the session log rather than written separately —
so what it must prove is that the derivation is faithful:

* a tool call and its result are ONE action, not two, and the action carries
  the result's verdict ("ran a command" and "ran a command that exited 1"
  are different claims);
* a failure is surfaced as a failure rather than buried among successes;
* a result whose call is missing is still recorded — a failure with no
  visible cause is still a failure;
* the rollup counts each file's real edits, not each log line.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from service.workspace_activity import build_activity, summarize_activity


def _entry(level: str, message: str, metadata: Dict[str, Any], ts: str = "2026-09-17T10:00:00") -> Dict[str, Any]:
    return {"timestamp": ts, "level": level, "message": message, "metadata": metadata}


def _use(tool: str, tool_id: str, **meta: Any) -> Dict[str, Any]:
    return _entry("TOOL_USE", f"🔧 {tool}", {
        "type": "tool_use", "tool_name": tool, "tool_id": tool_id, "detail": tool, **meta,
    })


def _result(tool: str, tool_id: str, *, is_error: bool = False,
            preview: str = "", duration_ms: int = 12) -> Dict[str, Any]:
    return _entry("TOOL_RESULT", f"TOOL_RESULT: {tool}", {
        "type": "tool_result", "tool_name": tool, "tool_id": tool_id,
        "is_error": is_error, "result_preview": preview, "duration_ms": duration_ms,
    })


_WROTE_A_FILE = _use("Write", "t1", file_changes={
    "file_path": "/w/app.py", "operation": "write", "lines_added": 12, "lines_removed": 0,
})
_RAN_A_COMMAND = _use("Bash", "t2", command_data={"command": "pytest -q", "cwd": "/w"})
_READ_A_FILE = _use("Read", "t3", file_read={"file_path": "/w/app.py"})


@pytest.fixture()
def log(monkeypatch: pytest.MonkeyPatch):
    """Install a log for the ledger to read, oldest-first as callers write it."""
    entries: List[Dict[str, Any]] = []

    def install(*rows: Dict[str, Any]) -> None:
        entries[:] = list(rows)

    def fake_read(session_id: str, limit: int = 100, level: Any = None,
                  offset: int = 0, newest_first: bool = True) -> List[Dict[str, Any]]:
        rows = list(entries)
        return list(reversed(rows)) if newest_first else rows

    import service.logging.session_logger as sl

    monkeypatch.setattr(sl, "read_logs_from_file", fake_read)
    return install


class TestPairing:
    def test_a_call_and_its_result_are_one_action(self, log) -> None:
        log(_WROTE_A_FILE, _result("Write", "t1", preview="ok"))
        entries = build_activity("s1")["entries"]
        assert len(entries) == 1
        assert entries[0]["kind"] == "file"
        assert entries[0]["ok"] is True
        assert entries[0]["durationMs"] == 12

    def test_a_command_carries_what_it_printed(self, log) -> None:
        log(_RAN_A_COMMAND, _result("Bash", "t2", preview="3 passed"))
        entry = build_activity("s1")["entries"][0]
        assert entry["kind"] == "command"
        assert entry["command"] == "pytest -q"
        assert entry["cwd"] == "/w"
        assert entry["output"] == "3 passed"

    def test_an_unfinished_call_is_recorded_with_no_verdict(self, log) -> None:
        """A turn that is still running, or one that died — either way the
        call happened and the record should say so."""
        log(_WROTE_A_FILE)
        entry = build_activity("s1")["entries"][0]
        assert entry["kind"] == "file"
        assert entry["ok"] is None

    def test_a_result_with_no_call_is_still_recorded(self, log) -> None:
        log(_result("Bash", "orphan", is_error=True, preview="boom"))
        entries = build_activity("s1")["entries"]
        assert len(entries) == 1
        assert entries[0]["kind"] == "error"
        assert entries[0]["error"] == "boom"


class TestFailures:
    def test_a_failed_command_surfaces_as_a_failure(self, log) -> None:
        log(_RAN_A_COMMAND, _result("Bash", "t2", is_error=True, preview="exit 1"))
        entry = build_activity("s1")["entries"][0]
        assert entry["kind"] == "error"
        assert entry["failedKind"] == "command"
        assert entry["error"] == "exit 1"

    def test_failures_can_be_read_on_their_own(self, log) -> None:
        log(
            _WROTE_A_FILE, _result("Write", "t1", preview="ok"),
            _RAN_A_COMMAND, _result("Bash", "t2", is_error=True, preview="exit 1"),
        )
        only = build_activity("s1", kinds=["error"])["entries"]
        assert [e["tool"] for e in only] == ["Bash"]


class TestOrderAndFilters:
    def test_newest_first_by_default(self, log) -> None:
        log(_WROTE_A_FILE, _RAN_A_COMMAND)
        kinds = [e["kind"] for e in build_activity("s1")["entries"]]
        assert kinds == ["command", "file"]

    def test_it_can_be_read_in_the_order_it_happened(self, log) -> None:
        log(_WROTE_A_FILE, _RAN_A_COMMAND)
        kinds = [e["kind"] for e in build_activity("s1", newest_first=False)["entries"]]
        assert kinds == ["file", "command"]

    def test_filtering_to_files(self, log) -> None:
        log(_WROTE_A_FILE, _RAN_A_COMMAND, _READ_A_FILE)
        kinds = {e["kind"] for e in build_activity("s1", kinds=["file"])["entries"]}
        assert kinds == {"file"}

    def test_the_limit_is_reported_as_truncation(self, log) -> None:
        log(_WROTE_A_FILE, _RAN_A_COMMAND, _READ_A_FILE)
        built = build_activity("s1", limit=1)
        assert len(built["entries"]) == 1
        assert built["truncated"] is True
        assert built["total"] == 3


class TestTurns:
    def test_turn_boundaries_are_part_of_the_record(self, log) -> None:
        log(
            _entry("COMMAND", "테스트를 돌려줘", {}),
            _RAN_A_COMMAND, _result("Bash", "t2", preview="3 passed"),
            _entry("RESPONSE", "전부 통과했습니다.", {"duration_ms": 900}),
        )
        entries = build_activity("s1", newest_first=False)["entries"]
        assert [e["kind"] for e in entries] == ["turn", "command", "turn"]
        assert entries[0]["role"] == "user"
        assert entries[2]["role"] == "assistant"

    def test_a_route_event_says_who_answered(self, log) -> None:
        log(_entry("INFO", "route", {
            "type": "route", "accountId": "a1", "label": "Claude 2", "model": "opus",
        }))
        entry = build_activity("s1")["entries"][0]
        assert entry["kind"] == "route"
        assert entry["label"] == "Claude 2"
        assert entry["failedOver"] is False

    def test_a_failover_is_marked_as_one(self, log) -> None:
        log(_entry("INFO", "failover", {"type": "failover", "accountId": "a1"}))
        assert build_activity("s1")["entries"][0]["failedOver"] is True


class TestSummary:
    def test_a_file_edited_twice_counts_once_with_both_edits(self, log) -> None:
        log(
            _WROTE_A_FILE, _result("Write", "t1", preview="ok"),
            _use("Edit", "t4", file_changes={
                "file_path": "/w/app.py", "operation": "edit",
                "lines_added": 3, "lines_removed": 1,
            }),
            _result("Edit", "t4", preview="ok"),
        )
        summary = summarize_activity("s1")
        assert len(summary["files"]) == 1
        record = summary["files"][0]
        assert record["path"] == "/w/app.py"
        assert record["writes"] == 2
        assert record["linesAdded"] == 15
        assert record["linesRemoved"] == 1
        assert set(record["operations"]) == {"write", "edit"}

    def test_commands_and_failures_are_listed(self, log) -> None:
        log(
            _RAN_A_COMMAND, _result("Bash", "t2", is_error=True, preview="exit 1"),
        )
        summary = summarize_activity("s1")
        assert [c["command"] for c in summary["commands"]] == ["pytest -q"]
        assert summary["commands"][0]["ok"] is False
        assert [f["tool"] for f in summary["failures"]] == ["Bash"]

    def test_reads_do_not_count_as_changes(self, log) -> None:
        """What the agent looked at is worth recording, but it is not a
        change — a summary that conflates them cannot answer "what changed"."""
        log(_READ_A_FILE, _result("Read", "t3", preview="..."))
        summary = summarize_activity("s1")
        assert summary["files"] == []
        assert summary["toolCounts"] == {"Read": 1}

    def test_an_empty_session_summarises_to_nothing(self, log) -> None:
        log()
        summary = summarize_activity("s1")
        assert summary["files"] == [] and summary["commands"] == []
        assert summary["turns"] == 0


class TestMetadataShapes:
    def test_metadata_stored_as_json_text_is_still_read(self, log) -> None:
        """The database round-trips metadata as text; the cache keeps a dict.
        Both reach here."""
        row = _WROTE_A_FILE.copy()
        row["metadata"] = json.dumps(row["metadata"], ensure_ascii=False)
        log(row)
        assert build_activity("s1")["entries"][0]["path"] == "/w/app.py"

    def test_a_missing_log_is_an_empty_ledger_not_an_error(self, log) -> None:
        log()
        assert build_activity("s1") == {
            "session_id": "s1", "entries": [], "total": 0, "scanned": 0, "truncated": False,
        }


class TestWhatWasAsked:
    """A turn row says what was asked. Both halves of that were wrong."""

    def test_the_logs_own_prefix_is_not_part_of_the_message(self, log) -> None:
        # The log writes `PROMPT: <text>`. That prefix belongs to the log line,
        # and carried through it lands on screen in front of every single thing
        # the user said.
        log(_entry("COMMAND", "PROMPT: 테스트를 돌려줘", {}))
        turns = [e for e in build_activity("s")["entries"] if e["kind"] == "turn"]
        assert turns[0]["text"] == "테스트를 돌려줘"
        assert turns[0]["role"] == "user"

    def test_a_scheduled_thought_is_not_the_user_asking(self, log) -> None:
        # An autonomous trigger arrives down the same channel as a typed
        # message. Recorded as `user`, the ledger claims someone asked for it.
        log(_entry("COMMAND", "PROMPT: [THINKING_TRIGGER:time_evening] The evening is here.", {}))
        turns = [e for e in build_activity("s")["entries"] if e["kind"] == "turn"]
        assert turns[0]["role"] == "trigger"
        assert turns[0]["text"].startswith("[THINKING_TRIGGER:time_evening]")

    def test_a_bare_prompt_is_left_alone(self, log) -> None:
        log(_entry("COMMAND", "just this", {}))
        turns = [e for e in build_activity("s")["entries"] if e["kind"] == "turn"]
        assert turns[0]["text"] == "just this"


def test_the_answer_is_not_prefixed_with_the_log_verdict(log) -> None:
    """`SUCCESS:` is the log line's word for "the turn finished", not part of
    what the agent said. On screen it read `SUCCESS: Error: CLI exited with
    code 1` — both of the log's prefixes, disagreeing, in front of a failure."""
    log(_entry("RESPONSE", "SUCCESS: 준비됐어.", {"success": True}))
    turns = [e for e in build_activity("s")["entries"] if e["kind"] == "turn"]
    assert turns[0]["text"] == "준비됐어."
    assert turns[0]["ok"] is True


def test_a_failed_turn_says_so(log) -> None:
    log(_entry("RESPONSE", "FAILED: exited with code 1", {"success": False}))
    turns = [e for e in build_activity("s")["entries"] if e["kind"] == "turn"]
    assert turns[0]["text"] == "exited with code 1"
    assert turns[0]["ok"] is False
