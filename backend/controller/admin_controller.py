"""Read-only admin endpoints (G13).

- GET /api/permissions/list   — current rule list with source breakdown
- GET /api/hooks/list         — current hook config + env opt-in status
- GET /api/admin/hook-fires   — recent HookRunner audit events (PR-E.3.2)

Skills are already covered by /api/skills/list (G7.4).
"""

from __future__ import annotations

import json
import os
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from controller.auth_controller import require_auth

logger = getLogger(__name__)

router = APIRouter(prefix="/api", tags=["admin"])


# ── Permissions ────────────────────────────────────────────────────


class PermissionRuleInfo(BaseModel):
    tool_name: str
    pattern: Optional[str] = None
    behavior: str
    source: str
    reason: Optional[str] = None


class PermissionListResponse(BaseModel):
    mode: str = Field(..., description="advisory | enforce")
    rules: List[PermissionRuleInfo]
    sources_consulted: List[str] = Field(
        default_factory=list,
        description="Paths the loader inspected — useful for debugging \"my rule isn't loaded\"",
    )


@router.get(
    "/permissions/list",
    response_model=PermissionListResponse,
    summary="Inspect the loaded permission matrix",
)
async def list_permissions(_auth: dict = Depends(require_auth)):
    """Returns every PermissionRule the install layer would forward
    to attach_runtime, plus the resolved mode (advisory / enforce)
    and the candidate paths the loader checked."""
    from service.permission.install import (
        _candidate_paths,
        install_permission_rules,
    )

    rules, mode = install_permission_rules()
    paths = [str(p) for p, _src in _candidate_paths()]
    return PermissionListResponse(
        mode=mode,
        rules=[
            PermissionRuleInfo(
                tool_name=r.tool_name,
                pattern=r.pattern,
                behavior=getattr(r.behavior, "value", str(r.behavior)),
                source=getattr(r.source, "value", str(r.source)),
                reason=r.reason,
            )
            for r in rules
        ],
        sources_consulted=paths,
    )


# ── Hooks ───────────────────────────────────────────────────────────


class HookEntryInfo(BaseModel):
    event: str
    command: List[str]
    timeout_ms: Optional[int] = None
    tool_filter: List[str] = Field(default_factory=list)


class HookListResponse(BaseModel):
    enabled: bool
    env_opt_in: bool = Field(..., description="GENY_ALLOW_HOOKS truthy?")
    config_path: str
    entries: List[HookEntryInfo]


