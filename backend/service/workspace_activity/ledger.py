"""What the agent actually did in its workspace.

Running an agent on a server is the same bargain as installing Claude Code on
one and giving it jobs: you are not watching, so the record has to be exact.
Not "the agent ran 43 tools" — *which file it wrote, what the command
printed, what exited non-zero, and which account paid for the turn.*

This is a **derived** view, not a second write path. It reads the session log
that every turn already writes (cache → database → file) and pairs each
``tool_use`` with its ``tool_result`` by tool id. That choice is the point:
a ledger with its own writer can disagree with the log, and when the two
disagree neither can be trusted. It also means the history of a session that
has since been deleted is still readable, because the log outlives it.

Entry kinds:

``file``     a file was created, written, edited or deleted
``command``  a shell command ran — with its exit status and output
``read``     a file was read (what the agent looked at, which is often the
             answer to "why did it do that")
``tool``     any other tool call
``turn``     a turn boundary: what was asked, what came back
``route``    which account answered, and whether it was a failover
``error``    a tool that failed, surfaced on its own so failures are not
             buried among successes
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

__all__ = ["ACTIVITY_KINDS", "build_activity", "summarize_activity"]

ACTIVITY_KINDS: Tuple[str, ...] = ("file", "command", "read", "tool", "turn", "route", "error")

#: Log levels the ledger reads. Everything else in the log is engine detail
#: (stage enter/exit, memory bookkeeping) that answers a different question.
_LEVELS = ("TOOL_USE", "TOOL_RESULT", "COMMAND", "RESPONSE", "INFO")

_FILE_OPERATIONS = {"create", "write", "edit", "delete", "rename", "multiedit"}


def _meta(entry: Dict[str, Any]) -> Dict[str, Any]:
    raw = entry.get("metadata")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _read_log(session_id: str, limit: int) -> List[Dict[str, Any]]:
    """Oldest-first log entries, from the durable store when there is one.

    The database and file carry the whole history including turns that ran
    before the last restart; the live cache is the fallback for a session
    whose logs have not been flushed yet.
    """
    from service.logging.session_logger import get_session_logger, read_logs_from_file

    entries: List[Dict[str, Any]] = []
    try:
        entries = read_logs_from_file(session_id, limit=limit, newest_first=True) or []
    except Exception as exc:  # noqa: BLE001 — a missing log is not an error
        logger.debug("activity: durable log unavailable for %s (%s)", session_id, exc)
    if not entries:
        session_logger = get_session_logger(session_id, create_if_missing=False)
        if session_logger is not None:
            entries = session_logger.get_logs(limit=limit, newest_first=True)
    return list(reversed(entries))


def _file_entry(seq: int, entry: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    change = meta.get("file_changes") or {}
    return {
        "seq": seq,
        "ts": entry.get("timestamp"),
        "kind": "file",
        "tool": meta.get("tool_name"),
        "toolId": meta.get("tool_id"),
        "path": change.get("file_path"),
        "operation": change.get("operation"),
        "linesAdded": change.get("lines_added"),
        "linesRemoved": change.get("lines_removed"),
        "truncated": bool(change.get("is_content_truncated")),
        "detail": meta.get("detail"),
        # filled in from the matching tool_result
        "ok": None,
        "durationMs": None,
        "error": None,
    }


def _command_entry(seq: int, entry: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    command = meta.get("command_data") or {}
    return {
        "seq": seq,
        "ts": entry.get("timestamp"),
        "kind": "command",
        "tool": meta.get("tool_name"),
        "toolId": meta.get("tool_id"),
        "command": command.get("command") or command.get("cmd"),
        "cwd": command.get("cwd"),
        "description": command.get("description"),
        "detail": meta.get("detail"),
        "ok": None,
        "durationMs": None,
        "output": None,
        "outputTruncated": False,
        "error": None,
    }


def _read_entry(seq: int, entry: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    read = meta.get("file_read") or {}
    return {
        "seq": seq,
        "ts": entry.get("timestamp"),
        "kind": "read",
        "tool": meta.get("tool_name"),
        "toolId": meta.get("tool_id"),
        "path": read.get("file_path") or read.get("path"),
        "detail": meta.get("detail"),
        "ok": None,
        "durationMs": None,
        "error": None,
    }


def _tool_entry(seq: int, entry: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "seq": seq,
        "ts": entry.get("timestamp"),
        "kind": "tool",
        "tool": meta.get("tool_name"),
        "toolId": meta.get("tool_id"),
        "detail": meta.get("detail"),
        "input": meta.get("input_preview"),
        "inputTruncated": bool(meta.get("is_truncated")),
        "ok": None,
        "durationMs": None,
        "error": None,
    }


def _classify_use(seq: int, entry: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    if meta.get("file_changes"):
        return _file_entry(seq, entry, meta)
    if meta.get("command_data"):
        return _command_entry(seq, entry, meta)
    if meta.get("file_read"):
        return _read_entry(seq, entry, meta)
    return _tool_entry(seq, entry, meta)


def _apply_result(target: Dict[str, Any], meta: Dict[str, Any]) -> None:
    """Fold a ``tool_result`` into the call it belongs to.

    A tool call without its result is only half the record — "ran a command"
    is not the same claim as "ran a command that exited 1".
    """
    failed = bool(meta.get("is_error"))
    target["ok"] = not failed
    target["durationMs"] = meta.get("duration_ms")
    preview = meta.get("result_preview")
    if target["kind"] == "command":
        target["output"] = preview
        target["outputTruncated"] = bool(meta.get("is_truncated"))
    if failed:
        target["error"] = preview
        target["kind"] = "error"
        target["failedKind"] = target.get("failedKind") or _kind_before_failure(target)


def _kind_before_failure(target: Dict[str, Any]) -> str:
    if "command" in target:
        return "command"
    if target.get("operation"):
        return "file"
    if "path" in target:
        return "read"
    return "tool"


def build_activity(
    session_id: str,
    *,
    limit: int = 200,
    scan: int = 2000,
    kinds: Optional[Sequence[str]] = None,
    newest_first: bool = True,
) -> Dict[str, Any]:
    """The workspace's history, newest first by default.

    ``scan`` bounds how much of the log is read to build it; ``limit`` bounds
    what comes back. They are separate because one workspace action can take
    several log entries (a call, its result), so the two never line up.
    """
    wanted: Optional[Set[str]] = {k for k in (kinds or ()) if k in ACTIVITY_KINDS} or None
    raw = _read_log(session_id, max(scan, limit))

    activity: List[Dict[str, Any]] = []
    by_tool_id: Dict[str, Dict[str, Any]] = {}
    seq = 0

    for entry in raw:
        meta = _meta(entry)
        kind = meta.get("type")
        level = str(entry.get("level") or "")

        if kind == "tool_use" or level == "TOOL_USE":
            seq += 1
            item = _classify_use(seq, entry, meta)
            activity.append(item)
            tool_id = meta.get("tool_id")
            if tool_id:
                by_tool_id[str(tool_id)] = item
            continue

        if kind == "tool_result" or level == "TOOL_RESULT":
            tool_id = str(meta.get("tool_id") or "")
            target = by_tool_id.pop(tool_id, None)
            if target is None:
                # An unpaired result — an older log, or a call whose
                # announcement was lost. Record it rather than drop it: a
                # failure with no visible cause is still a failure.
                seq += 1
                target = _tool_entry(seq, entry, meta)
                activity.append(target)
            _apply_result(target, meta)
            continue

        if level == "COMMAND":
            seq += 1
            activity.append({
                "seq": seq, "ts": entry.get("timestamp"), "kind": "turn",
                "role": "user", "text": entry.get("message"),
            })
            continue

        if level == "RESPONSE":
            seq += 1
            activity.append({
                "seq": seq, "ts": entry.get("timestamp"), "kind": "turn",
                "role": "assistant", "text": entry.get("message"),
                "durationMs": meta.get("duration_ms"),
                "cost": meta.get("cost_usd"),
            })
            continue

        if meta.get("type") in ("route", "failover"):
            seq += 1
            activity.append({
                "seq": seq, "ts": entry.get("timestamp"), "kind": "route",
                "accountId": meta.get("accountId"), "label": meta.get("label"),
                "model": meta.get("model"), "failedOver": meta.get("type") == "failover",
            })

    if wanted is not None:
        activity = [a for a in activity if a["kind"] in wanted]
    if newest_first:
        activity.reverse()
    return {
        "session_id": session_id,
        "entries": activity[:limit],
        "total": len(activity),
        "scanned": len(raw),
        "truncated": len(activity) > limit,
    }


def summarize_activity(session_id: str, *, scan: int = 5000) -> Dict[str, Any]:
    """A rollup: which files the agent touched, what it ran, what failed.

    The question an operator actually opens a workspace with — "what changed
    while I wasn't looking" — answered without reading a log.
    """
    built = build_activity(session_id, limit=10 ** 6, scan=scan, newest_first=False)
    files: Dict[str, Dict[str, Any]] = {}
    commands: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    tool_counts: Dict[str, int] = {}
    turns = 0

    for item in built["entries"]:
        tool = item.get("tool")
        if tool:
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
        kind = item["kind"] if item["kind"] != "error" else item.get("failedKind", "tool")

        if kind == "file" and item.get("path"):
            record = files.setdefault(item["path"], {
                "path": item["path"], "operations": [], "writes": 0,
                "linesAdded": 0, "linesRemoved": 0, "lastTs": None, "failed": 0,
            })
            operation = item.get("operation") or "write"
            if operation not in record["operations"]:
                record["operations"].append(operation)
            record["writes"] += 1
            record["linesAdded"] += int(item.get("linesAdded") or 0)
            record["linesRemoved"] += int(item.get("linesRemoved") or 0)
            record["lastTs"] = item.get("ts")
            if item["kind"] == "error":
                record["failed"] += 1
        elif kind == "command" and item.get("command"):
            commands.append({
                "seq": item["seq"], "ts": item.get("ts"), "command": item["command"],
                "cwd": item.get("cwd"), "ok": item.get("ok"),
                "durationMs": item.get("durationMs"),
            })
        elif kind == "turn":
            turns += 1

        if item["kind"] == "error":
            failures.append({
                "seq": item["seq"], "ts": item.get("ts"), "tool": item.get("tool"),
                "error": item.get("error"),
            })

    return {
        "session_id": session_id,
        "files": sorted(files.values(), key=lambda f: f["path"]),
        "commands": commands,
        "failures": failures,
        "toolCounts": dict(sorted(tool_counts.items(), key=lambda kv: -kv[1])),
        "turns": turns,
        "scanned": built["scanned"],
    }
