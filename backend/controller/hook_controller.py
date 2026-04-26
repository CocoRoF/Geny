"""Hook entry CRUD (PR-E.3.1).

Mutates the ``hooks`` section of user-scope ``~/.geny/settings.json`` so
the operator can manage subprocess hooks (the executor's HookEvent
runner) without hand-editing the file.

Pairs with the existing read endpoint at ``/api/hooks/list``
(admin_controller). The cascade-merged inspection still belongs there;
this controller is write-only against the user-scope file.

The on-disk schema mirrors the executor's HookConfig::

    {
      "hooks": {
        "enabled": true,
        "audit_log_path": null,
        "entries": {
          "PRE_TOOL_USE": [
            {"command": ["echo", "hi"], "timeout_ms": 1000, "tool_filter": []}
          ]
        }
      }
    }

Index-addressed mutation per (event, position) — entry order is
significant (HookRunner fires them sequentially).
"""

from __future__ import annotations

import json
import os
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

logger = getLogger(__name__)

router = APIRouter(prefix="/api/hooks", tags=["hooks"])

# Mirrors geny_executor.hooks.HookEvent. Kept in sync by hand — listing
# them here lets the API reject typos before they hit the parser.
_KNOWN_EVENTS = {
    "PRE_TOOL_USE",
    "POST_TOOL_USE",
    "USER_PROMPT_SUBMIT",
    "STOP",
    "SESSION_START",
    "SESSION_END",
    "SUBAGENT_STOP",
    "PRE_COMPACT",
}


# ── Schemas ──────────────────────────────────────────────


class HookEntryPayload(BaseModel):
    event: str = Field(..., description="HookEvent name (e.g. PRE_TOOL_USE)")
    command: List[str] = Field(..., min_length=1)
    timeout_ms: Optional[int] = Field(None, ge=1)
    tool_filter: List[str] = Field(default_factory=list)


class HookEntryRow(BaseModel):
    """Returned in the per-event list. Includes the index so a follow-up
    PUT/DELETE can target it without re-reading the file."""
    event: str
    idx: int
    command: List[str]
    timeout_ms: Optional[int] = None
    tool_filter: List[str] = Field(default_factory=list)


class HookEntriesResponse(BaseModel):
    enabled: bool
    audit_log_path: Optional[str] = None
    entries: List[HookEntryRow] = Field(default_factory=list)
    settings_path: str


class HookEnabledPatch(BaseModel):
    enabled: bool


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
    norm = event.strip().upper()
    if norm not in _KNOWN_EVENTS:
        raise HTTPException(
            400,
            f"unknown hook event {event!r}; known: {sorted(_KNOWN_EVENTS)}",
        )
    return norm


def _entry_to_dict(payload: HookEntryPayload) -> Dict[str, Any]:
    out: Dict[str, Any] = {"command": list(payload.command)}
    if payload.timeout_ms is not None:
        out["timeout_ms"] = payload.timeout_ms
    if payload.tool_filter:
        out["tool_filter"] = list(payload.tool_filter)
    return out


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
        if not isinstance(raw_list, list):
            continue
        for idx, entry in enumerate(raw_list):
            if not isinstance(entry, dict):
                continue
            rows.append(HookEntryRow(
                event=str(event_name),
                idx=idx,
                command=list(entry.get("command") or []),
                timeout_ms=entry.get("timeout_ms"),
                tool_filter=list(entry.get("tool_filter") or []),
            ))
    return HookEntriesResponse(
        enabled=bool(section.get("enabled", False)),
        audit_log_path=section.get("audit_log_path"),
        entries=rows,
        settings_path=str(path),
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
    bucket = entries_map.get(event_norm) or []
    if idx < 0 or idx >= len(bucket):
        raise HTTPException(404, f"hook index {idx} out of range for event {event_norm}")
    bucket.pop(idx)
    if bucket:
        entries_map[event_norm] = bucket
    else:
        # Drop empty event keys to keep the file tidy.
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