@router.get(
    "/hooks/list",
    response_model=HookListResponse,
    summary="Inspect the loaded HookConfig",
)
async def list_hooks(_auth: dict = Depends(require_auth)):
    """Returns the HookConfig that install_hook_runner would build
    plus the env opt-in status. Both gates must be open for hooks
    to actually fire."""
    from service.hooks.install import hooks_yaml_path

    env_opt_in = os.environ.get("GENY_ALLOW_HOOKS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    path = hooks_yaml_path()

    enabled = False
    entries: List[HookEntryInfo] = []
    try:
        from geny_executor.hooks import load_hooks_config

        cfg = load_hooks_config(path)
        enabled = bool(getattr(cfg, "enabled", False))
        for event, event_entries in (cfg.entries or {}).items():
            event_name = getattr(event, "value", str(event))
            for ent in event_entries:
                entries.append(
                    HookEntryInfo(
                        event=event_name,
                        command=list(getattr(ent, "command", []) or []),
                        timeout_ms=getattr(ent, "timeout_ms", None),
                        tool_filter=list(getattr(ent, "tool_filter", []) or []),
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("list_hooks: load failed: %s", exc)

    return HookListResponse(
        enabled=enabled,
        env_opt_in=env_opt_in,
        config_path=str(path),
        entries=entries,
    )


# ── Recent hook fires (PR-E.3.2) ───────────────────────────────────


class HookFireRecord(BaseModel):
    """One row in the hook audit log JSONL.

    Schema mirrors what HookRunner writes to ``audit_log_path``: an
    arbitrary dict keyed by the runner's record format (event,
    payload, outcome, timing). We pass it through as a free-form dict
    so future runner enrichments don't need a parallel update here.
    """
    record: Dict[str, Any]


class HookFiresResponse(BaseModel):
    audit_path: Optional[str] = Field(
        None,
        description="Resolved audit log path. None when hooks aren't configured.",
    )
    exists: bool = False
    fires: List[HookFireRecord] = Field(default_factory=list)
    truncated: bool = Field(
        False,
        description="True when more rows existed than the requested limit.",
    )


def _resolve_audit_path() -> Optional[Path]:
    """Pull audit_log_path from settings.json:hooks → fall back to None.

    Mirrors the hook install layer (settings.json wins; legacy yaml is
    not consulted here since the editor only writes settings.json)."""
    try:
        from geny_executor.settings import get_default_loader

        section = get_default_loader().get_section("hooks")
    except Exception:
        return None
    if not isinstance(section, dict):
        return None
    raw = section.get("audit_log_path")
    if not isinstance(raw, str) or not raw:
        return None
    return Path(raw).expanduser()


@router.get(
    "/admin/hook-fires",
    response_model=HookFiresResponse,
    summary="Recent HookRunner audit-log entries",
)
async def list_hook_fires(
    limit: int = 100,
    _auth: dict = Depends(require_auth),
):
    """Return the last *limit* JSONL records from the configured
    ``hooks.audit_log_path``. Acts as a poor-operator's ring buffer
    until the executor exposes one natively (planned executor 1.4.0).

    Empty payload (with ``audit_path=None``) when hooks aren't
    configured to write an audit log — that's the expected state for
    most installs.
    """
    if limit <= 0 or limit > 1000:
        raise HTTPException(400, "limit must be in 1..1000")

    path = _resolve_audit_path()
    if path is None:
        return HookFiresResponse(audit_path=None, exists=False, fires=[])
    if not path.exists():
        return HookFiresResponse(audit_path=str(path), exists=False, fires=[])

    # Tail the file by reading all lines and slicing — JSONL hook
    # files are usually small (one row per fire); if they grow large
    # the operator should rotate. Avoid pulling > 5MB into memory.
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise HTTPException(500, f"audit log stat failed: {exc}")
    if size > 5 * 1024 * 1024:
        raise HTTPException(
            413,
            f"audit log {path} too large ({size}B); rotate or shrink",
        )

    truncated = False
    fires: List[HookFireRecord] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise HTTPException(500, f"audit log read failed: {exc}")

    if len(lines) > limit:
        truncated = True
        lines = lines[-limit:]

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            # Malformed line — skip but don't fail the whole call.
            continue
        if isinstance(record, dict):
            fires.append(HookFireRecord(record=record))

    return HookFiresResponse(
        audit_path=str(path),
        exists=True,
        fires=fires,
        truncated=truncated,
    )


# ── Recent tool events (PR-E.4.1) ──────────────────────────────────


class ToolEventRow(BaseModel):
    ts: float
    kind: str  # "start" | "complete"
    tool_name: str
    tool_use_id: Optional[str] = None
    session_id: Optional[str] = None
    is_error: Optional[bool] = None
    duration_ms: Optional[int] = None
    extra: Optional[Dict[str, Any]] = None


class RecentToolEventsResponse(BaseModel):
    events: List[ToolEventRow] = Field(default_factory=list)
    capacity: int = 0
    returned: int = 0


@router.get(
    "/admin/recent-tool-events",
    response_model=RecentToolEventsResponse,
    summary="Process-wide ring buffer of recent tool start/complete events",
)
async def recent_tool_events(
    limit: int = 50,
    _auth: dict = Depends(require_auth),
):
    """Snapshot the agent_session-side tool event ring. Newest last.

    Used by the AdminPanel "Recent Activity" panel to surface what
    every session in this process has been calling lately — spans
    sessions because the ring is process-wide.
    """
    if limit <= 0 or limit > 500:
        raise HTTPException(400, "limit must be in 1..500")
    from service.telemetry.tool_event_ring import capacity, snapshot

    rows = snapshot(limit=limit)
    return RecentToolEventsResponse(
        events=[ToolEventRow(**r) for r in rows],
        capacity=capacity(),
        returned=len(rows),
    )
