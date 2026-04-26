"""Read-only admin endpoints (G13).

- GET /api/permissions/list      — current rule list with source breakdown
- GET /api/hooks/list            — current hook config + env opt-in status
- GET /api/admin/hook-fires      — recent HookRunner audit events (PR-E.3.2)
- GET /api/admin/recent-tool-events  — recent tool event ring (PR-E.4.1)
- GET /api/admin/recent-permissions  — recent permission decisions (PR-E.4.2)
- GET /api/admin/system-status   — subsystem health snapshot (PR-F.6.1/2/5)

Skills are already covered by /api/skills/list (G7.4).
"""

from __future__ import annotations

import json
import os
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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


# ── Recent permission decisions (PR-E.4.2) ─────────────────────────


class PermissionDecisionRow(BaseModel):
    ts: float
    decision: str
    tool_name: Optional[str] = None
    rule_tool: Optional[str] = None
    rule_pattern: Optional[str] = None
    rule_source: Optional[str] = None
    rule_reason: Optional[str] = None
    session_id: Optional[str] = None
    message: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class RecentPermissionsResponse(BaseModel):
    decisions: List[PermissionDecisionRow] = Field(default_factory=list)
    capacity: int = 0
    returned: int = 0


@router.get(
    "/admin/recent-permissions",
    response_model=RecentPermissionsResponse,
    summary="Process-wide ring buffer of recent permission decisions",
)
async def recent_permissions(
    limit: int = 50,
    _auth: dict = Depends(require_auth),
):
    """Snapshot the agent_session-side permission decision ring.

    Today populated when the permission guard rejects a tool call
    (guard_reject). Future executor versions are expected to emit
    explicit allow/ask decisions; this endpoint will pick those up
    automatically as long as the bridge feeds them.
    """
    if limit <= 0 or limit > 500:
        raise HTTPException(400, "limit must be in 1..500")
    from service.telemetry.permission_ring import capacity, snapshot

    rows = snapshot(limit=limit)
    return RecentPermissionsResponse(
        decisions=[PermissionDecisionRow(**r) for r in rows],
        capacity=capacity(),
        returned=len(rows),
    )


# ── System status (PR-F.6.1, PR-F.6.3, PR-F.6.5) ───────────────────


class SubsystemStatus(BaseModel):
    name: str
    present: bool
    detail: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class SystemStatusResponse(BaseModel):
    subsystems: List[SubsystemStatus] = Field(default_factory=list)
    cron: Optional[Dict[str, Any]] = None  # {running, jobs, cycle_seconds}
    task_runner: Optional[Dict[str, Any]] = None  # {running, in_flight, max_concurrency}
    started_at: Optional[str] = None


_LIFESPAN_KEYS = (
    "app_db",
    "auth_service",
    "config_manager",
    "tool_loader",
    "mcp_loader",
    "global_mcp_config",
    "shared_folder_manager",
    "ws_abandoned_detector",
    "environment_service",
    "task_runner",
    "cron_runner",
    "cron_store",
    "state_provider",
)


def _subsystem_row(state: Any, key: str) -> SubsystemStatus:
    val = getattr(state, key, None)
    present = val is not None
    detail = None
    if present:
        try:
            detail = type(val).__name__
        except Exception:
            detail = str(val)
    return SubsystemStatus(name=key, present=present, detail=detail)


@router.get(
    "/admin/system-status",
    response_model=SystemStatusResponse,
    summary="Subsystem health snapshot",
)
async def system_status(request: Request, _auth: dict = Depends(require_auth)):
    """One-call snapshot of every lifespan-installed subsystem plus
    the cron + task runner liveness signals.

    Pairs F.6.1 (lifespan inventory), F.6.3 (cron status), and F.6.5
    (task-runner stats) so the AdminPanel "System Status" panel
    needs exactly one request.
    """
    state = request.app.state
    rows = [_subsystem_row(state, k) for k in _LIFESPAN_KEYS]

    # Cron runner introspection. The runner doesn't expose a public
    # "running" — fall back to the internal _daemon task's done()
    # state which is observable across executor versions.
    cron_block: Optional[Dict[str, Any]] = None
    cron_runner = getattr(state, "cron_runner", None)
    cron_store = getattr(state, "cron_store", None)
    if cron_runner is not None:
        daemon = getattr(cron_runner, "_daemon", None)
        running = bool(daemon is not None and not daemon.done())
        cycle = getattr(cron_runner, "_cycle", None)
        jobs_count = None
        if cron_store is not None:
            try:
                jobs = await cron_store.list()
                jobs_count = len(jobs)
            except Exception:
                jobs_count = None
        cron_block = {
            "running": running,
            "cycle_seconds": cycle,
            "jobs": jobs_count,
        }

    # Task runner queue stats — best-effort introspection.
    tr_block: Optional[Dict[str, Any]] = None
    task_runner = getattr(state, "task_runner", None)
    if task_runner is not None:
        # geny-executor BackgroundTaskRunner exposes _registry +
        # _max_concurrency by convention; lookups are guarded.
        registry = getattr(task_runner, "_registry", None)
        in_flight = None
        if registry is not None:
            list_method = getattr(registry, "list", None)
            try:
                if callable(list_method):
                    rows_ = list_method()
                    in_flight = sum(
                        1 for r in rows_
                        if getattr(r, "status", None)
                        and getattr(r.status, "value", str(r.status)) in {"pending", "running"}
                    )
            except Exception:
                in_flight = None
        tr_block = {
            "running": True,
            "in_flight": in_flight,
            "max_concurrency": getattr(task_runner, "_max_concurrency", None),
        }

    return SystemStatusResponse(
        subsystems=rows,
        cron=cron_block,
        task_runner=tr_block,
    )


