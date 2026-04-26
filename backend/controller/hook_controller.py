"""Hook entry CRUD.

Mutates the ``hooks`` section of user-scope ``~/.geny/settings.json`` so
the operator can manage subprocess hooks (the executor's ``HookRunner``)
without hand-editing the file.

H.1 (cycle 20260426_2) — full schema rewrite to match
``geny_executor.hooks.HookConfigEntry`` exactly. Prior shape was
incompatible with the executor's parser (``command: List[str]`` instead
of ``str``; ``tool_filter`` instead of ``match`` dict) and hooks never
fired. See ``dev_docs/20260426_2/analysis/01_hook_schema_bug.md``.

On-disk schema (post-H.1)::

    {
      "hooks": {
        "enabled": true,
        "audit_log_path": "/var/log/geny/hooks.jsonl",
        "entries": {
          "pre_tool_use": [
            {
              "command": "/usr/local/bin/audit-hook",
              "args": ["--session", "${session_id}"],
              "timeout_ms": 1000,
              "match": {"tool": "Bash"},
              "env": {"DEBUG": "1"},
              "working_dir": "/tmp"
            }
          ]
        }
      }
    }

Event keys are the lowercase ``HookEvent.value`` (the form executor's
``parse_hook_config`` accepts). Reads tolerate the legacy uppercase
form so a pre-H.1 settings.json migrates lazily on next write.

Backwards-compat read migration:
- Capitalized event keys → lowercase.
- ``command: List[str]`` → ``command: str`` (head) + ``args: List[str]`` (tail).
- ``tool_filter: ["X"]`` → ``match: {"tool": "X"}`` (single-tool case
  preserved; multi-tool surfaces as a warning + first wins).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from service.auth.auth_middleware import require_auth

logger = getLogger(__name__)

router = APIRouter(prefix="/api/hooks", tags=["hooks"])

# Mirrors ``geny_executor.hooks.HookEvent`` (lowercase enum *values*).
# Synced by hand — listing them lets the API reject typos before they
# hit the executor's parser.
_KNOWN_EVENTS = frozenset({
    "session_start",
    "session_end",
    "pipeline_start",
    "pipeline_end",
    "stage_enter",
    "stage_exit",
    "user_prompt_submit",
    "pre_tool_use",
    "post_tool_use",
    "post_tool_failure",
    "permission_request",
    "permission_denied",
    "loop_iteration_end",
    "cwd_changed",
    "mcp_server_state",
    "notification",
})


# ── Schemas ──────────────────────────────────────────────


class HookEntryPayload(BaseModel):
    """Mirrors ``geny_executor.hooks.HookConfigEntry``.

    ``command`` is the executable path (string). ``args`` is the
    argument list — kept separate because the executor never spawns a
    shell, so quoting / escaping inside a single string would not
    behave the way operators expect.
    """

    event: str = Field(..., description="HookEvent value (e.g. pre_tool_use)")
    command: str = Field(..., min_length=1, description="Executable path")
    args: List[str] = Field(default_factory=list)
    timeout_ms: Optional[int] = Field(None, ge=1)
    match: Dict[str, Any] = Field(
        default_factory=dict,
        description="Filter expression. Empty = fires for every event of this kind. "
                    'Today the only meaningful key is "tool" (exact tool name).',
    )
    env: Dict[str, str] = Field(default_factory=dict)
    working_dir: Optional[str] = None

    @field_validator("command")
    @classmethod
    def _command_str(cls, v: Any) -> str:
        # Defensive: reject the legacy List[str] shape with a clear error
        # so a stale frontend gets a useful 422 instead of "string type
        # expected".
        if isinstance(v, list):
            raise ValueError(
                "'command' must be a string (single executable). For arguments use 'args'.",
            )
        if not isinstance(v, str):
            raise ValueError("'command' must be a string")
        return v.strip()


class HookEntryRow(BaseModel):
    """One entry as returned to the UI; identical shape to
    :class:`HookEntryPayload` plus the index."""

    event: str
    idx: int
    command: str
    args: List[str] = Field(default_factory=list)
    timeout_ms: Optional[int] = None
    match: Dict[str, Any] = Field(default_factory=dict)
    env: Dict[str, str] = Field(default_factory=dict)
    working_dir: Optional[str] = None


class HookEntriesResponse(BaseModel):
    enabled: bool
    audit_log_path: Optional[str] = None
    entries: List[HookEntryRow] = Field(default_factory=list)
    settings_path: str
    known_events: List[str] = Field(default_factory=list)


class HookEnabledPatch(BaseModel):
    enabled: bool


class HookAuditLogPatch(BaseModel):
    audit_log_path: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────


def _user_settings_path() -> Path:
    return Path.home() / ".geny" / "settings.json"


def _read_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            500,
            f"settings.json at {path} is not valid JSON: {exc}",
        )


def _write_settings_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
            fp.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _hooks_section(data: Dict[str, Any]) -> Dict[str, Any]:
    section = data.get("hooks")
    if not isinstance(section, dict):
        section = {}
        data["hooks"] = section
    return section


def _entries_map(section: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    entries = section.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        section["entries"] = entries
    return entries


def _validate_event(event: str) -> str:
    """Normalize event name to lowercase + verify membership.

    Accepts both legacy uppercase ("PRE_TOOL_USE") and current lowercase
    ("pre_tool_use") for inputs so older clients keep working until
    they refresh.
    """
    norm = event.strip().lower()
    if norm not in _KNOWN_EVENTS:
        raise HTTPException(
            400,
            f"unknown hook event {event!r}; known: {sorted(_KNOWN_EVENTS)}",
        )
    return norm


def _entry_to_dict(payload: HookEntryPayload) -> Dict[str, Any]:
    """Serialize a payload into the executor-compatible on-disk shape."""
    out: Dict[str, Any] = {"command": payload.command}
    if payload.args:
        out["args"] = list(payload.args)
    if payload.timeout_ms is not None:
        out["timeout_ms"] = payload.timeout_ms
    if payload.match:
        out["match"] = dict(payload.match)
    if payload.env:
        out["env"] = dict(payload.env)
    if payload.working_dir:
        out["working_dir"] = payload.working_dir
    return out


def _normalize_legacy_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """Best-effort migration of a pre-H.1 entry to the new shape.

    Returns ``None`` when the entry is malformed beyond recovery so the
    caller can skip it without crashing the whole list.
    """
    if not isinstance(raw, dict):
        return None
    cmd_raw = raw.get("command")
    args_raw = raw.get("args") or []
    if isinstance(cmd_raw, list):
        # Legacy shape — split into head + tail.
        if not cmd_raw:
            return None
        command = str(cmd_raw[0])
        args_legacy = [str(a) for a in cmd_raw[1:]]
        # Append explicit args after legacy split-args (rare combination).
        if isinstance(args_raw, list):
            args_legacy.extend(str(a) for a in args_raw)
        args = args_legacy
    else:
        command = str(cmd_raw or "").strip()
        if not command:
            return None
        args = [str(a) for a in args_raw] if isinstance(args_raw, list) else []

    # tool_filter (legacy) → match (current)
    match = dict(raw.get("match") or {})
    tool_filter = raw.get("tool_filter")
    if isinstance(tool_filter, list) and tool_filter and "tool" not in match:
        match["tool"] = str(tool_filter[0])
        if len(tool_filter) > 1:
            logger.warning(
                "hook entry tool_filter has multiple tools %s; only the "
                "first survives the match-dict migration. Split into "
                "separate entries to keep all of them.",
                tool_filter,
            )

    env_raw = raw.get("env") or {}
    env = (
        {str(k): str(v) for k, v in env_raw.items()}
        if isinstance(env_raw, dict)
        else {}
    )
    timeout_ms = raw.get("timeout_ms")
    if timeout_ms is not None:
        try:
            timeout_ms = int(timeout_ms)
            if timeout_ms <= 0:
                timeout_ms = None
        except (TypeError, ValueError):
            timeout_ms = None
    working_dir = raw.get("working_dir")
    if working_dir is not None and not isinstance(working_dir, str):
        working_dir = None

    return {
        "command": command,
        "args": args,
        "timeout_ms": timeout_ms,
        "match": match,
        "env": env,
        "working_dir": working_dir,
    }


def _reload_loader() -> None:
    try:
        from geny_executor.settings import get_default_loader

        get_default_loader().reload()
    except Exception as exc:  # noqa: BLE001
        logger.warning("hook_entries: loader reload failed: %s", exc)


def _build_response(data: Dict[str, Any], path: Path) -> HookEntriesResponse:
    section = _hooks_section(data)
    entries_map = _entries_map(section)
    rows: List[HookEntryRow] = []
    for event_name, raw_list in entries_map.items():
        # Tolerate legacy uppercase event keys — normalize for display.
        event_lc = str(event_name).strip().lower()
        if not isinstance(raw_list, list):
            continue
        for idx, raw in enumerate(raw_list):
            normalized = _normalize_legacy_entry(raw)
            if normalized is None:
                continue
            rows.append(HookEntryRow(
                event=event_lc,
                idx=idx,
                command=normalized["command"],
                args=normalized["args"],
                timeout_ms=normalized["timeout_ms"],
                match=normalized["match"],
                env=normalized["env"],
                working_dir=normalized["working_dir"],
            ))
    return HookEntriesResponse(
        enabled=bool(section.get("enabled", False)),
        audit_log_path=section.get("audit_log_path"),
        entries=rows,
        settings_path=str(path),
        known_events=sorted(_KNOWN_EVENTS),
    )


# ── Endpoints ────────────────────────────────────────────


@router.get("/entries", response_model=HookEntriesResponse)
async def list_entries(_auth: dict = Depends(require_auth)):
    path = _user_settings_path()
    data = _read_settings(path)
    return _build_response(data, path)


@router.post("/entries", response_model=HookEntriesResponse)
async def append_entry(
    body: HookEntryPayload,
    _auth: dict = Depends(require_auth),
):
    event = _validate_event(body.event)
    path = _user_settings_path()
    data = _read_settings(path)
    section = _hooks_section(data)
    entries_map = _entries_map(section)
    # Migrate legacy uppercase key in-place if present.
    upper = event.upper()
    if upper in entries_map and event not in entries_map:
        entries_map[event] = entries_map.pop(upper)
    entries_map.setdefault(event, []).append(_entry_to_dict(body))
    _write_settings_atomic(path, data)
    _reload_loader()
    return _build_response(data, path)


@router.put("/entries/{event}/{idx}", response_model=HookEntriesResponse)
async def replace_entry(
    event: str,
    idx: int,
    body: HookEntryPayload,
    _auth: dict = Depends(require_auth),
):
    event_norm = _validate_event(event)
    if body.event and _validate_event(body.event) != event_norm:
        raise HTTPException(400, "URL event differs from body event")
    path = _user_settings_path()
    data = _read_settings(path)
    section = _hooks_section(data)
    entries_map = _entries_map(section)
    upper = event_norm.upper()
    if upper in entries_map and event_norm not in entries_map:
        entries_map[event_norm] = entries_map.pop(upper)
    bucket = entries_map.get(event_norm) or []
    if idx < 0 or idx >= len(bucket):
        raise HTTPException(404, f"hook index {idx} out of range for event {event_norm}")
    bucket[idx] = _entry_to_dict(body)
    entries_map[event_norm] = bucket
    _write_settings_atomic(path, data)
    _reload_loader()
    return _build_response(data, path)


@router.delete("/entries/{event}/{idx}", response_model=HookEntriesResponse)
async def delete_entry(
    event: str,
    idx: int,
    _auth: dict = Depends(require_auth),
):
    event_norm = _validate_event(event)
    path = _user_settings_path()
    data = _read_settings(path)
    section = _hooks_section(data)
    entries_map = _entries_map(section)
    upper = event_norm.upper()
    if upper in entries_map and event_norm not in entries_map:
        entries_map[event_norm] = entries_map.pop(upper)
    bucket = entries_map.get(event_norm) or []
    if idx < 0 or idx >= len(bucket):
        raise HTTPException(404, f"hook index {idx} out of range for event {event_norm}")
    bucket.pop(idx)
    if bucket:
        entries_map[event_norm] = bucket
    else:
        entries_map.pop(event_norm, None)
    _write_settings_atomic(path, data)
    _reload_loader()
    return _build_response(data, path)


@router.patch("/enabled", response_model=HookEntriesResponse)
async def patch_enabled(
    body: HookEnabledPatch,
    _auth: dict = Depends(require_auth),
):
    """Toggle the file-side ``enabled`` flag. Note that ``GENY_ALLOW_HOOKS``
    env opt-in is still required for hooks to actually fire — this only
    controls the config-side gate.
    """
    path = _user_settings_path()
    data = _read_settings(path)
    section = _hooks_section(data)
    section["enabled"] = bool(body.enabled)
    _write_settings_atomic(path, data)
    _reload_loader()
    return _build_response(data, path)


@router.patch("/audit-log", response_model=HookEntriesResponse)
async def patch_audit_log(
    body: HookAuditLogPatch,
    _auth: dict = Depends(require_auth),
):
    """Set / clear the audit log path. ``None`` removes it."""
    path = _user_settings_path()
    data = _read_settings(path)
    section = _hooks_section(data)
    if body.audit_log_path is None or not body.audit_log_path.strip():
        section.pop("audit_log_path", None)
    else:
        section["audit_log_path"] = body.audit_log_path.strip()
    _write_settings_atomic(path, data)
    _reload_loader()
    return _build_response(data, path)