# ── Tool usage counts (PR-G — Tool 사용량 / 호출 카운터) ─────────────


class ToolUsageRow(BaseModel):
    tool_name: str
    calls: int
    completes: int
    errors: int
    total_duration_ms: int
    last_at: float


class ToolUsageResponse(BaseModel):
    counts: List[ToolUsageRow] = Field(default_factory=list)
    window_size: int = 0  # number of events in the underlying ring


@router.get(
    "/admin/tool-usage",
    response_model=ToolUsageResponse,
    summary="Per-tool aggregate counts from the live event ring",
)
async def tool_usage(_auth: dict = Depends(require_auth)):
    """Aggregate tool start/complete/error counters from the
    process-wide ring buffer (PR-E.4.1). Window is the ring's last
    200 events, not lifetime — for lifetime stats wire a Prometheus
    exporter (out of scope today)."""
    from service.telemetry.tool_event_ring import snapshot, usage_counts

    rows = usage_counts()
    return ToolUsageResponse(
        counts=[ToolUsageRow(**r) for r in rows],
        window_size=len(snapshot(limit=10_000)),
    )


# ── In-process hook handlers (PR-G — In-process hook handler list) ──


class InProcessHookHandlerRow(BaseModel):
    event: str
    handler_count: int


class InProcessHandlersResponse(BaseModel):
    enabled: bool
    handlers: List[InProcessHookHandlerRow] = Field(default_factory=list)
    total: int = 0


@router.get(
    "/admin/hook-in-process-handlers",
    response_model=InProcessHandlersResponse,
    summary="Counts of in-process HookRunner handlers per event",
)
async def hook_in_process_handlers(_auth: dict = Depends(require_auth)):
    """Surface :py:meth:`HookRunner.list_in_process_handlers` for the
    HooksTab "in-process handlers" panel.

    Empty (enabled=False) when no HookRunner is bound today (no
    sessions or executor < 1.2.0)."""
    handlers: Dict[str, int] = {}
    enabled = False
    try:
        # The runner is per-session; AgentSessionManager caches the
        # current default. Walk every live session and merge counts.
        from controller.agent_controller import agent_manager

        for sess in agent_manager.list_agents():
            sid = sess.get("session_id") if isinstance(sess, dict) else getattr(sess, "session_id", None)
            if not sid:
                continue
            agent = agent_manager.get_agent(sid)
            if agent is None:
                continue
            pipeline = getattr(agent, "_pipeline", None)
            if pipeline is None:
                continue
            tool_stage = pipeline.get_stage(10) if hasattr(pipeline, "get_stage") else None
            ctx = getattr(tool_stage, "_context", None) if tool_stage else None
            runner = getattr(ctx, "hook_runner", None) if ctx else None
            if runner is None:
                continue
            enabled = bool(getattr(runner, "enabled", False))
            list_fn = getattr(runner, "list_in_process_handlers", None)
            if not callable(list_fn):
                continue
            for ev, count in list_fn().items():
                ev_name = getattr(ev, "value", str(ev))
                handlers[ev_name] = handlers.get(ev_name, 0) + int(count)
    except Exception as exc:  # noqa: BLE001
        logger.debug("hook_in_process_handlers: %s", exc)

    rows = [InProcessHookHandlerRow(event=ev, handler_count=cnt) for ev, cnt in sorted(handlers.items())]
    return InProcessHandlersResponse(
        enabled=enabled,
        handlers=rows,
        total=sum(r.handler_count for r in rows),
    )


# ── Settings migration status viewer (PR-G) ────────────────────────


class SettingsMigrationStatusResponse(BaseModel):
    legacy_files_present: List[str] = Field(default_factory=list)
    settings_json_path: Optional[str] = None
    settings_json_exists: bool = False
    settings_json_sections: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


@router.get(
    "/admin/settings-migration-status",
    response_model=SettingsMigrationStatusResponse,
    summary="Visibility into the legacy-yaml → settings.json migration",
)
async def settings_migration_status(_auth: dict = Depends(require_auth)):
    """Helps operators understand whether they still have legacy YAML
    files lying around after the dual-read migration (PR-D.2.x)."""
    notes: List[str] = []
    legacy: List[str] = []

    # Permission yaml
    try:
        from service.permission.install import _candidate_paths

        for p, _src in _candidate_paths():
            if p.exists():
                legacy.append(str(p))
    except Exception:
        pass

    # Hook yaml
    try:
        from service.hooks.install import hooks_yaml_path

        h = hooks_yaml_path()
        if h.exists():
            legacy.append(str(h))
    except Exception:
        pass

    # Settings.json snapshot
    settings_path = Path.home() / ".geny" / "settings.json"
    sections: List[str] = []
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                sections = sorted(data.keys())
        except Exception as exc:  # noqa: BLE001
            notes.append(f"settings.json parse failed: {exc}")

    if legacy and sections:
        notes.append(
            "Legacy YAML files still present alongside settings.json — "
            "delete them after verifying the migration to keep one source of truth.",
        )
    elif not settings_path.exists() and not legacy:
        notes.append(
            "No settings.json and no legacy yaml — installation is using "
            "defaults across the board.",
        )

    return SettingsMigrationStatusResponse(
        legacy_files_present=legacy,
        settings_json_path=str(settings_path),
        settings_json_exists=settings_path.exists(),
        settings_json_sections=sections,
        notes=notes,
    )
